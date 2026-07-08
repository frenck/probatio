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
                self.msg, code="sorted", translation_key="value_not_sorted"
            ) from exc

        if not in_order:
            raise ValueInvalid(
                self.msg, code="sorted", translation_key="value_not_sorted"
            )

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

    def __probatio_child_schemas__(self) -> tuple[typing.Any, ...]:
        """Return the raw per-position schemas this wraps, for ``Self`` detection."""
        return tuple(self.validators)

    def __call__(self, value: typing.Any) -> typing.Any:
        """Validate each position, rebuilding the sequence of the same type."""
        if not isinstance(value, list | tuple) or len(value) != len(self._schemas):
            raise ExactSequenceInvalid(
                self.msg,
                translation_key="expected_sequence_of_items",
                placeholders={"count": len(self._schemas)},
            )

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
        # the way the sequence engine does rather than leak a TypeError. A list or
        # tuple subclass whose constructor is not ``(iterable)`` (a custom
        # ``__init__``/``__new__``) cannot be rebuilt that way, so fall back to the
        # plain base type rather than leak the TypeError its constructor raises.
        out_type = type(value)
        try:
            if issubclass(out_type, tuple) and hasattr(out_type, "_fields"):
                return out_type(*result)
            return out_type(result)
        except TypeError:
            return list(result) if issubclass(out_type, list) else tuple(result)


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
                raise TypeInvalid(
                    self.msg,
                    translation_key="expected_collection",
                    placeholders={"detail": str(exc)},
                ) from exc
            length = len(value)

        try:
            unique = set(value)
        except Exception as exc:
            raise TypeInvalid(
                self.msg,
                translation_key="contains_unhashable_elements",
                placeholders={"detail": str(exc)},
            ) from exc

        if len(unique) != length:
            seen: set[typing.Any] = set()
            duplicates: set[typing.Any] = set()
            for item in value:
                if item in seen:
                    duplicates.add(item)
                else:
                    seen.add(item)
            raise Invalid(
                self.msg,
                translation_key="contains_duplicate_items",
                placeholders={"items": list(duplicates)},
            )

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
            raise TypeInvalid(
                self.msg,
                translation_key="cannot_convert_to_set",
                placeholders={"detail": str(exc)},
            ) from exc


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

    def __probatio_child_schemas__(self) -> tuple[typing.Any, ...]:
        """Return the raw element schemas this wraps, for ``Self`` detection."""
        return tuple(self.validators)

    def __call__(self, value: typing.Any) -> typing.Any:
        """Match each item to an unused validator, in any order."""
        if not isinstance(value, list | tuple):
            raise Invalid(
                self.msg,
                translation_key="expected_sequence",
                placeholders={"expected": "sequence"},
            )
        if len(value) != len(self._schemas):
            raise Invalid(
                self.msg,
                translation_key="expected_sequence_of_items",
                placeholders={"count": len(self._schemas)},
            )

        consumed: set[int] = set()
        missing: list[tuple[int, typing.Any]] = []
        for index, item in enumerate(value):
            if not self._consume(item, consumed):
                missing.append((index, item))

        if len(missing) == 1:
            position, item = missing[0]
            raise Invalid(
                self.msg,
                translation_key="element_not_valid",
                placeholders={"position": position, "item": item},
            )
        if missing:
            raise MultipleInvalid(
                [
                    Invalid(
                        self.msg,
                        translation_key="element_not_valid",
                        placeholders={"position": position, "item": item},
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

    def __probatio_child_schemas__(self) -> tuple[typing.Any, ...]:
        """Return the single wrapped schema, for ``Self`` detection."""
        return (self.validator,)

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

    def __probatio_child_schemas__(self) -> tuple[typing.Any, ...]:
        """Return the single wrapped schema, for ``Self`` detection."""
        return (self.validator,)

    def __call__(self, value: typing.Any) -> typing.Any:
        """Validate, re-raising any failure with the replacement message."""
        try:
            return self._schema(value)
        except Invalid as exc:
            error_cls = self.cls or Invalid
            raise error_cls(self.msg) from exc


def _require_sequence(value: typing.Any, msg: str | None) -> None:
    """Raise ValueInvalid unless the value is a list or tuple.

    The collection shapers work on a list or tuple, not a bare string (which would
    split character by character) or a scalar. Shared so they agree on what counts.
    """
    if not isinstance(value, list | tuple):
        raise ValueInvalid(
            msg,
            translation_key="expected_sequence",
            placeholders={"expected": "sequence"},
        )


class Split(_SafeValidator):
    """Split a delimited string into a list.

    ``Split(",")`` turns ``"a, b ,c"`` into ``["a", "b", "c"]``: each piece is
    stripped and empty pieces dropped by default, the common shape for a
    comma-separated config value. Pass ``strip=False`` or ``drop_empty=False`` to keep
    whitespace or empty pieces. A non-string is rejected.
    """

    def __init__(
        self,
        sep: str = ",",
        *,
        strip: bool = True,
        drop_empty: bool = True,
        msg: str | None = None,
    ) -> None:
        """Store the separator and the strip and drop-empty options."""
        self.sep = sep
        self.strip = strip
        self.drop_empty = drop_empty
        self.msg = msg

    def __repr__(self) -> str:
        """Render as a constructor call showing the separator and options."""
        return (
            f"Split(sep={self.sep!r}, strip={self.strip!r}, "
            f"drop_empty={self.drop_empty!r})"
        )

    def __call__(self, value: typing.Any) -> list[str]:
        """Return the string split into a list, else raise ValueInvalid."""
        if not isinstance(value, str):
            raise ValueInvalid(self.msg, translation_key="expected_string")
        parts = value.split(self.sep)
        if self.strip:
            parts = [part.strip() for part in parts]
        if self.drop_empty:
            parts = [part for part in parts if part]
        return parts


class Join(_SafeValidator):
    """Join a sequence into a delimited string, the inverse of ``Split``.

    ``Join(",")`` turns ``[1, 2, 3]`` into ``"1,2,3"``, converting each element to a
    string. A value that is not a list or tuple is rejected, so a bare string is not
    joined character by character.
    """

    def __init__(self, sep: str = ",", *, msg: str | None = None) -> None:
        """Store the separator."""
        self.sep = sep
        self.msg = msg

    def __repr__(self) -> str:
        """Render as a constructor call showing the separator."""
        return f"Join({self.sep!r})"

    def __call__(self, value: typing.Any) -> str:
        """Return the sequence joined into a string, else raise ValueInvalid."""
        _require_sequence(value, self.msg)
        return self.sep.join(str(item) for item in value)


class Sort(_SafeValidator):
    """Sort a sequence into ascending order, returning a new list.

    ``Sort()`` orders the items; pass ``reverse=True`` for descending. Unlike
    ``Sorted``, which validates order and returns the value unchanged, this reorders.
    A value that is not a list or tuple, or whose items cannot be ordered, is
    rejected.
    """

    def __init__(self, *, reverse: bool = False, msg: str | None = None) -> None:
        """Store the sort direction."""
        self.reverse = reverse
        self.msg = msg

    def __repr__(self) -> str:
        """Render as a constructor call showing the direction."""
        return f"Sort(reverse={self.reverse!r})"

    def __call__(self, value: typing.Any) -> list[typing.Any]:
        """Return the sorted sequence, else raise ValueInvalid."""
        _require_sequence(value, self.msg)
        try:
            return sorted(value, reverse=self.reverse)
        except Exception as exc:
            # Incomparable items (``[1, "a"]``) raise TypeError; a hostile comparison
            # raises worse. Contain either as Invalid rather than leak it.
            raise ValueInvalid(
                self.msg, translation_key="invalid_value_or_type"
            ) from exc


class Dedupe(_SafeValidator):
    """Remove duplicate items from a sequence, keeping first-seen order.

    ``Dedupe()`` turns ``[1, 2, 1, 3]`` into ``[1, 2, 3]``. Unlike ``Unique``, which
    validates distinctness and returns the value unchanged, this drops the repeats. A
    value that is not a list or tuple, or with an unhashable item, is rejected.
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __repr__(self) -> str:
        """Render as a constructor call."""
        return "Dedupe()"

    def __call__(self, value: typing.Any) -> list[typing.Any]:
        """Return the sequence without duplicates, else raise ValueInvalid."""
        _require_sequence(value, self.msg)
        try:
            return list(dict.fromkeys(value))
        except Exception as exc:
            # An unhashable item raises TypeError; a hostile ``__eq__``/``__hash__``
            # raises worse. Contain either as Invalid rather than leak it.
            raise ValueInvalid(
                self.msg, translation_key="invalid_value_or_type"
            ) from exc


class First(_SafeValidator):
    """Return the first item of a sequence.

    ``First()`` picks ``value[0]``, handy when a source returns a one-element list. A
    value that is not a list or tuple, or an empty one, is rejected.
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __repr__(self) -> str:
        """Render as a constructor call."""
        return "First()"

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the first item, else raise ValueInvalid."""
        _require_sequence(value, self.msg)
        if not value:
            raise ValueInvalid(self.msg, translation_key="value_not_empty")
        return value[0]


class Last(_SafeValidator):
    """Return the last item of a sequence.

    ``Last()`` picks ``value[-1]``. A value that is not a list or tuple, or an empty
    one, is rejected.
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __repr__(self) -> str:
        """Render as a constructor call."""
        return "Last()"

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the last item, else raise ValueInvalid."""
        _require_sequence(value, self.msg)
        if not value:
            raise ValueInvalid(self.msg, translation_key="value_not_empty")
        return value[-1]


class Without(_SafeValidator):
    """Drop every item equal to one of the given values, returning a new list.

    ``Without(None, 0)`` removes each ``None`` and ``0`` from a list, for pruning
    sentinels and placeholders (``Without(None)`` alone drops the ``None`` holes). A
    value that is not a list or tuple is rejected.
    """

    def __init__(self, *values: typing.Any, msg: str | None = None) -> None:
        """Store the values to drop."""
        self.values = values
        self.msg = msg

    def __repr__(self) -> str:
        """Render as a constructor call showing the dropped values."""
        body = ", ".join(repr(value) for value in self.values)
        return f"Without({body})"

    def __call__(self, value: typing.Any) -> list[typing.Any]:
        """Return the sequence without the listed values, else raise ValueInvalid."""
        _require_sequence(value, self.msg)
        try:
            return [item for item in value if item not in self.values]
        except Exception as exc:
            # ``in`` calls each item's ``__eq__``, which may raise (a signaling
            # ``Decimal``, a hostile object). Contain it as Invalid rather than leak.
            raise ValueInvalid(
                self.msg, translation_key="invalid_value_or_type"
            ) from exc
