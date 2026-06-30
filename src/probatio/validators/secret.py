"""The ``Secret`` validator and its masking carrier.

``Secret`` validates a value (optionally against an inner schema) and wraps it in
a ``SecretValue``: a carrier that hides the value from ``repr``, ``str``, and any
rendered validation error, so a credential in a config does not leak into logs.
Read the real value back with ``.get_secret_value()``.

The protection covers the validated value (what you log, repr, or render after
validation) and ``Secret``'s own failures (a bad secret is reported without
echoing it). It does not reach back into ``humanize_error`` called against the
raw, pre-validation input; humanize the validated output, not the raw data, when
secrets are involved.
"""

from __future__ import annotations

import typing

from probatio.error import Invalid, SecretInvalid
from probatio.schema import compile_schema
from probatio.validators._base import _SafeValidator

# A fixed-length mask, so the rendered form does not even reveal the length.
_MASK = "**********"


class SecretValue:
    """A wrapper that hides its value from ``repr``, ``str``, and error output."""

    __slots__ = ("_value",)

    def __init__(self, value: typing.Any) -> None:
        """Store the protected value."""
        self._value = value

    def get_secret_value(self) -> typing.Any:
        """Return the real, unmasked value."""
        return self._value

    def __repr__(self) -> str:
        """Render masked, never showing the value."""
        return f"SecretValue('{_MASK}')"

    def __str__(self) -> str:
        """Render masked, never showing the value."""
        return _MASK

    def __eq__(self, other: object) -> bool:
        """Compare equal to another SecretValue holding an equal value."""
        return isinstance(other, SecretValue) and self._value == other._value

    def __hash__(self) -> int:
        """Hash by the wrapped value, so a SecretValue works as a dict key."""
        return hash(self._value)


class Secret(_SafeValidator):
    """Validate a value, then wrap it in a ``SecretValue`` so it cannot leak.

    The optional inner schema validates the raw value first (``Secret(str)`` to
    require a string; the default accepts anything). A failure is reported without
    echoing the value, so the secret never reaches an error message. An input that
    is already a ``SecretValue`` is unwrapped and re-validated, so validation stays
    idempotent.
    """

    def __init__(self, schema: typing.Any = object, msg: str | None = None) -> None:
        """Compile the optional inner schema and store a message."""
        self.schema = schema
        self._validate = compile_schema(schema)
        self.msg = msg

    def __call__(self, value: typing.Any) -> SecretValue:
        """Return the validated value wrapped in a SecretValue."""
        if isinstance(value, SecretValue):
            value = value.get_secret_value()

        try:
            validated = self._validate(value)
        except Invalid as exc:
            # Never echo the secret in the error.
            raise SecretInvalid(self.msg or "secret value is not valid") from exc

        return SecretValue(validated)
