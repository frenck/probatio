"""Validators that wrap other validators or shape sequences."""

from __future__ import annotations

import typing

from probatio.error import (
    ExactSequenceInvalid,
    Invalid,
    MultipleInvalid,
    TypeInvalid,
    ValueInvalid,
)
from probatio.schema import Schema
from probatio.validators._base import _SafeValidator


class Sorted(_SafeValidator):
    """Require a sequence to be in ascending order, returning it unchanged."""

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it is sorted, else raise ValueInvalid.

        Iterating and comparing the items runs user code (``__iter__`` and the
        items' comparison dunders), which may raise anything: a non-iterable, an
        incomparable pair, a ``Decimal('NaN')``, or a hostile object. Any such
        failure is reported as a ValueInvalid, not a leaked exception.
        """
        try:
            in_order = list(value) == sorted(value)
        except Exception as exc:
            raise ValueInvalid(
                self.msg or "value is not sorted", code="sorted"
            ) from exc

        if not in_order:
            raise ValueInvalid(self.msg or "value is not sorted", code="sorted")

        return value


class ExactSequence(_SafeValidator):
    """Validate a fixed-length sequence, each position by its own schema."""

    def __init__(self, validators: typing.Any, msg: str | None = None) -> None:
        """Compile one schema per position and remember the count."""
        self.validators = list(validators)
        self.msg = msg
        self._schemas = [Schema(validator) for validator in self.validators]

    def __repr__(self) -> str:
        """Render as a constructor call, matching voluptuous."""
        return f"ExactSequence({self.validators!r})"

    def __call__(self, value: typing.Any) -> typing.Any:
        """Validate each position, rebuilding the sequence of the same type."""
        if not isinstance(value, list | tuple) or len(value) != len(self._schemas):
            message = self.msg or f"expected a sequence of {len(self._schemas)} items"
            raise ExactSequenceInvalid(message)

        result = []
        errors: list[Invalid] = []
        for index, (schema, item) in enumerate(zip(self._schemas, value, strict=True)):
            try:
                result.append(schema(item))
            except MultipleInvalid as exc:
                # A compiled Schema always reports through MultipleInvalid, so a
                # bare Invalid never reaches here.
                for error in exc.errors:
                    error.prepend([index])
                    errors.append(error)

        if errors:
            raise MultipleInvalid(errors)

        # Rebuild the sequence as its own type. A namedtuple takes its fields
        # positionally (``Point(*result)``), not as a single iterable, so detect it
        # the way the sequence engine does rather than leak a TypeError.
        out_type = type(value)
        if issubclass(out_type, tuple) and hasattr(out_type, "_fields"):
            return out_type(*result)
        return out_type(result)


class Unique(_SafeValidator):
    """Require the items of a collection to be distinct."""

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if every item is unique, else raise Invalid.

        Items must be hashable (voluptuous builds a ``set`` to compare): an
        unhashable element is reported as a ``TypeInvalid``, not a leaked
        ``TypeError``. The duplicates are listed in the message, matching
        voluptuous.

        An unsized iterable (a generator) is materialized into a list first, so
        building the set does not consume it before the count, which would
        otherwise leak a ``TypeError`` from ``len`` on the exhausted iterable.
        """
        try:
            length = len(value)
        except Exception:  # noqa: BLE001 - __len__ is user code; may raise anything
            try:
                value = list(value)
            except Exception as exc:
                message = self.msg or f"expected a collection: {exc}"
                raise TypeInvalid(message) from exc
            length = len(value)

        try:
            unique = set(value)
        except Exception as exc:
            message = self.msg or f"contains unhashable elements: {exc}"
            raise TypeInvalid(message) from exc

        if len(unique) != length:
            seen: set[typing.Any] = set()
            duplicates: set[typing.Any] = set()
            for item in value:
                if item in seen:
                    duplicates.add(item)
                else:
                    seen.add(item)
            message = self.msg or f"contains duplicate items: {list(duplicates)}"
            raise Invalid(message)

        return value


class Set(_SafeValidator):
    """Convert an iterable into a set.

    JSON has no set type, so collections arrive as lists. ``Set`` turns one into
    a set, reporting a value that cannot become a set (an unhashable element) as
    a TypeInvalid rather than leaking the underlying error.
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return ``set(value)``, or raise TypeInvalid if it cannot be built."""
        try:
            return set(value)
        except Exception as exc:
            message = self.msg or f"cannot be converted to a set: {exc}"
            raise TypeInvalid(message) from exc


class Unordered(_SafeValidator):
    """Validate a sequence whose items may appear in any order.

    Each item must match one of the element validators, and each validator is
    consumed by at most one item, so ``Unordered([str, int])`` accepts a string
    and an int in either order. The sequence length must equal the validator
    count.
    """

    def __init__(
        self,
        validators: typing.Any,
        msg: str | None = None,
        **kwargs: typing.Any,
    ) -> None:
        """Compile one schema per validator, passing kwargs to each sub-schema."""
        self.validators = list(validators)
        self.msg = msg
        self._schemas = [Schema(validator, **kwargs) for validator in self.validators]

    def __call__(self, value: typing.Any) -> typing.Any:
        """Match each item to an unused validator, in any order."""
        if not isinstance(value, list | tuple):
            message = self.msg or f"Value {value} is not sequence!"
            raise Invalid(message)
        if len(value) != len(self._schemas):
            message = self.msg or (
                f"List lengths differ, value:{len(value)} "
                f"!= target:{len(self._schemas)}"
            )
            raise Invalid(message)

        consumed: set[int] = set()
        missing: list[tuple[int, typing.Any]] = []
        for index, item in enumerate(value):
            if not self._consume(item, consumed):
                missing.append((index, item))

        if len(missing) == 1:
            position, item = missing[0]
            message = self.msg or (
                f"Element #{position} ({item}) is not valid against any validator"
            )
            raise Invalid(message)
        if missing:
            raise MultipleInvalid(
                [
                    Invalid(
                        self.msg
                        or (
                            f"Element #{position} ({item}) is not valid "
                            "against any validator"
                        ),
                    )
                    for position, item in missing
                ],
            )

        return value

    def _consume(self, item: typing.Any, consumed: set[int]) -> bool:
        """Match an item to the first not-yet-used validator that accepts it."""
        for schema_index, schema in enumerate(self._schemas):
            if schema_index in consumed:
                continue
            try:
                schema(item)
            except Invalid:
                continue
            consumed.add(schema_index)
            return True
        return False


class EnsureList(_SafeValidator):
    """Wrap a value in a list so a scalar and a list are handled the same.

    A list passes through unchanged, ``None`` becomes an empty list, and anything
    else is wrapped in a single-item list. It never fails; it normalizes the
    common "one value or a list of them" config shape.
    """

    def __call__(self, value: typing.Any) -> list[typing.Any]:
        """Return the value as a list."""
        if value is None:
            return []
        return value if isinstance(value, list) else [value]


class Maybe(_SafeValidator):
    """Allow ``None``, or otherwise validate against the wrapped validator."""

    def __init__(self, validator: typing.Any, msg: str | None = None) -> None:
        """Compile the wrapped validator."""
        self.validator = validator
        self.msg = msg
        self._schema = Schema(validator)

    def __repr__(self) -> str:
        """Render as a constructor call.

        Probatio's ``Maybe`` is a first-class validator, so it reads back as
        ``Maybe(...)``; voluptuous implements ``Maybe`` as an ``Any`` and reprs it
        as such.
        """
        return f"Maybe({self.validator!r}, msg={self.msg!r})"

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return None unchanged, else the validated value."""
        if value is None:
            return None

        try:
            return self._schema(value)
        except Invalid as exc:
            if self.msg is not None:
                raise Invalid(self.msg) from exc
            raise


class Msg(_SafeValidator):
    """Wrap a validator and replace its failure message."""

    def __init__(
        self,
        validator: typing.Any,
        msg: str,
        cls: type[Invalid] | None = None,
    ) -> None:
        """Compile the validator and remember the replacement message and class."""
        self.validator = validator
        self.msg = msg
        self.cls = cls
        self._schema = Schema(validator)

    def __call__(self, value: typing.Any) -> typing.Any:
        """Validate, re-raising any failure with the replacement message."""
        try:
            return self._schema(value)
        except Invalid as exc:
            error_cls = self.cls or Invalid
            raise error_cls(self.msg) from exc
