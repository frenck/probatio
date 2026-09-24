"""Tests for the annotation model and its propagation through validation."""

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
    Annotations,
    Coerce,
    CompilePolicy,
    ExactSequence,
    Object,
    Optional,
    Required,
    Schema,
    annotate,
    annotations_of,
    carry_annotations,
    get_compile_policy,
    set_compile_policy,
    supports_annotations,
)
from probatio import Any as AnyOf
from probatio import annotations as annotations_module
from probatio.annotations import ANNOTATIONS_ATTR

if TYPE_CHECKING:
    from collections.abc import Iterator

# The marker a loader would attach: where the value came from. Tests assert it is
# still there after validation rebuilt the container.
SOURCE = {"file": "app.yaml", "line": 12}

# Enough calls for a schema to warm up under any policy. The AUTO threshold is 50
# and the ON policy compiles on the first call, so this covers both.
WARMUP_CALLS = 60


class AnnotatedDict(dict):
    """A dict subclass that makes room for annotations with one slot."""

    __slots__ = ("__probatio_annotations__",)


class AnnotatedList(list):
    """A list subclass that makes room for annotations with one slot."""

    __slots__ = ("__probatio_annotations__",)


class AnnotatedStr(str):
    """A str subclass that makes room for annotations, used as a mapping key."""

    __slots__ = ("__probatio_annotations__",)


class AnnotatedTuple(tuple):  # noqa: SLOT001
    """A tuple subclass carrying annotations in its __dict__.

    A tuple subclass cannot declare a non-empty __slots__, and an empty one would
    leave nowhere for the attribute to live, so this relies on the ordinary instance
    dict, which is the second of the two ways a type opts in.
    """


class FixedList(list):
    """A list subclass whose constructor takes no iterable, so a rebuild fails."""

    __slots__ = ("__probatio_annotations__",)

    def __init__(self) -> None:
        """Fill the list with its fixed contents."""
        super().__init__(["x"])


class ReadOnlyCarrier(dict):
    """A dict subclass exposing its annotations through a read-only property."""

    @property
    def __probatio_annotations__(self) -> Annotations:
        """Return the fixed annotations this type was built with."""
        return Annotations(fixed=True)


class WritableCarrier(dict):
    """A dict subclass exposing its annotations through a settable property.

    Not a carrier: probatio will not write through a setter, so this stands for the
    shape the protocol rejects even though the write would technically land.
    """

    __slots__ = ("_where",)

    @property
    def __probatio_annotations__(self) -> Annotations | None:
        """Return the annotations assembled from this type's own fields."""
        return getattr(self, "_where", None)

    @__probatio_annotations__.setter
    def __probatio_annotations__(self, value: Mapping[str, Any]) -> None:
        """Store the annotations in this type's own field."""
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
    """An attribute-bearing object with a slot for its annotations."""

    __slots__ = ("__probatio_annotations__", "x", "y")

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
    """An attribute-bearing object whose annotations live in its instance dict."""

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


def annotated_dict(data: dict[Any, Any] | None = None) -> AnnotatedDict:
    """Return an AnnotatedDict of the data, annotated with the source marker."""
    return annotate(AnnotatedDict(data if data is not None else {"a": "x"}), SOURCE)


def annotated_list(items: list[Any] | None = None) -> AnnotatedList:
    """Return an AnnotatedList of the items, annotated with the source marker."""
    return annotate(AnnotatedList(items if items is not None else ["x"]), SOURCE)


def assert_carried(result: Any, expected_type: type) -> None:
    """Assert the value has the expected type and still carries the source marker."""
    assert type(result) is expected_type
    assert annotations_of(result) == SOURCE


def mark_checked(value: Any) -> Any:
    """Annotate a value as checked and return it."""
    return annotate(value, checked=True)


def strip_empty_values(value: Any) -> Any:
    """Rebuild a mapping without its empty values, moving the annotations across."""
    kept = type(value)((key, item) for key, item in value.items() if item)
    return carry_annotations(value, kept)


def strip_empty_values_unaware(value: Any) -> Any:
    """Rebuild a mapping without its empty values, leaving the annotations behind."""
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


def test_annotations_from_a_mapping() -> None:
    """A mapping passed positionally becomes the annotations."""
    assert Annotations({"file": "app.yaml"}) == {"file": "app.yaml"}


def test_annotations_from_keyword_arguments() -> None:
    """Keyword arguments alone become the annotations."""
    assert Annotations(file="app.yaml", line=12) == SOURCE


def test_annotations_from_a_mapping_and_keywords() -> None:
    """A mapping and keywords combine, with the keyword winning on a shared key."""
    assert Annotations({"file": "app.yaml", "line": 1}, line=12) == SOURCE


def test_annotations_can_be_empty() -> None:
    """Built with nothing at all, the annotations are empty."""
    assert Annotations() == {}


def test_annotations_copy_the_source_mapping() -> None:
    """The source mapping is copied, so a later change to it does not reach in."""
    source = {"file": "app.yaml"}
    annotations = Annotations(source)
    source["file"] = "other.yaml"
    assert annotations == {"file": "app.yaml"}


def test_annotations_cannot_be_mutated_through_their_storage() -> None:
    """The backing mapping is read-only, so the immutability is enforced not advised."""
    annotations = Annotations(SOURCE)
    with pytest.raises(TypeError):
        annotations._data["file"] = "other.yaml"  # type: ignore[index]
    assert annotations == SOURCE


def test_annotations_survive_a_pickle_round_trip() -> None:
    """Pickling rebuilds an equal Annotations, despite the read-only backing store."""
    annotations = Annotations(SOURCE)
    assert pickle.loads(pickle.dumps(annotations)) == SOURCE  # noqa: S301


@pytest.mark.parametrize("clone", [copy.copy, copy.deepcopy])
def test_annotations_survive_a_copy(clone: Any) -> None:
    """Copying and deep-copying both rebuild an equal Annotations."""
    annotations = Annotations(SOURCE)
    assert clone(annotations) == SOURCE


def test_annotations_read_by_key() -> None:
    """A key reads back the value annotated under it."""
    assert Annotations(SOURCE)["file"] == "app.yaml"


def test_annotations_report_their_length() -> None:
    """len counts the annotations."""
    assert len(Annotations(SOURCE)) == 2


def test_annotations_iterate_their_keys() -> None:
    """Iterating yields the annotation keys."""
    assert list(Annotations(SOURCE)) == ["file", "line"]


def test_annotations_support_membership() -> None:
    """A key is in the annotations when it was annotated."""
    annotations = Annotations(SOURCE)
    assert "file" in annotations
    assert "missing" not in annotations


def test_annotations_get_returns_a_default() -> None:
    """get returns the value, or the default for a key that is not there."""
    annotations = Annotations(SOURCE)
    assert annotations.get("file") == "app.yaml"
    assert annotations.get("missing", "fallback") == "fallback"


def test_annotations_expose_keys_values_and_items() -> None:
    """The mapping views report the annotations."""
    annotations = Annotations(SOURCE)
    assert list(annotations.keys()) == ["file", "line"]
    assert list(annotations.values()) == ["app.yaml", 12]
    assert list(annotations.items()) == [("file", "app.yaml"), ("line", 12)]


def test_annotations_equal_a_plain_dict() -> None:
    """Annotations compare equal to a plain dict of the same contents."""
    assert Annotations(SOURCE) == {"file": "app.yaml", "line": 12}
    assert Annotations(SOURCE) != {"file": "app.yaml"}


def test_annotations_raise_key_error_for_a_missing_key() -> None:
    """Reading a key that was never annotated raises KeyError."""
    with pytest.raises(KeyError):
        Annotations(SOURCE)["missing"]


def test_annotations_repr_shows_the_annotations() -> None:
    """The repr names the type and renders the annotations themselves."""
    assert repr(Annotations(file="app.yaml")) == "Annotations({'file': 'app.yaml'})"


def test_merge_returns_a_new_object_and_leaves_the_original() -> None:
    """merge builds a new Annotations; the original is untouched."""
    original = Annotations(SOURCE)
    merged = original.merge({"checked": True})
    assert merged is not original
    assert original == SOURCE
    assert merged == {**SOURCE, "checked": True}


def test_merge_lets_the_incoming_values_win() -> None:
    """On a shared key the incoming value replaces the existing one."""
    assert Annotations(SOURCE).merge({"line": 99})["line"] == 99


def test_merge_accepts_keyword_arguments() -> None:
    """merge takes keywords, with or without a mapping alongside them."""
    assert Annotations(SOURCE).merge(checked=True) == {**SOURCE, "checked": True}
    assert Annotations(SOURCE).merge({"line": 99}, checked=True) == {
        "file": "app.yaml",
        "line": 99,
        "checked": True,
    }


def test_merge_with_nothing_returns_the_same_object() -> None:
    """Merging nothing in has nothing to build, so the same object comes back."""
    original = Annotations(SOURCE)
    assert original.merge() is original


def test_annotations_are_unhashable() -> None:
    """Annotations are a Mapping, so they are not hashable. Pin that deliberately."""
    assert Annotations.__hash__ is None
    with pytest.raises(TypeError, match="unhashable"):
        hash(Annotations(SOURCE))


def test_supports_annotations_for_a_slotted_carrier() -> None:
    """A type declaring the attribute in __slots__ can hold annotations."""
    assert supports_annotations(AnnotatedDict()) is True


def test_supports_annotations_for_a_plain_dict_class() -> None:
    """A type whose instances have an ordinary __dict__ can hold annotations."""
    assert supports_annotations(DictPoint()) is True


@pytest.mark.parametrize("carrier", [WritableCarrier, ReadOnlyCarrier])
def test_supports_annotations_is_false_for_a_property(carrier: type) -> None:
    """A property takes the write as a call, so probatio will not carry through it."""
    assert supports_annotations(carrier()) is False


def test_supports_annotations_is_false_for_a_custom_setattr() -> None:
    """An overridden __setattr__ takes every write, so it is not a plain attribute."""

    class Guarded:
        """Routes every attribute write through code of its own."""

        __slots__ = ("__probatio_annotations__",)

        def __setattr__(self, name: str, value: Any) -> None:
            """Perform the write through object, after seeing it."""
            object.__setattr__(self, name, value)

    assert supports_annotations(Guarded()) is False


def test_supports_annotations_runs_no_descriptor_code() -> None:
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
        """Exposes the annotation attribute through the descriptor above."""

        __probatio_annotations__ = Loud()

    assert supports_annotations(LoudCarrier()) is False
    assert calls == []


def test_supports_annotations_is_false_for_a_class_object() -> None:
    """A class exposes a read-only __dict__ proxy, so it is not a carrier."""
    assert supports_annotations(dict) is False
    assert supports_annotations(AnnotatedDict) is False


@pytest.mark.parametrize("value", [{}, [], "text", 1, ()])
def test_supports_annotations_is_false_for_builtin_values(value: Any) -> None:
    """A plain dict, list, str, int or tuple makes no room for the attribute."""
    assert supports_annotations(value) is False


def test_annotations_of_a_bare_carrier_is_none() -> None:
    """A carrier that was never annotated reports no annotations."""
    assert annotations_of(AnnotatedDict()) is None


def test_annotations_of_a_value_that_cannot_carry_is_none() -> None:
    """A value with nowhere to hold the attribute reports no annotations."""
    assert annotations_of({"a": "x"}) is None


def test_annotations_of_returns_the_stored_object() -> None:
    """An Annotations already on the value is handed back, not rebuilt."""
    value = annotated_dict()
    assert annotations_of(value) is value.__probatio_annotations__


def test_annotations_of_normalizes_a_plain_dict() -> None:
    """A plain mapping in the attribute is read back as an Annotations."""
    value = AnnotatedDict()
    value.__probatio_annotations__ = {"file": "app.yaml"}
    result = annotations_of(value)
    assert type(result) is Annotations
    assert result == {"file": "app.yaml"}


def test_annotations_of_rejects_a_non_mapping() -> None:
    """A carrier holding something that is not a mapping is broken, and says so."""
    value = AnnotatedDict()
    value.__probatio_annotations__ = "app.yaml"
    with pytest.raises(TypeError, match="which is not a mapping"):
        annotations_of(value)


def test_annotate_attaches_to_a_bare_carrier() -> None:
    """A carrier with no annotations yet gets the given ones."""
    assert annotations_of(annotate(AnnotatedDict(), file="app.yaml")) == {
        "file": "app.yaml",
    }


def test_annotate_merges_with_the_new_values_winning() -> None:
    """Existing annotations are kept, and the incoming ones win on a shared key."""
    value = annotate(AnnotatedDict(), file="app.yaml", line=1)
    annotate(value, line=12, checked=True)
    assert annotations_of(value) == {**SOURCE, "checked": True}


def test_annotate_returns_the_value() -> None:
    """annotate hands the value back, so it reads well as a validator's last line."""
    value = AnnotatedDict()
    assert annotate(value, file="app.yaml") is value


def test_annotate_accepts_a_positional_mapping() -> None:
    """A mapping can be passed positionally instead of as keywords."""
    assert annotations_of(annotate(AnnotatedDict(), SOURCE)) == SOURCE


def test_annotate_accepts_a_mapping_and_keywords() -> None:
    """A mapping and keywords combine, with the keyword winning on a shared key."""
    value = annotate(AnnotatedDict(), {"file": "app.yaml", "line": 1}, line=12)
    assert annotations_of(value) == SOURCE


def test_annotate_with_nothing_is_a_no_op() -> None:
    """With no mapping and no keywords there is nothing to attach."""
    value = AnnotatedDict()
    assert annotate(value) is value
    assert annotations_of(value) is None


# An int and a plain dict have nowhere to put the attribute; the ``dict`` type
# object itself refuses the write with a TypeError rather than an AttributeError.
@pytest.mark.parametrize("value", [1, {}, dict])
def test_annotate_is_silent_on_a_value_that_cannot_carry(value: Any) -> None:
    """A value with nowhere to put annotations comes back unchanged, not an error."""
    assert annotate(value, SOURCE) is value
    assert annotations_of(value) is None


def test_annotate_is_silent_on_a_read_only_property() -> None:
    """A carrier whose property cannot be written keeps what it had, without raising."""
    value = ReadOnlyCarrier()
    assert annotate(value, SOURCE) is value
    assert annotations_of(value) == {"fixed": True}


def test_annotate_rejects_a_broken_carrier() -> None:
    """A carrier already holding a non-mapping raises, the way reading it does."""
    value = AnnotatedDict()
    value.__probatio_annotations__ = "app.yaml"
    with pytest.raises(TypeError, match="which is not a mapping"):
        annotate(value, line=12)


def test_carry_annotations_copies_to_the_target() -> None:
    """The source's annotations land on the target, which is returned."""
    target = AnnotatedDict()
    assert carry_annotations(annotated_dict(), target) is target
    assert annotations_of(target) == SOURCE


def test_carry_annotations_replaces_what_the_target_carried() -> None:
    """The carry replaces the target's own annotations rather than merging into them."""
    target = annotate(AnnotatedDict(), own=True)
    carry_annotations(annotated_dict(), target)
    assert annotations_of(target) == SOURCE


def test_carry_annotations_leaves_the_target_alone_without_a_source() -> None:
    """A source carrying nothing leaves the target's own annotations in place."""
    target = annotate(AnnotatedDict(), own=True)
    assert carry_annotations(AnnotatedDict(), target) is target
    assert annotations_of(target) == {"own": True}


# A plain dict has nowhere to hold the attribute; the ``dict`` type object itself
# refuses the write with a TypeError rather than an AttributeError.
@pytest.mark.parametrize("target", [{}, dict])
def test_carry_annotations_is_silent_on_an_unwilling_target(target: Any) -> None:
    """A target with nowhere to hold the attribute is returned unchanged."""
    assert carry_annotations(annotated_dict(), target) is target
    assert annotations_of(target) is None


class HostileCarrier(list):
    """A list subclass whose annotation getter and setter both raise.

    The safe-validator contract forbids a built-in leaking anything but Invalid, and
    both ends of the carry are attribute access that can run a carrier's own code.
    """

    __slots__ = ()

    @property
    def __probatio_annotations__(self) -> Annotations:
        """Raise rather than report annotations."""
        message = "carrier getter blew up"
        raise RuntimeError(message)

    @__probatio_annotations__.setter
    def __probatio_annotations__(self, value: Mapping[str, Any]) -> None:
        """Raise rather than store annotations."""
        message = "carrier setter blew up"
        raise RuntimeError(message)


def test_carry_annotations_swallows_a_hostile_getter() -> None:
    """A source whose annotation getter raises leaves the target unchanged."""
    target = AnnotatedList(["x"])
    assert carry_annotations(HostileCarrier(["x"]), target) is target
    assert annotations_of(target) is None


def test_carry_annotations_swallows_a_hostile_setter() -> None:
    """A target whose annotation setter raises is returned unchanged."""
    target = HostileCarrier(["x"])
    assert carry_annotations(annotated_list(), target) is target


def test_annotate_swallows_a_hostile_setter() -> None:
    """annotate treats a setter that raises as a value that cannot hold annotations."""

    class HostileSetter(list):
        """Readable, but refuses the write with an exception of its own."""

        __slots__ = ()

        @property
        def __probatio_annotations__(self) -> Annotations | None:
            """Report no annotations."""
            return None

        @__probatio_annotations__.setter
        def __probatio_annotations__(self, value: Mapping[str, Any]) -> None:
            """Raise rather than store annotations."""
            message = "carrier setter blew up"
            raise RuntimeError(message)

    value = HostileSetter(["x"])
    assert annotate(value, SOURCE) is value


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
    """A carrier whose annotation setter writes into the container it is given.

    The hazard the write guard exists for: a setter receives the container itself, so
    it can add a key a mapping schema never saw or replace an item a sequence schema
    just checked.
    """

    __slots__ = ("_where",)

    @property
    def __probatio_annotations__(self) -> Any:
        """Return whatever was stored."""
        return getattr(self, "_where", None)

    @__probatio_annotations__.setter
    def __probatio_annotations__(self, value: Mapping[str, Any]) -> None:
        """Store the annotations, and smuggle an unvalidated key in with them."""
        object.__setattr__(self, "_where", value)
        self["injected"] = "not validated"


class InjectingList(list):
    """A carrier whose annotation setter replaces a validated item."""

    __slots__ = ("_where",)

    @property
    def __probatio_annotations__(self) -> Any:
        """Return whatever was stored."""
        return getattr(self, "_where", None)

    @__probatio_annotations__.setter
    def __probatio_annotations__(self, value: Mapping[str, Any]) -> None:
        """Store the annotations, and replace the first item while at it."""
        object.__setattr__(self, "_where", value)
        if self:
            self[0] = "not an int"


def _injecting(cls: type, items: Any) -> Any:
    """Build an injecting carrier that already reports annotations."""
    value = cls(items)
    object.__setattr__(value, "_where", Annotations(SOURCE))
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

        __slots__ = ("__probatio_annotations__",)

    assert supports_annotations(Turncoat()) is True

    def refuse(_self: Any, _name: str, _value: Any) -> None:
        """Refuse every attribute write from here on."""
        message = "no writes"
        raise RuntimeError(message)

    Turncoat.__setattr__ = refuse  # type: ignore[method-assign, assignment]

    value = Turncoat({"a": "x"})
    assert annotate(value, SOURCE) is value
    assert carry_annotations(annotated_dict(), value) is value


def test_the_carrier_cache_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """The per-type answer cache clears when it fills, so it cannot grow forever."""
    monkeypatch.setattr(annotations_module, "_PLAIN_ATTRIBUTE_LIMIT", 4)
    monkeypatch.setattr(annotations_module, "_PLAIN_ATTRIBUTE", {})
    for index in range(10):
        carrier = type(f"Carrier{index}", (dict,), {"__slots__": (ANNOTATIONS_ATTR,)})
        assert supports_annotations(carrier()) is True
    assert len(annotations_module._PLAIN_ATTRIBUTE) <= 4


def test_a_plain_class_default_still_uses_the_instance_dict() -> None:
    """An ordinary class attribute of that name is shadowed, so the type still carries."""

    class Defaulted(dict):
        """Declares a default and keeps an ordinary instance dict."""

        __probatio_annotations__ = None

    assert supports_annotations(Defaulted()) is True
    result = Schema({"a": str})(annotate(Defaulted({"a": "x"}), SOURCE))
    assert_carried(result, Defaulted)


def test_a_plain_class_default_without_an_instance_dict_is_not_a_carrier() -> None:
    """With no instance dict there is nowhere for the write to land, default or not."""

    class Defaulted(dict):
        """Declares a default but no storage to shadow it with."""

        __slots__ = ()
        __probatio_annotations__ = None

    assert supports_annotations(Defaulted()) is False


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
    assert carry_annotations(annotated_list(), Sneaky([1])) is not None


def test_annotations_cannot_have_their_storage_rebound() -> None:
    """The backing mapping cannot be swapped out, which sharing one object relies on."""
    annotations = Annotations(SOURCE)
    with pytest.raises(AttributeError):
        annotations._data = {"line": 99}  # type: ignore[misc]
    assert annotations == SOURCE


def test_annotations_refuse_attribute_deletion() -> None:
    """Deleting the storage is refused for the same reason as rebinding it."""
    annotations = Annotations(SOURCE)
    with pytest.raises(AttributeError):
        del annotations._data  # type: ignore[misc]
    assert annotations == SOURCE


def test_carry_annotations_shares_the_annotations_object() -> None:
    """Source and target share one object, which is safe because it cannot change."""
    source = annotated_dict()
    target = AnnotatedDict()
    carry_annotations(source, target)
    assert annotations_of(target) is annotations_of(source)


def test_mapping_schema_keeps_annotations() -> None:
    """A rebuilt mapping is the same subclass and carries the same annotations."""
    assert_carried(Schema({"a": str})(annotated_dict()), AnnotatedDict)


def test_mapping_with_allow_extra_keeps_annotations() -> None:
    """ALLOW_EXTRA copies the unlisted keys across and the annotations with them."""
    result = Schema({"a": str}, extra=ALLOW_EXTRA)(annotated_dict({"a": "x", "b": 1}))
    assert result == {"a": "x", "b": 1}
    assert_carried(result, AnnotatedDict)


def test_mapping_with_remove_extra_keeps_annotations() -> None:
    """REMOVE_EXTRA drops the unlisted keys but not the annotations."""
    result = Schema({"a": str}, extra=REMOVE_EXTRA)(annotated_dict({"a": "x", "b": 1}))
    assert result == {"a": "x"}
    assert_carried(result, AnnotatedDict)


def test_mapping_with_prevent_extra_keeps_annotations() -> None:
    """PREVENT_EXTRA, the default, rebuilds with the annotations intact."""
    result = Schema({"a": str}, extra=PREVENT_EXTRA)(annotated_dict())
    assert_carried(result, AnnotatedDict)


def test_empty_mapping_schema_keeps_annotations() -> None:
    """An empty schema that copies everything through still carries the annotations."""
    result = Schema({}, extra=ALLOW_EXTRA)(annotated_dict())
    assert result == {"a": "x"}
    assert_carried(result, AnnotatedDict)


def test_optional_key_keeps_annotations() -> None:
    """An Optional key does not change what the rebuilt mapping carries."""
    assert_carried(Schema({Optional("a"): str})(annotated_dict()), AnnotatedDict)


def test_required_key_keeps_annotations() -> None:
    """A Required key does not change what the rebuilt mapping carries."""
    assert_carried(Schema({Required("a"): str})(annotated_dict()), AnnotatedDict)


def test_type_key_schema_keeps_annotations() -> None:
    """A schema keyed by a type matches through the validator path and still carries."""
    assert_carried(Schema({str: str})(annotated_dict()), AnnotatedDict)


def test_mapping_inside_all_keeps_annotations() -> None:
    """A mapping schema wrapped in All carries the annotations through."""
    assert_carried(Schema(All({"a": str}))(annotated_dict()), AnnotatedDict)


def test_mapping_inside_any_keeps_annotations() -> None:
    """A mapping schema wrapped in Any carries the annotations through."""
    assert_carried(Schema(AnyOf({"a": str}))(annotated_dict()), AnnotatedDict)


def test_bare_dict_schema_keeps_annotations() -> None:
    """Schema(dict) is a type check returning the value itself, annotations and all."""
    assert_carried(Schema(dict)(annotated_dict()), AnnotatedDict)


def test_sequence_schema_keeps_annotations() -> None:
    """A rebuilt list is the same subclass and carries the same annotations."""
    assert_carried(Schema([str])(annotated_list()), AnnotatedList)


def test_multi_element_sequence_keeps_annotations() -> None:
    """A list schema with several element schemas rebuilds and still carries."""
    result = Schema([str, int])(annotated_list(["x", 1]))
    assert result == ["x", 1]
    assert_carried(result, AnnotatedList)


def test_sequence_inside_all_keeps_annotations() -> None:
    """A list schema wrapped in All carries the annotations through."""
    assert_carried(Schema(All([str]))(annotated_list()), AnnotatedList)


def test_bare_list_schema_keeps_annotations() -> None:
    """Schema(list) is a type check returning the value itself, annotations and all."""
    assert_carried(Schema(list)(annotated_list()), AnnotatedList)


def test_exact_sequence_keeps_list_annotations() -> None:
    """ExactSequence rebuilds a list subclass and carries its annotations across."""
    result = Schema(ExactSequence([str, int]))(annotated_list(["x", 1]))
    assert result == ["x", 1]
    assert_carried(result, AnnotatedList)


def test_exact_sequence_returns_a_plain_list_unwrapped() -> None:
    """A plain list stays a plain list through ExactSequence, with no carry attempted."""
    result = Schema(ExactSequence([str, int]))(["x", 1])
    assert type(result) is list
    assert result == ["x", 1]
    assert annotations_of(result) is None


def test_exact_sequence_keeps_tuple_annotations() -> None:
    """ExactSequence rebuilds a tuple subclass and carries its annotations across."""
    data = annotate(AnnotatedTuple(("x", 1)), SOURCE)
    result = Schema(ExactSequence([str, int]))(data)
    assert result == ("x", 1)
    assert_carried(result, AnnotatedTuple)


def test_annotations_survive_at_every_nesting_depth() -> None:
    """A container three levels down keeps its own annotations, distinct from above."""
    leaf = annotate(AnnotatedList(["x"]), depth=3)
    middle = annotate(AnnotatedDict({"items": leaf}), depth=2)
    data = annotate(AnnotatedDict({"inner": middle}), depth=1)

    result = Schema({"inner": {"items": [str]}})(data)

    assert annotations_of(result) == {"depth": 1}
    assert annotations_of(result["inner"]) == {"depth": 2}
    assert annotations_of(result["inner"]["items"]) == {"depth": 3}
    assert type(result["inner"]["items"]) is AnnotatedList


@pytest.mark.usefixtures("_compile_policy")
def test_alias_resolution_does_not_lose_the_annotations() -> None:
    """A mapping with aliases still carries, though the pre-pass rebinds its input."""
    # The alias pre-pass replaces the input with a plain dict, which carries nothing.
    # The carry therefore has to happen before it, and only an Alias schema notices.
    schema = Schema({Alias("name", "title"): str})
    result = schema(annotate(AnnotatedDict({"title": "kitchen"}), SOURCE))
    assert dict(result) == {"name": "kitchen"}
    assert_carried(result, AnnotatedDict)


def test_an_annotated_key_keeps_its_own_annotations() -> None:
    """A key carrying annotations survives the rebuild with them, independently."""
    key = annotate(AnnotatedStr("a"), origin="key")
    result = Schema({"a": str})(annotate(AnnotatedDict({key: "x"}), origin="mapping"))
    (out_key,) = result
    assert type(out_key) is AnnotatedStr
    assert annotations_of(out_key) == {"origin": "key"}
    assert annotations_of(result) == {"origin": "mapping"}


@pytest.mark.usefixtures("_compile_policy")
def test_mapping_annotations_survive_under_both_compile_policies() -> None:
    """The generated mapping path bails for a subclass, so the two engines agree."""
    schema = Schema({"a": str})
    result = None
    for _ in range(WARMUP_CALLS):
        result = schema(annotated_dict())
    assert_carried(result, AnnotatedDict)


@pytest.mark.usefixtures("_compile_policy")
def test_sequence_annotations_survive_under_both_compile_policies() -> None:
    """The generated sequence path bails for a subclass, so the two engines agree."""
    schema = Schema([str])
    result = None
    for _ in range(WARMUP_CALLS):
        result = schema(annotated_list())
    assert_carried(result, AnnotatedList)


def test_a_plain_dict_is_untouched() -> None:
    """The common case, a plain dict in and a plain dict out, is unaffected."""
    result = Schema({"a": str})({"a": "x"})
    assert type(result) is dict
    assert annotations_of(result) is None


def test_a_foreign_mapping_loses_its_annotations() -> None:
    """A Mapping that is not a dict rebuilds as a plain dict, which cannot carry."""
    data = annotate(ForeignMapping({"a": "x"}), SOURCE)
    result = Schema({"a": str})(data)
    assert type(result) is dict
    assert result == {"a": "x"}
    assert annotations_of(result) is None


def test_a_list_subclass_that_cannot_be_rebuilt_loses_its_annotations() -> None:
    """A subclass whose constructor takes no iterable degrades to a plain list."""
    result = Schema([str])(annotate(FixedList(), SOURCE))
    assert type(result) is list
    assert result == ["x"]
    assert annotations_of(result) is None


def test_a_namedtuple_round_trips_through_the_sequence_rebuild() -> None:
    """A namedtuple is rebuilt field by field and comes back as itself."""
    result = Schema((str, int))(Pair("x", 1))
    assert type(result) is Pair
    assert result == Pair("x", 1)


def test_coerce_to_dict_loses_annotations() -> None:
    """Coerce builds a plain dict, so the annotations are gone. That is intended."""
    result = Schema(Coerce(dict))(annotated_dict())
    assert type(result) is dict
    assert annotations_of(result) is None


def test_a_validator_after_the_schema_adds_to_the_annotations() -> None:
    """All(schema, validator) ends with the loader's annotations and the validator's."""
    result = Schema(All({"a": str}, mark_checked))(annotated_dict())
    assert type(result) is AnnotatedDict
    assert annotations_of(result) == {**SOURCE, "checked": True}


def test_a_validator_before_the_schema_has_its_annotation_carried() -> None:
    """All(validator, schema) carries the validator's addition through the rebuild."""
    result = Schema(All(mark_checked, {"a": str}))(annotated_dict())
    assert type(result) is AnnotatedDict
    assert annotations_of(result) == {**SOURCE, "checked": True}


def test_a_validator_that_rebuilds_can_carry_the_annotations() -> None:
    """A validator that builds its own container keeps the metadata by carrying it."""
    data = annotated_dict({"a": "x", "b": ""})
    result = Schema(All({"a": str, "b": str}, strip_empty_values))(data)
    assert result == {"a": "x"}
    assert_carried(result, AnnotatedDict)


def test_a_validator_that_rebuilds_without_carrying_loses_the_annotations() -> None:
    """Preserving the type is not preserving the annotations: the documented limit."""
    data = annotated_dict({"a": "x", "b": ""})
    result = Schema(All({"a": str, "b": str}, strip_empty_values_unaware))(data)
    assert type(result) is AnnotatedDict
    assert result == {"a": "x"}
    assert annotations_of(result) is None


@pytest.mark.parametrize("carrier", [SlottedPoint, DictPoint])
def test_object_carries_when_the_write_runs_no_user_code(carrier: type) -> None:
    """A slot or __dict__ carrier keeps its annotations through an Object rebuild."""
    result = Schema(Object({"x": int, "y": int}))(annotate(carrier(1, 2), SOURCE))
    assert result == carrier(1, 2)
    assert_carried(result, carrier)


def test_object_does_not_carry_through_a_property() -> None:
    """A property setter could rewrite validated attributes, so Object declines it."""
    writes: list[Any] = []

    class Located:
        """Keeps its annotations behind a property, recording every write."""

        __slots__ = ("x",)

        def __init__(self, x: Any = None) -> None:
            """Store the coordinate."""
            self.x = x

        @property
        def __probatio_annotations__(self) -> Annotations:
            """Report a fixed set of annotations."""
            return Annotations(SOURCE)

        @__probatio_annotations__.setter
        def __probatio_annotations__(self, value: Mapping[str, Any]) -> None:
            """Record that the carry reached this carrier's own code."""
            writes.append(value)

    result = Schema(Object({"x": int}))(Located(1))
    assert result.x == 1
    assert writes == []


def test_object_does_not_carry_through_a_custom_setattr() -> None:
    """An overridden __setattr__ can write anything, so Object declines it too."""
    writes: list[str] = []

    class Guarded:
        """Records every attribute write, including the annotation one."""

        __slots__ = ("__probatio_annotations__", "x")

        def __init__(self, x: Any = None) -> None:
            """Store the coordinate."""
            self.x = x

        def __setattr__(self, name: str, value: Any) -> None:
            """Record the write, then perform it."""
            writes.append(name)
            object.__setattr__(self, name, value)

    annotated = annotate(Guarded(1), SOURCE)
    writes.clear()
    result = Schema(Object({"x": int}))(annotated)
    assert result.x == 1
    assert ANNOTATIONS_ATTR not in writes
    assert annotations_of(result) is None


def test_object_does_not_undo_validation_through_a_property_carrier() -> None:
    """A property over validated fields cannot put the unvalidated values back."""

    class Located:
        """An object exposing its annotations over two fields the schema validates."""

        __slots__ = ("file", "line")

        def __init__(self, file: str, line: int) -> None:
            """Store the source location this object came from."""
            self.file = file
            self.line = line

        @property
        def __probatio_annotations__(self) -> Annotations:
            """Return the location as annotations, reading the two fields."""
            return Annotations(file=self.file, line=self.line)

        @__probatio_annotations__.setter
        def __probatio_annotations__(self, annotations: Mapping[str, Any]) -> None:
            """Write the location back into the two fields."""
            self.file = annotations["file"]
            self.line = annotations["line"]

    # ``line`` arrives as a string and the schema coerces it. Carrying the property
    # afterwards would write the original "5" back over the validated 5.
    result = Schema(Object({"file": str, "line": Coerce(int)}))(
        Located("app.yaml", "5")
    )
    assert result.line == 5
    assert result.file == "app.yaml"


@pytest.mark.parametrize("carrier", [SlottedPoint, DictPoint])
def test_object_does_not_offer_the_annotation_attribute_as_a_field(
    carrier: type,
) -> None:
    """The attribute is probatio's own metadata, so PREVENT_EXTRA never sees it."""
    value = annotate(carrier(1, 2), SOURCE)
    schema = Schema(Object({"x": int, "y": int}), extra=PREVENT_EXTRA)
    assert schema(value) == carrier(1, 2)


def test_object_ignores_an_unset_annotation_slot() -> None:
    """An object whose annotation slot was never set validates: the slot is not read."""
    result = Schema(Object({"x": int, "y": int}))(SlottedPoint(1, 2))
    assert result == SlottedPoint(1, 2)
    assert annotations_of(result) is None
