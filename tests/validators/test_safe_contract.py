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
from typing import Any, NoReturn, Self

import pytest
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
    Divide,
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
    Map,
    Match,
    Maybe,
    Modulo,
    Msg,
    MultipleOf,
    Multiply,
    NotIn,
    Offset,
    Remap,
    RemovePrefix,
    RemoveSuffix,
    Replace,
    RequiredIf,
    RequiredWith,
    RequiredWithout,
    Schema,
    SetTo,
    Snap,
    SomeOf,
    StartsWith,
    Strip,
    TaggedUnion,
    Title,
    Truncate,
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
    "Divide": Divide(2),
    "EndsWith": EndsWith("z"),
    "Equal": Equal(1),
    "ExactSequence": ExactSequence([int, str]),
    "ExactlyOne": ExactlyOne("a", "b"),
    "Immutable": Immutable("a"),
    "In": In([1, 2, 3]),
    "Literal": Literal("x"),
    "Map": Map({1: "a", 2: "b"}),
    "Match": Match(r"^a+$"),
    "Maybe": Maybe(int),
    "Modulo": Modulo(5),
    "Msg": Msg(int, "bad"),
    "MultipleOf": MultipleOf(3),
    "Multiply": Multiply(2),
    "NotIn": NotIn([1, 2]),
    "Offset": Offset(2),
    "Remap": Remap(0, 1, 0, 1),
    "RemovePrefix": RemovePrefix("p"),
    "RemoveSuffix": RemoveSuffix("s"),
    "Replace": Replace("a", "b"),
    "RequiredIf": RequiredIf({"a": 1}, "b"),
    "RequiredWith": RequiredWith("a", "b"),
    "RequiredWithout": RequiredWithout("a", "b"),
    "SetTo": SetTo(5),
    "Snap": Snap(0.5),
    "SomeOf": SomeOf([int, str], min_valid=1),
    "StartsWith": StartsWith("a"),
    "TaggedUnion": TaggedUnion("type", {"a": {"type": "a"}}),
    "Truncate": Truncate(5),
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


class _HostileDunders:
    """A value whose validation-path dunders all raise, to enforce the contract.

    Models a malicious or buggy object: comparison, membership, length, truthiness,
    iteration, and numeric-conversion dunders each raise a non-``Invalid`` exception.
    A built-in validator that applies one of these operators to the value must
    contain the failure as ``Invalid``, never let it escape.

    ``__str__``/``__repr__`` stay safe on purpose: a value that cannot even be
    rendered is degenerate (no code anywhere could format it), so it is out of the
    contract's scope, which is about validation *operations* on the value.
    """

    @staticmethod
    def _boom(*_args: object) -> NoReturn:
        message = "hostile dunder"
        raise RuntimeError(message)

    __eq__ = __ne__ = __lt__ = __le__ = __gt__ = __ge__ = _boom
    __contains__ = __len__ = __bool__ = __iter__ = _boom
    __float__ = __int__ = __index__ = __mod__ = _boom

    def __hash__(self) -> int:
        """Stay hashable (hashing the value is not the operation under test)."""
        return 0

    def __repr__(self) -> str:
        """Render safely, so an error message about this value never raises."""
        return "<hostile>"


class _TaggedList(list):
    """A ``list`` subclass whose constructor is not ``(iterable)``.

    A validator that rebuilds a sequence as its own type (``ExactSequence``, the
    engine's list path) must not leak the ``TypeError`` this constructor raises when
    called with a single iterable; it holds ``[1, "a"]`` so it satisfies the
    ``ExactSequence([int, str])`` under test and actually reaches the rebuild.
    """

    def __init__(self, items: Any, tag: object) -> None:
        """Build the list from ``items`` and stash an extra, non-iterable field."""
        super().__init__(items)
        self.tag = tag


class _Pair(tuple):
    """A ``tuple`` subclass whose constructor is not ``(iterable)`` (like ``_TaggedList``)."""

    __slots__ = ()

    def __new__(cls, a: object, b: object) -> Self:
        """Build a two-element tuple from positional arguments."""
        return super().__new__(cls, (a, b))


# The hostile probes: values that historically slip past a validator's guards. Fed
# to every built-in deterministically (``test_no_builtin_leaks_on_a_hostile_probe``)
# so each is exercised on every run, and also mixed into the recursive fuzz below for
# random breadth. The deterministic feed is the real net: the fuzz draws any one
# probe only occasionally, too rarely to reliably reach a specific parser branch.
_HOSTILE_PROBES: list[Any] = [
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
    # Unicode digit look-alikes: ``str.isdigit()``/``isnumeric()`` accept these, but
    # ``int()`` rejects the superscript ones, so a parser that gates on the wrong
    # predicate leaks a ValueError (the bug that hit the duration parser).
    "²",  # a superscript two on its own
    "1:²",  # and in a colon slot, the exact shape that broke the duration parser
    "\uff11\uff12\uff13",  # fullwidth 123: isdigit() and int() accept, still exotic
    # Oversized strings: past ``int()``'s string-length limit and past a small
    # ``max_size``, so a validator that does ``int(str)`` or scans the whole string
    # is exercised at scale.
    "9" * 5000,
    "a" * 5000,
    (),
    (1, 2),
    # Container subclasses with a non-``(iterable)`` constructor, to stress the
    # type-preserving rebuild paths.
    _TaggedList([1, "a"], "tag"),
    _Pair(1, "a"),
    _HostileDunders(),
]

_hostile = st.sampled_from(_HOSTILE_PROBES)

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


def _probe_id(probe: object) -> str:
    """A short, readable parametrize id, so an oversized probe does not bloat node ids."""
    text = repr(probe)
    return text if len(text) <= 24 else f"{text[:21]}..."


@pytest.mark.parametrize("probe", _HOSTILE_PROBES, ids=_probe_id)
def test_no_builtin_leaks_on_a_hostile_probe(probe: Any) -> None:
    """Each hostile probe, fed to every built-in, yields only Invalid, never a leak.

    Deterministic counterpart to the fuzz above: the fuzz draws any one probe only
    occasionally, so a specific parser branch (a superscript digit in a duration, an
    oversized ``int(str)``, a rebuild of a hostile container subclass) is reached
    reliably only by feeding every probe to every validator on every run. Each
    operator-boundary guard (comparison, membership, length, truthiness, iteration,
    numeric conversion) is exercised too, via the dunder-raising probe.
    """
    for schema in _SAFE_SCHEMAS:
        with contextlib.suppress(Invalid):
            schema(probe)
