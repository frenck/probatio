"""Cross-field validators: rules that relate several keys of a mapping.

Unlike a marker (which annotates one key), these inspect the whole mapping, so
they are used after a dict schema with ``All``:

    Schema(All({...}, RequiredWith("tls", "cert")))

``RequiredWith`` and ``RequiredWithout`` require keys based on the presence (or
absence) of a trigger; ``RequiredIf`` requires keys when one or more fields hold a
given value; ``Check`` runs an arbitrary predicate over the value with a paired
message. The first three take a ``mode`` of ``"any"`` or ``"all"`` to combine
several triggers or conditions. ``AtLeastOne``, ``AtMostOne``, ``ExactlyOne``, and
``AllOrNone`` are the key-group presence rules: how many of a set of keys may or
must appear. Unlike the conditional rules, they reject a non-mapping by default
(``require_mapping=True``), matching what Home Assistant and ESPHome expect; pass
``require_mapping=False`` to leave a non-mapping untouched inside a pipeline.
"""

from __future__ import annotations

import typing
from collections.abc import Mapping

from probatio.error import (
    DictInvalid,
    ExclusiveInvalid,
    InclusiveInvalid,
    Invalid,
    MultipleInvalid,
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
                        raise RequiredFieldInvalid(
                            self.msg,
                            path=[key],
                            translation_key="required_when_present",
                            placeholders={
                                "key": key,
                                "triggers": _join(self.triggers, self.mode),
                            },
                        )
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
                        raise RequiredFieldInvalid(
                            self.msg,
                            path=[key],
                            translation_key="required_when_absent",
                            placeholders={
                                "key": key,
                                "triggers": _join(self.triggers, self.mode),
                            },
                        )
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
                        raise RequiredFieldInvalid(
                            self.msg,
                            path=[key],
                            translation_key="required_when_value",
                            placeholders={
                                "key": key,
                                "conditions": self._describe(),
                            },
                        )
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


class _KeyGroup(_SafeValidator):
    """Shared base for the key-presence rules over a mapping.

    Each rule names a set of keys and constrains how many of them may or must
    appear. By default a non-mapping value is rejected (``require_mapping``),
    matching what Home Assistant and ESPHome expect from these rules; pass
    ``require_mapping=False`` to leave a non-mapping untouched, so the rule can sit
    inside a larger pipeline that type-checks elsewhere.
    """

    def __init__(
        self,
        *keys: typing.Any,
        msg: str | None = None,
        require_mapping: bool = True,
    ) -> None:
        """Store the keys, the optional message, and the non-mapping policy."""
        self.keys = _require_keys(keys)
        self.msg = msg
        self.require_mapping = require_mapping

    def _mapping(self, value: typing.Any) -> Mapping[typing.Any, typing.Any] | None:
        """Return the value as a mapping, or None to pass a non-mapping through.

        Raises ``DictInvalid`` for a non-mapping when ``require_mapping`` is set,
        using the same wording the dict schema itself uses.
        """
        if isinstance(value, Mapping):
            return value
        if self.require_mapping:
            raise DictInvalid(translation_key="expected_mapping")
        return None


class AtLeastOne(_KeyGroup):
    """Require at least one of the named keys to be present in the mapping.

    ``AtLeastOne("host", "url")``: the mapping must contain ``host`` or ``url``, or
    both. A dict-level rule (voluptuous lacks it; Home Assistant rolled its own
    ``has_at_least_one_key``), used on its own or after a dict schema with ``All``.
    A non-mapping is rejected unless ``require_mapping=False``.
    """

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the mapping, raising if none of the keys are present."""
        mapping = self._mapping(value)
        if mapping is not None and not _present(mapping, self.keys):
            raise RequiredFieldInvalid(
                self.msg,
                translation_key="required_any_of",
                placeholders={"keys": list(self.keys)},
            )
        return value


class AtMostOne(_KeyGroup):
    """Allow at most one of the named keys to be present in the mapping.

    ``AtMostOne("include", "exclude")``: at most one of ``include``/``exclude`` may
    appear; both together fail. A dict-level rule, used on its own or after a dict
    schema with ``All``. When more than one is present, each offending key is
    reported with its own path, so an editor can point at every one. A non-mapping
    is rejected unless ``require_mapping=False``.
    """

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the mapping, raising one error per key when more than one appears."""
        mapping = self._mapping(value)
        if mapping is not None:
            present = _present(mapping, self.keys)
            if len(present) > 1:
                placeholders = {"keys": list(self.keys)}
                raise MultipleInvalid(
                    [
                        ExclusiveInvalid(
                            self.msg,
                            path=[key],
                            translation_key="allowed_at_most_one_of",
                            placeholders=placeholders,
                        )
                        for key in present
                    ]
                )
        return value


class ExactlyOne(_KeyGroup):
    """Require exactly one of the named keys to be present in the mapping.

    ``ExactlyOne("token", "password")``: one of the keys must appear, and only one.
    None is too few, two or more is too many. A dict-level rule, used on its own or
    after a dict schema with ``All``. Too many keys are reported one per offending
    key with its path; none present is a single pathless error, as there is no
    specific key to blame. A non-mapping is rejected unless ``require_mapping=False``.
    """

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the mapping, raising if not exactly one of the keys is present."""
        mapping = self._mapping(value)
        if mapping is not None:
            present = _present(mapping, self.keys)
            if not present:
                raise RequiredFieldInvalid(
                    self.msg,
                    translation_key="required_one_of",
                    placeholders={"keys": list(self.keys)},
                )
            if len(present) > 1:
                placeholders = {"keys": list(self.keys)}
                raise MultipleInvalid(
                    [
                        ExclusiveInvalid(
                            self.msg,
                            path=[key],
                            translation_key="allowed_one_of",
                            placeholders=placeholders,
                        )
                        for key in present
                    ]
                )
        return value


class AllOrNone(_KeyGroup):
    """Require the named keys to be present together, or none of them.

    ``AllOrNone("lat", "lon")``: either both ``lat`` and ``lon`` appear, or neither
    does; one without the other fails. The dict-level form of ``Inclusive`` (and
    ESPHome's ``has_none_or_all_keys``), used on its own or after a dict schema with
    ``All``. When some but not all appear, each missing key is reported with its own
    path. A non-mapping is rejected unless ``require_mapping=False``.
    """

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the mapping, raising if some but not all of the keys are present."""
        mapping = self._mapping(value)
        if mapping is not None:
            present = _present(mapping, self.keys)
            if present and len(present) != len(self.keys):
                missing = [key for key in self.keys if key not in mapping]
                placeholders = {"keys": list(self.keys)}
                raise MultipleInvalid(
                    [
                        InclusiveInvalid(
                            self.msg,
                            path=[key],
                            translation_key="required_none_or_all_of",
                            placeholders=placeholders,
                        )
                        for key in missing
                    ]
                )
        return value
