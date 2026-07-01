"""Property-based fuzzing of the probatio-only validators.

These validators have no voluptuous counterpart, so they cannot join the
differential engine fuzz. Instead, two invariants are hammered with generated
input:

- Robustness: a validator only ever raises ``Invalid``. Arbitrary junk in must
  come out as a clean validation error, never a leaked ``TypeError``,
  ``OverflowError``, or similar.
- Idempotent acceptance: a value that validates produces output that validates
  again, so the validated result is always a valid input to the same schema.
"""

from __future__ import annotations

import contextlib
from decimal import Decimal
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import probatio
from probatio import (
    ASCII,
    ULID,
    UUID,
    Alpha,
    Alphanumeric,
    Base64,
    Boolean,
    Byte,
    ByteLength,
    Clamp,
    Date,
    Datetime,
    Duration,
    Email,
    EndsWith,
    EnsureList,
    Fqdn,
    FqdnUrl,
    Hex,
    HexColor,
    HexInt,
    Hostname,
    IPAddress,
    IPNetwork,
    IPv4Address,
    IPv6Address,
    IsBlockDevice,
    IsDir,
    IsFifo,
    IsFile,
    IsRegex,
    IsSocket,
    IsSymlink,
    JSONString,
    Latitude,
    Longitude,
    MacAddress,
    MultipleOf,
    Negative,
    NonEmpty,
    NonNegative,
    NoWhitespace,
    PathExists,
    Percentage,
    Port,
    Positive,
    PrintableASCII,
    Range,
    Schema,
    Slug,
    SmallFloat,
    Sorted,
    StartsWith,
    Time,
    TimeZone,
    TimeZoneInfo,
    Url,
    YAMLString,
)

# One instance of every probatio-only validator.
_VALIDATORS = (
    IPv4Address(),
    IPv6Address(),
    IPAddress(),
    IPNetwork(),
    MacAddress(),
    UUID(),
    Hostname(),
    Fqdn(),
    Port(),
    Time(),
    Duration(),
    TimeZone(),
    TimeZoneInfo(),
    EnsureList(),
    Slug(),
    Negative(),
    NonNegative(),
    MultipleOf(3),
    MultipleOf(0.5),  # a float factor overflows on a huge int; must stay clean
    Percentage(),
    NonEmpty(),
    Byte(),
    SmallFloat(),
    IsRegex(),
    JSONString(),
    YAMLString(),
    IsSymlink(),
    IsSocket(),
    IsFifo(),
    IsBlockDevice(),
    Alpha(),
    Alphanumeric(),
    ASCII(),
    PrintableASCII(),
    NoWhitespace(),
    StartsWith("a"),
    EndsWith("z"),
    ByteLength(max=10),
    HexColor(),
    Base64(),
    Hex(),
    HexInt(),
    Sorted(),
    ULID(),
    Latitude(),
    Longitude(),
)

# voluptuous-shared leaf validators have a differential counterpart, but nothing
# was fuzzing them for the no-leak invariant, which is how several real leaks
# (Url on a non-string, Range on Decimal('NaN'), Port on infinity) survived 100%
# line coverage. They are checked for robustness only, not re-validation.
_SHARED_LEAF_VALIDATORS = (
    Range(min=0, max=10),
    Clamp(min=0, max=10),
    Positive(),
    Url(),
    FqdnUrl(),
    Email(),
    Boolean(),
    Date(),
    Datetime(),
    IsDir(),
    IsFile(),
    PathExists(),
)
_SCHEMAS = [Schema(v) for v in (*_VALIDATORS, *_SHARED_LEAF_VALIDATORS)]
# The parsing validators decode to a value that is not itself a valid input
# (a dict is not a JSON string), so they are excluded from the re-validation
# invariant but kept in the robustness one.
_IDEMPOTENT_SCHEMAS = [
    Schema(validator)
    for validator in _VALIDATORS
    if not isinstance(validator, JSONString | YAMLString)
]

# Hostile scalars that have tripped real leaks: NaN/infinity (float and Decimal),
# integers too large to convert to float, lone surrogates and NUL bytes, and
# tuples (which some validators feed to parsers that raise odd exceptions).
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
        (1, 2, 3),
    ],
)

# Deliberately wide, including unbounded integers, NaN/infinity, Decimals, bytes,
# and nested containers, to probe for leaked exceptions.
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
def test_new_validators_only_raise_invalid(value: Any) -> None:
    """No probatio-only validator leaks a non-Invalid exception, whatever the input."""
    for schema in _SCHEMAS:
        with contextlib.suppress(probatio.Invalid):
            schema(value)


@given(value=_values)
@settings(
    max_examples=500,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_new_validators_output_revalidates(value: Any) -> None:
    """A validated value is itself a valid input, so re-validation never raises."""
    for schema in _IDEMPOTENT_SCHEMAS:
        try:
            first = schema(value)
        except probatio.Invalid:
            continue
        # Must not raise: the output of a successful validation re-validates.
        schema(first)
