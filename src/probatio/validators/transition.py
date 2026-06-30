"""Transition validators: rules that compare new data against its previous value.

These validate an update against the state it replaces. The previous value is
supplied through the call-time context, so the same compiled schema validates
every update:

    schema(new_config, context=old_config)

``current_context()`` returns that previous mapping, and the validators read it.
Like the other cross-field rules, they run after a dict schema with ``All`` and
see the whole (new) mapping. With no context (a first validation, nothing to
compare against) they are a no-op. They compare only top-level fields.
"""

from __future__ import annotations

import typing
from collections.abc import Mapping

from probatio.error import ImmutableInvalid, SchemaError
from probatio.schema import current_context
from probatio.validators._base import _SafeValidator


def _changed(old: typing.Any, new: typing.Any) -> bool:
    """Whether two values differ, treating a comparison that cannot run as changed.

    A guard that raises (a signaling Decimal, say) cannot prove the value is
    unchanged, so immutability errs on the safe side and counts it as a change,
    never a leaked exception.
    """
    try:
        return bool(old != new)
    except Exception:  # noqa: BLE001 - __eq__/__bool__ are user code; never leak
        return True


def _fields(fields: tuple[typing.Any, ...], name: str) -> tuple[typing.Any, ...]:
    """Require at least one field name for a transition rule."""
    if not fields:
        message = f"{name} needs at least one field"
        raise SchemaError(message)
    return fields


class Immutable(_SafeValidator):
    """Reject a change to a field's value between the previous data and the new.

    ``Immutable("user_id")``: if ``user_id`` is present in both the previous
    mapping (from ``current_context()``) and the new one, the two must be equal.
    A field being set for the first time (absent in the previous) is allowed; a
    field the update omits is not checked. The value passes through unchanged.
    """

    def __init__(self, *fields: typing.Any, msg: str | None = None) -> None:
        """Store the immutable field name(s) and an optional message."""
        self.fields = _fields(fields, "Immutable")
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the mapping, raising if an immutable field changed."""
        previous = current_context()

        if isinstance(value, Mapping) and isinstance(previous, Mapping):
            for field in self.fields:
                if (
                    field in previous
                    and field in value
                    and _changed(previous[field], value[field])
                ):
                    message = self.msg or f"{field!r} cannot be changed"
                    raise ImmutableInvalid(message, path=[field])

        return value


class WriteOnce(_SafeValidator):
    """Allow a field to be set once, then reject any later change.

    ``WriteOnce("token")``: while the previous value (from ``current_context()``)
    is absent or ``None``, the field may take any value; once it holds a value, a
    differing new value is rejected. So a field can go from unset to set, but not
    from one value to another. The value passes through unchanged.
    """

    def __init__(self, *fields: typing.Any, msg: str | None = None) -> None:
        """Store the write-once field name(s) and an optional message."""
        self.fields = _fields(fields, "WriteOnce")
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the mapping, raising if an already-set field changed."""
        previous = current_context()

        if isinstance(value, Mapping) and isinstance(previous, Mapping):
            for field in self.fields:
                old = previous.get(field)
                if old is not None and field in value and _changed(old, value[field]):
                    message = self.msg or f"{field!r} is write-once and already set"
                    raise ImmutableInvalid(message, path=[field])

        return value
