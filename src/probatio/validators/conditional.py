"""Cross-field validators: rules that relate several keys of a mapping.

Unlike a marker (which annotates one key), these inspect the whole mapping, so
they are used after a dict schema with ``All``:

    Schema(All({...}, RequiredWith("tls", "cert")))

``RequiredWith`` and ``RequiredWithout`` require keys based on the presence (or
absence) of a trigger; ``RequiredIf`` requires keys when one or more fields hold a
given value; ``Check`` runs an arbitrary predicate over the value with a paired
message. The first three take a ``mode`` of ``"any"`` or ``"all"`` to combine
several triggers or conditions. ``AtLeastOne``, ``AtMostOne``, and ``ExactlyOne``
are the key-group presence rules: how many of a set of keys may or must appear.
"""

from __future__ import annotations

import typing
from collections.abc import Mapping

from probatio.error import (
    ExclusiveInvalid,
    Invalid,
    RequiredFieldInvalid,
    SchemaError,
)
from probatio.validators._base import _SafeValidator

_MODES = ("any", "all")


def _check_mode(mode: str) -> str:
    """Reject a mode that is not ``"any"`` or ``"all"``."""
    if mode not in _MODES:
        message = f"mode must be 'any' or 'all', got {mode!r}"
        raise SchemaError(message)
    return mode


def _as_keys(trigger: typing.Any) -> tuple[typing.Any, ...]:
    """Normalize a single key or a list of keys into a tuple of keys.

    A ``list`` means several keys; anything else is one key. A list can never be a
    mapping key (it is unhashable), so this never mistakes a real key for a list.
    """
    keys = tuple(trigger) if isinstance(trigger, list) else (trigger,)
    if not keys:
        message = "needs at least one trigger key"
        raise SchemaError(message)
    return keys


def _fires(flags: list[bool], mode: str) -> bool:
    """Combine per-trigger flags by the mode (any of them, or all of them)."""
    return all(flags) if mode == "all" else any(flags)


def _join(keys: tuple[typing.Any, ...], mode: str) -> str:
    """Render a trigger list for a message, naming the mode when there are several."""
    if len(keys) == 1:
        return repr(keys[0])
    joined = ", ".join(repr(key) for key in keys)
    return f"{mode} of [{joined}]"


def _require_keys(keys: tuple[typing.Any, ...]) -> tuple[typing.Any, ...]:
    """Reject an empty key list for a key-group validator."""
    if not keys:
        message = "needs at least one key"
        raise SchemaError(message)
    return keys


def _key_list(keys: tuple[typing.Any, ...]) -> str:
    """Render a key list for a message: ``'a', 'b', 'c'``."""
    return ", ".join(repr(key) for key in keys)


def _present(
    value: Mapping[typing.Any, typing.Any], keys: tuple[typing.Any, ...]
) -> list[typing.Any]:
    """Return the named keys that are present in the mapping, in the given order."""
    return [key for key in keys if key in value]


class RequiredWith(_SafeValidator):
    """Require keys to be present when a trigger key is present.

    ``RequiredWith("tls", "cert", "key")``: if ``tls`` is in the mapping, then
    ``cert`` and ``key`` must be too. Pass a list of trigger keys with
    ``mode="any"`` (the default, any one present fires the rule) or ``mode="all"``
    (every trigger must be present). When the rule does not fire, nothing is
    required. The value passes through unchanged.
    """

    def __init__(
        self,
        trigger: typing.Any,
        *required: typing.Any,
        mode: str = "any",
        msg: str | None = None,
    ) -> None:
        """Store the trigger key(s), the keys they require, and the combine mode."""
        self.triggers = _as_keys(trigger)
        self.required = required
        self.mode = _check_mode(mode)
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the mapping, raising if a required key is missing."""
        if isinstance(value, Mapping):
            flags = [key in value for key in self.triggers]
            if _fires(flags, self.mode):
                for key in self.required:
                    if key not in value:
                        message = self.msg or (
                            f"{key!r} is required when "
                            f"{_join(self.triggers, self.mode)} is present"
                        )
                        raise RequiredFieldInvalid(message, path=[key])
        return value


class RequiredWithout(_SafeValidator):
    """Require keys to be present when a trigger key is absent.

    ``RequiredWithout("cert", "cert_path")``: if ``cert`` is not in the mapping,
    then ``cert_path`` must be. Pass a list of trigger keys with ``mode="any"``
    (the default, any one absent fires the rule) or ``mode="all"`` (every trigger
    must be absent). The value passes through unchanged.
    """

    def __init__(
        self,
        trigger: typing.Any,
        *required: typing.Any,
        mode: str = "any",
        msg: str | None = None,
    ) -> None:
        """Store the trigger key(s), the keys they require, and the combine mode."""
        self.triggers = _as_keys(trigger)
        self.required = required
        self.mode = _check_mode(mode)
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the mapping, raising if a required key is missing."""
        if isinstance(value, Mapping):
            flags = [key not in value for key in self.triggers]
            if _fires(flags, self.mode):
                for key in self.required:
                    if key not in value:
                        message = self.msg or (
                            f"{key!r} is required when "
                            f"{_join(self.triggers, self.mode)} is absent"
                        )
                        raise RequiredFieldInvalid(message, path=[key])
        return value


def _matches(
    value: Mapping[typing.Any, typing.Any], key: typing.Any, expected: typing.Any
) -> bool:
    """Whether ``value[key]`` equals ``expected``, treating a raising compare as no."""
    if key not in value:
        return False
    try:
        return bool(value[key] == expected)
    except (TypeError, ArithmeticError):
        # A comparison that cannot evaluate (a signaling Decimal, say) is not a
        # match, never a leaked exception.
        return False


class RequiredIf(_SafeValidator):
    """Require keys to be present when one or more fields hold a value.

    ``RequiredIf({"auth": "token"}, "token")``: if ``auth`` equals ``"token"``,
    then the ``token`` key must be present. With several conditions, ``mode="all"``
    (the default) fires only when every condition holds, and ``mode="any"`` fires
    when any one does. When the rule does not fire, nothing is required. The value
    passes through unchanged.
    """

    def __init__(
        self,
        conditions: Mapping[typing.Any, typing.Any],
        *required: typing.Any,
        mode: str = "all",
        msg: str | None = None,
    ) -> None:
        """Store the field/value conditions, the required keys, and the mode."""
        self.conditions = dict(conditions)
        if not self.conditions:
            message = "needs at least one condition"
            raise SchemaError(message)
        self.required = required
        self.mode = _check_mode(mode)
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the mapping, raising if a required key is missing."""
        if isinstance(value, Mapping):
            flags = [
                _matches(value, key, expected)
                for key, expected in self.conditions.items()
            ]
            if _fires(flags, self.mode):
                for key in self.required:
                    if key not in value:
                        message = self.msg or (
                            f"{key!r} is required when {self._describe()}"
                        )
                        raise RequiredFieldInvalid(message, path=[key])
        return value

    def _describe(self) -> str:
        """Render the conditions for a message, naming the mode when there are several."""
        pairs = [
            f"{key!r} is {expected!r}" for key, expected in self.conditions.items()
        ]
        if len(pairs) == 1:
            return pairs[0]
        return f"{self.mode} of ({', '.join(pairs)})"


class Check(_SafeValidator):
    """Validate the whole value with a boolean predicate and a message.

    ``Check(lambda d: d["start"] < d["end"], "start must be before end")``: the
    predicate is called with the value and must return truthy. A falsy result, or
    a predicate that raises (a missing key, a type error), is reported with the
    message, so the value never leaks a raw exception. Use it after a dict schema
    with ``All`` for a cross-field rule the markers cannot express.
    """

    def __init__(
        self,
        predicate: typing.Callable[[typing.Any], typing.Any],
        msg: str,
    ) -> None:
        """Store the predicate and the message to report when it does not hold."""
        self.predicate = predicate
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if the predicate holds, else raise Invalid."""
        try:
            holds = self.predicate(value)
        except Invalid:
            raise
        except Exception as exc:
            # A predicate that cannot evaluate (a missing key, a wrong type) is a
            # failed check, reported with the message, not a leaked exception.
            raise Invalid(self.msg) from exc
        if not holds:
            raise Invalid(self.msg)
        return value


class AtLeastOne(_SafeValidator):
    """Require at least one of the named keys to be present in the mapping.

    ``AtLeastOne("host", "url")``: the mapping must contain ``host`` or ``url``, or
    both. A dict-level rule (voluptuous lacks it; Home Assistant rolled its own
    ``has_at_least_one_key``), used after a dict schema with ``All``. The value
    passes through unchanged, and a non-mapping is left alone.
    """

    def __init__(self, *keys: typing.Any, msg: str | None = None) -> None:
        """Store the keys, at least one of which must be present."""
        self.keys = _require_keys(keys)
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the mapping, raising if none of the keys are present."""
        if isinstance(value, Mapping) and not _present(value, self.keys):
            message = self.msg or f"at least one of {_key_list(self.keys)} is required"
            raise RequiredFieldInvalid(message)
        return value


class AtMostOne(_SafeValidator):
    """Allow at most one of the named keys to be present in the mapping.

    ``AtMostOne("include", "exclude")``: at most one of ``include``/``exclude`` may
    appear; both together fail. A dict-level rule, used after a dict schema with
    ``All``. The value passes through unchanged, and a non-mapping is left alone.
    """

    def __init__(self, *keys: typing.Any, msg: str | None = None) -> None:
        """Store the keys, at most one of which may be present."""
        self.keys = _require_keys(keys)
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the mapping, raising if more than one of the keys is present."""
        if isinstance(value, Mapping):
            present = _present(value, self.keys)
            if len(present) > 1:
                message = self.msg or (
                    f"at most one of {_key_list(self.keys)} is allowed, "
                    f"got {_key_list(tuple(present))}"
                )
                raise ExclusiveInvalid(message)
        return value


class ExactlyOne(_SafeValidator):
    """Require exactly one of the named keys to be present in the mapping.

    ``ExactlyOne("token", "password")``: one of the keys must appear, and only one.
    None is too few, two or more is too many. A dict-level rule, used after a dict
    schema with ``All``. The value passes through unchanged, and a non-mapping is
    left alone.
    """

    def __init__(self, *keys: typing.Any, msg: str | None = None) -> None:
        """Store the keys, exactly one of which must be present."""
        self.keys = _require_keys(keys)
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the mapping, raising if not exactly one of the keys is present."""
        if isinstance(value, Mapping):
            present = _present(value, self.keys)
            if not present:
                message = (
                    self.msg or f"exactly one of {_key_list(self.keys)} is required"
                )
                raise RequiredFieldInvalid(message)
            if len(present) > 1:
                message = self.msg or (
                    f"exactly one of {_key_list(self.keys)} is allowed, "
                    f"got {_key_list(tuple(present))}"
                )
                raise ExclusiveInvalid(message)
        return value
