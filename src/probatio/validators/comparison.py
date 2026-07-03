"""Range, length, and membership validators."""

from __future__ import annotations

import re
import typing

from probatio.error import (
    ContainsInvalid,
    InInvalid,
    Invalid,
    LengthInvalid,
    LiteralInvalid,
    MultipleOfInvalid,
    NotInInvalid,
    RangeInvalid,
    SchemaError,
)
from probatio.validators._base import _SafeValidator

# Collapses each run of whitespace to a single normalization character.
_WHITESPACE = re.compile(r"\s+")

# A percentage runs from 0 to 100.
_MIN_PERCENT = 0
_MAX_PERCENT = 100
# A byte runs from 0 to 255.
_MAX_BYTE = 255
# Geographic coordinate bounds.
_MAX_LATITUDE = 90
_MAX_LONGITUDE = 180


def _sorted_for_message(container: typing.Any) -> list[typing.Any]:
    """Render a container for an error message, sorted like voluptuous can.

    Voluptuous renders membership containers sorted in its messages. Mixed or
    otherwise unorderable contents fall back to insertion order so the message
    never raises while building.
    """
    try:
        return sorted(container)
    except Exception:  # noqa: BLE001 - a member's comparison dunder may raise anything
        return list(container)


class Equal(_SafeValidator):
    """Require the value to equal a fixed target."""

    def __init__(self, target: typing.Any, msg: str | None = None) -> None:
        """Store the value to compare against."""
        self.target = target
        self.msg = msg

    def __repr__(self) -> str:
        """Render as a constructor call, matching voluptuous."""
        return f"Equal({self.target!r})"

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it equals the target, else raise Invalid.

        ``!=`` calls the value's ``__eq__``, which is user code and may raise
        anything (a signaling ``Decimal('sNaN')`` raises, a hostile object can raise
        worse). Any such failure is reported as a mismatch, never leaked.
        """
        try:
            unequal = value != self.target
        except Exception:  # noqa: BLE001 - the value's __eq__ is user code; never leak
            unequal = True

        if unequal:
            raise Invalid(
                self.msg,
                translation_key="value_not_equal",
                placeholders={"target": self.target},
            )
        return value


class Literal(_SafeValidator):
    """Require the value to match a fixed literal, returning the literal.

    Unlike a bare literal in a schema, ``Literal`` is a callable validator: it
    can be composed in ``All``/``Any`` and carries its own ``LiteralInvalid``.
    """

    def __init__(self, lit: typing.Any) -> None:
        """Store the literal to match against (read as ``.lit``)."""
        self.lit = lit

    def __call__(self, value: typing.Any, msg: str | None = None) -> typing.Any:
        """Return the literal if the value matches it, else LiteralInvalid."""
        try:
            unequal = self.lit != value
        except Exception:  # noqa: BLE001 - the value's __eq__ is user code; never leak
            unequal = True

        if unequal:
            raise LiteralInvalid(
                msg,
                translation_key="expected_type",
                placeholders={"expected": self.lit},
            )
        return self.lit

    def __str__(self) -> str:
        """Render as the underlying literal."""
        return str(self.lit)

    def __repr__(self) -> str:
        """Render as the underlying literal's repr."""
        return repr(self.lit)


class Contains(_SafeValidator):
    """Require a collection to contain a given item."""

    def __init__(self, item: typing.Any, msg: str | None = None) -> None:
        """Store the item the collection must contain."""
        self.item = item
        self.msg = msg

    def __repr__(self) -> str:
        """Render as a constructor call, matching voluptuous."""
        return f"Contains({self.item!r})"

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it contains the item, else ContainsInvalid."""
        try:
            present = self.item in value
        except Exception as exc:
            # ``in`` calls the container's ``__contains__``, which is user code and
            # may raise anything: an ``ipaddress`` network checks ``other._version``
            # (AttributeError), a hostile object can raise worse. Treat any such
            # failure as "not a collection that contains the item".
            raise ContainsInvalid(self.msg, translation_key="not_a_collection") from exc

        if not present:
            raise ContainsInvalid(
                self.msg,
                translation_key="value_must_contain",
                placeholders={"item": self.item},
            )
        return value


class Range(_SafeValidator):
    """Require a value to fall within a numeric range."""

    def __init__(
        self,
        min: typing.Any = None,
        max: typing.Any = None,
        min_included: bool = True,
        max_included: bool = True,
        msg: str | None = None,
    ) -> None:
        """Store the bounds and whether each endpoint is inclusive."""
        self.min = min
        self.max = max
        self.min_included = min_included
        self.max_included = max_included
        self.msg = msg

    def __repr__(self) -> str:
        """Render as a constructor call, matching voluptuous."""
        return (
            f"Range(min={self.min!r}, max={self.max!r}, "
            f"min_included={self.min_included!r}, "
            f"max_included={self.max_included!r}, msg={self.msg!r})"
        )

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it is in range, else raise RangeInvalid.

        The bound comparisons call the value's comparison dunders, which are user
        code and may raise anything (a ``Decimal('NaN')`` raises ``InvalidOperation``,
        a hostile object can raise worse). Any such failure is reported as a
        RangeInvalid too, so the validator never leaks a raw exception.
        """
        try:
            if self.min is not None:
                # Negated form (raise unless in bounds), so a NaN, where every
                # comparison is False, is rejected rather than slipping through.
                in_bounds = value >= self.min if self.min_included else value > self.min
                if not in_bounds:
                    key = "range_min" if self.min_included else "range_min_exclusive"
                    raise RangeInvalid(
                        self.msg,
                        translation_key=key,
                        placeholders={"min": self.min},
                    )

            if self.max is not None:
                in_bounds = value <= self.max if self.max_included else value < self.max
                if not in_bounds:
                    key = "range_max" if self.max_included else "range_max_exclusive"
                    raise RangeInvalid(
                        self.msg,
                        translation_key=key,
                        placeholders={"max": self.max},
                    )
        except Invalid:
            # An out-of-bounds RangeInvalid raised just above carries the precise
            # message; let it through rather than redescribing it below.
            raise
        except Exception as exc:
            raise RangeInvalid(
                self.msg, translation_key="invalid_value_or_type"
            ) from exc

        return value


class Clamp(_SafeValidator):
    """Pin a value into a range instead of failing when it falls outside."""

    def __init__(
        self,
        min: typing.Any = None,
        max: typing.Any = None,
        msg: str | None = None,
    ) -> None:
        """Store the lower and upper limits."""
        self.min = min
        self.max = max
        self.msg = msg

    def __repr__(self) -> str:
        """Render as a constructor call, matching voluptuous."""
        return f"Clamp(min={self.min!r}, max={self.max!r})"

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value clamped to the configured limits."""
        try:
            if self.min is not None and value < self.min:
                return self.min
            if self.max is not None and value > self.max:
                return self.max
        except Exception as exc:
            raise RangeInvalid(
                self.msg, translation_key="invalid_value_or_type"
            ) from exc

        return value


class Positive(Range):
    """Require a number to be greater than zero."""

    def __init__(self, msg: str | None = None) -> None:
        """Bound the value above zero (exclusive)."""
        super().__init__(min=0, min_included=False, msg=msg)


class NonNegative(Range):
    """Require a number to be zero or greater."""

    def __init__(self, msg: str | None = None) -> None:
        """Bound the value at zero or above."""
        super().__init__(min=0, msg=msg)


class Negative(Range):
    """Require a number to be less than zero."""

    def __init__(self, msg: str | None = None) -> None:
        """Bound the value below zero (exclusive)."""
        super().__init__(max=0, max_included=False, msg=msg)


class MultipleOf(_SafeValidator):
    """Require a number to be an integer multiple of a non-zero factor."""

    def __init__(self, factor: typing.Any, msg: str | None = None) -> None:
        """Store the factor; reject a zero or non-numeric factor at build time."""
        if not isinstance(factor, int | float) or factor == 0:
            message = "MultipleOf factor must be a non-zero number"
            raise SchemaError(message)
        self.factor = factor
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it is a multiple of the factor, else raise.

        Only a real number is accepted: ``%`` on a ``str``/``bytes`` is string
        formatting, not modulo, and a ``bool`` is not a meaningful count, so both
        are rejected rather than mishandled.
        """
        placeholders = {"factor": self.factor}
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise MultipleOfInvalid(
                self.msg, translation_key="value_multiple_of", placeholders=placeholders
            )

        try:
            # ``%`` with a float factor promotes a huge int to float, which can
            # overflow (an ArithmeticError); an ``int`` subclass can also define a
            # ``__mod__`` that raises. Report either cleanly, not as a leak.
            remainder = value % self.factor
        except Exception as exc:
            raise MultipleOfInvalid(
                self.msg, translation_key="value_multiple_of", placeholders=placeholders
            ) from exc

        if remainder != 0:
            raise MultipleOfInvalid(
                self.msg, translation_key="value_multiple_of", placeholders=placeholders
            )
        return value


def _percent_value(value: typing.Any, msg: str | None) -> float:
    """Validate a percentage (number or ``"NN%"`` string) as a float in 0 to 100.

    A ``bool`` is rejected (it is not a meaningful percentage), matching the other
    numeric validators like ``MultipleOf``.
    """
    if isinstance(value, bool):
        raise RangeInvalid(msg, translation_key="expected_percentage")

    raw = value[:-1] if isinstance(value, str) and value.endswith("%") else value
    try:
        # ``float`` on an int too large to represent raises OverflowError, and on an
        # object it calls a user-defined ``__float__`` that may raise anything; report
        # either cleanly rather than leaking it.
        number = float(raw)
    except Invalid:
        # A deliberate Invalid from the value's own ``__float__`` is a real validation
        # error; keep it rather than masking it as a RangeInvalid.
        raise
    except Exception as exc:
        raise RangeInvalid(msg, translation_key="expected_percentage") from exc

    if not _MIN_PERCENT <= number <= _MAX_PERCENT:
        raise RangeInvalid(msg, translation_key="expected_percentage")
    return number


class FromPercentage(_SafeValidator):
    """Parse a percentage into a ``float`` in 0 to 100.

    Accepts a number or a string ending in ``%`` (the percent sign is stripped before
    parsing); a bare numeric string works too. ``Percentage`` is the validate-only
    sibling that checks the same and returns the value unchanged.
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> float:
        """Return the percentage as a float in range, else raise RangeInvalid."""
        return _percent_value(value, self.msg)


class Percentage(_SafeValidator):
    """Validate a percentage in 0 to 100, returning the value unchanged.

    Accepts a number or a string ending in ``%`` (a bare numeric string works too).
    Use ``FromPercentage`` when you want the value parsed to a ``float``.
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it is a valid percentage, else raise RangeInvalid."""
        _percent_value(value, self.msg)
        return value


class Byte(Range):
    """Require a number to be a byte value (0 to 255 inclusive)."""

    def __init__(self, msg: str | None = None) -> None:
        """Bound the value to the 0..255 range."""
        super().__init__(min=0, max=_MAX_BYTE, msg=msg)


class SmallFloat(Range):
    """Require a number to be a unit fraction (0 to 1 inclusive)."""

    def __init__(self, msg: str | None = None) -> None:
        """Bound the value to the 0..1 range."""
        super().__init__(min=0, max=1, msg=msg)


class Latitude(Range):
    """Require a number to be a valid latitude (-90 to 90 inclusive)."""

    def __init__(self, msg: str | None = None) -> None:
        """Bound the value to the latitude range."""
        super().__init__(min=-_MAX_LATITUDE, max=_MAX_LATITUDE, msg=msg)


class Longitude(Range):
    """Require a number to be a valid longitude (-180 to 180 inclusive)."""

    def __init__(self, msg: str | None = None) -> None:
        """Bound the value to the longitude range."""
        super().__init__(min=-_MAX_LONGITUDE, max=_MAX_LONGITUDE, msg=msg)


class NonEmpty(_SafeValidator):
    """Require a sized value (string, list, mapping) to not be empty."""

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it has a non-zero length, else raise LengthInvalid.

        A value with no usable length (``len`` raising, including a user ``__len__``
        that raises anything) is reported as a LengthInvalid too, never leaked.
        """
        try:
            empty = len(value) == 0
        except Exception as exc:
            raise LengthInvalid(self.msg, translation_key="value_not_empty") from exc

        if empty:
            raise LengthInvalid(self.msg, translation_key="value_not_empty")
        return value


class Length(_SafeValidator):
    """Require the length of a sized value to fall within bounds."""

    def __init__(
        self,
        min: typing.Any = None,
        max: typing.Any = None,
        msg: str | None = None,
    ) -> None:
        """Store the minimum and maximum allowed lengths."""
        self.min = min
        self.max = max
        self.msg = msg

    def __repr__(self) -> str:
        """Render as a constructor call, matching voluptuous."""
        return f"Length(min={self.min!r}, max={self.max!r})"

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if its length is in bounds, else LengthInvalid.

        With no bound set, the length is never measured, so any value passes
        (matching voluptuous). A value with no usable length (``len`` raising,
        including a user ``__len__`` that raises) is a LengthInvalid, never leaked.
        """
        if self.min is None and self.max is None:
            return value

        try:
            length = len(value)
        except Exception as exc:
            raise LengthInvalid(self.msg, translation_key="value_no_length") from exc

        if self.min is not None and length < self.min:
            raise LengthInvalid(
                self.msg,
                translation_key="length_min",
                placeholders={"min": self.min},
            )
        if self.max is not None and length > self.max:
            raise LengthInvalid(
                self.msg,
                translation_key="length_max",
                placeholders={"max": self.max},
            )
        return value


class In(_SafeValidator):
    """Require the value to be a member of a container.

    ``fold_case=True`` matches case-insensitively, and ``space`` collapses each run
    of whitespace in a string value to the given character (``space=" "`` to
    normalize spacing, ``space="_"`` so ``"front door"`` matches ``"front_door"``).
    When either normalizes the value, the normalized value is returned, the way
    a coercing membership check does; otherwise the value is returned unchanged.

    On a miss the error suggests the closest allowed members (``did you mean ...?``)
    when both the value and the members are strings, and carries them on the error's
    ``candidates``, mirroring the unknown-key hint a mapping schema gives.
    """

    def __init__(
        self,
        container: typing.Any,
        msg: str | None = None,
        *,
        fold_case: bool = False,
        space: str | None = None,
    ) -> None:
        """Store the container (read as ``.container``), message, and normalization."""
        self.container = container
        self.msg = msg
        self.fold_case = fold_case
        self.space = space

    def __repr__(self) -> str:
        """Render as a constructor call, matching voluptuous."""
        return f"In({self.container!r})"

    def _normalize(self, value: typing.Any) -> typing.Any:
        """Apply the space and case normalization to a string, else pass through."""
        if not isinstance(value, str):
            return value
        if self.space is not None:
            value = _WHITESPACE.sub(self.space, value)
        if self.fold_case:
            value = value.casefold()
        return value

    def _contains(self, candidate: typing.Any) -> bool:
        """Whether the candidate is a member, normalizing members to match.

        Only the case-folding or space-normalizing ``In`` reaches here; the plain
        membership test is inlined in ``__call__``.
        """
        return any(candidate == self._normalize(member) for member in self.container)

    def _string_members(self) -> list[str]:
        """Return the string members, the pool a 'did you mean ...?' hint matches."""
        return [member for member in self.container if isinstance(member, str)]

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the (normalized) value if it is in the container, else raise."""
        # The common ``In`` has no case-folding and no space normalization, so the
        # value passes through unchanged and membership is a plain ``in``. Inline that
        # to skip the ``_normalize`` and ``_contains`` calls on the hot path; only a
        # folding or space-normalizing ``In`` pays for them.
        fast = not self.fold_case and self.space is None
        candidate = value if fast else self._normalize(value)

        try:
            present = candidate in self.container if fast else self._contains(candidate)
        except Exception as exc:
            raise InInvalid(self.msg, translation_key="value_not_allowed") from exc

        if not present:
            # The suggestion match is deferred to the error, so a miss inside a
            # combinator branch that is then discarded never pays for difflib.
            raise InInvalid(
                self.msg,
                translation_key="value_one_of",
                placeholders={"values": _sorted_for_message(self.container)},
                suggest_value=value,
                suggest_pool=self._string_members(),
                suffix=self.msg is None,
            )
        return candidate


class NotIn(_SafeValidator):
    """Require the value to be absent from a container."""

    def __init__(self, container: typing.Any, msg: str | None = None) -> None:
        """Store the disallowed container and an optional message."""
        self.container = container
        self.msg = msg

    def __repr__(self) -> str:
        """Render as a constructor call, matching voluptuous."""
        return f"NotIn({self.container!r})"

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it is not in the container, else NotInInvalid."""
        try:
            present = value in self.container
        except Exception as exc:
            raise NotInInvalid(self.msg, translation_key="value_not_allowed") from exc

        if present:
            raise NotInInvalid(
                self.msg,
                translation_key="value_not_one_of",
                placeholders={"values": _sorted_for_message(self.container)},
            )
        return value
