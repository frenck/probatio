"""Tests for carrying a container subclass's instance state across validation.

Rebuilding a ``dict`` or ``list`` subclass keeps its type but builds a fresh,
empty instance, so anything the original held in ``__slots__`` or ``__dict__``
used to be dropped. The node classes below mirror the shape annotatedyaml gives
Home Assistant's YAML nodes (a source file and line in ``__slots__``), without
depending on that library: they are the state the engine must now carry through.
"""

from __future__ import annotations

import collections
import collections.abc
import typing

import pytest

from probatio import (
    ALLOW_EXTRA,
    PREVENT_EXTRA,
    REMOVE_EXTRA,
    Alias,
    All,
    Any,
    Coerce,
    CompilePolicy,
    ExactSequence,
    Optional,
    Remove,
    Required,
    Schema,
    set_compile_policy,
)

_FILE = "configuration.yaml"


class NodeDict(dict):
    __slots__ = ("__config_file__", "__line__")


class NodeList(list):
    __slots__ = ("__config_file__", "__line__")


class NodeStr(str):
    __slots__ = ("__config_file__", "__line__")


class NodeTuple(tuple):  # noqa: SLOT001 - the point is the instance __dict__
    # A tuple subclass cannot declare a non-empty __slots__, so its state lives
    # in an instance __dict__ instead. That is the other half of the protocol.
    pass


def _annotate[T](node: T, line: int) -> T:
    """Stamp a node with the file and line a YAML loader would record."""
    node.__config_file__ = _FILE  # type: ignore[attr-defined]
    node.__line__ = line  # type: ignore[attr-defined]
    return node


def _source(value: object) -> tuple[typing.Any, typing.Any]:
    """Return the (file, line) a node carries, or (None, None) if it lost them."""
    return (
        getattr(value, "__config_file__", None),
        getattr(value, "__line__", None),
    )


@pytest.fixture(
    params=[CompilePolicy.OFF, CompilePolicy.ON],
    ids=["interpreted", "compiled"],
)
def policy(request: pytest.FixtureRequest) -> CompilePolicy:
    """Run the test body once interpreted and once with compilation forced on."""
    chosen: CompilePolicy = request.param
    set_compile_policy(chosen)
    return chosen


# Mapping schema shapes, each built after the compile policy is set so the
# schema is compiled (or not) as the policy says.
_MAPPING_CASES: dict[str, tuple[typing.Any, dict[str, typing.Any]]] = {
    "literal_keys": (lambda: Schema({"a": str}), {"a": "1"}),
    "allow_extra": (
        lambda: Schema({"a": str}, extra=ALLOW_EXTRA),
        {"a": "1", "b": 2},
    ),
    "remove_extra": (
        lambda: Schema({"a": str}, extra=REMOVE_EXTRA),
        {"a": "1", "b": 2},
    ),
    "prevent_extra": (lambda: Schema({"a": str}, extra=PREVENT_EXTRA), {"a": "1"}),
    "empty_allow_extra": (lambda: Schema({}, extra=ALLOW_EXTRA), {"a": "1"}),
    "optional_key": (
        lambda: Schema({Optional("a"): str, Optional("b", default="d"): str}),
        {"a": "1"},
    ),
    "required_key": (lambda: Schema({Required("a"): str}), {"a": "1"}),
    "type_key": (lambda: Schema({str: str}), {"a": "1"}),
    "all_of_mapping": (lambda: Schema(All({"a": str})), {"a": "1"}),
    "any_of_mapping": (lambda: Schema(Any({"a": str}, {"b": int})), {"a": "1"}),
    "alias_key": (lambda: Schema({Alias("a", "A"): str}), {"A": "1"}),
    "remove_key": (
        lambda: Schema({"a": str, Remove("b"): str}),
        {"a": "1", "b": "2"},
    ),
}


@pytest.mark.parametrize("case", list(_MAPPING_CASES))
@pytest.mark.usefixtures("policy")
def test_dict_subclass_state_survives_every_mapping_shape(case: str) -> None:
    """Every mapping schema shape returns the subclass with its annotation intact."""
    build, data = _MAPPING_CASES[case]
    result = build()(_annotate(NodeDict(data), 12))
    assert type(result) is NodeDict
    assert _source(result) == (_FILE, 12)


_SEQUENCE_CASES: dict[str, tuple[typing.Any, list[typing.Any]]] = {
    "single_element": (lambda: Schema([str]), ["x", "y"]),
    "element_union": (lambda: Schema([str, int]), ["x", 1]),
    "all_of_sequence": (lambda: Schema(All([str])), ["x"]),
    "remove_element": (lambda: Schema([Remove("drop"), str]), ["x", "drop"]),
    "empty_sequence": (lambda: Schema([]), []),
    "exact_sequence": (lambda: Schema(ExactSequence([str, int])), ["x", 1]),
}


@pytest.mark.parametrize("case", list(_SEQUENCE_CASES))
@pytest.mark.usefixtures("policy")
def test_list_subclass_state_survives_every_sequence_shape(case: str) -> None:
    """Every sequence schema shape returns the subclass with its annotation intact."""
    build, data = _SEQUENCE_CASES[case]
    result = build()(_annotate(NodeList(data), 7))
    assert type(result) is NodeList
    assert _source(result) == (_FILE, 7)


def test_exact_sequence_validator_carries_state_directly() -> None:
    """ExactSequence called on its own rebuilds the subclass with its annotation."""
    result = ExactSequence([str, int])(_annotate(NodeList(["x", 1]), 3))
    assert result == ["x", 1]
    assert type(result) is NodeList
    assert _source(result) == (_FILE, 3)


def test_tuple_subclass_state_survives() -> None:
    """A tuple subclass keeps the state it holds in its instance __dict__."""
    result = Schema((int,))(_annotate(NodeTuple((1, 2)), 5))
    assert result == (1, 2)
    assert type(result) is NodeTuple
    assert _source(result) == (_FILE, 5)


def test_set_subclass_state_survives() -> None:
    """A set subclass rebuilt by the sequence engine keeps its annotation."""

    class NodeSet(set):
        __slots__ = ("__config_file__", "__line__")

    result = Schema({int})(_annotate(NodeSet({1, 2}), 6))
    assert result == {1, 2}
    assert type(result) is NodeSet
    assert _source(result) == (_FILE, 6)


def test_namedtuple_rebuilds_positionally_without_state() -> None:
    """A namedtuple has no instance state, and rebuilding it still works."""
    point = collections.namedtuple("Point", ["x", "y"])  # noqa: PYI024
    result = Schema((int, int))(point(1, 2))
    assert result == (1, 2)
    assert type(result) is point


def test_namedtuple_subclass_carries_its_state() -> None:
    """A namedtuple subclass with a __dict__ keeps it across the positional rebuild."""
    point = collections.namedtuple("Point", ["x", "y"])  # noqa: PYI024

    class LocatedPoint(point):  # type: ignore[valid-type, misc]
        pass

    result = Schema((int, int))(_annotate(LocatedPoint(1, 2), 9))
    assert result == (1, 2)
    assert type(result) is LocatedPoint
    assert _source(result) == (_FILE, 9)


def test_exact_sequence_namedtuple_carries_its_state() -> None:
    """ExactSequence rebuilds a namedtuple subclass positionally and carries state."""
    point = collections.namedtuple("Point", ["x", "y"])  # noqa: PYI024

    class LocatedPoint(point):  # type: ignore[valid-type, misc]
        pass

    result = ExactSequence([int, int])(_annotate(LocatedPoint(1, 2), 11))
    assert type(result) is LocatedPoint
    assert _source(result) == (_FILE, 11)


@pytest.mark.usefixtures("policy")
def test_state_survives_at_every_level_of_a_nested_structure() -> None:
    """Each nested node keeps its own line, so a loss says which level lost it."""
    data = _annotate(
        NodeDict(
            {
                "sensors": _annotate(
                    NodeList(
                        [
                            _annotate(NodeDict({"name": "kitchen"}), 30),
                            _annotate(NodeDict({"name": "hall"}), 40),
                        ],
                    ),
                    20,
                ),
                "meta": _annotate(NodeDict({"owner": "erik"}), 50),
            },
        ),
        10,
    )

    result = Schema(
        {"sensors": [{"name": str}], "meta": {"owner": str}},
    )(data)

    assert _source(result) == (_FILE, 10)
    assert _source(result["sensors"]) == (_FILE, 20)
    assert _source(result["sensors"][0]) == (_FILE, 30)
    assert _source(result["sensors"][1]) == (_FILE, 40)
    assert _source(result["meta"]) == (_FILE, 50)


@pytest.mark.usefixtures("policy")
def test_a_deeply_nested_node_still_reports_where_it_came_from() -> None:
    """The motivating case: a deep node's file and line survive a realistic schema."""
    config = _annotate(
        NodeDict(
            {
                "light": _annotate(
                    NodeList(
                        [
                            _annotate(
                                NodeDict(
                                    {
                                        "platform": "template",
                                        "lights": _annotate(
                                            NodeDict(
                                                {
                                                    "porch": _annotate(
                                                        NodeDict({"old": "yes"}),
                                                        12,
                                                    ),
                                                },
                                            ),
                                            11,
                                        ),
                                    },
                                ),
                                10,
                            ),
                        ],
                    ),
                    9,
                ),
            },
        ),
        1,
    )

    schema = Schema(
        {
            "light": [
                {
                    Required("platform"): str,
                    "lights": {str: {"old": str}},
                },
            ],
        },
    )
    result = schema(config)

    porch = result["light"][0]["lights"]["porch"]
    assert type(porch) is NodeDict
    file_name, line = _source(porch)
    assert f"near {file_name}:{line}" == "near configuration.yaml:12"


@pytest.mark.usefixtures("policy")
def test_str_subclass_state_survives_a_scalar_schema() -> None:
    """A str subclass is never rebuilt, so its annotation passes straight through."""
    value = _annotate(NodeStr("porch"), 12)
    for schema in (Schema(str), Schema("porch"), Schema(Any("porch", "hall"))):
        result = schema(value)
        assert type(result) is NodeStr
        assert _source(result) == (_FILE, 12)


@pytest.mark.usefixtures("policy")
def test_bare_container_schemas_pass_the_value_through() -> None:
    """Schema(dict) and Schema(list) return the value itself, annotation and all."""
    mapping = _annotate(NodeDict({"a": 1}), 4)
    sequence = _annotate(NodeList([1]), 5)
    assert Schema(dict)(mapping) is mapping
    assert Schema(list)(sequence) is sequence


@pytest.mark.usefixtures("policy")
def test_plain_containers_are_unchanged() -> None:
    """The plain dict and list fast paths still return plain, stateless containers."""
    mapping = Schema({"a": int})({"a": 1})
    sequence = Schema([int])([1, 2])
    assert type(mapping) is dict
    assert type(sequence) is list
    assert _source(mapping) == (None, None)
    assert _source(sequence) == (None, None)


def test_coerce_to_dict_returns_a_plain_dict() -> None:
    """Coerce(dict) builds a plain dict, so it carries nothing, as intended."""
    result = Schema(Coerce(dict))(_annotate(NodeDict({"a": 1}), 4))
    assert result == {"a": 1}
    assert type(result) is dict
    assert _source(result) == (None, None)


def test_a_foreign_mapping_rebuilds_as_a_plain_dict() -> None:
    """A Mapping that is not a dict subclass rebuilds plain, with nothing carried."""

    class Annotated(collections.abc.Mapping):
        def __init__(self, data: dict[str, typing.Any], line: int) -> None:
            self._data = data
            self.__line__ = line

        def __getitem__(self, key: str) -> typing.Any:
            return self._data[key]

        def __iter__(self) -> typing.Any:
            return iter(self._data)

        def __len__(self) -> int:
            return len(self._data)

    result = Schema({"a": int})(Annotated({"a": 1}, 4))
    assert result == {"a": 1}
    assert type(result) is dict
    assert _source(result) == (None, None)


def test_a_subclass_with_no_state_is_rebuilt_untouched() -> None:
    """A subclass carrying nothing takes the cheap path and gains no attributes."""

    class Bare(dict):
        pass

    result = Schema({"a": int})(Bare({"a": 1}))
    assert type(result) is Bare
    assert result.__dict__ == {}


def test_only_the_slots_that_were_set_are_carried() -> None:
    """An unset slot stays unset on the rebuilt node instead of raising."""
    node = NodeDict({"a": 1})
    node.__line__ = 12  # __config_file__ deliberately left unset

    result = Schema({"a": int})(node)
    assert result.__line__ == 12
    with pytest.raises(AttributeError):
        _ = result.__config_file__


def test_instance_dict_state_is_carried() -> None:
    """A subclass with a __dict__ and no __slots__ keeps its attributes."""

    class Tagged(dict):
        pass

    node = Tagged({"a": 1})
    node.tag = "kitchen"

    result = Schema({"a": int})(node)
    assert type(result) is Tagged
    assert result.tag == "kitchen"


def test_both_instance_dict_and_slots_are_carried() -> None:
    """A subclass with both a __dict__ and __slots__ keeps each of them."""

    class Mixed(dict):
        __slots__ = ("__dict__", "__line__")

    node = Mixed({"a": 1})
    node.__line__ = 12
    node.tag = "kitchen"

    result = Schema({"a": int})(node)
    assert result.__line__ == 12
    assert result.tag == "kitchen"


def test_an_overridden_getstate_is_never_called() -> None:
    """A subclass __getstate__ cannot intercept the carry: the read is unbound."""

    class Hostile(dict):
        __slots__ = ("__config_file__", "__line__")

        def __getstate__(self) -> typing.Any:
            message = "never called"
            raise RuntimeError(message)

    result = Schema({"a": int})(_annotate(Hostile({"a": 1}), 12))
    assert result == {"a": 1}
    assert type(result) is Hostile
    assert _source(result) == (_FILE, 12)


def test_custom_pickle_state_is_out_of_scope() -> None:
    """A custom __getstate__/__setstate__ pair is skipped; attributes still carry."""

    class Custom(list):
        def __getstate__(self) -> typing.Any:
            return ("custom", "payload")

        def __setstate__(self, state: typing.Any) -> None:
            self.restored = state

    node = Custom([1, 2])
    node.own = "attr"

    result = Schema([int])(node)
    assert result == [1, 2]
    assert type(result) is Custom
    assert result.own == "attr"
    assert not hasattr(result, "restored")


def test_a_subclass_that_refuses_the_state_still_validates() -> None:
    """A __setattr__ that rejects a slot costs that slot, not the validation."""

    class Locked(dict):
        __slots__ = ("__line__",)

        def __setattr__(self, name: str, value: typing.Any) -> None:
            message = "read-only"
            raise AttributeError(message)

    node = Locked({"a": 1})
    object.__setattr__(node, "__line__", 12)

    result = Schema({"a": int})(node)
    assert result == {"a": 1}
    assert type(result) is Locked
    assert not hasattr(result, "__line__")


def test_dict_backed_state_survives_a_refusing_setattr() -> None:
    """__dict__ state bypasses __setattr__, so a refusing subclass still keeps it."""

    class LockedDict(dict):
        def __setattr__(self, name: str, value: typing.Any) -> None:
            message = "read-only"
            raise AttributeError(message)

    node = LockedDict({"a": 1})
    node.__dict__["__line__"] = 12  # __setattr__ would refuse, so seed it directly

    result = Schema({"a": int})(node)
    assert result == {"a": 1}
    assert type(result) is LockedDict
    assert result.__line__ == 12


def test_a_subclass_whose_state_cannot_be_read_still_validates() -> None:
    """A slot that raises when it is read costs that slot, not the validation."""
    blocked = True

    class Unreadable(dict):
        __slots__ = ("__line__",)

        def __getattribute__(self, name: str) -> typing.Any:
            if blocked and name == "__line__":
                message = "unreadable"
                raise RuntimeError(message)
            return super().__getattribute__(name)

    node = Unreadable({"a": 1})
    object.__setattr__(node, "__line__", 12)

    result = Schema({"a": int})(node)
    blocked = False  # let the assertions below read the slot again

    assert result == {"a": 1}
    assert type(result) is Unreadable
    assert not hasattr(result, "__line__")


def test_state_is_carried_before_the_fill_so_setitem_sees_it() -> None:
    """The carry runs before the values land, so a subclass __setitem__ reads it."""

    class LineAware(dict):
        def __setitem__(self, key: str, value: typing.Any) -> None:
            super().__setitem__(key, f"{value}@{self.__line__}")

    node = LineAware({"a": "x"})
    node.__line__ = 12

    result = Schema({"a": str})(node)
    assert result == {"a": "x@12"}


def test_a_list_subclass_that_cannot_rebuild_carries_nothing() -> None:
    """The plain-list fallback holds no state, and the carry leaves it alone."""

    class TaggedList(list):
        def __init__(self, items: object, tag: object) -> None:
            super().__init__(items)  # type: ignore[arg-type]
            self.tag = tag

    result = Schema([int])(TaggedList([1, 2], "x"))
    assert result == [1, 2]
    assert type(result) is list
    assert not hasattr(result, "tag")


def test_the_compiled_mapping_path_is_really_exercised() -> None:
    """Under the ON policy the schema truly compiles, and a subclass still carries."""
    set_compile_policy(CompilePolicy.ON)
    schema = Schema({"a": int}).compile()
    assert getattr(schema._compiled, "__name__", "") == "_validate"

    assert schema({"a": 1}) == {"a": 1}  # the generated plain-dict path
    result = schema(_annotate(NodeDict({"a": 1}), 12))
    assert type(result) is NodeDict
    assert _source(result) == (_FILE, 12)
