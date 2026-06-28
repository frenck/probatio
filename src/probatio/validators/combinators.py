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

from probatio.error import (
    AllInvalid,
    AnyInvalid,
    Invalid,
    MultipleInvalid,
    NotEnoughValid,
    TooManyValid,
)
from probatio.schema import PREVENT_EXTRA, compile_schema
from probatio.validators._base import _SafeValidator


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

    def _compile_branches(self) -> None:  # pragma: no cover - each combinator overrides
        """Recompile ``self.validators`` into ``self._compiled`` under ``self._extra``."""
        raise NotImplementedError

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
    expected: str | None,
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
    if expected is not None:
        message = f"expected {expected}"
        raise AnyInvalid(message)
    if best is None:
        message = "no valid value found"
        raise AnyInvalid(message)
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

    def __call__(self, value: typing.Any) -> typing.Any:
        """Run each validator in sequence, returning the final value.

        A failure raises ``MultipleInvalid`` (matching voluptuous), unless a
        custom ``msg`` was given, in which case it raises a bare ``AllInvalid``.

        The ``try`` wraps the whole loop rather than each step: the loop stops at
        the first failing validator either way, so one handler per call keeps the
        hot path (every value runs through here) a tight loop.
        """
        try:
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


def _type_tuple(compiled: list[typing.Any]) -> tuple[type, ...] | None:
    """Return the branch types if every branch is a plain type check, else None.

    When all of an ``Any``/``Union``'s branches are bare types (``Any(int, str)``)
    a single ``isinstance(value, types)`` decides acceptance, which is much faster
    than calling each branch and catching an ``Invalid`` until one matches. A type
    check returns its value unchanged, so the matched value is just the value.
    """
    types: list[type] = []
    for branch in compiled:
        checked_type = getattr(branch, "checked_type", None)
        if checked_type is None:
            return None
        types.append(checked_type)
    return tuple(types) if types else None


def _run_typed_any(
    types: tuple[type, ...],
    value: typing.Any,
    msg: str | None,
) -> typing.Any:
    """Resolve an all-type ``Any``/``Union`` without per-branch exceptions.

    One ``isinstance`` accepts on the hot path. On a miss, a single descriptive
    ``AnyInvalid("expected int or str")`` is raised, built from the branch type
    names, without running any branch. So both the match and the miss skip the
    try/except churn.
    """
    if isinstance(value, types):
        return value
    if msg is not None:
        raise AnyInvalid(msg)
    expected = " or ".join(branch.__name__ for branch in types)
    message = f"expected {expected}"
    raise AnyInvalid(message)


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
        self._types = _type_tuple(self._compiled)
        self._expected = _expected_label(self.validators)

    def __call__(self, value: typing.Any) -> typing.Any:
        """Try each validator, returning the first that accepts the value."""
        # All-type branches resolve by one isinstance, both on match and on miss.
        if self._types is not None:
            return _run_typed_any(self._types, value, self.msg)
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
        self._types = _type_tuple(self._compiled) if self.discriminant is None else None
        self._expected = _expected_label(self.validators)

    def __call__(self, value: typing.Any) -> typing.Any:
        """Try the (possibly narrowed) candidates, returning the first match."""
        if self.discriminant is None:
            if self._types is not None:
                return _run_typed_any(self._types, value, self.msg)
            return _run_any(self._compiled, value, self.msg, self._expected)
        # A discriminant returns a subset of the raw validators; resolve each to
        # its compiled form, compiling any object it returns that was not among
        # the originals (matching voluptuous, which recompiles the chosen set).
        candidates = [
            self._compiled_by_id.get(id(option))
            or compile_schema(option, extra=self._extra)
            for option in self.discriminant(value, self.validators)
        ]
        # The discriminant chose a subset, so the all-branches label would not
        # describe it; let the chosen branch errors surface instead.
        return _run_any(candidates, value, self.msg, None)

    def __repr__(self) -> str:
        """Render as ``Union(v, ..., msg=...)``."""
        return _combinator_repr(self)


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
            raise TooManyValid(message)
        raise NotEnoughValid(message)


And = All
Or = Any
# voluptuous exposes Switch as an alias of Union (the discriminant-driven form).
Switch = Union
