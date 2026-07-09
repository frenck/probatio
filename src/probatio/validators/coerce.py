"""Coercion and boolean-reading validators."""

from __future__ import annotations

import enum
import typing
from decimal import Decimal, InvalidOperation

from probatio.error import BooleanInvalid, CoerceInvalid, Invalid, SchemaError
from probatio.markers import UNDEFINED
from probatio.validators._base import _SafeValidator
from probatio.validators.decorators import message

_TRUE_STRINGS = frozenset({"1", "true", "yes", "on", "enable"})
_FALSE_STRINGS = frozenset({"0", "false", "no", "off", "disable"})
# The empty values ``EmptyToNone`` maps to ``None``: a string or a container with no
# items. A falsy scalar (``0``, ``False``) is a value, not an absence, so it is left.
_EMPTY_CONTAINERS = (str, bytes, list, tuple, dict, set, frozenset)


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
        # Filled on the first failure, not eagerly: building the default message
        # placeholders (and for an enum, its value pool) walks the enum members, a
        # cost a schema that never fails should not pay at construction either.
        self._failure_cache: tuple[str, dict[str, str], tuple[str, ...]] | None = None

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
            # A typed local instead of typing.cast: cast is a real function call in
            # CPython, and this line runs once per coerced value on the hot path.
            coerced: T = self.type(value)
        except Invalid:
            raise
        except Exception as exc:
            if isinstance(self.type, type) and isinstance(value, self.type):
                # Already the target type; the constructor just cannot take its own
                # instance (``uuid.UUID(a_uuid)`` raises). Pass it through so coercion
                # is idempotent: re-validating an already-coerced value does not fail.
                return typing.cast("T", value)
            # The suggestion match is deferred to the error, so a miss inside a
            # combinator branch that is then discarded never pays for difflib. The
            # translation key, placeholders, and pool depend only on ``self.type``,
            # so they are built once on the first failure; ``self.msg`` stays
            # raise-time.
            cached = self._failure_cache
            if cached is None:
                key, placeholders = self._default_message_parts()
                cached = (key, placeholders, tuple(self._enum_values()))
                self._failure_cache = cached
            raise CoerceInvalid(
                self.msg,
                suggest_value=value,
                suggest_pool=cached[2],
                suffix=self.msg is None,
                translation_key=cached[0],
                placeholders=cached[1],
            ) from exc
        else:
            return coerced

    def _default_message_parts(self) -> tuple[str, dict[str, str]]:
        """Pick the failure key and placeholders, listing an enum's values.

        Matches voluptuous: a plain target reads "expected int", an enum target
        appends its value pool ("expected Color or one of 'red', 'green'").
        """
        if isinstance(self.type, type) and issubclass(self.type, enum.Enum):
            values = ", ".join(repr(member.value) for member in self.type)
            return (
                "expected_type_or_one_of",
                {"expected": self.type_name, "values": values},
            )
        return "expected_type", {"expected": self.type_name}

    def _enum_values(self) -> list[str]:
        """Return the string enum values, the pool a 'did you mean ...?' hint matches.

        Matches the member values (what ``Coerce(enum)`` actually accepts, since it
        coerces with ``enum(value)``), not the names, so a suggestion always names a
        value that would validate. Empty for a non-enum target.
        """
        if not (isinstance(self.type, type) and issubclass(self.type, enum.Enum)):
            return []
        return [member.value for member in self.type if isinstance(member.value, str)]


@message("expected boolean", cls=BooleanInvalid, translation_key="expected_boolean")
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
            raise Invalid(
                self.msg, translation_key="value_must_be_number_string"
            ) from exc

        exponent = number.as_tuple().exponent
        if not isinstance(exponent, int):  # NaN or infinity
            raise Invalid(self.msg, translation_key="value_has_no_precision")

        precision = len(number.as_tuple().digits)
        scale = -exponent
        if self.precision is not None and precision != self.precision:
            raise Invalid(
                self.msg,
                translation_key="precision_must_equal",
                placeholders={"precision": self.precision},
            )
        if self.scale is not None and scale != self.scale:
            raise Invalid(
                self.msg,
                translation_key="scale_must_equal",
                placeholders={"scale": self.scale},
            )

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


class _Passthrough:
    """Type of the ``PASSTHROUGH`` sentinel: a ``Map`` miss returns the value unchanged."""

    def __repr__(self) -> str:
        """Render as ``PASSTHROUGH`` so it reads clearly in debug output."""
        return "PASSTHROUGH"


PASSTHROUGH = _Passthrough()


class Map(_SafeValidator):
    """Translate a value through a mapping, like a status code to a name.

    ``Map({0: "off", 1: "on", 2: "auto"})`` returns the mapped value for a key it
    knows. This is the bring-your-own-table generalization of a domain converter:
    probatio does not pick the mapping, you do, so a disputed or app-specific lookup
    (an RSSI bucket, a vendor status code) stays yours. An unhashable value, which
    cannot be a mapping key, is treated as a miss.

    A value not in the mapping is rejected. Two escapes change that. A ``default``
    value is returned in place of any miss (``Map({...}, default=None)`` folds every
    unknown key to ``None``). Passing ``default=PASSTHROUGH`` instead returns the
    value *unchanged* on a miss, so a ``Map`` rewrites only the keys it lists and
    leaves everything else alone. That is the difference between "unknown means this
    fixed value" and "only touch what I named".
    """

    def __init__(
        self,
        mapping: typing.Any,
        *,
        default: typing.Any = UNDEFINED,
        msg: str | None = None,
    ) -> None:
        """Store the mapping and optional default; reject a non-dict mapping at build."""
        if not isinstance(mapping, dict):
            message = "Map mapping must be a dict"
            raise SchemaError(message)
        self.mapping = mapping
        self.default = default
        self.msg = msg

    def __repr__(self) -> str:
        """Render as a constructor call showing the mapping."""
        return f"Map({self.mapping!r})"

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the mapped value, the default on a miss, else raise Invalid."""
        try:
            return self.mapping[value]
        except Exception as exc:
            # A miss (KeyError), an unhashable value (TypeError), or a hostile
            # ``__hash__``/``__eq__``: none is a valid key. ``PASSTHROUGH`` leaves the
            # value as-is; any other default replaces the miss; otherwise report the
            # allowed keys.
            if self.default is PASSTHROUGH:
                return value
            if self.default is not UNDEFINED:
                return self.default
            raise Invalid(
                self.msg,
                translation_key="value_one_of",
                placeholders={"values": list(self.mapping)},
            ) from exc


class EmptyToNone(_SafeValidator):
    """Replace an empty string or container with ``None``, leaving other values alone.

    ``EmptyToNone()`` turns ``""``, ``[]``, and ``{}`` into ``None``, the common
    "empty means unset" normalization from config and forms. A non-empty value passes
    through, and so does a falsy scalar like ``0`` or ``False`` (``0`` is a value, not
    an absence). It is the reverse of ``DefaultTo``, which fills a ``None``.
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __repr__(self) -> str:
        """Render as a constructor call."""
        return "EmptyToNone()"

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return None for an empty string or container, else the value unchanged."""
        if isinstance(value, _EMPTY_CONTAINERS) and len(value) == 0:
            return None
        return value
