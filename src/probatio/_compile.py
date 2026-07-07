"""The schema compile walk: turn a declarative schema into a validating callable.

This is the construction hot path, split out of ``schema.py`` as free functions so
it can be accelerated as its own unit (mypyc, ADR-010) without ``Schema`` itself,
which must stay a plain Python class because user code and the dataclass/TypedDict
builders subclass it. ``Schema.__init__`` threads its ``extra``/``required`` into a
small :class:`CompileCtx` and calls :func:`compile_node`; the ``Self`` recursion and
the leaf-validator factories live here too, since the walk produces them.

``Schema`` is referenced only for one ``isinstance`` check (a nested ``Schema`` reused
as a value); it is registered by ``schema.py`` at import through
:data:`_SCHEMA_CLS`, so this module never imports ``schema`` and the two stay free of
an import cycle.
"""

from __future__ import annotations

import sys
from contextvars import ContextVar
from enum import Enum
from typing import TYPE_CHECKING, Any, cast

from probatio._engine import (
    PREVENT_EXTRA,
    CompiledSchema,
    _Candidate,
    _MappingValidator,
    _ObjectValidator,
    _SequenceValidator,
)
from probatio.error import (
    EnumInvalid,
    Invalid,
    ScalarInvalid,
    SchemaError,
    TypeInvalid,
    ValueInvalid,
)
from probatio.markers import (
    UNDEFINED,
    Alias,
    Exclusive,
    Extra,
    Forbidden,
    Inclusive,
    Marker,
    Object,
    Optional,
    Remove,
    Required,
    Self,
    resolve_key,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Collection

# The ``Schema`` class, registered by ``schema.py`` at import time (before any
# compile runs). Held as a plain reference so this module needs no import of
# ``schema``, breaking what would otherwise be an import cycle. Only ``compile_node``
# reads it, to recognize a nested ``Schema`` reused as a mapping value.
_SCHEMA_CLS: Any = None


# The schema currently being compiled, so a ``Self`` reference inside it can be
# resolved to the enclosing (root) schema. Only the outermost compile sets it.
_COMPILING_ROOT: ContextVar[Any] = ContextVar(
    "probatio_compiling_root",
    default=None,
)

# True while ``compile_schema`` compiles a combinator's sub-schema. A ``Self``
# there is wrapped in its own ``Schema(Self)`` (so it has no enclosing mapping at
# compile time), and is resolved at validation time instead of being rejected the
# way a bare ``Schema(Self)`` is.
_COMPILING_FOR_COMBINATOR: ContextVar[bool] = ContextVar(
    "probatio_compiling_for_combinator",
    default=False,
)

# The schema currently being validated, so a ``Self`` deferred from inside a
# combinator resolves to the enclosing schema at call time (when its compile-time
# root was only the throwaway ``Schema(Self)`` wrapper).
_ACTIVE_ROOT: ContextVar[Any] = ContextVar(
    "probatio_active_root",
    default=None,
)

# Current ``Self`` recursion depth, so cyclic or pathologically deep data raises a
# clean Invalid instead of crashing the interpreter with a RecursionError. Each
# ``Self`` level costs several stack frames, so the cap is a fraction of the
# interpreter's recursion limit, read live so a caller that raises the limit for
# genuinely deep data scales with it.
_SELF_DEPTH: ContextVar[int] = ContextVar("probatio_self_depth", default=0)
_SELF_DEPTH_DIVISOR = 8


class recursion_guard:  # noqa: N801 - a context manager, named like contextlib's
    """Bound recursive validation so deep or cyclic data fails cleanly.

    Raises ``Invalid`` once the recursion passes a fraction of the interpreter's
    limit, rather than letting Python crash with ``RecursionError``. Used by
    ``Self``, the JSON Schema decoder's recursive ``$ref`` validators, and the
    recursive-dataclass reference.

    ``cost`` is how much one level counts against the shared budget. It defaults to
    1 (``Self`` and ``$ref``, a couple of stack frames per level); a heavier path
    passes a larger cost so the guard fires before the real stack overflows. The
    budget is shared, so mixed recursion (a ``Self`` schema containing a recursive
    dataclass, say) accounts for both correctly.

    A plain class rather than ``@contextmanager``: it sits on the per-level
    recursion hot path, and skipping the generator machinery is roughly twice as
    fast per ``with``.
    """

    __slots__ = ("_cost", "_token")

    def __init__(self, cost: int = 1) -> None:
        """Store how much this level costs against the shared depth budget."""
        self._cost = cost

    def __enter__(self) -> None:
        """Charge one level, raising ``Invalid`` if the budget is exceeded."""
        depth = _SELF_DEPTH.get() + self._cost
        if depth > sys.getrecursionlimit() // _SELF_DEPTH_DIVISOR:
            raise Invalid(translation_key="recursion_too_deep")
        self._token = _SELF_DEPTH.set(depth)

    def __exit__(self, *exc: object) -> None:
        """Release this level's charge back to the budget."""
        _SELF_DEPTH.reset(self._token)


def _deferred_self(data: Any) -> Any:
    """Validate ``data`` against the schema being validated (a deferred ``Self``).

    Used when ``Self`` was compiled inside a combinator, so its enclosing schema
    was not known at compile time. The active root is set by ``Schema.__call__``,
    so a ``Self`` reached only by calling a combinator on its own (never through a
    schema) is a definition error rather than a crash.
    """
    root = _ACTIVE_ROOT.get()
    if root is None:
        message = "Self has no enclosing schema to validate against"
        raise SchemaError(message)

    with recursion_guard():
        return root._compiled(data)  # noqa: SLF001


def _schema_uses_self(node: Any) -> bool:
    """Report whether ``Self`` appears anywhere in a schema definition.

    Only such schemas record an active root when validated (the contextvar is not
    free), so every non-recursive schema skips that cost. The walk descends into
    mappings, sequences, and the raw children of combinators and wrappers; it does
    not enter a nested ``Schema``, which resolves its own ``Self``.
    """
    if node is Self:
        return True
    if isinstance(node, dict):
        return any(
            _schema_uses_self(k) or _schema_uses_self(v) for k, v in node.items()
        )
    if isinstance(node, list | tuple | set | frozenset):
        return any(_schema_uses_self(element) for element in node)
    # A validator that wraps other schemas (a combinator, a sequence shaper,
    # ``Maybe``/``Msg``) exposes them through ``__probatio_child_schemas__``, so the
    # walk reaches them without guessing which attribute each stored them under.
    child_schemas = getattr(node, "__probatio_child_schemas__", None)
    if child_schemas is not None:
        return any(_schema_uses_self(child) for child in child_schemas())
    return False


def _match_any_key(key: Any) -> Any:
    """Return the key unchanged: an ``Extra`` catch-all matches any key."""
    return key


class _TypeCheck:
    """A compiled ``isinstance`` check the engine can inline via ``checked_type``.

    Behaves like the closure ``_compile_type`` used to return when called, but
    exposes the type so the mapping and sequence loops can do the isinstance
    inline and avoid a call per value on the hot path.
    """

    __slots__ = ("_expected", "checked_type")

    def __init__(self, checked_type: type) -> None:
        """Store the type to check and its name for the error message."""
        self.checked_type = checked_type
        self._expected = checked_type.__name__

    def __call__(self, data: Any) -> Any:
        """Require the value to be an instance of the expected type."""
        if not isinstance(data, self.checked_type):
            raise TypeInvalid(
                context={"expected": self._expected},
                translation_key="expected_type",
                placeholders={"expected": self._expected},
            )
        return data


class _FloatCheck:
    """Validate ``float`` honoring the PEP 484 numeric tower: an ``int`` is accepted.

    A bare ``float`` accepts a ``float`` unchanged and an ``int`` normalized to
    ``float``, and rejects everything else (a ``str``, ``None``, and ``bool``, which
    is an ``int`` subclass but not a number a ``float`` field should hold). This is a
    deliberate deviation from voluptuous, whose ``isinstance`` rejects an ``int``
    here (ADR-017): ``5`` genuinely is a valid ``float`` value, and probatio's own
    ``to_json_schema`` already emits ``{"type": "number"}``, which accepts integers.

    It accepts *and coerces* rather than passing the ``int`` through, so a ``float``
    field never ends up holding an ``int`` and the "the type is true" invariant
    holds. Unlike ``_TypeCheck`` it exposes no ``checked_type``, so the mapping and
    sequence engines never inline it as a bare ``isinstance`` (which cannot coerce)
    and always call it, keeping the normalized value.
    """

    __slots__ = ()

    def __call__(self, data: Any) -> Any:
        """Return a ``float`` unchanged, an ``int`` as ``float``, else raise."""
        if isinstance(data, float):
            return data
        if isinstance(data, int) and not isinstance(data, bool):
            return float(data)
        raise TypeInvalid(
            context={"expected": "float"},
            translation_key="expected_type",
            placeholders={"expected": "float"},
        )


# One shared, immutable ``_FloatCheck``: like the ``_TypeCheck`` instances below it
# carries no per-schema state, so every ``float`` schema holds the same one.
_FLOAT_CHECK = _FloatCheck()


# One shared ``_TypeCheck`` per builtin type: these are by far the most common
# type schemas, they cannot grow a ``__probatio_validate__`` (builtins reject
# setattr), and a ``_TypeCheck`` is immutable (slots, never written after init),
# so every schema can hold the same instance instead of allocating its own.
# ``float`` is intentionally absent: it maps to ``_FLOAT_CHECK`` (the numeric
# tower, ADR-017), not a bare ``isinstance``.
_BUILTIN_TYPE_CHECKS: dict[type, _TypeCheck] = {
    builtin: _TypeCheck(builtin)
    for builtin in (
        str,
        int,
        bool,
        bytes,
        bytearray,
        complex,
        list,
        tuple,
        dict,
        set,
        frozenset,
    )
}


class _EnumCheck:
    """Validate against an ``Enum``, accepting a member or one of its values.

    A bare ``Enum`` used as a schema would otherwise validate by ``isinstance``,
    which rejects the member's value, the string a loader hands you, and accepts
    only an already-built member. This accepts a member instance unchanged, or any
    value that maps to one (returning the member), and reports the valid values
    otherwise. It is the built-in consumer of the self-validation idea for the
    stdlib types that cannot carry the protocol method (ADR-007); ``Flag`` and the
    ``IntEnum``/``StrEnum`` family ride here too, since they all subclass ``Enum``.
    """

    __slots__ = ("_enum", "_expected")

    def __init__(self, enum_cls: type[Enum]) -> None:
        """Store the enum type and its name for the error message."""
        self._enum = enum_cls
        self._expected = enum_cls.__name__

    def __call__(self, data: Any) -> Any:
        """Return the matching member, or raise ``EnumInvalid`` listing the values."""
        if isinstance(data, self._enum):
            return data
        try:
            return self._enum(data)
        except (ValueError, TypeError) as exc:
            # ValueError: no member has this value. TypeError: the value is
            # unhashable, so the value-to-member lookup cannot even be tried.
            values = [member.value for member in self._enum]
            raise EnumInvalid(
                context={"expected": self._expected, "values": values},
                translation_key="value_one_of",
                placeholders={"values": values},
            ) from exc


class CompileCtx:
    """The per-build state the compile walk threads instead of a ``Schema``.

    ``extra`` and ``required`` are the enclosing schema's policies, read while
    compiling its keys. ``uses_self`` starts false and is set true the moment a
    ``Self`` (or a combinator branch holding one) is reached, so the walk runs once
    and ``Schema`` reads the result back afterwards.
    """

    __slots__ = ("extra", "required", "uses_self")

    def __init__(self, extra: int, required: bool) -> None:  # noqa: FBT001
        """Start a build with the schema's extra-key and required policies."""
        self.extra = extra
        self.required = required
        self.uses_self = False


def compile_node(schema: Any, ctx: CompileCtx) -> CompiledSchema:  # noqa: PLR0911
    """Dispatch a schema node to the right compiler for its kind."""
    if schema is Self:
        ctx.uses_self = True
        return _compile_self()
    if isinstance(schema, type):
        return _compile_type(schema)
    # Object subclasses dict, so it has to be matched before the dict branch.
    if isinstance(schema, Object):
        return _compile_object(schema, ctx)
    if isinstance(schema, dict):
        return _compile_dict(schema, ctx)
    if isinstance(schema, list | tuple | set | frozenset):
        return _compile_sequence(schema, ctx)
    if (
        _SCHEMA_CLS is not None
        and isinstance(schema, _SCHEMA_CLS)
        and (direct := _compile_nested_schema(schema)) is not None
    ):
        return direct
    if callable(schema):
        # A combinator compiles its branches at construction with the strict
        # default extra. When this schema sets a different policy, rebind the
        # combinator so the policy reaches dict schemas nested inside it
        # (matching voluptuous), on a copy so the shared instance is untouched.
        if ctx.extra != PREVENT_EXTRA:
            rebind = getattr(schema, "__probatio_with_extra__", None)
            # Rebinding only matters when a branch holds a nested mapping (the
            # policy changes how a dict compiles); a combinator of types and
            # lists compiles identically, so skip the copy and recompile.
            needs = getattr(schema, "__probatio_needs_extra__", None)
            if rebind is not None and (needs is None or needs()):
                schema = rebind(ctx.extra)

        # A combinator or wrapper compiled its own branches at construction, so
        # the compile walk never descends into them; detect a ``Self`` nested in
        # one on the branch node itself. Only a node that holds child schemas
        # (``validators``/``validator``) can carry a nested ``Self``, so a plain
        # leaf validator skips the walk entirely.
        if not ctx.uses_self and (
            hasattr(schema, "validators") or hasattr(schema, "validator")
        ):
            ctx.uses_self = _schema_uses_self(schema)

        # probatio's own validators always raise Invalid (never leak a
        # ValueError), so they can be called directly. Arbitrary callables go
        # through the guard that turns a ValueError into an Invalid.
        return (
            cast("CompiledSchema", schema)
            if getattr(schema, "__probatio_safe__", False)
            else _compile_callable(schema)
        )
    return _compile_literal(schema)


def _compile_dict(schema: dict[Any, Any], ctx: CompileCtx) -> CompiledSchema:
    """Compile a mapping schema into a candidate-matching validator."""
    candidates = [_make_candidate(k, v, ctx) for k, v in schema.items()]
    # An Extra catch-all is tried after every named key, regardless of where
    # it sits in the schema dict (matching voluptuous).
    candidates.sort(key=lambda candidate: candidate.key_schema is Extra)
    return _MappingValidator(candidates, ctx.extra)


def _compile_object(schema: Object, ctx: CompileCtx) -> CompiledSchema:
    """Compile an Object schema: validate attributes, then rebuild the object."""
    candidates = [_make_candidate(k, v, ctx) for k, v in schema.items()]
    candidates.sort(key=lambda candidate: candidate.key_schema is Extra)
    mapping = _MappingValidator(candidates, ctx.extra, invalid_msg="object value")
    return _ObjectValidator(mapping, schema.cls)


def _compile_sequence(schema: Collection[Any], ctx: CompileCtx) -> CompiledSchema:
    """Compile a sequence or set; each item must match one element schema.

    A ``Remove`` element matches like its wrapped schema, but a matching item
    is dropped from the result instead of kept (voluptuous semantics), so
    ``[Remove(1), int]`` strips every ``1`` and validates the rest.
    """
    element_checks: list[CompiledSchema] = []
    remove_flags: list[bool] = []
    for element in schema:
        if isinstance(element, Remove):
            element_checks.append(compile_node(element.schema, ctx))
            remove_flags.append(True)
        else:
            element_checks.append(compile_node(element, ctx))
            remove_flags.append(False)

    # Match on the broad category (list/tuple/set/frozenset), not the schema's
    # exact type, so a schema written as a namedtuple instance still accepts a
    # plain tuple (voluptuous semantics). A namedtuple is a tuple subclass, so
    # it lands on ``tuple``.
    schema_type = type(schema)
    base_type = next(
        base for base in (list, tuple, set, frozenset) if issubclass(schema_type, base)
    )
    return _SequenceValidator(base_type, element_checks, remove_flags)


def _make_candidate(key: Any, value_schema: Any, ctx: CompileCtx) -> _Candidate:
    """Turn one ``schema`` item into a compiled candidate."""
    if key is Extra:
        # A catch-all: it matches any key (its check_key returns the key
        # unchanged) and validates the value, so unmatched keys are kept and
        # checked rather than rejected by the extra-key policy.
        return _Candidate(
            key_schema=Extra,
            check_key=_match_any_key,
            check_value=compile_node(value_schema, ctx),
            required=False,
            default=UNDEFINED,
            remove=False,
            is_literal=False,
        )

    # Classify the key's markers into facets: the presence marker that governs
    # it, the bare key underneath, whether it is ``Secret`` (redact its value on
    # failure), the message, the default, and whether it is required. ``Required``
    # and ``Optional`` dominate real schemas, so they are matched by exact type
    # and skip both the isinstance ladder and the chain resolver. A bare key is
    # next. Everything else (the other markers, a lone ``Secret``, or markers
    # nested to compose facets like ``Optional(Secret("password"))``) takes the
    # general path: resolve the chain, then classify with the full ladder.
    # ``marker`` is typed ``Any`` so the facet-specific attributes
    # (``group_of_exclusion``, ``input_names``) read cleanly under their guards.
    marker: Any
    is_alias = is_remove = is_forbidden = is_exclusive = is_inclusive = False
    key_type = type(key)
    if (key_type is Required or key_type is Optional) and not isinstance(
        key.schema,
        Marker,
    ):
        marker = key
        key_schema = key.schema
        secret = False
        msg = key.msg
        is_required = key_type is Required
        is_optional = not is_required
        default = key.default
        required = is_required or (ctx.required and not is_optional)
    elif not isinstance(key, Marker):
        marker = None
        key_schema = key
        secret = False
        msg = None
        is_required = is_optional = False
        default = UNDEFINED
        required = ctx.required
    else:
        facets = resolve_key(key)
        marker = facets.marker
        key_schema = facets.key
        secret = facets.secret
        msg = facets.msg
        # Subtypes are honored (Inclusive and Exclusive are Optional), so the
        # dispatch stays correct for a custom marker subclass too.
        is_required = isinstance(marker, Required)
        is_optional = isinstance(marker, Optional)
        is_alias = isinstance(marker, Alias)
        is_remove = isinstance(marker, Remove)
        is_forbidden = isinstance(marker, Forbidden)
        is_exclusive = isinstance(marker, Exclusive)
        is_inclusive = isinstance(marker, Inclusive)
        if marker is None:
            # A key wrapped only in ``Secret`` carries no presence semantics.
            default = UNDEFINED
            required = ctx.required
        else:
            default = (
                marker.default
                if (is_required or is_optional or is_alias)
                else UNDEFINED
            )
            # An Alias carries its own required flag and is self-contained, so a
            # schema-wide ``required`` does not force it (like Optional).
            required = (
                is_required
                or (is_alias and marker.required)
                or (
                    ctx.required
                    and not (is_optional or is_remove or is_forbidden or is_alias)
                )
            )

    # A ``Secret`` around a type or callable key is rejected inside
    # ``resolve_key`` (the general path above), so it never reaches here.
    if type(key_schema) is str:
        # The overwhelmingly common key shape: a plain string is a literal (not
        # a type, not callable), so skip the classification and the ``compile_node``
        # dispatch ladder it would walk to reach the same equality check.
        is_literal = True
        check_key = _compile_literal(key_schema)
    else:
        is_literal = not (isinstance(key_schema, type) or callable(key_schema))
        check_key = compile_node(key_schema, ctx)
    check_value = compile_node(value_schema, ctx)

    return _Candidate(
        key_schema=key_schema,
        check_key=check_key,
        check_value=check_value,
        required=required,
        default=default,
        remove=is_remove,
        forbidden=is_forbidden,
        is_literal=is_literal,
        secret=secret,
        exclusive_group=(marker.group_of_exclusion if is_exclusive else None),
        exclusive_required=(marker.group_required if is_exclusive else False),
        inclusive_group=(marker.group_of_inclusion if is_inclusive else None),
        msg=msg,
        value_type=getattr(check_value, "checked_type", None),
        key_type=getattr(check_key, "checked_type", None),
        complex_keys=(
            # Required(Any("a", "b")): the candidate keys, so a "none present"
            # failure can report "at least one of [...] is required". Read by
            # attribute to avoid importing Any (circular with combinators).
            list(key_schema.validators)
            if is_required and getattr(key_schema, "is_complex_key", False)
            else None
        ),
        alias_input_names=marker.input_names if is_alias else (),
        value_schema=value_schema,
    )


def _compile_self() -> CompiledSchema:
    """Compile a ``Self`` reference to a deferred call to the root schema.

    ``Self`` as a direct mapping value or sequence element is compiled within
    the enclosing schema, and binds to it immediately. Inside a combinator
    (``Any(Self, ...)``) it is compiled eagerly as its own ``Schema(Self)``,
    so it has no enclosing mapping yet; it is deferred and resolved at
    validation time. A bare ``Schema(Self)`` (Self with nothing around it) has
    no enclosing schema at all and is a definition error.
    """
    # Inside a combinator, Self always defers to the root being validated. A
    # combinator compiles its branches before the enclosing schema exists, so
    # any _COMPILING_ROOT reached here is an intermediate branch schema, not the
    # schema Self refers to. In Any({key: Self}, str) the dict branch compiles
    # as its own Schema and would capture Self; binding to it would trap the
    # recursion in that one branch, so a string leaf never falls through to the
    # sibling str branch. Deferring re-runs the whole combinator instead.
    if _COMPILING_FOR_COMBINATOR.get():
        return _deferred_self

    root = _COMPILING_ROOT.get()
    if root is not None and root.schema is not Self:
        # Direct Self: bind to the enclosing schema now.
        def validate(data: Any) -> Any:
            """Validate recursively against the enclosing schema, depth-guarded."""
            with recursion_guard():
                # root is the enclosing Schema; reading its compiled engine
                # here lets recursion follow whatever engine it is now on.
                return root._compiled(data)  # noqa: SLF001

        return validate

    # A bare Schema(Self), or Self wrapped by a validator that compiles it
    # outside a combinator: there is no enclosing schema to resolve against.
    message = (
        "Self must be a mapping value, sequence element, or combinator "
        "branch, not a schema on its own"
    )
    raise SchemaError(message)


def _compile_type(schema: type) -> CompiledSchema:
    """Compile a type into an isinstance check, or its self-validation (ADR-007).

    A type that knows how to validate a raw value of itself takes precedence
    over the bare ``isinstance``: a ``__probatio_validate__`` classmethod is
    used as the validator (normalized like any callable), and an ``Enum``
    subclass gets value-or-member coercion. Everything else returns a
    ``_TypeCheck``, whose ``checked_type`` the mapping and sequence engines
    read to inline the ``isinstance`` into their loops and skip a call per
    value. Called directly (when not inlined) it behaves like the closure.
    """
    # ``float`` honors the numeric tower (an ``int`` is accepted and normalized),
    # a deliberate deviation from voluptuous's bare ``isinstance`` (ADR-017).
    if schema is float:
        return _FLOAT_CHECK
    # ``type(schema) is type`` excludes metaclass instances, whose custom
    # ``__eq__``/``__hash__`` could otherwise spoof a builtin in the lookup.
    if (
        type(schema) is type
        and (cached := _BUILTIN_TYPE_CHECKS.get(schema)) is not None
    ):
        return cached
    protocol = getattr(schema, "__probatio_validate__", None)
    if callable(protocol):
        return _compile_callable(protocol)
    if issubclass(schema, Enum):
        return _EnumCheck(schema)
    return _TypeCheck(schema)


def _compile_callable(schema: Callable[[Any], Any]) -> CompiledSchema:
    """Compile a callable validator, normalizing the errors it may raise."""

    def validate(data: Any) -> Any:
        """Run the callable, turning a ValueError into an Invalid.

        A standard-library or user callable raises ``ValueError`` with a
        reason ("invalid isoformat string", say). voluptuous discards that
        reason and reports a bare "not a valid value"; probatio keeps it, so
        the message tells you why. The detail is appended only when the
        exception carries one (carry-forward of voluptuous issue #417).
        """
        try:
            return schema(data)
        except Invalid:
            raise
        except ValueError as exc:
            if detail := str(exc):
                raise ValueInvalid(
                    translation_key="not_a_valid_value_detail",
                    placeholders={"detail": detail},
                ) from exc
            raise ValueInvalid(translation_key="not_a_valid_value") from exc

    return validate


def _compile_literal(schema: Any) -> CompiledSchema:
    """Compile a literal into an equality check."""

    def validate(data: Any) -> Any:
        """Require the value to equal the literal."""
        if data != schema:
            raise ScalarInvalid(translation_key="not_a_valid_value")
        return data

    return validate


def _compile_nested_schema(schema: Any) -> CompiledSchema | None:
    """Compile a nested ``Schema`` node to a direct engine delegation, or ``None``.

    A composed schema (a prebuilt ``Schema`` reused as a mapping value or sequence
    element, the way large applications assemble config schemas) would otherwise
    compile as an arbitrary callable: a ValueError guard around the full
    ``Schema.__call__``, several frames per matched value. When the inner engine
    is the mapping or sequence validator, the wrapping adds nothing: those engines
    raise ``MultipleInvalid`` for value failures exactly as ``__call__`` would
    surface it, and their bare wrong-type error aggregates identically because the
    enclosing engine flattens a ``MultipleInvalid`` to the same leaves. So
    composition costs one delegating frame instead. Reading ``_compiled`` live
    (not capturing it) follows the inner schema's own bootstrap and compile swaps.

    ``None`` means "keep the wrapper", in two cases. Inside a combinator, because
    voluptuous resolves ``Any(Schema(int), float)`` on a miss to the branch's own
    error ("expected int"), and the ``MultipleInvalid`` the wrapper raises is what
    preserves that; unwrapping would turn it into the combined ``AnyInvalid``. And
    for a ``Self``-using inner, whose ``__call__`` records the active root that
    ``Self`` resolves against.
    """
    # A lazily-deferred inner must build now: its ``_uses_self`` and engine are read
    # here to decide the delegation, so a half-built one cannot be reasoned about.
    schema._ensure_built()  # noqa: SLF001
    if _COMPILING_FOR_COMBINATOR.get() or schema._uses_self:  # noqa: SLF001
        return None
    # An armed schema parks its engine in ``_interpreted`` (``_compiled`` is the
    # bootstrap); an unarmed one holds it in ``_compiled``.
    engine = schema.__dict__.get("_interpreted", schema._compiled)  # noqa: SLF001
    if not isinstance(engine, (_MappingValidator, _SequenceValidator)):
        return None

    def validate(data: Any) -> Any:
        """Delegate to the nested schema's live engine."""
        return schema._compiled(data)  # noqa: SLF001

    return validate
