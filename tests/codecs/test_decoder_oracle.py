"""Behavioral oracle for the ``propertyNames`` decode against the reference.

The encoder already has an oracle (``test_encoder_differential``); the decoder had
none, so a newly implemented keyword had nothing but hand-written examples holding
it in place. These tests close that for ``propertyNames`` by running the decoded
validator and ``jsonschema``'s reference implementation over the same documents
and inputs.

The property is one-directional, the same shape the encoder oracles use: the
decoded validator must never *accept* what the reference rejects. Widening is the
failure mode that matters, because it silently lets an untrusted document through.
Probatio being stricter is expected and allowed: a declared property set is a
closed contract here (its deliberate strict default), where JSON Schema leaves the
object open unless ``additionalProperties`` says otherwise.

The matrix carries a negated unanchored ``pattern`` on purpose. It is what caught
the search/match gap: JSON Schema ``pattern`` searches while ``Match`` anchors,
which only narrowed on its own but inverted into a widening under ``not``.
"""

from __future__ import annotations

import itertools
from typing import Any

import jsonschema
import pytest

from probatio import Invalid, from_json_schema, to_json_schema

_VALIDATOR = jsonschema.Draft202012Validator

# Key schemas: vacuous (two spellings), a closed set, a length bound, a pattern,
# and a negation, so the decode is exercised on more than the enum it was written
# for.
_KEY_SCHEMAS: list[Any] = [
    {"type": "string"},
    {"enum": ["a", "b"]},
    {"type": "string", "maxLength": 2},
    {"type": "string", "pattern": "^x"},
    {},
    True,
    {"not": {"enum": ["bad"]}},
    {"not": {"pattern": "x"}},
    {"pattern": "x"},
]
_ADDITIONAL: list[Any] = [
    None,
    True,
    False,
    {"type": "string"},
    {"type": "integer"},
    {},
]
_PROPERTIES: list[Any] = [
    None,
    {},
    {"a": {"type": "string"}},
    {"xy": {"type": "string"}},
]
_REQUIRED: list[Any] = [None, [], ["a"], ["zz"]]

_VALUES: list[dict[str, Any]] = [
    {},
    {"a": "s"},
    {"a": 1},
    {"b": "s"},
    {"xy": "s"},
    {"x1": "s"},
    {"zz": "s"},
    {"bad": "s"},
    {"a": "s", "b": "s"},
    {"": "s"},
    {"toolongkey": "s"},
    {"xy": "s", "a": "s"},
]


def _documents() -> list[dict[str, Any]]:
    """Every propertyNames-bearing object document the matrix describes."""
    documents = []
    for key, additional, properties, required in itertools.product(
        _KEY_SCHEMAS, _ADDITIONAL, _PROPERTIES, _REQUIRED
    ):
        document: dict[str, Any] = {"type": "object", "propertyNames": key}
        if additional is not None:
            document["additionalProperties"] = additional
        if properties is not None:
            document["properties"] = properties
        if required is not None:
            document["required"] = required
        documents.append(document)

    return documents


def _accepts(schema: Any, value: Any) -> bool:
    """Whether the decoded schema accepts the value."""
    try:
        schema(value)
    except Invalid:
        return False
    return True


@pytest.mark.parametrize("document", _documents(), ids=str)
def test_decoded_property_names_never_widens(document: dict[str, Any]) -> None:
    """A decoded propertyNames document never accepts what the reference rejects."""
    _VALIDATOR.check_schema(document)
    reference = _VALIDATOR(document)
    schema = from_json_schema(document)

    for value in _VALUES:
        if _accepts(schema, value):
            assert reference.is_valid(value), (
                f"decoded schema widens: probatio accepts {value!r} but the "
                f"reference rejects it for {document!r}"
            )


def test_unsatisfiable_required_name_accepts_nothing() -> None:
    """A required name the key schema forbids makes the whole object unsatisfiable.

    Forbidding just that key would still accept every object omitting it, which is
    wider than the document allows and is what the oracle caught.
    """
    document = {
        "type": "object",
        "required": ["zz"],
        "propertyNames": {"enum": ["a", "b"]},
    }
    reference = _VALIDATOR(document)
    schema = from_json_schema(document)

    for value in [{}, {"a": "s"}, {"zz": "s"}, {"a": "s", "b": "s"}]:
        assert not reference.is_valid(value)
        with pytest.raises(Invalid):
            schema(value)


@pytest.mark.parametrize("document", _documents(), ids=str)
def test_property_names_roundtrip_reaches_a_behavioral_fixpoint(
    document: dict[str, Any],
) -> None:
    """Re-encoding a decoded propertyNames document stops changing what it accepts.

    The property the codec promises (see ``test_fuzz_roundtrip``): the *first*
    trip may be lossy, but from the second schema onward the accept set is fixed.
    The emitted document itself is not asserted stable; a pre-existing ``allOf``
    accretion in the ``All`` encode/decode pair grows it on every trip, on the
    value path just as much as here.
    """
    once = from_json_schema(document)
    emitted = to_json_schema(once)
    # The fixpoint is behavioral, but a document that no validator would accept
    # makes the comparison meaningless, so each trip has to stay a valid schema.
    _VALIDATOR.check_schema(emitted)
    twice = from_json_schema(emitted)
    re_emitted = to_json_schema(twice)
    _VALIDATOR.check_schema(re_emitted)
    thrice = from_json_schema(re_emitted)

    for value in _VALUES:
        assert _accepts(twice, value) == _accepts(thrice, value), (
            f"round trip is not a fixpoint for {value!r} on {document!r}"
        )


# Every standalone constraint keyword, with the JSON type it constrains. A value
# of any other type satisfies it without inspection, so wrapping it in ``not``
# must reject that value rather than accept it.
_TYPE_SCOPED: list[tuple[str, dict[str, Any]]] = [
    ("minLength", {"minLength": 5}),
    ("maxLength", {"maxLength": 2}),
    ("pattern", {"pattern": "x"}),
    ("minimum", {"minimum": 10}),
    ("maximum", {"maximum": 1}),
    ("exclusiveMinimum", {"exclusiveMinimum": 10}),
    ("exclusiveMaximum", {"exclusiveMaximum": 1}),
    ("multipleOf", {"multipleOf": 2}),
    ("minItems", {"minItems": 3}),
    ("maxItems", {"maxItems": 1}),
    ("uniqueItems", {"uniqueItems": True}),
    ("contains", {"contains": {"const": 9}}),
    ("minProperties", {"minProperties": 2}),
    ("maxProperties", {"maxProperties": 1}),
]

_MIXED_TYPES: list[Any] = [
    "str",
    "",
    "xy",
    5,
    5.5,
    True,
    False,
    None,
    [],
    [1, 1],
    [9],
    {},
    {"a": 1},
]


@pytest.mark.parametrize(
    ("name", "body"), _TYPE_SCOPED, ids=[n for n, _ in _TYPE_SCOPED]
)
@pytest.mark.parametrize("form", ["bare", "negated"])
def test_a_standalone_keyword_is_scoped_to_its_own_type(
    name: str,
    body: dict[str, Any],
    form: str,
) -> None:
    """A typeless keyword agrees with the reference on values of every JSON type.

    Unscoped, these only narrowed, which is easy to miss. Under ``not`` the same
    gap inverts into a widening, so both forms are checked.
    """
    document = {"not": body} if form == "negated" else body
    _VALIDATOR.check_schema(document)
    reference = _VALIDATOR(document)
    schema = from_json_schema(document)

    for value in _MIXED_TYPES:
        assert _accepts(schema, value) == reference.is_valid(value), (
            f"{name} disagrees with the reference on {value!r} ({form})"
        )


@pytest.mark.parametrize(
    "document",
    [
        {"pattern": "x"},
        {"minLength": 5},
        {"minimum": 10},
        {"multipleOf": 2},
        {"minItems": 3},
        {"contains": {"const": 9}},
        {"properties": {"a": {"type": "integer"}}},
        {"maxProperties": 1},
    ],
    ids=str,
)
def test_a_typeless_keyword_survives_re_encoding(document: dict[str, Any]) -> None:
    """Re-emitting a type-scoped keyword keeps it, and adds no type of its own.

    The scoping wrapper means what a JSON Schema keyword already means, so it
    re-emits as the bare keyword. Carrying the inner renderer's ``type`` out with
    it would narrow, since the typeless form accepts other types vacuously.
    """
    schema = from_json_schema(document)
    emitted = to_json_schema(schema)
    _VALIDATOR.check_schema(emitted)
    assert emitted, f"{document} re-encoded to an open schema, losing the keyword"

    reference = _VALIDATOR(emitted)
    for value in _MIXED_TYPES:
        if _accepts(schema, value):
            assert reference.is_valid(value), (
                f"re-encoding {document} narrows: it rejects {value!r}"
            )
