"""Hypothesis strategies shared by the fuzz tests.

A *spec* is a small, library-agnostic description of a schema (nested tuples).
``build(spec, lib)`` materializes it in either probatio or voluptuous, so the
exact same schema can be run in both and their behavior compared. The data
strategy generates JSON-shaped values likely to both pass and fail, and
``fitting`` builds a value shaped like a given spec.

The construct set is deliberately the subset where probatio is meant to match
voluptuous exactly. Numeric/length bounds are always guarded behind a type check
(``All(int, Range(...))``) so a bound is never compared against an incomparable
value, which both libraries would treat as an uncaught ``TypeError`` rather than a
validation error.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from hypothesis import strategies as st

if TYPE_CHECKING:
    from random import Random

_literals = st.one_of(
    st.integers(min_value=-10, max_value=10),
    st.text(max_size=3),
    st.booleans(),
    st.none(),
)

# The differential oracle (to_json_schema against the reference validator) needs
# literals free of the Python/JSON impedances: a bool is an ``int`` in Python but
# not a JSON number, so ``Schema(int)`` accepts ``True`` while ``{"type":
# "integer"}`` rejects it, which reads as a spurious narrowing. Dropping booleans
# keeps the no-narrowing check meaningful.
_json_literals = st.one_of(
    st.integers(min_value=-10, max_value=10),
    st.text(max_size=3),
    st.none(),
)


# Remove is pinned by curated cases (``test_conformance.py``, ``test_mapping.py``)
# and not fuzzed. A matching ``Remove`` is final in probatio, while voluptuous only
# marks the key and keeps it when a key tried later accepts it too, a documented
# deviation. Every ``Remove`` beside one of the catch-alls below would land on it.
_KEY_KINDS = ("required", "optional")
_EXTRA_MODES = (None, "allow", "remove")
# Members of one all-or-none group and of one at-most-one group. A single group
# of each is enough for two members to meet in one mapping.
_GROUP_KINDS = ("inclusive", "exclusive")

# What a mapping's catch-all entry is keyed on. ``Extra`` is the marker; the rest
# are *variable keys*, where the key itself is validated. Without them every
# property suite is blind to the whole region, ``{str: int}`` included, and to the
# ``propertyNames`` the encoder renders from a restrictive one.
_CATCHALL_KINDS = ("extra", "str_key", "int_key", "in_key", "coerce_key")

# Field names and data keys are drawn from this shared alphabet as well as from
# free text. Were both sides to draw arbitrary text independently, a generated
# value would almost never land on a declared property or inside a variable key's
# set, and the mapping region would be explored far more shallowly than the
# example counts suggest. The digits matter for a coercing key, which turns
# "1" into a number the way a property name never could.
_KEY_ALPHABET = ("a", "b", "c", "1", "2")

# The membership key's set is fixed rather than drawn: the declared field names
# are random text, so a fixed set reliably produces both a name inside it and
# names outside, which is the interesting pairing.
_IN_KEY_MEMBERS = ("a", "b")

# A mapping can carry more than one variable key, and which one a name lands on
# decides its value schema, so the pairing matters: with ``{int: int, str: str}``
# the universal ``str`` key accepts a value the partial one does not. Every
# *ordered* pair is generated, because order decides which key an encoder reaches
# first, and enumerating beats picking the combinations that come to mind.
_CATCHALL_PAIRS = (
    ("extra", "str_key"),
    ("extra", "int_key"),
    ("extra", "in_key"),
    ("extra", "coerce_key"),
    ("str_key", "extra"),
    ("str_key", "int_key"),
    ("str_key", "in_key"),
    ("str_key", "coerce_key"),
    ("int_key", "extra"),
    ("int_key", "str_key"),
    ("int_key", "in_key"),
    ("int_key", "coerce_key"),
    ("in_key", "extra"),
    ("in_key", "str_key"),
    ("in_key", "int_key"),
    ("in_key", "coerce_key"),
    ("coerce_key", "extra"),
    ("coerce_key", "str_key"),
    ("coerce_key", "int_key"),
    ("coerce_key", "in_key"),
)


def _names() -> st.SearchStrategy[str]:
    """Property names: the shared alphabet, plus free text for the odd shapes."""
    return st.sampled_from(_KEY_ALPHABET) | st.text(min_size=1, max_size=3)


# The pairs without ``Extra``. Beside another variable key ``Extra`` is tried last
# in probatio and ahead of the type keys in voluptuous, a documented deviation, so
# a differential against voluptuous leaves those pairs out.
_CATCHALL_PAIRS_WITHOUT_EXTRA = tuple(
    pair for pair in _CATCHALL_PAIRS if "extra" not in pair
)


def specs(
    *,
    no_narrowing: bool = False,
    extra_beside_a_variable_key: bool = True,
    float_type: bool = True,
    markers: bool = False,
) -> st.SearchStrategy[Any]:
    """A recursive strategy yielding library-agnostic schema specs.

    With ``no_narrowing=True`` the strategy drops the constructs whose JSON Schema
    rendering is a documented lossy narrowing (``Coerce`` cannot express its input
    coercion; ``Clamp`` accepts out-of-range values it then clamps) and drops
    boolean literals (the bool-is-int impedance). The remainder is the subset over
    which the emitted schema must never reject an input probatio accepts, so the
    differential oracle can assert exactly that.

    The next two switches keep a differential against voluptuous inside the
    region where probatio means to behave exactly like it. Each turns off one
    documented deviation: ``Extra`` beside another variable key (see above), and
    the ``float`` type, which takes an ``int`` in probatio and not in voluptuous
    (ADR-017). A caller that wants ``float`` schemas compared anyway keeps the
    type and passes its values through ``without_integers``.

    ``markers=True`` adds the keys that do more than say required or optional: a
    key with a default, and members of an ``Inclusive`` and an ``Exclusive``
    group. It is opt-in because the codec suites built on this strategy render a
    document from every spec, and those keys have rules of their own there. While
    ``float`` is in the type set a default is never an integer; integer defaults
    are drawn with ``float_type=False``.
    """
    literals = _json_literals if no_narrowing else _literals
    types = [int, str, float] if no_narrowing else [int, str, bool, float]
    if not float_type:
        types.remove(float)
    pairs = (
        _CATCHALL_PAIRS
        if extra_beside_a_variable_key
        else _CATCHALL_PAIRS_WITHOUT_EXTRA
    )
    leaf_options = [
        st.sampled_from(types).map(lambda t: ("type", t)),
        literals.map(lambda v: ("literal", v)),
        literals.map(lambda v: ("equal", v)),
        st.lists(literals, min_size=1, max_size=4).map(lambda xs: ("in", xs)),
        st.lists(literals, min_size=1, max_size=4).map(lambda xs: ("not_in", xs)),
        st.tuples(
            st.integers(min_value=-10, max_value=0),
            st.integers(min_value=0, max_value=10),
        ).map(lambda mm: ("range", mm[0], mm[1])),
        st.tuples(
            st.integers(min_value=0, max_value=2),
            st.integers(min_value=2, max_value=5),
        ).map(lambda mm: ("length", mm[0], mm[1])),
    ]
    if not no_narrowing:
        leaf_options += [
            st.tuples(
                st.integers(min_value=-10, max_value=0),
                st.integers(min_value=0, max_value=10),
            ).map(lambda mm: ("clamp", mm[0], mm[1])),
            st.sampled_from([int, str, float]).map(lambda t: ("coerce", t)),
        ]
    leaves = st.one_of(*leaf_options)
    key_kinds: st.SearchStrategy[Any] = st.sampled_from(_KEY_KINDS)
    if markers:
        # A default is validated against the key's value schema like any input,
        # so under a schema that may hold ``float`` an integer default would let
        # ADR-017 back in through the schema, past ``without_integers``.
        defaults = literals.map(without_integers) if float_type else literals
        key_kinds |= st.sampled_from(_GROUP_KINDS) | st.tuples(
            st.sampled_from(_KEY_KINDS), defaults
        )
    return st.recursive(
        leaves,
        lambda children: st.one_of(
            children.map(lambda c: ("maybe", c)),
            st.lists(children, min_size=1, max_size=3).map(lambda cs: ("any", cs)),
            st.lists(children, min_size=1, max_size=3).map(lambda cs: ("union", cs)),
            children.map(lambda c: ("list", c)),
            st.builds(
                lambda fields, extra, catchall: ("dict", fields, extra, catchall),
                st.dictionaries(
                    _names(),
                    st.tuples(key_kinds, children),
                    max_size=3,
                ),
                st.sampled_from(_EXTRA_MODES),
                st.one_of(
                    st.none(),
                    st.tuples(st.sampled_from(_CATCHALL_KINDS), children),
                    # A pair carries a value schema *each*. Sharing one makes the
                    # pair useless for the thing it exists to check: taking the
                    # first key's value and merging both produce the same document
                    # when the values are identical.
                    st.tuples(st.sampled_from(pairs), children, children),
                ),
            ),
        ),
        max_leaves=8,
    )


def data(*, booleans: bool = True, floats: bool = True) -> st.SearchStrategy[Any]:
    """JSON-shaped values: scalars, lists, and string-keyed dicts (no NaN/inf).

    ``booleans=False`` drops bare booleans and ``floats=False`` drops floats, for
    a differential oracle where Python's numeric equality (``0 == 0.0``,
    ``1 == True``) would read a strict-typed schema's rejection as a spurious
    narrowing (an ``enum`` member matches a cross-type number under probatio's
    ``==`` but not under the JSON type model the schema encodes).
    """
    scalars = st.none() | st.integers(min_value=-12, max_value=12) | st.text(max_size=3)
    if floats:
        scalars |= st.floats(allow_nan=False, allow_infinity=False)
    if booleans:
        scalars |= st.booleans()
    return st.recursive(
        scalars,
        lambda c: st.lists(c, max_size=3) | st.dictionaries(_names(), c, max_size=3),
        max_leaves=6,
    )


# What a value is replaced by when a near miss is wanted: one of every JSON shape.
_STRAY_VALUES: tuple[Any, ...] = (None, 0, 1, -1, 1.5, True, "", "a", "1", [], {})

# How often a value is a stray one and not what the spec asks for. Often enough
# that most mappings carry a wrong value somewhere, rarely enough that most of a
# nested schema is still reached.
_STRAY_CHANCE = 0.15


def fitting(spec: Any, random: Random) -> Any:
    """Draw a value shaped like a spec: mostly one it accepts, sometimes a near miss.

    ``data()`` knows nothing of the schema it is paired with, so a random value
    almost never gets past the first type check and the engine below it goes
    unvisited. This builds the value from what the spec asks for, and swaps in a
    stray value at any level, which is where the near misses come from: a mapping
    of the right keys with one wrong value, a list with one stray item.

    It is a plain function over a ``random.Random`` (draw one with
    ``st.randoms()``) and not a strategy, because a strategy built per spec costs
    more than the validation it is there to exercise.
    """
    if random.random() < _STRAY_CHANCE:
        return random.choice(_STRAY_VALUES)

    return _fitting_value(spec, random)


def _small_int(random: Random) -> int:
    """An integer in the range the specs draw their bounds and literals from."""
    return random.randint(-12, 12)


def _fitting_type(spec: Any, random: Random) -> Any:
    """A value of the type, or an ``int`` where the type is ``float``."""
    if spec[1] is str:
        return random.choice(("", "a", "b", "1", "ab"))
    if spec[1] is bool:
        return random.choice((True, False))
    if spec[1] is float and random.random() < 0.5:
        return random.uniform(-12, 12)
    return _small_int(random)


def _fitting_dict(spec: Any, random: Random) -> dict[str, Any]:
    """A mapping with some of the declared fields and a few undeclared names.

    An undeclared name takes a value shaped like one of the catch-alls' value
    schemas, since which catch-all a name lands on is the engine's decision.
    """
    _, fields, _, catchall = spec
    value: dict[str, Any] = {}
    # With a catch-all there is always an undeclared name for it to take.
    for _ in range(random.randint(0 if catchall is None else 1, 3)):
        name = random.choice(_KEY_ALPHABET)
        value[name] = (
            random.choice(_STRAY_VALUES)
            if catchall is None
            else fitting(random.choice(catchall[1:]), random)
        )

    for name, (_, child) in fields.items():
        if random.random() < 0.7:
            value[name] = fitting(child, random)

    return value


def _fitting_value(spec: Any, random: Random) -> Any:
    """A value the spec is likely to accept, by kind."""
    kind = spec[0]
    if kind == "type":
        return _fitting_type(spec, random)
    if kind in ("literal", "equal"):
        return spec[1]
    if kind == "in":
        return random.choice(spec[1])
    if kind in ("not_in", "range", "clamp"):
        return _small_int(random)
    if kind == "length":
        return "x" * random.randint(0, 6)
    if kind == "coerce":
        return random.choice((_small_int(random), "1", "x"))
    if kind == "maybe":
        return random.choice((None, fitting(spec[1], random)))
    if kind in ("any", "union"):
        return fitting(random.choice(spec[1]), random)
    if kind == "list":
        return [fitting(spec[1], random) for _ in range(random.randint(0, 3))]
    return _fitting_dict(spec, random)


def without_integers(value: Any) -> Any:
    """Turn every integer in a value into a float next to it, booleans aside.

    For a differential against voluptuous that keeps the ``float`` type: an
    ``int`` is the one value the two libraries disagree on there (ADR-017).
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value + 0.5
    if isinstance(value, list):
        return [without_integers(item) for item in value]
    if isinstance(value, dict):
        return {key: without_integers(item) for key, item in value.items()}
    return value


def build(spec: Any, lib: Any) -> Any:
    """Materialize a spec as a schema fragment in ``lib`` (probatio or voluptuous)."""
    kind = spec[0]
    if kind in ("type", "literal"):
        return spec[1]
    if kind == "equal":
        return lib.Equal(spec[1])
    if kind == "in":
        # A fresh list per library: voluptuous-openapi's convert() mutates the In
        # container in place, which would otherwise leak across the two builds.
        return lib.In(list(spec[1]))
    if kind == "not_in":
        return lib.NotIn(list(spec[1]))
    if kind == "range":
        return lib.All(int, lib.Range(min=spec[1], max=spec[2]))
    if kind == "clamp":
        return lib.All(int, lib.Clamp(min=spec[1], max=spec[2]))
    if kind == "length":
        return lib.All(str, lib.Length(min=spec[1], max=spec[2]))
    if kind == "coerce":
        return lib.Coerce(spec[1])
    if kind == "maybe":
        return lib.Maybe(build(spec[1], lib))
    if kind == "any":
        return lib.Any(*[build(child, lib) for child in spec[1]])
    if kind == "union":
        return lib.Union(*[build(child, lib) for child in spec[1]])
    if kind == "list":
        return [build(spec[1], lib)]
    # The only remaining kind is a mapping spec: ("dict", fields, extra, catchall).
    return _build_dict(spec, lib)


def _build_dict(spec: Any, lib: Any) -> Any:
    """Materialize a mapping spec: marker kinds, an extra policy, and a catch-all."""
    _, fields, extra, catchall = spec
    mapping: dict[Any, Any] = {}
    for key, (key_kind, child) in fields.items():
        mapping[_field_key(key, key_kind, lib)] = build(child, lib)
    if catchall is not None:
        kinds, *children = catchall
        # A single kind comes with one child; a pair comes with one each, so a
        # mapping can hold two variable keys wanting different values.
        for one, child in zip(
            (kinds,) if isinstance(kinds, str) else kinds, children, strict=True
        ):
            mapping[_catchall_key(one, lib)] = build(child, lib)
    if extra is None:
        return mapping
    policy = lib.ALLOW_EXTRA if extra == "allow" else lib.REMOVE_EXTRA
    return lib.Schema(mapping, extra=policy)


def _field_key(key: str, kind: Any, lib: Any) -> Any:
    """The marker a declared field sits under.

    A kind is a name, or a ``(name, default)`` pair for a key that fills itself in.
    """
    if kind == "inclusive":
        return lib.Inclusive(key, "all or none")
    if kind == "exclusive":
        return lib.Exclusive(key, "at most one")

    kind, *default = kind if isinstance(kind, tuple) else (kind,)
    marker = lib.Required if kind == "required" else lib.Optional
    return marker(key, default=default[0]) if default else marker(key)


def _catchall_key(kind: str, lib: Any) -> Any:
    """The key a catch-all entry sits under: the Extra marker or a variable key.

    A variable key is validated like any other schema, so the engine applies it to
    every key no literal marker matched. ``str`` is the everyday catch-all shape;
    ``int`` is one no JSON property name can satisfy; the membership key is what a
    ``propertyNames`` enum decodes to.
    """
    if kind == "extra":
        return lib.Extra
    if kind == "str_key":
        return str
    if kind == "int_key":
        return int
    if kind == "coerce_key":
        # A key that *transforms*: it accepts the property name "1" by turning it
        # into a number, which no ``{"type": "integer"}`` rendering can express.
        return lib.Coerce(int)
    return lib.In(list(_IN_KEY_MEMBERS))


def canonical_openapi(node: Any) -> Any:
    """Erase the dimensions to_openapi renders more correctly than voluptuous-openapi.

    ``to_openapi`` diverges from the oracle in a few documented ways: a closed
    mapping emits ``additionalProperties: false`` (the oracle omits it), an empty
    ``required`` is omitted (the oracle emits ``required: []``, invalid on 3.0),
    a nullable enum keeps null as a member (the oracle drops it), and a 3.0
    exclusive bound uses the Draft 4 boolean-companion form where the oracle emits
    the numeric form. Normalizing those away on both sides leaves the rest of the
    structure to compare; the behavioral oracle checks the corrected dimensions.
    """
    if isinstance(node, dict):
        result = {
            key: canonical_openapi(value)
            for key, value in node.items()
            if key not in ("additionalProperties", "nullable")
        }
        # An omitted empty ``required`` and an emitted ``required: []`` are equal.
        if result.get("required") == []:
            del result["required"]
        # An enum's ``type`` diverges (probatio drops it for a mixed-type enum,
        # and omits duplicates and orders members differently from the oracle's
        # ``set``), so compare an enum by its sorted, null-free member set alone.
        if isinstance(result.get("enum"), list):
            members = {v for v in result["enum"] if v is not None}
            result["enum"] = sorted(members, key=repr)
            result.pop("type", None)
        if isinstance(result.get("type"), list):
            kept = [t for t in result["type"] if t != "null"]
            result["type"] = kept[0] if len(kept) == 1 else kept
        # The 3.0 boolean-companion exclusive bound canonicalizes to the numeric
        # (3.1/oracle) form, so both spellings compare equal.
        for bound in ("Minimum", "Maximum"):
            exclusive = f"exclusive{bound}"
            inclusive = bound.lower()
            if result.get(exclusive) is True and inclusive in result:
                result[exclusive] = result.pop(inclusive)
        return result
    if isinstance(node, list):
        return [canonical_openapi(item) for item in node]
    return node
