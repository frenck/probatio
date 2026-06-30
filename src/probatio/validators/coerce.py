"""Coercion and boolean-reading validators."""

from __future__ import annotations

import enum
import typing
from decimal import Decimal, InvalidOperation

from probatio.error import BooleanInvalid, CoerceInvalid, Invalid
from probatio.validators._base import _SafeValidator
from probatio.validators.decorators import message

_TRUE_STRINGS = frozenset({"1", "true", "yes", "on", "enable"})
_FALSE_STRINGS = frozenset({"0", "false", "no", "off", "disable"})


class Coerce[T](_SafeValidator):
    """Coerce a value to a type, failing cleanly when the conversion does not.

    Generic in the target type, so ``Coerce(int)`` is a ``Coerce[int]`` whose call
    is typed as returning an ``int`` rather than ``Any``.
    """

    def __init__(
        self,
        type: type[T] | typing.Callable[[typing.Any], T],
        msg: str | None = None,
    ) -> None:
        """Store the target type (read as ``.type``) and an optional message."""
        # Kept ``Any`` (not the generic union) so readers of ``.type`` elsewhere (the
        # codecs) are unaffected; ``T`` is bound from the parameter for the call return.
        self.type: typing.Any = type
        self.type_name: str = getattr(type, "__name__", str(type))
        self.msg = msg

    def __repr__(self) -> str:
        """Render as a constructor call, matching voluptuous."""
        return f"Coerce({self.type_name}, msg={self.msg!r})"

    def __call__(self, value: typing.Any) -> T:
        """Return ``type(value)``, or raise CoerceInvalid if it cannot.

        Calling the target is user code (``int(value)`` runs the value's
        ``__int__``/``__index__``, a custom converter runs whatever it likes), so it
        may raise anything: ``Coerce(int)`` on infinity (OverflowError),
        ``Coerce(Decimal)`` on junk (decimal.InvalidOperation), a hostile dunder.
        Any such failure becomes a CoerceInvalid rather than leaking, keeping the
        safe-validator contract. A target that raises ``Invalid`` itself passes
        through unchanged.
        """
        try:
            return typing.cast("T", self.type(value))
        except Invalid:
            raise
        except Exception as exc:
            # The suggestion match is deferred to the error, so a miss inside a
            # combinator branch that is then discarded never pays for difflib.
            raise CoerceInvalid(
                self.msg or self._default_message(),
                suggest_value=value,
                suggest_pool=self._enum_values(),
                suffix=self.msg is None,
            ) from exc

    def _default_message(self) -> str:
        """Build the failure message, listing an enum's values (like voluptuous)."""
        message = f"expected {self.type_name}"
        if isinstance(self.type, type) and issubclass(self.type, enum.Enum):
            values = ", ".join(repr(member.value) for member in self.type)
            message = f"{message} or one of {values}"

        return message

    def _enum_values(self) -> list[str]:
        """Return the string enum values, the pool a 'did you mean ...?' hint matches.

        Matches the member values (what ``Coerce(enum)`` actually accepts, since it
        coerces with ``enum(value)``), not the names, so a suggestion always names a
        value that would validate. Empty for a non-enum target.
        """
        if not (isinstance(self.type, type) and issubclass(self.type, enum.Enum)):
            return []
        return [member.value for member in self.type if isinstance(member.value, str)]


@message("expected boolean", cls=BooleanInvalid)
def Boolean(value: typing.Any) -> bool:
    """Read common truthy/falsy strings (and other values) as a boolean.

    Decorated with ``message``, so ``Boolean`` is a factory: ``Boolean()`` builds
    the validator, matching voluptuous (``Schema(Boolean())``). The message and
    error class can be overridden, like ``Boolean("not a flag")``.
    """
    if isinstance(value, str):
        # No surrounding-whitespace stripping, matching voluptuous: " true " is
        # not a boolean string.
        lowered = value.lower()
        if lowered in _TRUE_STRINGS:
            return True
        if lowered in _FALSE_STRINGS:
            return False
        raise ValueError

    try:
        return bool(value)
    except Exception as exc:
        # Surface as ValueError so the ``message`` wrapper renders it as the
        # configured BooleanInvalid rather than letting the dunder error escape.
        raise ValueError from exc


class SetTo(_SafeValidator):
    """Ignore the input and always produce a fixed value."""

    def __init__(self, value: typing.Any) -> None:
        """Store the value to set."""
        self.value = value

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the configured value, regardless of the input."""
        del value
        return self.value


class Number(_SafeValidator):
    """Validate a numeric string, optionally checking its precision and scale.

    Precision is the count of significant digits, scale is the count of decimal
    places. With ``yield_decimal`` the parsed ``Decimal`` is returned instead of
    the original string.
    """

    def __init__(
        self,
        precision: int | None = None,
        scale: int | None = None,
        msg: str | None = None,
        yield_decimal: bool = False,
    ) -> None:
        """Store the expected precision/scale and the output preference."""
        self.precision = precision
        self.scale = scale
        self.msg = msg
        self.yield_decimal = yield_decimal

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the number (or its Decimal) if precision/scale match."""
        try:
            number = Decimal(value)
        except (InvalidOperation, TypeError, ValueError, ArithmeticError) as exc:
            # ArithmeticError covers OverflowError: a 3-element sequence is read by
            # Decimal as a (sign, digits, exponent) spec, and a huge exponent
            # overflows the C long, which must not leak.
            message = self.msg or "value must be a number enclosed in a string"
            raise Invalid(message) from exc

        exponent = number.as_tuple().exponent
        if not isinstance(exponent, int):  # NaN or infinity
            message = self.msg or "value has no precision"
            raise Invalid(message)

        precision = len(number.as_tuple().digits)
        scale = -exponent
        if self.precision is not None and precision != self.precision:
            message = self.msg or f"precision must be equal to {self.precision}"
            raise Invalid(message)
        if self.scale is not None and scale != self.scale:
            message = self.msg or f"scale must be equal to {self.scale}"
            raise Invalid(message)

        return number if self.yield_decimal else value


class DefaultTo(_SafeValidator):
    """Replace ``None`` with a default, passing other values through."""

    def __init__(self, default: typing.Any, msg: str | None = None) -> None:
        """Store the default to use when the value is None."""
        self.default = default
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the default when the value is None, else the value."""
        if value is None:
            return self.default
        return value
