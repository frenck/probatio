"""Combinators: validators built from other validators.

``All`` applies every validator in turn, chaining the output forward, and all
must pass. ``Any`` returns the first validator that accepts the value and fails
only when none do. ``And`` and ``Or`` are the conventional aliases.

The combinator named ``Any`` shadows ``typing.Any`` inside this module, so the
typing one is referred to as ``typing.Any`` throughout.
"""

from __future__ import annotations

import copy
import typing
from collections.abc import Mapping

from probatio.error import (
    AllInvalid,
    AnyInvalid,
    Invalid,
    MultipleInvalid,
    NotEnoughValid,
    SchemaError,
    TooManyValid,
)
from probatio.schema import PREVENT_EXTRA, Schema, compile_schema
from probatio.validators._base import _SafeValidator

# Sentinel for "this branch pins no literal at the discriminator key", so ``None``
# stays usable as a real tag value.
_NO_TAG = object()


def _is_literal_tag(value: typing.Any) -> bool:
    """Whether a value can be a discriminator tag: a hashable, plain literal.

    A type (``int``) or a validator (``In([...])``, a ``Schema``) is not a tag, so a
    branch whose discriminator key maps to one of those is not auto-routable.
    """
    if isinstance(value, type) or callable(value):
        return False
    try:
        hash(value)
    except TypeError:
        return False
    return True


def _branch_holds_mapping(node: typing.Any) -> bool:
    """Whether a node holds a dict schema the rebind's extra policy would reach.

    The rebind recompiles a branch under the new policy, which reaches a mapping
    directly, through a sequence, or through a nested combinator (combinators
    re-thread the policy too). It does not reach into a nested ``Schema`` or a
    wrapper like ``Maybe`` (they compile their own contents under their own
    policy), so those are leaves here.
    """
    if isinstance(node, dict):
        return True
    if isinstance(node, list | tuple | set | frozenset):
        return any(_branch_holds_mapping(element) for element in node)

    children = getattr(node, "validators", None)
    if isinstance(children, list):
        return any(_branch_holds_mapping(child) for child in children)
    return False


class _Combinator(_SafeValidator):
    """Base for the combinators, threading an enclosing schema's extra policy in.

    A combinator compiles its branches at construction with the strict default
    extra policy. When a ``Schema`` wraps it with a different ``extra``, the schema
    rebinds it through ``__probatio_with_extra__``, which recompiles the branches
    under that policy on a copy. That carries the policy into dict schemas nested
    in the combinator, the way voluptuous compiles them, without mutating the
    shared combinator instance.
    """

    _extra: int
    validators: list[typing.Any]

    def _compile_branches(self) -> None:  # pragma: no cover - each combinator overrides
        """Recompile ``self.validators`` into ``self._compiled`` under ``self._extra``."""
        raise NotImplementedError

    def __probatio_child_schemas__(self) -> tuple[typing.Any, ...]:
        """Return the raw child schemas this combinator wraps, for ``Self`` detection."""
        return tuple(self.validators)

    def __probatio_needs_extra__(self) -> bool:
        """Whether a non-strict extra could reach a nested mapping in the branches.

        The extra policy only changes how a dict schema compiles, so a combinator
        whose branches hold no mapping (``Any(str, [str])``) compiles identically
        under any policy and need not be rebound, skipping the copy and recompile.
        """
        return any(_branch_holds_mapping(branch) for branch in self.validators)

    def __probatio_with_extra__(self, extra: int) -> _Combinator:
        """Return a copy of this combinator recompiled under ``extra``.

        The enclosing ``Schema`` only rebinds when its policy differs from the
        combinator's strict default, so this recompiles on a fresh copy and never
        touches the shared instance.
        """
        clone = copy.copy(self)
        clone._extra = extra  # noqa: SLF001
        clone._compile_branches()  # noqa: SLF001

        return clone


def _branch_label(branch: typing.Any) -> str | None:
    """Return a short label for an ``Any`` branch, or None when it has no clear one.

    A branch names something concrete when it is a type (its name), ``None``, or
    a scalar literal (its repr). A validator branch (a ``Range``, a callable) has
    no such label.
    """
    if branch is None or branch is type(None):
        return "None"
    if isinstance(branch, type):
        return branch.__name__
    if isinstance(branch, str | int | float | bool):
        return repr(branch)
    return None


def _expected_label(validators: list[typing.Any]) -> str | None:
    """Join the branch labels as ``a or b or c``, or None if any branch lacks one.

    Drives ``Any``'s default error message: when every branch is labelable the
    failure can say "expected int or None" instead of voluptuous's terse "expected
    int" (first branch only) or "not a valid value". When a branch is an arbitrary
    validator, there is no clean label, so the combined message is skipped and the
    nearest branch error speaks for itself.
    """
    labels: list[str] = []
    for branch in validators:
        label = _branch_label(branch)
        if label is None:
            return None
        labels.append(label)

    return " or ".join(labels) if labels else None


def _run_any(
    candidates: list[typing.Any],
    value: typing.Any,
    msg: str | None,
    miss_label: str | None,
) -> typing.Any:
    """Return the first candidate that accepts the value, else raise.

    On a miss: a custom ``msg`` wins; otherwise, when every branch is labelable,
    a single descriptive ``AnyInvalid("expected a or b")`` is raised (issue #412),
    which deliberately diverges from voluptuous's terser message. Failing that
    (a validator branch with no label), the error from the branch that reached the
    deepest path is surfaced, the way voluptuous does. The best error is tracked
    bare and wrapped once, so a failing ``Any`` allocates no per-branch wrapper.
    """
    best: Invalid | None = None
    best_depth = -1
    for compiled in candidates:
        try:
            return compiled(value)
        except Invalid as exc:
            depth = len(exc.path)
            if depth > best_depth:
                best, best_depth = exc, depth

    if msg is not None:
        raise AnyInvalid(msg)
    if miss_label is not None:
        raise AnyInvalid(
            translation_key="expected_type",
            placeholders={"expected": miss_label},
        )
    if best is None:
        raise AnyInvalid(translation_key="no_valid_value")
    if isinstance(best, MultipleInvalid):
        raise best
    raise MultipleInvalid([best])


def _combinator_repr(combinator: typing.Any) -> str:
    """Render ``Name(v, ..., msg=...)``, matching voluptuous's combinator repr.

    The repr shows up in an error path when a combinator is used as a mapping
    key (``Required(Any("a", "b"))``), so it must match voluptuous byte for byte.
    """
    body = ", ".join(repr(validator) for validator in combinator.validators)
    return f"{type(combinator).__name__}({body}, msg={combinator.msg!r})"


class All(_Combinator):
    """Apply every validator in turn; all must pass, the output chains forward."""

    def __init__(
        self,
        *validators: typing.Any,
        msg: str | None = None,
        required: bool = False,
        **kwargs: typing.Any,
    ) -> None:
        """Keep the raw validators (for introspection) and compile each.

        ``required`` propagates into mapping sub-schemas; other keyword arguments
        are accepted and ignored, matching voluptuous.
        """
        del kwargs
        self.validators = list(validators)
        self.msg = msg
        self.required = required
        self._extra = PREVENT_EXTRA
        self._compile_branches()

    def _compile_branches(self) -> None:
        """Compile each validator under the current extra policy."""
        self._compiled = [
            compile_schema(validator, required=self.required, extra=self._extra)
            for validator in self.validators
        ]
        # The two-validator form (``All(Coerce(int), Range(...))``) dominates real
        # schemas, so ``__call__`` unrolls it; precompute the pair here, the single
        # place ``self._compiled`` is (re)built.
        self._pair = tuple(self._compiled) if len(self._compiled) == 2 else None

    def __call__(self, value: typing.Any) -> typing.Any:
        """Run each validator in sequence, returning the final value.

        A failure raises ``MultipleInvalid`` (matching voluptuous), unless a
        custom ``msg`` was given, in which case it raises a bare ``AllInvalid``.

        The ``try`` wraps the whole loop rather than each step: the loop stops at
        the first failing validator either way, so one handler per call keeps the
        hot path (every value runs through here) a tight loop. The unrolled pair
        path shares those handlers, so a branch failure behaves identically.
        """
        try:
            if (pair := self._pair) is not None:
                return pair[1](pair[0](value))
            for compiled in self._compiled:
                value = compiled(value)
        except MultipleInvalid as exc:
            if self.msg is not None:
                raise AllInvalid(self.msg) from exc
            raise
        except Invalid as exc:
            if self.msg is not None:
                raise AllInvalid(self.msg) from exc
            raise MultipleInvalid([exc]) from exc

        return value

    def __repr__(self) -> str:
        """Render as ``All(v, ..., msg=...)``."""
        return _combinator_repr(self)


def _type_tuple(
    validators: list[typing.Any], compiled: list[typing.Any]
) -> tuple[tuple[type, ...], bool] | None:
    """Return ``(types, allow_none)`` when every branch is a bare type or ``None``.

    Such an ``Any``/``Union`` resolves with a single ``isinstance`` (plus a
    ``value is None`` check when a ``None`` branch is present) instead of calling
    each branch and catching an ``Invalid`` until one matches. Folding ``None`` in
    here keeps the very common ``Any(int, None)`` and ``Any(str, None)`` on the
    fast path. A type check returns its value unchanged, so the matched value is
    just the value. None if any branch is neither a type nor ``None``.
    """
    types: list[type] = []
    allow_none = False
    for raw, branch in zip(validators, compiled, strict=True):
        if raw is None:
            allow_none = True
            continue
        checked_type = getattr(branch, "checked_type", None)
        if checked_type is None:
            return None
        types.append(checked_type)

    if not types and not allow_none:
        return None
    return tuple(types), allow_none


def _float_superset(
    validators: list[typing.Any], compiled: list[typing.Any]
) -> tuple[tuple[type, ...], bool] | None:
    """Return ``(accept_types, allow_none)`` for an ``Any`` of types plus a float tower.

    Only for a branch set that is otherwise all bare types or ``None`` but for the
    float tower (ADR-017), which coerces an ``int`` and so has no ``checked_type`` to
    inline. The tower cannot fold into the single ``isinstance`` ``_type_tuple`` uses
    (a match may coerce, and branch order decides the result), so this gives the
    weaker but cheap signal ``__call__`` needs: the *superset* of types any branch
    could accept, ``float`` and ``int`` standing in for the tower. A value outside it
    cannot match any branch, so a miss is rejected with one ``isinstance``; a value
    inside it defers to the ordered, coercing ``_run_any``. ``None`` if a branch is
    neither a type, ``None``, nor the float tower, or if no float tower is present.
    """
    types: list[type] = []
    allow_none = False
    has_float_tower = False
    for raw, branch in zip(validators, compiled, strict=True):
        if raw is None:
            allow_none = True
            continue
        if getattr(branch, "is_float_tower", False):
            has_float_tower = True
            # The tower accepts a float or an int (coerced); a bool is excluded by
            # the tower itself, so let it into the ordered path to be rejected there.
            types.append(float)
            types.append(int)
            continue
        checked_type = getattr(branch, "checked_type", None)
        if checked_type is None:
            return None
        types.append(checked_type)

    if not has_float_tower:
        return None
    return tuple(types), allow_none


def _run_typed_any(
    types: tuple[type, ...],
    allow_none: bool,
    value: typing.Any,
    msg: str | None,
    miss_label: str | None,
) -> typing.Any:
    """Resolve an all-type (or None) ``Any``/``Union`` without per-branch exceptions.

    One ``isinstance``, plus a ``value is None`` check when a ``None`` branch is
    present, accepts on the hot path. On a miss a single ``AnyInvalid`` is raised
    with the label precomputed at branch-compile time (every branch is a type,
    so it always labels), without running any branch, so both the match and the
    miss skip the try/except churn.
    """
    if (allow_none and value is None) or isinstance(value, types):
        return value
    if msg is not None:
        raise AnyInvalid(msg)
    if miss_label is not None:
        raise AnyInvalid(
            translation_key="expected_type",
            placeholders={"expected": miss_label},
        )
    # The typed path always labels (every branch is a type), so this fallback
    # is unreachable; it keeps the type checker honest without a cast.
    raise AnyInvalid(translation_key="no_valid_value")  # pragma: no cover


def _run_float_superset_any(
    superset: tuple[tuple[type, ...], bool],
    candidates: list[typing.Any],
    value: typing.Any,
    msg: str | None,
    miss_label: str | None,
) -> typing.Any:
    """Resolve a types-plus-float-tower ``Any``, rejecting a miss with one isinstance.

    A value outside the accept superset cannot match any branch, so it is rejected
    without running one (the common error path). A value inside it might match, and a
    float branch may coerce, so it defers to the ordered ``_run_any`` which decides
    correctly. The tower keeps its fast rejection without giving up branch order or
    coercion on a hit.
    """
    accept_types, allow_none = superset
    if (allow_none and value is None) or isinstance(value, accept_types):
        return _run_any(candidates, value, msg, miss_label)
    if msg is not None:
        raise AnyInvalid(msg)
    if miss_label is not None:
        raise AnyInvalid(
            translation_key="expected_type",
            placeholders={"expected": miss_label},
        )
    # A float tower always labels (float and every other branch is a type), so this
    # fallback is unreachable; kept to satisfy the type checker without a cast.
    raise AnyInvalid(translation_key="no_valid_value")  # pragma: no cover


class Any(_Combinator):
    """Return the first validator that accepts the value; fail if none do."""

    # Marks Any as a "complex" mapping key: ``Required(Any("a", "b"))`` requires
    # at least one of the listed keys present (voluptuous 0.16.0, PR #534). The
    # compiler reads this by attribute to avoid importing Any (a circular import).
    is_complex_key = True

    def __init__(
        self,
        *validators: typing.Any,
        msg: str | None = None,
        required: bool = False,
        **kwargs: typing.Any,
    ) -> None:
        """Keep the raw validators (for introspection) and compile each.

        ``required`` propagates into mapping sub-schemas; other keyword arguments
        are accepted and ignored, matching voluptuous.
        """
        del kwargs
        self.validators = list(validators)
        self.msg = msg
        self.required = required
        self._extra = PREVENT_EXTRA
        self._compile_branches()

    def _compile_branches(self) -> None:
        """Compile each branch under the current extra policy."""
        self._compiled = [
            compile_schema(validator, required=self.required, extra=self._extra)
            for validator in self.validators
        ]
        self._types = _type_tuple(self.validators, self._compiled)
        # When a float tower blocks the single-isinstance path, keep a cheap miss
        # rejection via the accept superset (ADR-017). Only computed when needed.
        self._float_superset = (
            _float_superset(self.validators, self._compiled)
            if self._types is None
            else None
        )
        # Prebuilt so a miss does not re-derive a label that only depends on the
        # branch labels, which are fixed here; the sentence itself renders lazily
        # from the "expected_type" catalog template.
        self._expected = _expected_label(self.validators)

    def __call__(self, value: typing.Any) -> typing.Any:
        """Try each validator, returning the first that accepts the value."""
        # All-type (or None) branches resolve by one isinstance, on match and miss.
        if self._types is not None:
            return _run_typed_any(*self._types, value, self.msg, self._expected)
        if self._float_superset is not None:
            return _run_float_superset_any(
                self._float_superset, self._compiled, value, self.msg, self._expected
            )
        return _run_any(self._compiled, value, self.msg, self._expected)

    def __repr__(self) -> str:
        """Render as ``Any(v, ..., msg=...)``."""
        return _combinator_repr(self)


class Union(_Combinator):
    """Like ``Any``, but an optional discriminant narrows which validators to try.

    Without a discriminant it behaves like ``Any``. With one, the discriminant is
    called as ``discriminant(value, validators)`` and returns the subset of the
    raw validators to attempt, which is how a tagged/discriminated union picks
    its branch instead of trying every alternative.
    """

    def __init__(
        self,
        *validators: typing.Any,
        msg: str | None = None,
        required: bool = False,
        discriminant: typing.Any = None,
        **kwargs: typing.Any,
    ) -> None:
        """Keep the raw validators (for introspection) and compile each.

        ``required`` propagates into mapping sub-schemas; other keyword arguments
        are accepted and ignored, matching voluptuous.
        """
        del kwargs
        self.validators = list(validators)
        self.msg = msg
        self.required = required
        self.discriminant = discriminant
        self._extra = PREVENT_EXTRA
        self._compile_branches()

    def _compile_branches(self) -> None:
        """Compile each branch under the current extra policy, indexing by id."""
        self._compiled = [
            compile_schema(validator, required=self.required, extra=self._extra)
            for validator in self.validators
        ]
        # Map each raw validator to its compiled form by identity, so a
        # discriminant's chosen subset resolves in one lookup per choice instead
        # of scanning every validator for each choice.
        self._compiled_by_id = {
            id(raw): compiled
            for raw, compiled in zip(self.validators, self._compiled, strict=True)
        }
        self._types = (
            _type_tuple(self.validators, self._compiled)
            if self.discriminant is None
            else None
        )
        # Prebuilt for the same reason as in ``Any._compile_branches``.
        self._expected = _expected_label(self.validators)

    def __call__(self, value: typing.Any) -> typing.Any:
        """Try the (possibly narrowed) candidates, returning the first match."""
        if self.discriminant is None:
            if self._types is not None:
                return _run_typed_any(*self._types, value, self.msg, self._expected)
            return _run_any(self._compiled, value, self.msg, self._expected)
        # A discriminant returns a subset of the raw validators; resolve each to
        # its compiled form, compiling any object it returns that was not among
        # the originals (matching voluptuous, which recompiles the chosen set).
        # Compile a fresh object under the same required and extra policy as the
        # originals, so a discriminant-returned mapping does not lose the Union's
        # ``required`` intent. A fresh object is not cached: it may be short-lived,
        # and caching it by ``id`` would risk a reused id mapping to a stale branch.
        candidates = [
            self._compiled_by_id.get(id(option))
            or compile_schema(option, required=self.required, extra=self._extra)
            for option in self.discriminant(value, self.validators)
        ]
        # The discriminant chose a subset, so the all-branches label would not
        # describe it; let the chosen branch errors surface instead.
        return _run_any(candidates, value, self.msg, None)

    def __repr__(self) -> str:
        """Render as ``Union(v, ..., msg=...)``."""
        return _combinator_repr(self)


class TaggedUnion(Union):
    """A discriminated union: route on one key's value to the matching schema.

    ``TaggedUnion("type", {"grid": GRID, "solar": SOLAR})`` reads ``value["type"]``
    and validates against the single schema listed for that value, so a failure is
    reported against the branch the value selected (a bad ``grid`` field, not "matched
    none of the alternatives"). Pass ``default`` for a schema to fall back to when the
    key's value is not listed; without one, an unlisted value is rejected with the
    valid values named.

    ``cases`` is either a ``{tag: schema}`` mapping, or a list of branches that each
    pin the discriminator as a literal (``{Required("type"): "grid", ...}``), in which
    case the tag is read from each branch so it is written once. The list form only
    fits branches that carry that literal; a branch that does not (its schema never
    mentions the key) needs the mapping form. Either way the routing table is built
    once here, so validation is a single dict lookup.

    This is the readable form of a ``Union`` with a hand-written ``discriminant``, and
    mirrors Home Assistant's ``cv.key_value_schemas``.
    """

    def __init__(
        self,
        key: typing.Any,
        cases: dict[typing.Any, typing.Any] | list[typing.Any] | tuple[typing.Any, ...],
        *,
        default: typing.Any = None,
        msg: str | None = None,
        required: bool = False,
    ) -> None:
        """Store the discriminator key and the value-to-schema cases."""
        self.key = key
        self.cases = self._normalize_cases(key, cases)
        self.default = default
        branches = list(self.cases.values())
        if default is not None:
            branches.append(default)
        super().__init__(
            *branches, msg=msg, required=required, discriminant=self._route
        )

    @staticmethod
    def _normalize_cases(
        key: typing.Any, cases: typing.Any
    ) -> dict[typing.Any, typing.Any]:
        """Return a ``{tag: schema}`` map from either the mapping or the list form."""
        if isinstance(cases, dict):
            return dict(cases)
        if isinstance(cases, (list, tuple)):
            built: dict[typing.Any, typing.Any] = {}
            for index, branch in enumerate(cases):
                tag = TaggedUnion._tag_of(branch, key)
                if tag is _NO_TAG:
                    message = (
                        f"TaggedUnion branch at index {index} pins no literal {key!r} "
                        f"to route on; pass an explicit {{tag: schema}} mapping instead"
                    )
                    raise SchemaError(message)
                if tag in built:
                    message = f"TaggedUnion has more than one branch for tag {tag!r}"
                    raise SchemaError(message)
                built[tag] = branch
            return built
        message = (
            "TaggedUnion cases must be a {tag: schema} mapping, or a list of branches "
            "that each pin the discriminator literal"
        )
        raise SchemaError(message)

    @staticmethod
    def _tag_of(branch: typing.Any, key: typing.Any) -> typing.Any:
        """Read the literal a branch pins at ``key``, or ``_NO_TAG`` if it pins none.

        The branch's raw schema (a ``Schema`` unwraps to it) must be a mapping with the
        discriminator key, and the value there must be a plain literal (a string, an
        int, an enum member), not a type or another validator.
        """
        raw = branch.schema if isinstance(branch, Schema) else branch
        if not isinstance(raw, dict):
            return _NO_TAG
        for candidate, tag in raw.items():
            # A marker key (``Required("type")``) exposes its underlying key as
            # ``.schema``; a plain key is itself.
            underlying = getattr(candidate, "schema", candidate)
            if underlying == key and _is_literal_tag(tag):
                return tag
        return _NO_TAG

    def _route(self, value: typing.Any, alternatives: typing.Any) -> list[typing.Any]:
        """Pick the branch whose case matches ``value[key]``, else the default.

        ``__call__`` only reaches the discriminant path for a mapping, so ``value`` is
        a ``Mapping`` here.
        """
        del alternatives
        try:
            chosen = self.cases.get(value.get(self.key))
        except TypeError:
            # An unhashable discriminator value cannot be a case key: a miss, so with
            # a default set this routes to it.
            chosen = None
        if chosen is not None:
            return [chosen]
        return [self.default] if self.default is not None else []

    def __repr__(self) -> str:
        """Render as a constructor call showing the key and cases."""
        return f"TaggedUnion({self.key!r}, {self.cases!r})"

    def __call__(self, value: typing.Any) -> typing.Any:
        """Route on the key's value, else reject.

        A non-mapping is rejected as such (any ``Mapping`` is accepted, matching the
        rest of the engine, not just ``dict``). A mapping whose discriminator value is
        not a listed tag is rejected at the key, naming the valid tags, unless a
        ``default`` was given.
        """
        if not isinstance(value, Mapping):
            raise Invalid(self.msg, translation_key="expected_mapping")
        try:
            known = value.get(self.key) in self.cases
        except TypeError:
            # An unhashable discriminator value is not a listed tag.
            known = False
        if known or self.default is not None:
            # Union's discriminant path validates the chosen branch and surfaces its
            # own errors.
            return super().__call__(value)
        raise Invalid(
            self.msg,
            path=[self.key],
            translation_key="expected_discriminator",
            placeholders={"key": self.key, "values": list(self.cases)},
        )


class SomeOf(_Combinator):
    """Require the value to pass a bounded number of the given validators.

    The output of each passing validator feeds the next, like ``All``. At least
    one of ``min_valid`` and ``max_valid`` must be given: too few passes raises
    ``NotEnoughValid``, too many raises ``TooManyValid``.
    """

    def __init__(
        self,
        validators: typing.Any,
        min_valid: int | None = None,
        max_valid: int | None = None,
        msg: str | None = None,
        required: bool = False,
        **kwargs: typing.Any,
    ) -> None:
        """Compile each validator and store the pass-count bounds."""
        del kwargs
        if min_valid is None and max_valid is None:
            message = (
                "when using SomeOf you should specify at least one of "
                "min_valid and max_valid"
            )
            raise ValueError(message)
        self.validators = list(validators)
        self.min_valid = min_valid or 0
        self.max_valid = max_valid if max_valid is not None else len(self.validators)
        self.msg = msg
        self.required = required
        self._extra = PREVENT_EXTRA
        self._compile_branches()

    def _compile_branches(self) -> None:
        """Compile each validator under the current extra policy."""
        self._compiled = [
            compile_schema(validator, required=self.required, extra=self._extra)
            for validator in self.validators
        ]

    def __call__(self, value: typing.Any) -> typing.Any:
        """Run every validator, returning the value if the pass count is in range."""
        errors: list[Invalid] = []
        for compiled in self._compiled:
            try:
                value = compiled(value)
            except Invalid as exc:
                errors.append(exc)

        passed = len(self._compiled) - len(errors)
        if self.min_valid <= passed <= self.max_valid:
            return value

        message = self.msg or ", ".join(str(error) for error in errors)
        if passed > self.max_valid:
            # Joining branch errors matches voluptuous, but when every branch
            # passed there are no errors and the message would be empty ("");
            # say what actually went wrong: too many alternatives matched.
            if not message:
                raise TooManyValid(
                    translation_key="too_many_valid",
                    placeholders={"passed": passed, "max": self.max_valid},
                )
            raise TooManyValid(message)
        raise NotEnoughValid(message)


And = All
Or = Any
# voluptuous exposes Switch as an alias of Union (the discriminant-driven form).
Switch = Union
