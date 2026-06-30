"""Enforce the safe-validator contract across every built-in.

The contract (the library's #1 invariant): on any input, a built-in validator
returns a value or raises a subclass of ``Invalid``, and nothing else, never a
leaked ``ValueError``/``TypeError``/parser exception. The engine calls validators
back with untrusted data, so a leak escapes the ``MultipleInvalid`` a caller
catches.

This test enumerates *every* ``_SafeValidator`` subclass (so a newly added one is
covered automatically, or the completeness check fails until it is registered),
plus the factory and function validators that are not subclasses, and hammers each
with hostile generated input, asserting nothing but ``Invalid`` ever escapes.
"""

from __future__ import annotations

import contextlib
from decimal import Decimal
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from probatio import (
    AllOrNone,
    AtLeastOne,
    AtMostOne,
    Boolean,
    Capitalize,
    Check,
    Coerce,
    Contains,
    DefaultTo,
    Email,
    EndsWith,
    Equal,
    ExactlyOne,
    ExactSequence,
    FqdnUrl,
    Immutable,
    In,
    Invalid,
    Literal,
    Lower,
    Match,
    Maybe,
    Msg,
    MultipleOf,
    NotIn,
    Replace,
    RequiredIf,
    RequiredWith,
    RequiredWithout,
    Schema,
    SetTo,
    SomeOf,
    StartsWith,
    Strip,
    Title,
    Unordered,
    Upper,
    Url,
    WriteOnce,
)
from probatio.validators._base import _SafeValidator

# Constructor arguments for the subclasses that need them; everything else is
# instantiated with no arguments. A new subclass that needs arguments and is not
# listed here trips ``test_every_safe_validator_subclass_is_covered``.
_NEEDS_ARGS: dict[str, _SafeValidator] = {
    "AllOrNone": AllOrNone("a", "b"),
    "AtLeastOne": AtLeastOne("a", "b"),
    "AtMostOne": AtMostOne("a", "b"),
    "Check": Check(lambda _value: True, "bad"),
    "Coerce": Coerce(int),
    "Contains": Contains(1),
    "DefaultTo": DefaultTo(0),
    "EndsWith": EndsWith("z"),
    "Equal": Equal(1),
    "ExactSequence": ExactSequence([int, str]),
    "ExactlyOne": ExactlyOne("a", "b"),
    "Immutable": Immutable("a"),
    "In": In([1, 2, 3]),
    "Literal": Literal("x"),
    "Match": Match(r"^a+$"),
    "Maybe": Maybe(int),
    "Msg": Msg(int, "bad"),
    "MultipleOf": MultipleOf(3),
    "NotIn": NotIn([1, 2]),
    "Replace": Replace("a", "b"),
    "RequiredIf": RequiredIf({"a": 1}, "b"),
    "RequiredWith": RequiredWith("a", "b"),
    "RequiredWithout": RequiredWithout("a", "b"),
    "SetTo": SetTo(5),
    "SomeOf": SomeOf([int, str], min_valid=1),
    "StartsWith": StartsWith("a"),
    "Unordered": Unordered([int, str]),
    "WriteOnce": WriteOnce("a"),
}

# Built-in validators that are factories or plain functions, not subclasses, so the
# subclass walk does not reach them. They go through the engine's ValueError guard,
# but must still never leak any other exception type.
_FACTORY_VALIDATORS: list[Any] = [
    Email(),
    Url(),
    FqdnUrl(),
    Boolean(),
    Lower,
    Upper,
    Capitalize,
    Title,
    Strip,
]


def _all_subclasses(cls: type) -> set[type]:
    """Return every (transitive) subclass of ``cls``."""
    found: set[type] = set()
    for sub in cls.__subclasses__():
        found.add(sub)
        found |= _all_subclasses(sub)
    return found


# Public subclasses only; the private bases (_CharacterClass, _FilesystemCheck) are
# abstract and only ever used through their concrete children.
_SUBCLASSES = {
    cls.__name__: cls
    for cls in _all_subclasses(_SafeValidator)
    if not cls.__name__.startswith("_")
}


def _instance(name: str, cls: type) -> _SafeValidator:
    """Construct a representative instance of a safe-validator subclass."""
    if name in _NEEDS_ARGS:
        return _NEEDS_ARGS[name]
    return cls()


_SAFE_SCHEMAS = [
    Schema(_instance(name, cls)) for name, cls in sorted(_SUBCLASSES.items())
] + [Schema(validator) for validator in _FACTORY_VALIDATORS]


def test_every_safe_validator_subclass_is_covered() -> None:
    """Every _SafeValidator subclass is instantiable here, so all get fuzzed.

    A new subclass that needs constructor arguments must be added to ``_NEEDS_ARGS``;
    until then this fails, so a validator can never slip in unfuzzed.
    """
    uncovered = []
    for name, cls in _SUBCLASSES.items():
        if name in _NEEDS_ARGS:
            continue
        try:
            cls()
        except Exception:  # noqa: BLE001
            uncovered.append(name)

    assert not uncovered, (
        f"add constructor args to _NEEDS_ARGS for: {sorted(uncovered)}"
    )


_hostile = st.sampled_from(
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        10**400,
        -(10**400),
        "\ud800",
        "\udfff",
        "a\x00b",
        (),
        (1, 2),
    ],
)

_values = st.recursive(
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats()
    | st.decimals()
    | st.text(max_size=20)
    | st.binary(max_size=8)
    | _hostile,
    lambda children: (
        st.lists(children, max_size=4)
        | st.dictionaries(st.text(max_size=4), children, max_size=4)
    ),
    max_leaves=6,
)


@given(value=_values)
@settings(
    max_examples=500,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_no_builtin_validator_leaks_a_non_invalid_exception(value: Any) -> None:
    """No built-in validator leaks anything but Invalid, whatever the input."""
    for schema in _SAFE_SCHEMAS:
        with contextlib.suppress(Invalid):
            schema(value)
