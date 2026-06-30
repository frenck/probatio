"""Atheris harness: fuzz the untrusted-input JSON Schema decoder.

``from_json_schema`` and ``from_openapi`` build a validator from a JSON Schema
document that may come from an untrusted source. The contract is strict: a
malformed or hostile schema must be refused with a clean ``SchemaError`` (never a
raw ``TypeError``/``KeyError``/``RecursionError`` and never a hang), and the
validator it builds must, on any input, only ever raise ``Invalid``. This harness
drives a structured generator of JSON-Schema-shaped documents at the decoder and
treats any other escaping exception as a crash.

Run locally (needs the ``atheris`` package):
    python fuzz/fuzz_from_json_schema.py
"""

import sys

import atheris

with atheris.instrument_imports():
    from probatio import Invalid, SchemaError
    from probatio.codecs import from_json_schema, from_openapi

# The real keyword/type/format vocabulary, so the fuzzer explores actual decode
# paths instead of bouncing off "unknown keyword" early.
_KEYWORDS = [
    "type",
    "properties",
    "required",
    "items",
    "prefixItems",
    "enum",
    "const",
    "anyOf",
    "allOf",
    "oneOf",
    "not",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "pattern",
    "minItems",
    "maxItems",
    "uniqueItems",
    "contains",
    "minContains",
    "maxContains",
    "minProperties",
    "maxProperties",
    "additionalProperties",
    "format",
    "contentEncoding",
    "writeOnly",
    "nullable",
    "default",
    "$ref",
    "patternProperties",
    "propertyNames",
    "if",
    "then",
    "else",
]
_TYPES = ["object", "array", "string", "integer", "number", "boolean", "null"]
_FORMATS = [
    "email",
    "uri",
    "ipv4",
    "ipv6",
    "uuid",
    "hostname",
    "date",
    "date-time",
    "time",
    "byte",
    "unknown",
]


def _build(fdp, depth):
    """Build a JSON-Schema-shaped value from the fuzzer's bytes."""
    if depth <= 0 or not fdp.remaining_bytes():
        return fdp.PickValueInList([None, True, 0, "x", []])

    choice = fdp.ConsumeIntInRange(0, 7)
    if choice == 0:
        node = {}
        for _ in range(fdp.ConsumeIntInRange(0, 4)):
            node[fdp.PickValueInList(_KEYWORDS)] = _build(fdp, depth - 1)
        return node
    if choice == 1:
        return fdp.PickValueInList(_TYPES)
    if choice == 2:
        return fdp.PickValueInList(_FORMATS)
    if choice == 3:
        return [_build(fdp, depth - 1) for _ in range(fdp.ConsumeIntInRange(0, 3))]
    if choice == 4:
        return fdp.ConsumeIntInRange(-5, 1000)
    if choice == 5:
        return fdp.ConsumeBool()
    if choice == 6:
        return fdp.ConsumeUnicodeNoSurrogates(8)
    return fdp.ConsumeRegularFloat()


def TestOneInput(data: bytes) -> None:  # noqa: N802 (atheris entry point)
    """Decode a fuzzed schema and validate a fuzzed value through it."""
    fdp = atheris.FuzzedDataProvider(data)
    node = _build(fdp, 5)
    decoder = from_openapi if fdp.ConsumeBool() else from_json_schema

    try:
        schema = decoder(node)
    except SchemaError:
        return  # A refused schema is correct behavior, not a bug.

    # Any non-SchemaError from the decoder propagates here and is a real crash.
    try:
        schema(_build(fdp, 4))
    except Invalid:
        return  # A rejected value is correct; any other exception is a crash.


def main() -> None:
    """Set up and run the fuzzer."""
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
