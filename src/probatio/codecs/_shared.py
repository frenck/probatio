"""Shared pieces for the schema codecs."""

from __future__ import annotations

import datetime
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

from probatio.markers import Alias, Extra, resolve_key
from probatio.schema import Schema
from probatio.validators import (
    ASCII,
    E164,
    IBAN,
    ULID,
    UUID,
    AllOrNone,
    Alpha,
    Alphanumeric,
    AsTimezone,
    AtLeastOne,
    AtMostOne,
    ByteLength,
    CreditCard,
    DataURI,
    EndsWith,
    ExactlyOne,
    Fqdn,
    Hex,
    HexColor,
    Hostname,
    IPAddress,
    IPNetwork,
    IPv4Address,
    IPv6Address,
    IsRegex,
    MacAddress,
    Msg,
    NormalizeMacAddress,
    NoWhitespace,
    PrintableASCII,
    RequiredIf,
    RequiredWith,
    RequiredWithout,
    Slug,
    StartsWith,
    TimeZone,
    TimeZoneInfo,
)
from probatio.validators import Any as AnyValidator


class _Unsupported:
    """Sentinel a custom serializer returns to defer to the default handling."""

    def __repr__(self) -> str:
        """Render clearly in debug output."""
        return "UNSUPPORTED"


# Returned from a ``custom_serializer`` to mean "I do not handle this node, fall
# back to the default". Shared by ``to_field_list`` and ``to_openapi``.
UNSUPPORTED = _Unsupported()


# Returned from ``json_safe`` for a value with no JSON representation, so the
# caller can omit the offending keyword rather than emit an unserializable dict.
UNREPRESENTABLE = object()


@dataclass
class ExclusiveGroup:
    """The members of an ``Exclusive`` group and how an empty group is judged.

    Shared by the JSON Schema and OpenAPI codecs: an ``Exclusive`` group is
    version-independent (``oneOf``/``not`` exist on both), so both codecs must
    render it identically, and one accumulator here keeps them from drifting.
    """

    # One entry per member, holding the names that satisfy it. A member is
    # usually a literal key, so the names are a single one; a key schema over
    # several literals (``Any("hours", "minutes")``) is still one member, and any
    # of its names satisfies it.
    members: list[list[str]] = field(default_factory=list)
    required: bool = False
    has_default: bool = False


def literal_any_names(key: Any) -> list[str] | None:
    """Return the names an ``Any`` key lists, or None when it is not such a key.

    Only an ``Any`` made entirely of string literals names a fixed set of
    properties. One holding a type or validator (``Any(str, int)``) is a variable
    key like any other callable, and a non-string literal never matches a JSON
    key. Shared so both codecs agree on which keys expand; stringifying the
    members without this check emits a property literally named
    ``"<class 'str'>"``.
    """
    if not isinstance(key, AnyValidator) or not key.validators:
        return None
    if not all(isinstance(item, str) for item in key.validators):
        return None
    # ``Any("a", "a")`` names one property, so dedupe rather than emit the same
    # property and the same ``required`` branch twice.
    return list(dict.fromkeys(key.validators))


def contested_names(node: dict[Any, Any]) -> frozenset[str]:
    """Names an ``Any`` key of a mapping cannot be assumed to receive.

    A presence rule is only honest when the key it is written for is the one the
    engine actually hands the name to, and several things can take it first: a
    literal key (which wins whatever the declaration order), an ``Alias`` under any
    of its accepted names, another ``Any`` listing the same name, and a variable
    key (``{str: ...}``), which matches anything and wins when it is declared
    first. Whether a variable key gets there first is declaration order, so rather
    than model the engine's precedence this reports every name it cannot prove is
    safely owned; the codecs then leave the rule out. ``Extra`` is excluded: it is
    the catch-all for names nothing else matched, so it never takes one first.

    The properties are unaffected and always emitted. Only the object-level rule,
    which would otherwise contradict validation in either direction, is dropped.
    """
    counts: Counter[str] = Counter()
    listed_by_any: list[str] = []
    variable_key = False
    for key in node:
        facets = resolve_key(key)
        name = facets.key
        if isinstance(facets.marker, Alias):
            # The canonical name is claimed even when it is not accepted: the key
            # takes the value under it and then rejects it, so nothing else sees it.
            counts.update(
                {
                    claimed
                    for claimed in (*facets.marker.input_names, name)
                    if isinstance(claimed, str)
                }
            )
            continue
        if isinstance(name, str):
            counts[name] += 1
            continue
        if (names := literal_any_names(name)) is not None:
            counts.update(names)
            listed_by_any.extend(names)
            continue
        if name is not Extra and (isinstance(name, type) or callable(name)):
            # Only a key matching by shape can take a name it does not spell. A
            # non-string literal (``{1: ...}``) matches no JSON property name.
            variable_key = True

    contested = {name for name, count in counts.items() if count > 1}
    if variable_key:
        contested.update(listed_by_any)
    return frozenset(contested)


def constraint_names(key: Any) -> list[str] | None:
    """Return the names a key claims, or None when it claims no nameable set.

    A literal key claims its name and an ``Any`` over literals claims all of them.
    A variable key matches by shape rather than by name, so there is nothing for an
    object-level constraint to be written about. Whether those names are safely
    *owned* is a separate question (see ``contested_names``).
    """
    return [key] if isinstance(key, str) else literal_any_names(key)


def abandoned_group_names(
    node: dict[Any, Any], contested: frozenset[str]
) -> frozenset[str]:
    """Group names holding a member whose presence cannot be written down.

    A group means all of its members or none of them, so rendering the rest
    without one says something different: an ``Inclusive`` group would tie
    together fewer keys than it governs, and a required ``Exclusive`` group would
    demand one of the members that remain, rejecting input the mapping accepts.
    One unrenderable member therefore abandons the whole group.

    A member is unrenderable when it matches by shape rather than by name, or when
    a name it lists is contested (see ``contested_names``). Inclusive and exclusive
    group names share one namespace here; using one string for both kinds would
    abandon both, which drops a rule rather than emitting a wrong one.
    """
    abandoned: set[str] = set()
    for key in node:
        facets = resolve_key(key)
        # Read the attribute rather than test its value: "" is a legal group name
        # and a falsy one would otherwise fall through as no group at all.
        for attribute in ("group_of_inclusion", "group_of_exclusion"):
            if hasattr(facets.marker, attribute):
                group = getattr(facets.marker, attribute)
                break
        else:
            continue
        names = constraint_names(facets.key)
        if names is None or not contested.isdisjoint(names):
            abandoned.add(group)
    return frozenset(abandoned)


def member_present(names: list[str]) -> dict[str, Any]:
    """Match an object carrying at least one of a member's names."""
    if len(names) == 1:
        return {"required": [names[0]]}
    return {"anyOf": [{"required": [name]} for name in names]}


def _both_present(first: list[str], second: list[str]) -> dict[str, Any]:
    """Match an object carrying two members at once.

    Two single-name members are the compact ``{"required": [a, b]}``, which is what
    an ordinary all-literal group has always emitted; only a member covering
    several names needs the ``allOf`` form.
    """
    if len(first) == 1 and len(second) == 1:
        return {"required": [first[0], second[0]]}
    return {"allOf": [member_present(first), member_present(second)]}


def exclusive_constraint(group: ExclusiveGroup) -> dict[str, Any]:
    """Render one ``Exclusive`` group as at-most-one, or exactly-one when required.

    A required group with no default demands exactly one member (``oneOf`` over the
    per-member presence). Otherwise at most one member may appear: the negation
    of any two being present together. Shared so both codecs stay identical.
    """
    members = group.members
    if group.required and not group.has_default:
        return {"oneOf": [member_present(member) for member in members]}
    return at_most_one(members)


def at_most_one(members: list[list[str]]) -> dict[str, Any]:
    """Match an object carrying no two of these members at once.

    The negation of any pair being present together. A lone member can never
    collide with another, so it constrains nothing.
    """
    pairs = [
        (members[i], members[j])
        for i in range(len(members))
        for j in range(i + 1, len(members))
    ]
    return (
        {"not": {"anyOf": [_both_present(one, other) for one, other in pairs]}}
        if pairs
        else {}
    )


def key_presence_constraint(
    node: Any, *, dependent_required: bool
) -> dict[str, Any] | None:
    """Render AtLeastOne, AtMostOne, ExactlyOne or AllOrNone as object keywords.

    These rules sit beside a mapping schema rather than on one of its keys, so
    without this they left no trace in the rendered document and the result
    accepted combinations the schema rejects, which is the wrong direction for a
    constraint to be lost in.

    Returns None when the node is not one of those rules, or when a key is not a
    plain string and so has no spelling here. The caller then falls back to its
    usual widening, which ``strict=True`` still reports.

    ``dependent_required`` says whether the target understands
    ``dependentRequired``; OpenAPI 3.0 does not, and spells all-or-none out
    instead.
    """
    if not isinstance(node, AtLeastOne | AtMostOne | ExactlyOne | AllOrNone):
        return None

    names = list(node.keys)
    if not all(isinstance(name, str) for name in names):
        return None

    members = [[name] for name in names]

    if isinstance(node, AtLeastOne):
        return member_present(names)

    if isinstance(node, ExactlyOne):
        return {"oneOf": [member_present(member) for member in members]}

    if isinstance(node, AtMostOne):
        return at_most_one(members)

    return _all_or_none_constraint(names, dependent_required=dependent_required)


def conditional_required_constraint(
    node: Any, *, dependent_required: bool
) -> dict[str, Any] | None:
    """Render RequiredWith, RequiredWithout or RequiredIf as object keywords.

    Like the key-presence rules these sit beside the mapping, and dropping one
    leaves a document that accepts what the schema rejects. An implication is
    spelled ``anyOf: [{not: trigger}, consequence]`` rather than ``if``/``then``,
    because OpenAPI 3.0 has the first and not the second, and the single-trigger
    ``RequiredWith`` collapses to ``dependentRequired`` where that exists.

    Returns None when the node is not one of those rules, or when a key or a
    compared value has no spelling here; the caller then widens as before, which
    ``strict=True`` still reports.
    """
    if not isinstance(node, RequiredWith | RequiredWithout | RequiredIf):
        return None

    required = list(node.required)
    if not all(isinstance(name, str) for name in required):
        return None

    if isinstance(node, RequiredIf):
        return _required_if_constraint(node, required)

    triggers = list(node.triggers)
    if not all(isinstance(name, str) for name in triggers):
        return None

    return _trigger_constraint(
        node, triggers, required, dependent_required=dependent_required
    )


def _trigger_constraint(
    node: RequiredWith | RequiredWithout,
    triggers: list[str],
    required: list[str],
    *,
    dependent_required: bool,
) -> dict[str, Any]:
    """Render a rule driven by a trigger key being present or absent."""
    if isinstance(node, RequiredWithout):
        # An absent trigger fires it, so the escape is the trigger being there:
        # under "any" one present is not enough, every one has to be.
        present = (
            {"required": triggers}
            if node.mode == "any"
            else {"anyOf": [{"required": [name]} for name in triggers]}
        )
        return {"anyOf": [present, {"required": required}]}

    if node.mode == "any" and dependent_required:
        return {"dependentRequired": dict.fromkeys(triggers, required)}

    fired = (
        {"anyOf": [{"required": [name]} for name in triggers]}
        if node.mode == "any"
        else {"required": triggers}
    )
    return {"anyOf": [{"not": fired}, {"required": required}]}


def _required_if_constraint(
    node: RequiredIf, required: list[str]
) -> dict[str, Any] | None:
    """Render a value-driven rule, or None when a key or value has no spelling."""
    conditions = node.conditions
    if not all(isinstance(name, str) for name in conditions):
        return None

    held = []
    for name, value in conditions.items():
        safe = json_safe(value)
        if safe is UNREPRESENTABLE:
            return None
        held.append({"properties": {name: {"const": safe}}, "required": [name]})

    fired = (
        held[0]
        if len(held) == 1
        else {"anyOf" if node.mode == "any" else "allOf": held}
    )
    return {"anyOf": [{"not": fired}, {"required": required}]}


def _all_or_none_constraint(
    names: list[str], *, dependent_required: bool
) -> dict[str, Any]:
    """Say "all of these keys or none" with the keywords the target has."""
    if dependent_required:
        dependent = merge_dependent_required([names])
        return {"dependentRequired": dependent} if dependent else {}

    constraints = _all_or_none([[name] for name in names])
    return {"allOf": constraints} if constraints else {}


def inclusive_constraints(
    groups: Iterable[list[list[str]]],
) -> tuple[dict[str, list[str]], list[dict[str, Any]]]:
    """Split the ``Inclusive`` groups into a ``dependentRequired`` map and ``allOf``.

    A group whose members are each a single name renders as ``dependentRequired``,
    the idiomatic all-or-none keyword, and a sibling decoder reads it back as an
    ``Inclusive`` group. A group holding a member that covers several names cannot:
    ``dependentRequired`` maps one name to names that must accompany it, and has no
    way to say "if this name is present then at least *one* of those". Such a group
    renders as one implication per member instead, which says the same thing in
    ``allOf`` at the cost of reading less clearly (and of not decoding back).

    Returns the ``(dependentRequired, allOf)`` pair, either of which may be empty.
    """
    simple: list[list[str]] = []
    constraints: list[dict[str, Any]] = []
    for members in groups:
        if all(len(member) == 1 for member in members):
            simple.append([member[0] for member in members])
            continue
        constraints.extend(_all_or_none(members))
    return merge_dependent_required(simple), constraints


def _all_or_none(members: list[list[str]]) -> list[dict[str, Any]]:
    """Say "all of these members or none" as one implication per member.

    Each reads "this member is absent, or every other member is present". Together
    they allow only the empty case and the complete one.
    """
    # A lone member depends on nothing, so it constrains nothing.
    if len(members) < 2:
        return []

    constraints: list[dict[str, Any]] = []
    for index, member in enumerate(members):
        others = [
            member_present(other)
            for position, other in enumerate(members)
            if position != index
        ]
        # A single other member needs no ``allOf`` wrapper around it.
        rest = others[0] if len(others) == 1 else {"allOf": others}
        constraints.append({"anyOf": [{"not": member_present(member)}, rest]})
    return constraints


def merge_dependent_required(groups: Iterable[list[str]]) -> dict[str, list[str]]:
    """Merge multi-member all-or-none groups into one ``dependentRequired`` map.

    Each member requires every other member of its group. Group memberships are
    disjoint, so the merged map's connected components recover the original groups
    on decode. Shared so the JSON Schema and OpenAPI 3.1 encoders cannot drift.
    """
    dependent: dict[str, list[str]] = {}
    for members in groups:
        if len(members) > 1:
            for member in members:
                dependent[member] = [other for other in members if other != member]
    return dependent


def covers_every_property_name(key: Any) -> bool:
    """Whether a mapping's variable key matches every property name it can carry.

    ``Extra`` catches every unmatched key by definition, ``str`` matches every
    JSON property name (they are all strings), and ``object`` matches anything.
    Nothing else can be assumed to.

    Transparent wrappers are unwrapped first. ``Msg`` only swaps the error
    message and ``Schema`` only compiles what it is given, so ``Msg(str, "...")``
    and ``Schema(str)`` match exactly what ``str`` matches; treating either as
    partial would throw away a value schema that is perfectly representable. A
    bare ``Schema`` cannot be a key (it is unhashable), but one wrapped in a
    ``Msg`` can, so the loop handles both rather than either alone.

    The comparison is by identity on purpose. A key validator's ``__eq__`` is
    user code and can answer anything; a false "yes" would keep a value schema
    that rejects what the mapping accepts.

    Shared by both encoders: they ask the same question, and answering it in two
    places is how they drifted apart before.
    """
    # Exact types, not ``isinstance``. A subclass can override ``__call__`` to
    # match far less than what it wraps, and unwrapping one to ``str`` would call
    # it universal and keep a value schema that rejects keys the mapping accepts.
    # ``DataclassSchema`` and ``TypedDictSchema`` are two such subclasses already.
    while type(key) in (Msg, Schema):
        key = key.validator if type(key) is Msg else key.schema

    return key is Extra or key is str or key is object


def ordered_values(values: Any) -> list[Any]:
    """List a container's values, sorting a set so the emitted schema is stable.

    A list or tuple keeps the author's order. A set or frozenset has none, so its
    values are sorted by ``repr`` to keep codec output deterministic across runs
    (stable snapshots, no spurious schema diffs, no cache misses).
    """
    if isinstance(values, set | frozenset):
        return sorted(values, key=repr)
    return list(values)


def json_safe(value: Any) -> Any:  # noqa: PLR0911
    """Convert a value to a JSON-representable form, or ``UNREPRESENTABLE``.

    Both codecs must emit a document ``json.dumps`` accepts (an emitted ``const``,
    ``enum``, ``default``, or numeric bound holding a raw ``datetime``, ``Decimal``,
    ``Enum`` member, or ``bytes`` would otherwise crash the caller). Datetimes
    render ISO, a ``Decimal`` renders a float, an ``Enum`` member renders its
    value, and a tuple or set renders a list (JSON has no tuple, and a value on
    the wire arrives as a list anyway). Anything with no clean JSON form is
    reported unrepresentable so the caller can omit it.
    """
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Enum):
        return json_safe(value.value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime.datetime | datetime.date | datetime.time):
        return value.isoformat()
    if isinstance(value, list | tuple | set | frozenset):
        converted = [json_safe(item) for item in ordered_values(value)]
        return UNREPRESENTABLE if UNREPRESENTABLE in converted else converted
    if isinstance(value, dict):
        items = {key: json_safe(item) for key, item in value.items()}
        if any(not isinstance(key, str) for key in items) or (
            UNREPRESENTABLE in items.values()
        ):
            return UNREPRESENTABLE
        return items
    return UNREPRESENTABLE


# How a network/identifier validator renders as a string, shared by the JSON
# Schema and OpenAPI codecs so the two cannot drift. ``FORMAT_BY_TYPE`` carries a
# standard ``format`` keyword; ``STRING_TYPES`` has no standard format, so it
# renders as a plain string.
FORMAT_BY_TYPE: dict[type, str] = {
    IPv4Address: "ipv4",
    IPv6Address: "ipv6",
    UUID: "uuid",
    Hostname: "hostname",
    Fqdn: "hostname",
}
STRING_TYPES = (
    IPAddress,
    IPNetwork,
    MacAddress,
    NormalizeMacAddress,
    TimeZone,
    TimeZoneInfo,
    AsTimezone,
    Slug,
    Alpha,
    Alphanumeric,
    ASCII,
    PrintableASCII,
    NoWhitespace,
    StartsWith,
    EndsWith,
    ByteLength,
    HexColor,
    IsRegex,
    Hex,
    ULID,
    CreditCard,
    IBAN,
    DataURI,
    E164,
)
