"""Hardening against untrusted input: ReDoS patterns and unbounded recursion.

These cover the boundaries that matter when probatio validates data described by
an untrusted schema (a JSON Schema document) or recurses through ``Self``.
"""

from __future__ import annotations

import time

import pytest

import probatio as p
from probatio.codecs._regex_safety import _quantifier_is_variable, is_catastrophic
from probatio.error import SchemaError

CATASTROPHIC = [
    # Nested unbounded quantifiers.
    "(a+)+",
    "(a*)*",
    "(a+)*",
    "(a*)+",
    "^(a+)+$",
    r"(\d+)+",
    "((ab)+)+",
    "(a{1,}){2,}",
    "(a+)+tail",
    "((a+){2,})",
    # Nullable body or alternative under an unbounded quantifier.
    "(a?)+",
    "(a*)+",
    "(.*)*",
    "([a-z]*)+",
    "((ab)?)+",
    "(a|a?)+",
    "(|a)+",
    r"(a|\d?)+",
    "(a|[a-z]?)+",
    "(a|(x)?)+",
    # Overlapping alternatives (one a prefix of another) under a quantifier.
    "(a|aa)+",
    "(a|ab)+$",
    "(foo|foobar)+",
    # Adjacent unbounded quantifiers on overlapping character sets.
    "a+a+a+$",
    r"\d+\d+$",
    ".*.*",
    "[a-z]+[a-z]*",
    r"\w+\w+",
    "a+a*",
    ".+.+",
    r"[0-9]+\d+",  # the class and the escape both match digits
    r"[\d]+[\d]+",  # an escape inside a class is treated as matching anything
    "[^a]+[^b]+",  # two negated classes always overlap
    "(a[xy]b)+(a[xy]b)+",  # adjacent quantified groups (with a class inside)
    # Equal alternatives, group modifiers, bounded repeats, and class alternatives.
    "(a|a)+",
    "(a|a)*",
    "(?:a|a)+",
    "(?i:a|a)+",
    "(?P<x>a|a)+",
    "(.*a){15}$",  # a fixed repeat of an unbounded body is still exponential
    "(a+){2}",  # repeating an unbounded body backtracks
    "([a-c]|[a-c][a-c])+",  # overlapping class alternatives
    "(?=a|a)+",  # a lookahead group with overlapping alternatives
    "(?<=a|a)+",  # a lookbehind group with overlapping alternatives
    # Semantically overlapping alternatives the string compare alone would miss.
    "(ab|a[b])+",  # a literal and a single-char class that match the same string
    "(a.|ab)+",  # a wildcard atom overlapping a literal
    r"(\d|[0-9])+",  # an escape and a class spanning the same characters
    "(ab?|c)+",  # an alternative carrying a quantifier bails to overlapping
    # Bounded but variable-length runs of one character, as bad as (a+)+.
    "(a{1,3})+$",  # the classic bounded-inner-quantifier bypass
    "([a-z]{1,5})+",  # a class instead of a literal
    r"(\d{2,4})+",  # an escape, with a nonzero lower bound
    "(a{1,10}){1,10}$",  # a bounded outer repeat over a variable-length body
    "(aa{1,3})+",  # a fixed atom followed by a variable run of the same char
    "(^a{1,3})+",  # a zero-width anchor before the variable run
    "(.{1,3})+",  # a wildcard run, where every character is shared
    "(a{1,3}.)+",  # a variable run of 'a' next to a wildcard that also matches 'a'
    "(a{1,3}[^b])+",  # a variable run of 'a' next to a negated class that matches 'a'
    # Nullable bodies built from several optional atoms (not a single one).
    "(a?b?)*c$",  # two optional atoms make the body nullable
    "(a?b?c?)*$",  # three optional atoms, same shape
    "(a*b*)+",  # two zero-or-more atoms
    "((a?))*",  # a group whose only atom is optional is itself nullable
    "(a{,3})*",  # a brace whose minimum is zero is nullable, like a{0,3}
    "(^a?)*",  # a zero-width anchor in the body does not stop it being nullable
]

SAFE = [
    "abc",
    "a+",
    "a*",
    "(ab)+",
    "[a-z]+",
    "(a+)b",
    r"\(a+\)+",
    "(?:ab)+",
    "a{2,5}",
    "(ab){2,5}",
    "(foo|bar)+",
    "(jpg|png|gif)+",
    "(a|b|c)*",
    "(abc|def)*",
    "(ab?)+",
    "^[a-z0-9_]+$",
    "(a+)?",
    "{2,}",
    "(a{2)",
    "(a{)*",  # a malformed brace is not a zero-allowing quantifier, so not nullable
    # Adjacent quantifiers on disjoint character sets do not backtrack.
    "a+b+",
    r"\w+\s+\w+",
    r"\d+\D+",
    "[a-z]+[0-9]+",
    r"https?://\w+",
    r"a+\d+",
    # Odd-but-parseable shapes the scanner must walk without tripping.
    r"\bword",  # a zero-width escape, treated as matching anything
    "x[abc",  # an unterminated class
    "(abc",  # an unterminated group
    "b\\",  # a trailing backslash
    "[z-a]+[z-a]+",  # an inverted range yields an empty (non-overlapping) set
    "ab)cd",  # a stray closing parenthesis
    "a+?b",  # a lazy quantifier
    "(a|a){2",  # an unterminated brace quantifier is not a repeat
    "(a|a){x}",  # a malformed brace quantifier is not a repeat
    # Distinct alternatives that diverge on a later atom never co-match.
    "(cat|car)+",  # the third character differs
    "(ab|ac)+",  # the second character differs
    # Variable inner quantifiers whose run is broken by a disjoint separator.
    r"(\d{1,3}\.){3}\d{1,3}",  # the dotted-quad shape: digits split by a literal dot
    "(ab{1,3})+",  # the variable run of b is anchored by the leading a
    "(a{1,3}x)+",  # the variable run of a is closed by a mandatory x
    "(a{3})+",  # a fixed count is one length, so no ambiguous split
    "(a{1,3}(b))+",  # a nested group in the body is left to the other checks
    "(a{x,y})+",  # a non-numeric brace is a literal, not a variable repeat
]


@pytest.mark.parametrize("pattern", CATASTROPHIC)
def test_detector_flags_catastrophic_patterns(pattern: str) -> None:
    """A catastrophically backtracking pattern is detected."""
    assert is_catastrophic(pattern) is True


@pytest.mark.parametrize("pattern", SAFE)
def test_detector_passes_safe_patterns(pattern: str) -> None:
    """A pattern without nested unbounded quantifiers is allowed."""
    assert is_catastrophic(pattern) is False


@pytest.mark.parametrize(
    "quantifier",
    # ``{2,}`` varies too, though the run check rarely reaches an unbounded brace.
    ["+", "?", "{1,3}", "{2,}"],
)
def test_quantifier_is_variable_for_varying_repeats(quantifier: str) -> None:
    """A quantifier spanning more than one count is reported as variable."""
    assert _quantifier_is_variable("a" + quantifier, 1) is True


@pytest.mark.parametrize(
    "quantifier",
    [
        "{3}",  # a fixed count
        "",  # a bare atom repeats exactly once
        "{",  # a malformed brace is not a quantifier
        "{x,y}",  # a non-numeric brace is a literal
    ],
)
def test_quantifier_is_variable_for_fixed_repeats(quantifier: str) -> None:
    """A fixed or non-quantifier shape is not reported as variable."""
    assert _quantifier_is_variable("a" + quantifier, 1) is False


def test_detector_caps_huge_alternations_without_quadratic_cost() -> None:
    """A repeated group with a huge alternation is flagged fast, not analyzed O(n^2)."""
    pattern = "(" + "|".join(["a"] * 5000) + ")+"

    start = time.perf_counter()
    flagged = is_catastrophic(pattern)
    elapsed = time.perf_counter() - start

    assert flagged is True
    assert elapsed < 1.0  # the pairwise scan is skipped past the cap


def test_detector_does_not_expand_giant_character_classes() -> None:
    """A class spanning the whole codepoint range is handled fast, not materialized."""
    huge = "[ -" + chr(0x10FFFF) + "]"
    pattern = "(" + "|".join(huge for _ in range(40)) + ")+"

    start = time.perf_counter()
    is_catastrophic(pattern)

    assert time.perf_counter() - start < 1.0  # the range is treated as ANY, not built


def test_detector_caps_classes_built_from_many_ranges() -> None:
    """Many medium ranges that sum past the cap are treated as ANY, not materialized."""
    ranges = "".join(
        chr(0x100 + i * 0x100) + "-" + chr(0x100 + i * 0x100 + 0x90) for i in range(20)
    )
    pattern = "([" + ranges + "]|x)+"

    start = time.perf_counter()
    assert is_catastrophic(pattern) is True
    assert time.perf_counter() - start < 1.0


def test_detector_bounds_deeply_nested_nullable_groups() -> None:
    """Group nesting past the nullability-recursion cap is treated as nullable, fast."""
    pattern = "(" * 22 + "a?" + ")" * 22 + "*"

    start = time.perf_counter()
    assert is_catastrophic(pattern) is True
    assert time.perf_counter() - start < 1.0


def test_from_json_schema_rejects_catastrophic_pattern() -> None:
    """An untrusted schema with a catastrophic pattern is refused at decode time."""
    with pytest.raises(SchemaError, match="catastrophic"):
        p.from_json_schema({"type": "string", "pattern": "(a+)+$"})


def test_from_json_schema_accepts_a_safe_pattern() -> None:
    """A safe pattern decodes into a working Match validator."""
    schema = p.from_json_schema({"type": "string", "pattern": "^[a-z]+$"})
    assert schema("abc") == "abc"
    with pytest.raises(p.MultipleInvalid):
        schema("ABC")


def test_from_json_schema_rejects_a_non_string_pattern() -> None:
    """A non-string 'pattern' is refused at decode time, not at validation."""
    with pytest.raises(SchemaError, match="must be a string"):
        p.from_json_schema({"type": "string", "pattern": 1})


def test_from_json_schema_recursive_ref_is_depth_guarded() -> None:
    """A recursive $ref does not let deep data crash with a RecursionError."""
    schema = p.from_json_schema(
        {
            "$ref": "#/$defs/node",
            "$defs": {
                "node": {
                    "type": "object",
                    "properties": {"next": {"$ref": "#/$defs/node"}},
                    "additionalProperties": True,
                },
            },
        },
    )
    deep: dict = {}
    current = deep
    for _ in range(5000):
        current["next"] = {}
        current = current["next"]

    with pytest.raises(p.MultipleInvalid, match="nested too deeply"):
        schema(deep)


def test_developer_match_is_not_restricted() -> None:
    """A developer-written Match accepts any pattern, matching voluptuous."""
    # Building it must not raise; the trust boundary is the untrusted decode path.
    assert p.Schema(p.Match("(a+)+"))("aaa") == "aaa"


def test_from_json_schema_rejects_too_deep_a_document() -> None:
    """A pathologically nested schema is refused, not a RecursionError."""
    node: dict = {"type": "object", "properties": {}}
    deepest = node
    for _ in range(500):
        child: dict = {"type": "object", "properties": {}}
        deepest["properties"]["next"] = child
        deepest = child

    with pytest.raises(SchemaError, match="nests deeper"):
        p.from_json_schema(node)


def test_from_json_schema_rejects_a_deep_contains_chain() -> None:
    """A deeply nested typeless 'contains' is refused, not a RecursionError.

    The contains decode path spends more stack frames per level than the object
    path, so it is the case most likely to overflow before the depth guard fires.
    """
    node: dict = {"type": "integer"}
    for _ in range(500):
        node = {"contains": node}

    with pytest.raises(SchemaError, match="nests deeper"):
        p.from_json_schema(node)


@pytest.mark.parametrize("element", [["x"], {"a": 1}])
def test_from_json_schema_rejects_unhashable_required(element: object) -> None:
    """A non-string 'required' entry is refused with a clean SchemaError, not a TypeError."""
    with pytest.raises(SchemaError, match="required"):
        p.from_json_schema({"type": "object", "required": [element]})


def _recursive_schema() -> p.Schema:
    """A Self-recursive schema: a value with an optional nested 'next'."""
    return p.Schema({p.Required("v"): int, p.Optional("next"): p.Self})


def _nested_data(depth: int) -> dict:
    """Build data nested ``depth`` levels deep through the 'next' key."""
    root: dict = {"v": 1}
    current = root
    for _ in range(depth):
        current["next"] = {"v": 1}
        current = current["next"]
    return root


def test_self_accepts_reasonable_depth() -> None:
    """A modestly nested recursive structure validates fine."""
    assert _recursive_schema()(_nested_data(10)) is not None


def test_self_rejects_pathological_depth() -> None:
    """Very deep data raises a clean Invalid, never a RecursionError."""
    with pytest.raises(p.MultipleInvalid, match="nested too deeply"):
        _recursive_schema()(_nested_data(5000))


def test_self_rejects_cyclic_data() -> None:
    """Self-referential data is rejected cleanly, not as a RecursionError."""
    cyclic: dict = {"v": 1}
    cyclic["next"] = cyclic

    with pytest.raises(p.MultipleInvalid, match="nested too deeply"):
        _recursive_schema()(cyclic)
