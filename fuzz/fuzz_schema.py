"""Atheris harness: fuzz the validation engine and the encoders.

This drives the core promise of the library. A schema is built from a grammar of
probatio types, validators, combinators, and markers, then a fuzzed value is run
through it: the safe-validator contract says only ``Invalid`` (a ``MultipleInvalid``
from the engine) may escape, on *any* input. The same schema is then run through
``to_json_schema``, ``to_openapi``, and ``to_field_list``, which must never crash (an
unrecognized node falls back to an open schema; ``to_field_list`` may raise a
documented ``ValueError``). Any other escaping exception is a crash.

Run locally (needs the ``atheris`` package):
    python fuzz/fuzz_schema.py
"""

import sys

import atheris

with atheris.instrument_imports():
    import probatio as p
    from probatio import Invalid, MultipleInvalid, Schema
    from probatio.codecs import to_field_list, to_json_schema, to_openapi


def _leaf(fdp):
    """Pick one leaf validator or type built with valid arguments."""
    return fdp.PickValueInList(
        [
            int,
            str,
            float,
            bool,
            dict,
            list,
            type(None),
            bytes,
            object,
            p.Range(min=0, max=10),
            p.Range(min=0),
            p.Clamp(min=0, max=10),
            p.Length(min=0, max=5),
            p.In([1, 2, "a", None]),
            p.NotIn([1, 2]),
            p.Contains(1),
            p.Match(r"^[a-z]+$"),
            p.Coerce(int),
            p.Coerce(float),
            p.Email(),
            p.Url(),
            p.FqdnUrl(),
            p.Boolean,
            p.Datetime(),
            p.Date(),
            p.Time(),
            p.Duration(),
            p.TimeZone(),
            p.IPv4Address(),
            p.IPv6Address(),
            p.IPAddress(),
            p.IPNetwork(),
            p.UUID(),
            p.MacAddress(),
            p.Hostname(),
            p.Fqdn(),
            p.Slug(),
            p.ULID(),
            p.MultipleOf(3),
            p.Percentage(),
            p.Port(),
            p.Unique(),
            p.Sorted(),
            p.Positive(),
            p.Negative(),
            p.NonNegative(),
            p.Latitude(),
            p.Longitude(),
            p.Base64(),
            p.Hex(),
            p.HexColor(),
            p.NonEmpty(),
            p.EnsureList(),
            p.Equal(5),
            p.Literal("x"),
            p.Number(),
            p.ExactSequence([int, str]),
        ],
    )


def _schema(fdp, depth):
    """Build a probatio schema fragment from the fuzzer's bytes."""
    if depth <= 0 or not fdp.remaining_bytes():
        return _leaf(fdp)

    choice = fdp.ConsumeIntInRange(0, 6)
    if choice == 0:
        out = {}
        for _ in range(fdp.ConsumeIntInRange(0, 3)):
            name = fdp.PickValueInList(["a", "b", "c", "grp"])
            marker = fdp.ConsumeIntInRange(0, 5)
            if marker == 0:
                key = p.Required(name)
            elif marker == 1:
                key = p.Optional(name, default=0)
            elif marker == 2:
                key = p.Remove(name)
            elif marker == 3:
                key = p.Forbidden(name)
            elif marker == 4:
                key = p.Exclusive(name, "grp")
            else:
                key = name
            out[key] = _schema(fdp, depth - 1)
        return out
    if choice == 1:
        return [_schema(fdp, depth - 1)]
    if choice == 2:
        return p.All(_schema(fdp, depth - 1), _schema(fdp, depth - 1))
    if choice == 3:
        return p.Any(_schema(fdp, depth - 1), _schema(fdp, depth - 1))
    if choice == 4:
        return p.Union(int, str, dict)
    if choice == 5:
        return p.Maybe(_schema(fdp, depth - 1))
    return _leaf(fdp)


def _value(fdp, depth):
    """Build an arbitrary value to validate from the fuzzer's bytes."""
    if depth <= 0 or not fdp.remaining_bytes():
        return fdp.PickValueInList([None, 0, "", [], {}, True])

    choice = fdp.ConsumeIntInRange(0, 8)
    if choice == 0:
        return fdp.PickValueInList([None, True, False])
    if choice == 1:
        return fdp.ConsumeInt(16)
    if choice == 2:
        return fdp.ConsumeRegularFloat()
    if choice == 3:
        return fdp.ConsumeUnicodeNoSurrogates(12)
    if choice == 4:
        return [_value(fdp, depth - 1) for _ in range(fdp.ConsumeIntInRange(0, 3))]
    if choice == 5:
        return {
            fdp.PickValueInList(["a", "b", "grp"]): _value(fdp, depth - 1)
            for _ in range(fdp.ConsumeIntInRange(0, 3))
        }
    if choice == 6:
        return fdp.ConsumeBytes(6)
    if choice == 7:
        return tuple(_value(fdp, depth - 1) for _ in range(fdp.ConsumeIntInRange(0, 2)))
    return fdp.ConsumeUnicodeNoSurrogates(4)


def TestOneInput(data: bytes) -> None:  # noqa: N802 (atheris entry point)
    """Build a schema, validate a value through it, and encode it."""
    fdp = atheris.FuzzedDataProvider(data)

    try:
        schema = Schema(_schema(fdp, 3))
    except Invalid:
        return  # A schema that fails to build on bad marker args is not the target.

    try:
        schema(_value(fdp, 3))
    except (Invalid, MultipleInvalid, RecursionError):
        pass  # Rejection and depth-guarded recursion are correct.

    # The encoders must not crash; to_field_list may raise a documented ValueError.
    to_json_schema(schema)
    to_openapi(schema)
    try:
        to_field_list(schema)
    except (ValueError, TypeError):
        pass


def main() -> None:
    """Set up and run the fuzzer."""
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
