"""Generate a flat, specialized validator for a simple mapping schema.

This is the first cut of the compiled variant (the ``compile`` flag and
:meth:`Schema.compile`). It unrolls the generic per-key loop of
``_MappingValidator`` into straight-line code specialized to one schema's keys,
inlining type-value checks and reusing the already-compiled value validators.

It is deliberately *safe by construction*. The generated function is a fast
**success** path only: on the first sign of any failure (a missing required key,
a type mismatch, a value validator raising, an unexpected key, a declining
default), it raises ``_Bail`` and the caller re-runs the original interpreted
``_MappingValidator``, which produces the exact errors, paths, codes, and order.
Validation of valid data, the overwhelming common case, never leaves the fast
path; only a failure pays the interpreted re-run, and failures are not the hot
path. So the compiled and interpreted schemas return the same value and raise the
same error, and the generator only has to get the *happy* path right.

The one observable seam is side effects on the failure path. The fast path runs
fields optimistically, so a validator or ``default`` factory that already ran
before some later field bails runs a second time in the interpreted re-run. The
value and the error are still identical; only the count of side effects differs,
and only when validation fails. Probatio's own validators are pure, so this is
invisible for them; a user validator or default factory that mutates state should
be pure too, the same expectation the interpreted engine already leans on.

Anything it does not yet handle (type or callable keys, groups, aliases,
``Remove``/``Forbidden``, complex keys, recursion) makes ``compile_mapping``
return ``None``, and the schema stays interpreted.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from probatio._engine import (
    ALLOW_EXTRA,
    PREVENT_EXTRA,
    REMOVE_EXTRA,
    _MappingValidator,
)
from probatio.error import Invalid
from probatio.markers import Undefined

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import CodeType

    from probatio._engine import _Candidate
    from probatio.validators.coerce import Coerce
    from probatio.validators.combinators import All
    from probatio.validators.combinators import Any as AnyValidator
    from probatio.validators.comparison import In, Length, Range
    from probatio.validators.strings import Match

    _ValidatorTypes = tuple[
        type[Coerce[Any]],
        type[Range],
        type[In],
        type[AnyValidator],
        type[All],
        type[Length],
        type[Match],
    ]

# A missing key, distinct from any real value (a key whose value is ``None`` is
# present). Module-level so every generated function shares it by identity.
_MISSING = object()


class _Bail(Exception):  # noqa: N818 - a control-flow signal, not an error
    """Raised inside the fast path to fall back to the interpreted validator."""


@lru_cache(maxsize=512)
def _compile_source(source: str) -> CodeType:
    """Compile generated source to a code object, cached by the source text.

    Byte-compiling the source is the bulk of generation cost (around 85% of it), and
    schemas of the same shape (same keys in the same order, same validator kinds)
    generate byte-identical source. So caching the code object lets every later
    same-shape schema skip the compile and only bind a fresh namespace at ``exec``
    time, which is cheap. The cache is bounded, so an unusual churn of unique shapes
    evicts the oldest rather than growing without bound, and same-shape schemas now
    share one code object instead of each holding its own.
    """
    return compile(source, "<probatio-generated>", "exec")


def _holds_recursive_ref(value: Any) -> bool:
    """Report whether a value schema is (or inlines) a recursive ``$ref``.

    A recursive reference validates by re-entering the same schema. Compiling a
    mapping that holds one is unsafe: on a deep failure the generated function bails
    to the interpreted engine, which re-validates the whole nested subtree, and at
    every level up the stack, an exponential cascade. So the generator leaves such a
    mapping interpreted, the same way it leaves ``Self`` recursion interpreted. The
    walk descends the combinators it would otherwise inline (``All``/``Any`` expose
    ``validators``) and the elements of a sequence value schema (``[ref]``), which is
    inlined into this same mapping; a nested mapping value is a separate compilation
    that guards itself, so it is not walked here.
    """
    if getattr(value, "_probatio_recursive_ref", False):
        return True
    if isinstance(value, (list, tuple)):
        return any(_holds_recursive_ref(member) for member in value)
    sub = getattr(value, "validators", None)
    return sub is not None and any(_holds_recursive_ref(member) for member in sub)


def _is_generatable(validator: _MappingValidator) -> bool:
    """Report whether ``validator`` is the simple mapping shape this cut handles."""
    if validator._has_groups or validator._alias_lookup or validator._validators:  # noqa: SLF001
        return False
    if validator._extra not in (PREVENT_EXTRA, ALLOW_EXTRA, REMOVE_EXTRA):  # noqa: SLF001
        return False
    return all(
        candidate.is_literal
        and not candidate.forbidden
        and not candidate.remove
        and candidate.complex_keys is None
        and candidate.exclusive_group is None
        and candidate.inclusive_group is None
        and not candidate.alias_input_names
        # An exact ``str``, not a subclass: a ``StrEnum`` member is a ``str`` whose
        # ``repr`` (``<Svc.TURN_ON: 'turn_on'>``) is not valid source to emit, so it
        # stays interpreted (the engine handles it).
        and type(candidate.key_schema) is str
        and not _holds_recursive_ref(candidate.value_schema)
        for candidate in validator._candidates  # noqa: SLF001
    )


def _inline_coerce(target: Any) -> list[str] | None:
    """Inline a ``Coerce`` to int or float; leave the coerced value in ``_v``.

    An int (or float) passes through, a string is parsed, and anything else bails
    to the interpreted ``Coerce`` (which handles the rest, like a float-to-int
    truncation). The success cases produce exactly the same value ``Coerce`` would.
    """
    if target is int:
        return [
            "        if type(_v) is int:",
            "            pass",
            "        elif type(_v) is str:",
            "            try:",
            "                _v = int(_v)",
            "            except ValueError:",
            "                raise _Bail",
            "        else:",
            "            raise _Bail",
        ]
    if target is float:
        return [
            "        if type(_v) is float:",
            "            pass",
            "        elif type(_v) is int:",
            "            _v = float(_v)",
            "        elif type(_v) is str:",
            "            try:",
            "                _v = float(_v)",
            "            except ValueError:",
            "                raise _Bail",
            "        else:",
            "            raise _Bail",
        ]
    return None


def _inline_range(schema: Any, *, type_checked: bool = False) -> list[str] | None:
    """Inline a numeric ``Range`` with numeric bounds; ``_v`` is unchanged.

    ``type_checked`` is the caller asserting ``_v`` is already known to be an
    ``int`` or ``float`` (an inlined ``Coerce`` just guaranteed it), so the type
    guard would be dead code and is skipped.
    """
    low, high = schema.min, schema.max
    if (low is not None and not isinstance(low, (int, float))) or (
        high is not None and not isinstance(high, (int, float))
    ):
        return None

    lines = (
        []
        if type_checked
        else ["        if type(_v) not in (int, float):", "            raise _Bail"]
    )
    if low is not None:
        op = ">=" if schema.min_included else ">"
        lines += [f"        if not (_v {op} {low!r}):", "            raise _Bail"]
    if high is not None:
        op = "<=" if schema.max_included else "<"
        lines += [f"        if not (_v {op} {high!r}):", "            raise _Bail"]
    return lines


def _inline_length(schema: Any, tag: str) -> list[str] | None:
    """Inline a ``Length`` with integer bounds; ``_v`` is unchanged.

    With no bound set the value always passes, so nothing is emitted. A value whose
    ``len`` raises (no ``__len__``, or a user ``__len__`` that raises) bails to the
    interpreted ``Length``, which reports the real ``LengthInvalid``; an out-of-range
    length bails there too. A non-integer bound (unusual for a length) is left to the
    interpreted validator, so its own type handling stays the single source of truth.
    """
    low, high = schema.min, schema.max
    if low is None and high is None:
        return []
    if (low is not None and not isinstance(low, int)) or (
        high is not None and not isinstance(high, int)
    ):
        return None
    name = f"_len{tag}"
    lines = [
        "        try:",
        f"            {name} = len(_v)",
        # A len that raises is a failure the interpreted Length reports, not a crash;
        # match its ``except Exception`` so any __len__ blowup defers, never leaks.
        "        except Exception:",
        "            raise _Bail",
    ]
    if low is not None:
        lines += [f"        if {name} < {low!r}:", "            raise _Bail"]
    if high is not None:
        lines += [f"        if {name} > {high!r}:", "            raise _Bail"]
    return lines


def _inline_match(schema: Any, namespace: dict[str, Any], tag: str) -> list[str] | None:
    """Inline a ``Match`` regular-expression check; ``_v`` is unchanged.

    The compiled pattern is bound live (not re-emitted as source), and ``.match`` is
    used exactly as the interpreted ``Match`` does (anchored at the start). A value the
    pattern does not match, or one ``.match`` cannot take (a non-string ``TypeError``),
    bails to the interpreted ``Match`` for the real ``MatchInvalid``.
    """
    name = f"_re{tag}"
    namespace[name] = schema.pattern
    return [
        "        try:",
        f"            if {name}.match(_v) is None:",
        "                raise _Bail",
        "        except TypeError:",
        "            raise _Bail",
    ]


def _emit_membership(name: str) -> list[str]:
    """Emit a membership bail-check that survives a value ``in`` cannot test.

    A value not in ``name`` bails to the interpreted engine, which reports the real
    "not a valid option" error. ``name`` is either the live ``In`` container or the
    frozenset of an all-literal ``Any``. An unhashable value (a list, a dict) raises
    ``TypeError`` from ``in`` against a set, and a value whose comparison overflows (a
    ``decimal.InvalidOperation``, an ``ArithmeticError``) raises that; the interpreted
    ``In`` catches both and reports a miss, so the inline form catches both too and
    bails rather than letting either crash or leak.
    """
    # The inner ``raise _Bail`` is not caught by the ``except`` (``_Bail`` is
    # neither error); testing inline avoids a ``_hit`` store-and-load per check.
    return [
        "        try:",
        f"            if _v not in {name}:",
        "                raise _Bail",
        "        except (TypeError, ArithmeticError):",
        "            raise _Bail",
    ]


def _inline_in(schema: Any, namespace: dict[str, Any], tag: str) -> list[str] | None:
    """Inline a plain ``In`` membership test; ``_v`` is unchanged.

    The live ``schema.container`` is bound, not a snapshot, so membership matches the
    interpreted ``In`` exactly: it reflects a later mutation of the container and
    defers to the container's own ``__contains__``. A frozenset stays O(1) and a list
    stays O(n), the same cost the interpreted validator pays, so binding live trades
    no speed against the engine, it only forgoes a compile-time set upgrade the engine
    never did either.
    """
    if schema.fold_case or schema.space is not None:
        return None
    name = f"_in{tag}"
    namespace[name] = schema.container
    return _emit_membership(name)


def _inline_type(schema: type, namespace: dict[str, Any], tag: str) -> list[str] | None:
    """Inline an isinstance check for a plain (non-Enum) type; ``_v`` is unchanged."""
    if issubclass(schema, Enum):
        return None
    namespace[f"_ty{tag}"] = schema
    return [f"        if not isinstance(_v, _ty{tag}):", "            raise _Bail"]


def _inline_all(schema: Any, namespace: dict[str, Any], tag: str) -> list[str] | None:
    """Inline an ``All`` chain, bailing the whole chain if a branch is not inlinable.

    The chain tracks when ``_v`` is pinned to a numeric type: after an inlined
    ``Coerce(int)``/``Coerce(float)`` succeeds, a following ``Range``'s type guard
    is provably dead and is elided (``All(Coerce(int), Range(...))`` is the
    dominant hot-path composition). ``Range`` and ``In`` leave ``_v`` unchanged,
    so the knowledge survives them; any other branch conservatively resets it.
    """
    coerce_cls, range_cls, in_cls, _, _, _, _ = _validator_types()
    chained: list[str] = []
    numeric = False
    for position, sub in enumerate(schema.validators):
        if numeric and isinstance(sub, range_cls):
            sub_lines = _inline_range(sub, type_checked=True)
        else:
            sub_lines = _inline_value(sub, namespace, f"{tag}_{position}")
        if sub_lines is None:
            return None
        chained.extend(sub_lines)
        if isinstance(sub, coerce_cls):
            # The lines were emitted, so ``_inline_coerce`` accepted the target.
            numeric = sub.type is int or sub.type is float
        elif not isinstance(sub, (range_cls, in_cls)):
            numeric = False
    return chained


def _inline_any(schema: Any, namespace: dict[str, Any], tag: str) -> list[str] | None:
    """Inline an ``Any`` (or ``Maybe``) that reduces to a single check; ``_v`` unchanged.

    Three shapes inline. When every branch is a type, ``Any`` exposes ``_types`` as
    ``(type_tuple, allow_none)`` and resolves with one ``isinstance`` (the same fast
    path the engine takes). When every branch is a scalar literal (``Any("a", "b")``,
    the very common enum-like choice), the whole thing is a membership test, so it
    inlines as a frozenset ``in`` exactly like ``In``. Floats are excluded so a ``nan``
    branch (which ``==`` never matches but ``in`` would, by identity) stays interpreted.
    And ``Maybe(X)`` (``Any(X, None)``, one inlinable branch plus ``None``) inlines as a
    ``None`` guard around ``X``.

    A general mixed ``Any`` is *not* inlined as a fall-through cascade: an inline
    branch raises ``_Bail`` both on a real failure and on a deferral (``Coerce(int)``
    bails on a float so the interpreted ``Coerce`` can truncate it). In a cascade a
    deferral-bail would wrongly try the next branch, which might match a value the
    earlier branch only meant to defer (``Any(Coerce(int), float)`` on ``1.5`` would
    return ``1.5`` instead of ``1``). So those stay with the closure, which is correct.
    ``Maybe(X)`` is safe because ``None`` is disjoint from every non-``None`` value: a
    non-``None`` value validates against ``X`` alone, whose bail defers the whole ``Any``.
    """
    types = schema._types  # noqa: SLF001
    if types is not None:
        type_tuple, allow_none = types
        namespace[f"_an{tag}"] = type_tuple
        guard = "_v is not None and " if allow_none else ""
        return [
            f"        if {guard}not isinstance(_v, _an{tag}):",
            "            raise _Bail",
        ]

    branches = schema.validators
    if all(
        branch is None or isinstance(branch, (str, bytes, int)) for branch in branches
    ):
        namespace[f"_anin{tag}"] = frozenset(branches)
        return _emit_membership(f"_anin{tag}")

    non_none = [branch for branch in branches if branch is not None]
    if len(non_none) == 1 and len(non_none) < len(branches):
        inner = _inline_value(non_none[0], namespace, tag)
        if inner is not None:
            return ["        if _v is not None:", *["    " + line for line in inner]]
    return None


# The validator classes ``_inline_validator`` dispatches on, bound on first use: a
# module-level import would cycle (``probatio.schema`` imports this module, and the
# validator package imports ``probatio.schema``), and a per-call import was a
# measurable slice of generation cost. Generation first runs long after both
# modules are initialized, so the lazy binding always succeeds.
_VALIDATOR_TYPES: _ValidatorTypes | None = None


def _validator_types() -> _ValidatorTypes:
    """Return ``(Coerce, Range, In, AnyValidator, All, Length, Match)``, imported once."""
    global _VALIDATOR_TYPES  # noqa: PLW0603 - a write-once import cache
    if _VALIDATOR_TYPES is None:
        from probatio.validators.coerce import Coerce  # noqa: PLC0415
        from probatio.validators.combinators import All  # noqa: PLC0415
        from probatio.validators.combinators import Any as AnyValidator  # noqa: PLC0415
        from probatio.validators.comparison import In, Length, Range  # noqa: PLC0415
        from probatio.validators.strings import Match  # noqa: PLC0415

        _VALIDATOR_TYPES = (Coerce, Range, In, AnyValidator, All, Length, Match)
    return _VALIDATOR_TYPES


def _inline_validator(  # noqa: PLR0911 - a flat one-per-validator type dispatch
    schema: Any, namespace: dict[str, Any], tag: str
) -> list[str] | None:
    """Dispatch a non-type value schema to its inline emitter, or ``None``."""
    coerce_cls, range_cls, in_cls, any_cls, all_cls, length_cls, match_cls = (
        _validator_types()
    )

    if isinstance(schema, coerce_cls):
        return _inline_coerce(schema.type)
    if isinstance(schema, range_cls):
        return _inline_range(schema)
    if isinstance(schema, in_cls):
        return _inline_in(schema, namespace, tag)
    if isinstance(schema, any_cls):
        return _inline_any(schema, namespace, tag)
    if isinstance(schema, all_cls):
        return _inline_all(schema, namespace, tag)
    if isinstance(schema, length_cls):
        return _inline_length(schema, tag)
    if isinstance(schema, match_cls):
        return _inline_match(schema, namespace, tag)
    return None


def _inline_sequence(
    schema: list[Any], namespace: dict[str, Any], tag: str
) -> list[str] | None:
    """Inline a single-element list schema (``[str]``, ``[All(Coerce(int), ...)]``).

    Each item is validated by the element's own inline lines, with ``_v`` reused as
    the loop variable, and the rebuilt list is left in ``_v``. Only a plain ``list``
    is taken (``type(_v) is list``); a tuple, set, namedtuple, or list subclass bails
    to the interpreted sequence validator, which rebuilds the data's own type and
    reports the full per-item errors. A multi-element list (``[a, b]``, an each-item
    union) or a non-inlinable element also bails. The new list is fresh, so it never
    aliases the input, matching the interpreted validator.
    """
    if len(schema) != 1:
        return None
    element = _inline_value(schema[0], namespace, f"{tag}s")
    if element is None:
        return None
    src, seq = f"_src{tag}", f"_seq{tag}"
    return [
        "        if type(_v) is not list:",
        "            raise _Bail",
        f"        {src} = _v",
        f"        {seq} = []",
        f"        for _v in {src}:",
        # The element lines sit at the field-body indent; shift them one level deeper
        # to live inside the per-item loop.
        *["    " + line for line in element],
        f"            {seq}.append(_v)",
        f"        _v = {seq}",
    ]


def _inline_value(schema: Any, namespace: dict[str, Any], tag: str) -> list[str] | None:
    """Return inline lines validating ``_v`` against ``schema``, or ``None``.

    The lines leave the validated (and for ``Coerce``, transformed) value in the
    local ``_v`` and raise ``_Bail`` on anything they cannot handle, so the caller
    falls back to the interpreted validator. ``None`` means the schema is not one
    this cut inlines, and the caller calls the compiled closure instead.
    """
    if isinstance(schema, type):
        return _inline_type(schema, namespace, tag)
    if isinstance(schema, list):
        return _inline_sequence(schema, namespace, tag)
    return _inline_validator(schema, namespace, tag)


def _maybe_compile_nested(check_value: Any) -> Any:
    """Compile a nested mapping value, so the inner mapping runs generated too.

    A nested dict value (``"data": {...}``) is validated by a ``_MappingValidator``
    closure; generating it turns that inner per-key loop into straight-line code as
    well, which is most of why a flat schema compiles well but a nested one barely
    did. The compiled inner bails to its own interpreted validator, so a failure deep
    in the tree still produces the right errors, paths, and order. Anything that does
    not generate (a recursive ``$ref``, an unsupported shape) keeps its interpreted
    validator unchanged.
    """
    if not isinstance(check_value, _MappingValidator):
        return check_value
    generated = compile_mapping(check_value)
    return generated if generated is not None else check_value


def _emit_field(
    index: int, candidate: _Candidate, namespace: dict[str, Any], target: str
) -> list[str]:
    """Emit the fast-path lines for one literal key, storing into ``target``.

    ``target`` is the left-hand side the validated value is assigned to: ``out[k]``
    for a plain mapping, or a local ``_a{i}`` when the result is splatted straight
    into a dataclass constructor (so no intermediate dict is built).
    """
    krepr = repr(candidate.key_schema)
    value_type = candidate.value_type
    inline = (
        None
        if value_type is not None
        else _inline_value(candidate.value_schema, namespace, str(index))
    )

    if value_type is not None:
        namespace[f"_t{index}"] = value_type
        store = [
            f"        if isinstance(_v, _t{index}):",
            f"            {target} = _v",
            "        else:",
            "            raise _Bail",
        ]
    elif inline is not None:
        store = [*inline, f"        {target} = _v"]
    else:
        namespace[f"_c{index}"] = _maybe_compile_nested(candidate.check_value)
        store = [
            "        try:",
            f"            {target} = _c{index}(_v)",
            "        except _Invalid:",
            "            raise _Bail",
        ]

    if candidate.required and isinstance(candidate.default, Undefined):
        # A required key with no default fetches by subscript: one specialized
        # ``BINARY_SUBSCR`` instead of a bound ``dict.get`` call plus a sentinel
        # test per field. The ``KeyError`` fires only when the key is missing,
        # which is the failure path and bails to the interpreted engine anyway.
        return [
            "    try:",
            f"        _v = data[{krepr}]",
            "    except KeyError:",
            "        raise _Bail",
            "    else:",
            *store,
        ]

    lines = [f"    _v = data.get({krepr}, _MISSING)", "    if _v is _MISSING:"]
    if not isinstance(candidate.default, Undefined):
        namespace[f"_d{index}"] = candidate.default
        lines.append(f"        _v = _d{index}()")
        lines.append("        if isinstance(_v, _UNDEFINED_CLS):")
        lines.append("            raise _Bail")
        lines.extend(store)
    else:
        # Optional, no default: an absent key is simply not stored.
        lines.append("        pass")

    lines.append("    else:")
    lines.extend(store)
    return lines


def _emit_extra(
    extra: int, allowed: frozenset[Any], namespace: dict[str, Any]
) -> list[str]:
    """Emit the extra-key handling for the given policy, binding what it needs."""
    if extra == PREVENT_EXTRA:
        # The keys view superset-checks against the allowed set in C; the prebound
        # method skips a rich-comparison dispatch per call. An unexpected key bails
        # so the interpreted path reports it (with its suggestion).
        namespace["_issuperset"] = allowed.issuperset
        return ["    if not _issuperset(data.keys()):", "        raise _Bail"]
    if extra == ALLOW_EXTRA:
        namespace["_allowed"] = allowed
        return [
            "    for _k in data:",
            "        if _k not in _allowed:",
            "            out[_k] = data[_k]",
        ]
    # REMOVE_EXTRA drops unknown keys, which is what simply not copying them does.
    return []


def compile_mapping(
    validator: _MappingValidator,
    *,
    construct: type | None = None,
    fallback: Callable[[Any], Any] | None = None,
) -> Callable[[Any], Any] | None:
    """Generate a fast success-path validator for ``validator``, or ``None``.

    Returns ``None`` (the schema stays interpreted) unless the mapping is the
    simple shape this cut handles. With ``construct`` set (a dataclass type), each
    field is validated into a local and splatted straight into the constructor
    (``Type(name=_a0, age=_a1, ...)``), with no intermediate dict, fusing the
    mapping validation and the object construction; ``fallback`` is then the
    interpreted validator that does both, used on any bail. Construction needs every
    field present (each dataclass field is required or carries its default, so the
    locals are always assigned), so an ``ALLOW_EXTRA`` mapping (which keeps unknown
    keys the constructor would reject) is not generated.
    """
    if not _is_generatable(validator):
        return None
    if construct is not None and validator._extra == ALLOW_EXTRA:  # noqa: SLF001
        return None

    candidates = validator._candidates  # noqa: SLF001
    namespace: dict[str, Any] = {
        "_MISSING": _MISSING,
        "_Bail": _Bail,
        "_Invalid": Invalid,
        "_UNDEFINED_CLS": Undefined,
        "_interpreted": validator if fallback is None else fallback,
        "_Type": construct,
    }
    allowed = frozenset(candidate.key_schema for candidate in candidates)
    if construct is None:
        # One ``type()`` read serves both the foreign-type guard and the out-dict
        # setup, so the exact-dict case (nearly every call) pays one identity test.
        # A plain dict stays plain; a dict subclass is preserved (the engine does
        # so); a foreign Mapping or wrong type keeps the interpreted path, which
        # accepts the Mapping superset and raises the right type error.
        prologue = [
            "    _dt = type(data)",
            "    if _dt is dict:",
            "        out = {}",
            "    elif isinstance(data, dict):",
            "        out = _dt()",
            "    else:",
            "        return _interpreted(data)",
        ]
    else:
        # The fused constructor path builds no out dict; just guard the type.
        prologue = [
            "    if type(data) is not dict and not isinstance(data, dict):",
            "        return _interpreted(data)",
        ]

    # The field and extra-key lines are emitted at the function-body indent; they go
    # inside the ``try`` here, so they are shifted one level deeper.
    body: list[str] = []
    kwargs: list[str] = []
    for index, candidate in enumerate(candidates):
        if construct is None:
            target = f"out[{candidate.key_schema!r}]"
        else:
            target = f"_a{index}"
            kwargs.append(f"{candidate.key_schema}=_a{index}")
        body += [
            "    " + line for line in _emit_field(index, candidate, namespace, target)
        ]
    body += [
        "    " + line
        for line in _emit_extra(validator._extra, allowed, namespace)  # noqa: SLF001
    ]

    if not body:
        # A zero-field mapping with REMOVE_EXTRA emits nothing into the ``try``
        # (no fields, no extra-key copy), which would be a syntax error; a bare
        # ``pass`` keeps the block valid and still bails on a non-dict.
        body.append("        pass")

    tail = f"    return _Type({', '.join(kwargs)})" if construct else "    return out"
    lines = [
        "def _validate(data):",
        *prologue,
        "    try:",
        *body,
        "    except _Bail:",
        "        return _interpreted(data)",
        # Construction (if any) runs outside the try, so a dataclass __init__ error
        # propagates as itself, exactly as the interpreted constructor lets it.
        tail,
    ]

    exec(_compile_source("\n".join(lines)), namespace)  # noqa: S102 - trusted schema
    return namespace["_validate"]  # type: ignore[no-any-return]


def compile_sequence(
    schema: Any, fallback: Callable[[Any], Any]
) -> Callable[[Any], Any] | None:
    """Generate a fast success-path validator for a single-element list schema.

    A top-level ``Schema([element])`` is a sequence of one element schema, validated
    interpreted by ``_SequenceValidator`` as a chain of validator calls per item.
    This unrolls it into a generated loop with the element inlined, the same
    ``_inline_sequence`` a list-valued mapping field already uses, so each item costs
    straight-line code rather than a stack of calls. Returns ``None`` (the schema
    stays interpreted) unless ``schema`` is a single-element list whose element
    inlines; ``fallback`` is the interpreted validator, used on any bail and for a
    non-list input (a tuple, a list subclass), which it rebuilds as its own type.
    """
    namespace: dict[str, Any] = {"_Bail": _Bail, "_interpreted": fallback}
    inline = (
        _inline_sequence(schema, namespace, "0") if isinstance(schema, list) else None
    )
    if inline is None:
        return None

    # ``_inline_sequence`` already guards ``type(_v) is not list`` and leaves the
    # rebuilt list in ``_v``; here ``_v`` starts as the incoming data.
    lines = [
        "def _validate(data):",
        "    _v = data",
        "    try:",
        *inline,
        "    except _Bail:",
        "        return _interpreted(data)",
        "    return _v",
    ]
    exec(_compile_source("\n".join(lines)), namespace)  # noqa: S102 - trusted schema
    return namespace["_validate"]  # type: ignore[no-any-return]
