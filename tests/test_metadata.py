"""Tests for the metadata model and its propagation through validation."""

from __future__ import annotations

import copy
import pickle
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from probatio import (
    ALLOW_EXTRA,
    PREVENT_EXTRA,
    REMOVE_EXTRA,
    Alias,
    All,
    Coerce,
    CompilePolicy,
    ExactSequence,
    Metadata,
    Object,
    Optional,
    Required,
    Schema,
    add_metadata,
    carry_metadata,
    get_compile_policy,
    metadata_of,
    set_compile_policy,
    supports_metadata,
)
from probatio import Any as AnyOf
from probatio import metadata as metadata_module
from probatio.metadata import METADATA_ATTR

if TYPE_CHECKING:
    from collections.abc import Iterator

# The marker a loader would attach: where the value came from. Tests assert it is
# still there after validation rebuilt the container.
SOURCE = {"file": "app.yaml", "line": 12}

# Enough calls for a schema to warm up under any policy. The AUTO threshold is 50
# and the ON policy compiles on the first call, so this covers both.
WARMUP_CALLS = 60


class MetadataDict(dict):
    """A dict subclass that makes room for metadata with one slot."""

    __slots__ = ("__probatio_metadata__",)


class MetadataList(list):
    """A list subclass that makes room for metadata with one slot."""

    __slots__ = ("__probatio_metadata__",)


class MetadataStr(str):
    """A str subclass that makes room for metadata, used as a mapping key."""

    __slots__ = ("__probatio_metadata__",)


class MetadataTuple(tuple):  # noqa: SLOT001
    """A tuple subclass carrying metadata in its __dict__.

    A tuple subclass cannot declare a non-empty __slots__, and an empty one would
    leave nowhere for the attribute to live, so this relies on the ordinary instance
    dict, which is the second of the two ways a type opts in.
    """


class FixedList(list):
    """A list subclass whose constructor takes no iterable, so a rebuild fails."""

    __slots__ = ("__probatio_metadata__",)

    def __init__(self) -> None:
        """Fill the list with its fixed contents."""
        super().__init__(["x"])


class ReadOnlyCarrier(dict):
    """A dict subclass exposing its metadata through a read-only property."""

    @property
    def __probatio_metadata__(self) -> Metadata:
        """Return the fixed metadata this type was built with."""
        return Metadata(fixed=True)


class WritableCarrier(dict):
    """A dict subclass exposing its metadata through a settable property.

    Not a carrier: probatio will not write through a setter, so this stands for the
    shape the protocol rejects even though the write would technically land.
    """

    __slots__ = ("_where",)

    @property
    def __probatio_metadata__(self) -> Metadata | None:
        """Return the metadata assembled from this type's own fields."""
        return getattr(self, "_where", None)

    @__probatio_metadata__.setter
    def __probatio_metadata__(self, value: Mapping[str, Any]) -> None:
        """Store the metadata in this type's own field."""
        self._where = value


class ForeignMapping(Mapping):
    """A Mapping that is not a dict subclass, so validation rebuilds a plain dict."""

    def __init__(self, data: dict[Any, Any]) -> None:
        """Store the mapping this one reads from."""
        self._data = data

    def __getitem__(self, key: Any) -> Any:
        """Return the value stored under the key."""
        return self._data[key]

    def __iter__(self) -> Iterator[Any]:
        """Iterate the keys."""
        return iter(self._data)

    def __len__(self) -> int:
        """Return how many keys there are."""
        return len(self._data)


class SlottedPoint:
    """An attribute-bearing object with a slot for its metadata."""

    __slots__ = ("__probatio_metadata__", "x", "y")

    def __init__(self, x: Any = None, y: Any = None) -> None:
        """Store the two coordinates."""
        self.x = x
        self.y = y

    def __eq__(self, other: object) -> bool:
        """Compare by coordinates."""
        return isinstance(other, SlottedPoint) and (self.x, self.y) == (
            other.x,
            other.y,
        )

    def __hash__(self) -> int:
        """Hash by coordinates."""
        return hash((self.x, self.y))


class DictPoint:
    """An attribute-bearing object whose metadata live in its instance dict."""

    def __init__(self, x: Any = None, y: Any = None) -> None:
        """Store the two coordinates."""
        self.x = x
        self.y = y

    def __eq__(self, other: object) -> bool:
        """Compare by coordinates."""
        return isinstance(other, DictPoint) and (self.x, self.y) == (other.x, other.y)

    def __hash__(self) -> int:
        """Hash by coordinates."""
        return hash((self.x, self.y))


class Pair(NamedTuple):
    """A namedtuple rebuilt field by field through the sequence engine."""

    a: str
    b: int


def metadata_dict(data: dict[Any, Any] | None = None) -> MetadataDict:
    """Return a MetadataDict of the data, carrying the source marker."""
    return add_metadata(MetadataDict(data if data is not None else {"a": "x"}), SOURCE)


def metadata_list(items: list[Any] | None = None) -> MetadataList:
    """Return a MetadataList of the items, carrying the source marker."""
    return add_metadata(MetadataList(items if items is not None else ["x"]), SOURCE)


def assert_carried(result: Any, expected_type: type) -> None:
    """Assert the value has the expected type and still carries the source marker."""
    assert type(result) is expected_type
    assert metadata_of(result) == SOURCE


def mark_checked(value: Any) -> Any:
    """Mark a value as checked in its metadata and return it."""
    return add_metadata(value, checked=True)


def strip_empty_values(value: Any) -> Any:
    """Rebuild a mapping without its empty values, moving the metadata across."""
    kept = type(value)((key, item) for key, item in value.items() if item)
    return carry_metadata(value, kept)


def strip_empty_values_unaware(value: Any) -> Any:
    """Rebuild a mapping without its empty values, leaving the metadata behind."""
    return type(value)((key, item) for key, item in value.items() if item)


@pytest.fixture(params=[CompilePolicy.OFF, CompilePolicy.ON], ids=["off", "on"])
def _compile_policy(request: pytest.FixtureRequest) -> Iterator[None]:
    """Run the test under one compile policy, restoring the original afterwards."""
    original = get_compile_policy()
    set_compile_policy(request.param)
    try:
        yield
    finally:
        set_compile_policy(original)


def test_metadata_from_a_mapping() -> None:
    """A mapping passed positionally becomes the metadata."""
    assert Metadata({"file": "app.yaml"}) == {"file": "app.yaml"}


def test_metadata_from_keyword_arguments() -> None:
    """Keyword arguments alone become the metadata."""
    assert Metadata(file="app.yaml", line=12) == SOURCE


def test_metadata_from_a_mapping_and_keywords() -> None:
    """A mapping and keywords combine, with the keyword winning on a shared key."""
    assert Metadata({"file": "app.yaml", "line": 1}, line=12) == SOURCE


def test_metadata_can_be_empty() -> None:
    """Built with nothing at all, the metadata is empty."""
    assert Metadata() == {}


def test_metadata_copy_the_source_mapping() -> None:
    """The source mapping is copied, so a later change to it does not reach in."""
    source = {"file": "app.yaml"}
    metadata = Metadata(source)
    source["file"] = "other.yaml"
    assert metadata == {"file": "app.yaml"}


def test_metadata_cannot_be_reinitialized() -> None:
    """Calling __init__ again on a built Metadata leaves its contents alone."""
    metadata = Metadata(SOURCE)
    metadata.__init__(line=99)  # type: ignore[misc]
    assert metadata == SOURCE


def test_metadata_values_are_stored_as_given() -> None:
    """Immutability is shallow: a mutable value is the caller's own object."""
    findings: list[str] = []
    metadata = Metadata(findings=findings)
    findings.append("deprecated")
    assert metadata["findings"] is findings
    assert metadata["findings"] == ["deprecated"]


def test_metadata_cannot_be_mutated_through_their_storage() -> None:
    """The backing mapping is read-only, so the immutability is enforced not advised."""
    metadata = Metadata(SOURCE)
    with pytest.raises(TypeError):
        metadata._data["file"] = "other.yaml"  # type: ignore[index]
    assert metadata == SOURCE


def test_metadata_survive_a_pickle_round_trip() -> None:
    """Pickling rebuilds an equal Metadata, despite the read-only backing store."""
    metadata = Metadata(SOURCE)
    assert pickle.loads(pickle.dumps(metadata)) == SOURCE  # noqa: S301


@pytest.mark.parametrize("clone", [copy.copy, copy.deepcopy])
def test_metadata_survive_a_copy(clone: Any) -> None:
    """Copying and deep-copying both rebuild an equal Metadata."""
    metadata = Metadata(SOURCE)
    assert clone(metadata) == SOURCE


def test_metadata_read_by_key() -> None:
    """A key reads back the value stored under it."""
    assert Metadata(SOURCE)["file"] == "app.yaml"


def test_metadata_report_their_length() -> None:
    """len counts the metadata."""
    assert len(Metadata(SOURCE)) == 2


def test_metadata_iterate_their_keys() -> None:
    """Iterating yields the metadata keys."""
    assert list(Metadata(SOURCE)) == ["file", "line"]


def test_metadata_support_membership() -> None:
    """A key is in the metadata when it was added."""
    metadata = Metadata(SOURCE)
    assert "file" in metadata
    assert "missing" not in metadata


def test_metadata_get_returns_a_default() -> None:
    """get returns the value, or the default for a key that is not there."""
    metadata = Metadata(SOURCE)
    assert metadata.get("file") == "app.yaml"
    assert metadata.get("missing", "fallback") == "fallback"


def test_metadata_expose_keys_values_and_items() -> None:
    """The mapping views report the metadata."""
    metadata = Metadata(SOURCE)
    assert list(metadata.keys()) == ["file", "line"]
    assert list(metadata.values()) == ["app.yaml", 12]
    assert list(metadata.items()) == [("file", "app.yaml"), ("line", 12)]


def test_metadata_equal_a_plain_dict() -> None:
    """Metadata compare equal to a plain dict of the same contents."""
    assert Metadata(SOURCE) == {"file": "app.yaml", "line": 12}
    assert Metadata(SOURCE) != {"file": "app.yaml"}


def test_metadata_raise_key_error_for_a_missing_key() -> None:
    """Reading a key that was never added raises KeyError."""
    with pytest.raises(KeyError):
        Metadata(SOURCE)["missing"]


def test_metadata_repr_shows_the_metadata() -> None:
    """The repr names the type and renders the metadata themselves."""
    assert repr(Metadata(file="app.yaml")) == "Metadata({'file': 'app.yaml'})"


def test_merge_returns_a_new_object_and_leaves_the_original() -> None:
    """merge builds a new Metadata; the original is untouched."""
    original = Metadata(SOURCE)
    merged = original.merge({"checked": True})
    assert merged is not original
    assert original == SOURCE
    assert merged == {**SOURCE, "checked": True}


def test_merge_lets_the_incoming_values_win() -> None:
    """On a shared key the incoming value replaces the existing one."""
    assert Metadata(SOURCE).merge({"line": 99})["line"] == 99


def test_merge_accepts_keyword_arguments() -> None:
    """merge takes keywords, with or without a mapping alongside them."""
    assert Metadata(SOURCE).merge(checked=True) == {**SOURCE, "checked": True}
    assert Metadata(SOURCE).merge({"line": 99}, checked=True) == {
        "file": "app.yaml",
        "line": 99,
        "checked": True,
    }


def test_merge_with_nothing_returns_the_same_object() -> None:
    """Merging nothing in has nothing to build, so the same object comes back."""
    original = Metadata(SOURCE)
    assert original.merge() is original


def test_metadata_are_unhashable() -> None:
    """Metadata is a Mapping, so it is not hashable. Pin that deliberately."""
    assert Metadata.__hash__ is None
    with pytest.raises(TypeError, match="unhashable"):
        hash(Metadata(SOURCE))


def test_supports_metadata_for_a_slotted_carrier() -> None:
    """A type declaring the attribute in __slots__ can hold metadata."""
    assert supports_metadata(MetadataDict()) is True


def test_supports_metadata_for_a_plain_dict_class() -> None:
    """A type whose instances have an ordinary __dict__ can hold metadata."""
    assert supports_metadata(DictPoint()) is True


@pytest.mark.parametrize("carrier", [WritableCarrier, ReadOnlyCarrier])
def test_supports_metadata_is_false_for_a_property(carrier: type) -> None:
    """A property takes the write as a call, so probatio will not carry through it."""
    assert supports_metadata(carrier()) is False


def test_supports_metadata_is_false_for_a_custom_setattr() -> None:
    """An overridden __setattr__ takes every write, so it is not a plain attribute."""

    class Guarded:
        """Routes every attribute write through code of its own."""

        __slots__ = ("__probatio_metadata__",)

        def __setattr__(self, name: str, value: Any) -> None:
            """Perform the write through object, after seeing it."""
            object.__setattr__(self, name, value)

    assert supports_metadata(Guarded()) is False


def test_supports_metadata_runs_no_descriptor_code() -> None:
    """The class lookup reads the namespace, so a descriptor's __get__ never runs."""
    calls: list[str] = []

    class Loud:
        """A data descriptor that records and refuses every read."""

        def __get__(self, obj: Any, objtype: type | None = None) -> Any:
            """Record the read and raise, which must never happen here."""
            calls.append("get")
            message = "descriptor __get__ blew up"
            raise RuntimeError(message)

        def __set__(self, obj: Any, value: Any) -> None:
            """Accept the write."""

    class LoudCarrier(dict):
        """Exposes the metadata attribute through the descriptor above."""

        __probatio_metadata__ = Loud()

    assert supports_metadata(LoudCarrier()) is False
    assert calls == []


def test_supports_metadata_is_false_for_a_class_object() -> None:
    """A class exposes a read-only __dict__ proxy, so it is not a carrier."""
    assert supports_metadata(dict) is False
    assert supports_metadata(MetadataDict) is False


@pytest.mark.parametrize("value", [{}, [], "text", 1, ()])
def test_supports_metadata_is_false_for_builtin_values(value: Any) -> None:
    """A plain dict, list, str, int or tuple makes no room for the attribute."""
    assert supports_metadata(value) is False


def test_metadata_of_a_bare_carrier_is_none() -> None:
    """A carrier that was never given metadata reports none."""
    assert metadata_of(MetadataDict()) is None


def test_metadata_of_a_value_that_cannot_carry_is_none() -> None:
    """A value with nowhere to hold the attribute reports no metadata."""
    assert metadata_of({"a": "x"}) is None


def test_metadata_of_returns_the_stored_object() -> None:
    """A Metadata already on the value is handed back, not rebuilt."""
    value = metadata_dict()
    assert metadata_of(value) is value.__probatio_metadata__


def test_metadata_of_normalizes_a_plain_dict() -> None:
    """A plain mapping in the attribute is read back as a Metadata."""
    value = MetadataDict()
    value.__probatio_metadata__ = {"file": "app.yaml"}
    result = metadata_of(value)
    assert type(result) is Metadata
    assert result == {"file": "app.yaml"}


def test_metadata_of_rejects_a_non_mapping() -> None:
    """A carrier holding something that is not a mapping is broken, and says so."""
    value = MetadataDict()
    value.__probatio_metadata__ = "app.yaml"
    with pytest.raises(TypeError, match="which is not a mapping"):
        metadata_of(value)


def test_add_metadata_attaches_to_a_bare_carrier() -> None:
    """A carrier with no metadata yet gets the given ones."""
    assert metadata_of(add_metadata(MetadataDict(), file="app.yaml")) == {
        "file": "app.yaml",
    }


def test_add_metadata_merges_with_the_new_values_winning() -> None:
    """Existing keys are kept, and the incoming values win on a shared key."""
    value = add_metadata(MetadataDict(), file="app.yaml", line=1)
    add_metadata(value, line=12, checked=True)
    assert metadata_of(value) == {**SOURCE, "checked": True}


def test_add_metadata_returns_the_value() -> None:
    """add_metadata hands the value back, so it reads well as a validator's last line."""
    value = MetadataDict()
    assert add_metadata(value, file="app.yaml") is value


def test_add_metadata_accepts_a_positional_mapping() -> None:
    """A mapping can be passed positionally instead of as keywords."""
    assert metadata_of(add_metadata(MetadataDict(), SOURCE)) == SOURCE


def test_add_metadata_accepts_a_mapping_and_keywords() -> None:
    """A mapping and keywords combine, with the keyword winning on a shared key."""
    value = add_metadata(MetadataDict(), {"file": "app.yaml", "line": 1}, line=12)
    assert metadata_of(value) == SOURCE


def test_add_metadata_with_nothing_is_a_no_op() -> None:
    """With no mapping and no keywords there is nothing to attach."""
    value = MetadataDict()
    assert add_metadata(value) is value
    assert metadata_of(value) is None


# An int and a plain dict have nowhere to put the attribute; the ``dict`` type
# object itself refuses the write with a TypeError rather than an AttributeError.
@pytest.mark.parametrize("value", [1, {}, dict])
def test_add_metadata_is_silent_on_a_value_that_cannot_carry(value: Any) -> None:
    """A value with nowhere to put metadata comes back unchanged, not an error."""
    assert add_metadata(value, SOURCE) is value
    assert metadata_of(value) is None


def test_add_metadata_is_silent_on_a_read_only_property() -> None:
    """A carrier whose property cannot be written keeps what it had, without raising."""
    value = ReadOnlyCarrier()
    assert add_metadata(value, SOURCE) is value
    assert metadata_of(value) == {"fixed": True}


def test_add_metadata_rejects_a_broken_carrier() -> None:
    """A carrier already holding a non-mapping raises, the way reading it does."""
    value = MetadataDict()
    value.__probatio_metadata__ = "app.yaml"
    with pytest.raises(TypeError, match="which is not a mapping"):
        add_metadata(value, line=12)


def test_carry_metadata_copies_to_the_target() -> None:
    """The source's metadata land on the target, which is returned."""
    target = MetadataDict()
    assert carry_metadata(metadata_dict(), target) is target
    assert metadata_of(target) == SOURCE


def test_carry_metadata_replaces_what_the_target_carried() -> None:
    """The carry replaces the target's own metadata rather than merging into it."""
    target = add_metadata(MetadataDict(), own=True)
    carry_metadata(metadata_dict(), target)
    assert metadata_of(target) == SOURCE


def test_carry_metadata_leaves_the_target_alone_without_a_source() -> None:
    """A source carrying nothing leaves the target's own metadata in place."""
    target = add_metadata(MetadataDict(), own=True)
    assert carry_metadata(MetadataDict(), target) is target
    assert metadata_of(target) == {"own": True}


# A plain dict has nowhere to hold the attribute; the ``dict`` type object itself
# refuses the write with a TypeError rather than an AttributeError.
@pytest.mark.parametrize("target", [{}, dict])
def test_carry_metadata_is_silent_on_an_unwilling_target(target: Any) -> None:
    """A target with nowhere to hold the attribute is returned unchanged."""
    assert carry_metadata(metadata_dict(), target) is target
    assert metadata_of(target) is None


class HostileCarrier(list):
    """A list subclass whose metadata getter and setter both raise.

    The safe-validator contract forbids a built-in leaking anything but Invalid, and
    both ends of the carry are attribute access that can run a carrier's own code.
    """

    __slots__ = ()

    @property
    def __probatio_metadata__(self) -> Metadata:
        """Raise rather than report metadata."""
        message = "carrier getter blew up"
        raise RuntimeError(message)

    @__probatio_metadata__.setter
    def __probatio_metadata__(self, value: Mapping[str, Any]) -> None:
        """Raise rather than store metadata."""
        message = "carrier setter blew up"
        raise RuntimeError(message)


def test_carry_metadata_swallows_a_hostile_getter() -> None:
    """A source whose metadata getter raises leaves the target unchanged."""
    target = MetadataList(["x"])
    assert carry_metadata(HostileCarrier(["x"]), target) is target
    assert metadata_of(target) is None


def test_carry_metadata_swallows_a_hostile_setter() -> None:
    """A target whose metadata setter raises is returned unchanged."""
    target = HostileCarrier(["x"])
    assert carry_metadata(metadata_list(), target) is target


def test_add_metadata_swallows_a_hostile_setter() -> None:
    """add_metadata treats a setter that raises as a value that cannot hold metadata."""

    class HostileSetter(list):
        """Readable, but refuses the write with an exception of its own."""

        __slots__ = ()

        @property
        def __probatio_metadata__(self) -> Metadata | None:
            """Report no metadata."""
            return None

        @__probatio_metadata__.setter
        def __probatio_metadata__(self, value: Mapping[str, Any]) -> None:
            """Raise rather than store metadata."""
            message = "carrier setter blew up"
            raise RuntimeError(message)

    value = HostileSetter(["x"])
    assert add_metadata(value, SOURCE) is value


@pytest.mark.parametrize(
    "schema",
    [Schema(ExactSequence([str])), Schema([str]), Schema(All([str]))],
    ids=["exact_sequence", "sequence", "all"],
)
def test_a_hostile_carrier_cannot_break_the_safe_validator_contract(
    schema: Schema,
) -> None:
    """A carrier raising from its own code never escapes validation as itself."""
    # ExactSequence is a _SafeValidator: it may return a value or raise Invalid, and
    # nothing else. The carry runs the carrier's property, so it must not leak.
    assert schema(HostileCarrier(["x"])) == ["x"]


class InjectingDict(dict):
    """A carrier whose metadata setter writes into the container it is given.

    The hazard the write guard exists for: a setter receives the container itself, so
    it can add a key a mapping schema never saw or replace an item a sequence schema
    just checked.
    """

    __slots__ = ("_where",)

    @property
    def __probatio_metadata__(self) -> Any:
        """Return whatever was stored."""
        return getattr(self, "_where", None)

    @__probatio_metadata__.setter
    def __probatio_metadata__(self, value: Mapping[str, Any]) -> None:
        """Store the metadata, and smuggle an unvalidated key in with it."""
        object.__setattr__(self, "_where", value)
        self["injected"] = "not validated"


class InjectingList(list):
    """A carrier whose metadata setter replaces a validated item."""

    __slots__ = ("_where",)

    @property
    def __probatio_metadata__(self) -> Any:
        """Return whatever was stored."""
        return getattr(self, "_where", None)

    @__probatio_metadata__.setter
    def __probatio_metadata__(self, value: Mapping[str, Any]) -> None:
        """Store the metadata, and replace the first item while at it."""
        object.__setattr__(self, "_where", value)
        if self:
            self[0] = "not an int"


def _injecting(cls: type, items: Any) -> Any:
    """Build an injecting carrier that already reports metadata."""
    value = cls(items)
    object.__setattr__(value, "_where", Metadata(SOURCE))
    return value


def test_a_setter_cannot_inject_a_key_past_the_extra_policy() -> None:
    """The mapping carry never runs a setter that could add an unvalidated key."""
    result = Schema({"a": str}, extra=PREVENT_EXTRA)(
        _injecting(InjectingDict, {"a": "x"})
    )
    assert dict(result) == {"a": "x"}


def test_a_setter_cannot_replace_a_validated_sequence_item() -> None:
    """The sequence carry never runs a setter that could rewrite checked items."""
    result = Schema([int])(_injecting(InjectingList, [1, 2]))
    assert list(result) == [1, 2]


def test_a_setter_cannot_replace_an_exact_sequence_item() -> None:
    """ExactSequence is guarded the same way as the sequence engine."""
    result = Schema(ExactSequence([int, int]))(_injecting(InjectingList, [1, 2]))
    assert list(result) == [1, 2]


def test_a_class_that_turns_hostile_after_caching_degrades_to_a_no_op() -> None:
    """A carrier that starts refusing writes after being cached fails quietly."""
    # The eligibility answer is cached per class and a class namespace stays mutable,
    # so a cached answer can go stale. A carrier class is first-party code and is not
    # sandboxed (see ADR-018), but a stale answer must still not raise out of a
    # validator: a carrier's fault is never a validation failure.

    class Turncoat(dict):
        """An ordinary slot carrier, until it is not."""

        __slots__ = ("__probatio_metadata__",)

    assert supports_metadata(Turncoat()) is True

    def refuse(_self: Any, _name: str, _value: Any) -> None:
        """Refuse every attribute write from here on."""
        message = "no writes"
        raise RuntimeError(message)

    Turncoat.__setattr__ = refuse  # type: ignore[method-assign, assignment]

    value = Turncoat({"a": "x"})
    assert add_metadata(value, SOURCE) is value
    assert carry_metadata(metadata_dict(), value) is value


def test_the_carrier_cache_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """The per-type answer cache clears when it fills, so it cannot grow forever."""
    monkeypatch.setattr(metadata_module, "_PLAIN_ATTRIBUTE_LIMIT", 4)
    monkeypatch.setattr(metadata_module, "_PLAIN_ATTRIBUTE", {})
    for index in range(10):
        carrier = type(f"Carrier{index}", (dict,), {"__slots__": (METADATA_ATTR,)})
        assert supports_metadata(carrier()) is True
    assert len(metadata_module._PLAIN_ATTRIBUTE) <= 4


def test_a_plain_class_default_still_uses_the_instance_dict() -> None:
    """An ordinary class attribute of that name is shadowed, so the type still carries."""

    class Defaulted(dict):
        """Declares a default and keeps an ordinary instance dict."""

        __probatio_metadata__ = None

    assert supports_metadata(Defaulted()) is True
    result = Schema({"a": str})(add_metadata(Defaulted({"a": "x"}), SOURCE))
    assert_carried(result, Defaulted)


def test_a_plain_class_default_without_an_instance_dict_is_not_a_carrier() -> None:
    """With no instance dict there is nowhere for the write to land, default or not."""

    class Defaulted(dict):
        """Declares a default but no storage to shadow it with."""

        __slots__ = ()
        __probatio_metadata__ = None

    assert supports_metadata(Defaulted()) is False


def test_a_hostile_metaclass_cannot_break_the_carry() -> None:
    """Inspecting the target's class is guarded too, so a raising metaclass is safe."""

    class Hostile(type):
        """A metaclass that refuses to report its MRO."""

        @property
        def __mro__(cls) -> Any:
            """Raise rather than report the MRO."""
            message = "metaclass blew up"
            raise RuntimeError(message)

    class Sneaky(list, metaclass=Hostile):
        """A list subclass whose class cannot be inspected."""

    # The carry gives up rather than leaking the metaclass's exception.
    assert carry_metadata(metadata_list(), Sneaky([1])) is not None


def test_metadata_cannot_have_their_storage_rebound() -> None:
    """The backing mapping cannot be swapped out, which sharing one object relies on."""
    metadata = Metadata(SOURCE)
    with pytest.raises(AttributeError):
        metadata._data = {"line": 99}  # type: ignore[misc]
    assert metadata == SOURCE


def test_metadata_refuse_attribute_deletion() -> None:
    """Deleting the storage is refused for the same reason as rebinding it."""
    metadata = Metadata(SOURCE)
    with pytest.raises(AttributeError):
        del metadata._data  # type: ignore[misc]
    assert metadata == SOURCE


def test_carry_metadata_shares_the_metadata_object() -> None:
    """Source and target share one object, which is safe because it cannot change."""
    source = metadata_dict()
    target = MetadataDict()
    carry_metadata(source, target)
    assert metadata_of(target) is metadata_of(source)


def test_mapping_schema_keeps_metadata() -> None:
    """A rebuilt mapping is the same subclass and carries the same metadata."""
    assert_carried(Schema({"a": str})(metadata_dict()), MetadataDict)


def test_mapping_with_allow_extra_keeps_metadata() -> None:
    """ALLOW_EXTRA copies the unlisted keys across, and the metadata with them."""
    result = Schema({"a": str}, extra=ALLOW_EXTRA)(metadata_dict({"a": "x", "b": 1}))
    assert result == {"a": "x", "b": 1}
    assert_carried(result, MetadataDict)


def test_mapping_with_remove_extra_keeps_metadata() -> None:
    """REMOVE_EXTRA drops the unlisted keys but not the metadata."""
    result = Schema({"a": str}, extra=REMOVE_EXTRA)(metadata_dict({"a": "x", "b": 1}))
    assert result == {"a": "x"}
    assert_carried(result, MetadataDict)


def test_mapping_with_prevent_extra_keeps_metadata() -> None:
    """PREVENT_EXTRA, the default, rebuilds with the metadata intact."""
    result = Schema({"a": str}, extra=PREVENT_EXTRA)(metadata_dict())
    assert_carried(result, MetadataDict)


def test_empty_mapping_schema_keeps_metadata() -> None:
    """An empty schema that copies everything through still carries the metadata."""
    result = Schema({}, extra=ALLOW_EXTRA)(metadata_dict())
    assert result == {"a": "x"}
    assert_carried(result, MetadataDict)


def test_optional_key_keeps_metadata() -> None:
    """An Optional key does not change what the rebuilt mapping carries."""
    assert_carried(Schema({Optional("a"): str})(metadata_dict()), MetadataDict)


def test_required_key_keeps_metadata() -> None:
    """A Required key does not change what the rebuilt mapping carries."""
    assert_carried(Schema({Required("a"): str})(metadata_dict()), MetadataDict)


def test_type_key_schema_keeps_metadata() -> None:
    """A schema keyed by a type matches through the validator path and still carries."""
    assert_carried(Schema({str: str})(metadata_dict()), MetadataDict)


def test_mapping_inside_all_keeps_metadata() -> None:
    """A mapping schema wrapped in All carries the metadata through."""
    assert_carried(Schema(All({"a": str}))(metadata_dict()), MetadataDict)


def test_mapping_inside_any_keeps_metadata() -> None:
    """A mapping schema wrapped in Any carries the metadata through."""
    assert_carried(Schema(AnyOf({"a": str}))(metadata_dict()), MetadataDict)


def test_bare_dict_schema_keeps_metadata() -> None:
    """Schema(dict) is a type check returning the value itself, metadata and all."""
    assert_carried(Schema(dict)(metadata_dict()), MetadataDict)


def test_sequence_schema_keeps_metadata() -> None:
    """A rebuilt list is the same subclass and carries the same metadata."""
    assert_carried(Schema([str])(metadata_list()), MetadataList)


def test_multi_element_sequence_keeps_metadata() -> None:
    """A list schema with several element schemas rebuilds and still carries."""
    result = Schema([str, int])(metadata_list(["x", 1]))
    assert result == ["x", 1]
    assert_carried(result, MetadataList)


def test_sequence_inside_all_keeps_metadata() -> None:
    """A list schema wrapped in All carries the metadata through."""
    assert_carried(Schema(All([str]))(metadata_list()), MetadataList)


def test_bare_list_schema_keeps_metadata() -> None:
    """Schema(list) is a type check returning the value itself, metadata and all."""
    assert_carried(Schema(list)(metadata_list()), MetadataList)


def test_exact_sequence_keeps_list_metadata() -> None:
    """ExactSequence rebuilds a list subclass and carries its metadata across."""
    result = Schema(ExactSequence([str, int]))(metadata_list(["x", 1]))
    assert result == ["x", 1]
    assert_carried(result, MetadataList)


def test_exact_sequence_returns_a_plain_list_unwrapped() -> None:
    """A plain list stays a plain list through ExactSequence, with no carry attempted."""
    result = Schema(ExactSequence([str, int]))(["x", 1])
    assert type(result) is list
    assert result == ["x", 1]
    assert metadata_of(result) is None


def test_exact_sequence_keeps_tuple_metadata() -> None:
    """ExactSequence rebuilds a tuple subclass and carries its metadata across."""
    data = add_metadata(MetadataTuple(("x", 1)), SOURCE)
    result = Schema(ExactSequence([str, int]))(data)
    assert result == ("x", 1)
    assert_carried(result, MetadataTuple)


def test_metadata_survive_at_every_nesting_depth() -> None:
    """A container three levels down keeps its own metadata, distinct from above."""
    leaf = add_metadata(MetadataList(["x"]), depth=3)
    middle = add_metadata(MetadataDict({"items": leaf}), depth=2)
    data = add_metadata(MetadataDict({"inner": middle}), depth=1)

    result = Schema({"inner": {"items": [str]}})(data)

    assert metadata_of(result) == {"depth": 1}
    assert metadata_of(result["inner"]) == {"depth": 2}
    assert metadata_of(result["inner"]["items"]) == {"depth": 3}
    assert type(result["inner"]["items"]) is MetadataList


@pytest.mark.usefixtures("_compile_policy")
def test_alias_resolution_does_not_lose_the_metadata() -> None:
    """A mapping with aliases still carries, though the pre-pass rebinds its input."""
    # The alias pre-pass replaces the input with a plain dict, which carries nothing.
    # The carry therefore has to happen before it, and only an Alias schema notices.
    schema = Schema({Alias("name", "title"): str})
    result = schema(add_metadata(MetadataDict({"title": "kitchen"}), SOURCE))
    assert dict(result) == {"name": "kitchen"}
    assert_carried(result, MetadataDict)


def test_a_key_keeps_its_own_metadata() -> None:
    """A key carrying metadata survives the rebuild with it, independently."""
    key = add_metadata(MetadataStr("a"), origin="key")
    result = Schema({"a": str})(
        add_metadata(MetadataDict({key: "x"}), origin="mapping")
    )
    (out_key,) = result
    assert type(out_key) is MetadataStr
    assert metadata_of(out_key) == {"origin": "key"}
    assert metadata_of(result) == {"origin": "mapping"}


@pytest.mark.usefixtures("_compile_policy")
def test_mapping_metadata_survive_under_both_compile_policies() -> None:
    """The generated mapping path bails for a subclass, so the two engines agree."""
    schema = Schema({"a": str})
    result = None
    for _ in range(WARMUP_CALLS):
        result = schema(metadata_dict())
    assert_carried(result, MetadataDict)


@pytest.mark.usefixtures("_compile_policy")
def test_sequence_metadata_survive_under_both_compile_policies() -> None:
    """The generated sequence path bails for a subclass, so the two engines agree."""
    schema = Schema([str])
    result = None
    for _ in range(WARMUP_CALLS):
        result = schema(metadata_list())
    assert_carried(result, MetadataList)


def test_a_plain_dict_is_untouched() -> None:
    """The common case, a plain dict in and a plain dict out, is unaffected."""
    result = Schema({"a": str})({"a": "x"})
    assert type(result) is dict
    assert metadata_of(result) is None


def test_a_foreign_mapping_loses_its_metadata() -> None:
    """A Mapping that is not a dict rebuilds as a plain dict, which cannot carry."""
    data = add_metadata(ForeignMapping({"a": "x"}), SOURCE)
    result = Schema({"a": str})(data)
    assert type(result) is dict
    assert result == {"a": "x"}
    assert metadata_of(result) is None


def test_a_list_subclass_that_cannot_be_rebuilt_loses_its_metadata() -> None:
    """A subclass whose constructor takes no iterable degrades to a plain list."""
    result = Schema([str])(add_metadata(FixedList(), SOURCE))
    assert type(result) is list
    assert result == ["x"]
    assert metadata_of(result) is None


def test_a_namedtuple_round_trips_through_the_sequence_rebuild() -> None:
    """A namedtuple is rebuilt field by field and comes back as itself."""
    result = Schema((str, int))(Pair("x", 1))
    assert type(result) is Pair
    assert result == Pair("x", 1)


def test_coerce_to_dict_loses_metadata() -> None:
    """Coerce builds a plain dict, so the metadata is gone. That is intended."""
    result = Schema(Coerce(dict))(metadata_dict())
    assert type(result) is dict
    assert metadata_of(result) is None


def test_a_validator_after_the_schema_adds_to_the_metadata() -> None:
    """All(schema, validator) ends with the loader's metadata and the validator's."""
    result = Schema(All({"a": str}, mark_checked))(metadata_dict())
    assert type(result) is MetadataDict
    assert metadata_of(result) == {**SOURCE, "checked": True}


def test_a_validator_before_the_schema_has_its_metadata_carried() -> None:
    """All(validator, schema) carries the validator's addition through the rebuild."""
    result = Schema(All(mark_checked, {"a": str}))(metadata_dict())
    assert type(result) is MetadataDict
    assert metadata_of(result) == {**SOURCE, "checked": True}


def test_a_validator_that_rebuilds_can_carry_the_metadata() -> None:
    """A validator that builds its own container keeps the metadata by carrying it."""
    data = metadata_dict({"a": "x", "b": ""})
    result = Schema(All({"a": str, "b": str}, strip_empty_values))(data)
    assert result == {"a": "x"}
    assert_carried(result, MetadataDict)


def test_a_validator_that_rebuilds_without_carrying_loses_the_metadata() -> None:
    """Preserving the type is not preserving the metadata: the documented limit."""
    data = metadata_dict({"a": "x", "b": ""})
    result = Schema(All({"a": str, "b": str}, strip_empty_values_unaware))(data)
    assert type(result) is MetadataDict
    assert result == {"a": "x"}
    assert metadata_of(result) is None


@pytest.mark.parametrize("carrier", [SlottedPoint, DictPoint])
def test_object_carries_when_the_write_runs_no_user_code(carrier: type) -> None:
    """A slot or __dict__ carrier keeps its metadata through an Object rebuild."""
    result = Schema(Object({"x": int, "y": int}))(add_metadata(carrier(1, 2), SOURCE))
    assert result == carrier(1, 2)
    assert_carried(result, carrier)


def test_object_does_not_carry_through_a_property() -> None:
    """A property setter could rewrite validated attributes, so Object declines it."""
    writes: list[Any] = []

    class Located:
        """Keeps its metadata behind a property, recording every write."""

        __slots__ = ("x",)

        def __init__(self, x: Any = None) -> None:
            """Store the coordinate."""
            self.x = x

        @property
        def __probatio_metadata__(self) -> Metadata:
            """Report a fixed set of metadata."""
            return Metadata(SOURCE)

        @__probatio_metadata__.setter
        def __probatio_metadata__(self, value: Mapping[str, Any]) -> None:
            """Record that the carry reached this carrier's own code."""
            writes.append(value)

    result = Schema(Object({"x": int}))(Located(1))
    assert result.x == 1
    assert writes == []


def test_object_does_not_carry_through_a_custom_setattr() -> None:
    """An overridden __setattr__ can write anything, so Object declines it too."""
    writes: list[str] = []

    class Guarded:
        """Records every attribute write, including the metadata one."""

        __slots__ = ("__probatio_metadata__", "x")

        def __init__(self, x: Any = None) -> None:
            """Store the coordinate."""
            self.x = x

        def __setattr__(self, name: str, value: Any) -> None:
            """Record the write, then perform it."""
            writes.append(name)
            object.__setattr__(self, name, value)

    carrier = add_metadata(Guarded(1), SOURCE)
    writes.clear()
    result = Schema(Object({"x": int}))(carrier)
    assert result.x == 1
    assert METADATA_ATTR not in writes
    assert metadata_of(result) is None


def test_object_does_not_undo_validation_through_a_property_carrier() -> None:
    """A property over validated fields cannot put the unvalidated values back."""

    class Located:
        """An object exposing its metadata over two fields the schema validates."""

        __slots__ = ("file", "line")

        def __init__(self, file: str, line: int) -> None:
            """Store the source location this object came from."""
            self.file = file
            self.line = line

        @property
        def __probatio_metadata__(self) -> Metadata:
            """Return the location as metadata, reading the two fields."""
            return Metadata(file=self.file, line=self.line)

        @__probatio_metadata__.setter
        def __probatio_metadata__(self, metadata: Mapping[str, Any]) -> None:
            """Write the location back into the two fields."""
            self.file = metadata["file"]
            self.line = metadata["line"]

    # ``line`` arrives as a string and the schema coerces it. Carrying the property
    # afterwards would write the original "5" back over the validated 5.
    result = Schema(Object({"file": str, "line": Coerce(int)}))(
        Located("app.yaml", "5")
    )
    assert result.line == 5
    assert result.file == "app.yaml"


@pytest.mark.parametrize("carrier", [SlottedPoint, DictPoint])
def test_object_does_not_offer_the_metadata_attribute_as_a_field(
    carrier: type,
) -> None:
    """The attribute is probatio's own metadata, so PREVENT_EXTRA never sees it."""
    value = add_metadata(carrier(1, 2), SOURCE)
    schema = Schema(Object({"x": int, "y": int}), extra=PREVENT_EXTRA)
    assert schema(value) == carrier(1, 2)


def test_object_skips_a_metadata_slot_declared_as_a_string() -> None:
    """A carrier whose __slots__ is the metadata name as one string validates."""

    class Carrier:
        __slots__ = "__probatio_metadata__"  # noqa: PLC0205 - the form under test

    carrier = add_metadata(Carrier(), SOURCE)
    result = Schema(Object({}))(carrier)
    assert metadata_of(result) == SOURCE


def test_object_ignores_an_unset_metadata_slot() -> None:
    """An object whose metadata slot was never set validates: the slot is not read."""
    result = Schema(Object({"x": int, "y": int}))(SlottedPoint(1, 2))
    assert result == SlottedPoint(1, 2)
    assert metadata_of(result) is None
