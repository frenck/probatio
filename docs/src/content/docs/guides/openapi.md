---
title: OpenAPI
description: Render a Probatio schema as an OpenAPI Schema object, build one back, and handle nullable.
---

OpenAPI Schema objects are JSON Schema with a few of their own rules. `to_openapi`
and `from_openapi` are the OpenAPI pair, exported from the top level. `from_openapi`
is the JSON Schema decoder plus the OpenAPI extras, so its supported keywords,
round-trip caveats, and untrusted-input guards match [JSON
Schema](/guides/json-schema/); read that page first. The `to_openapi` encoder is a
separate implementation (it targets OpenAPI 3.0 or 3.1 and takes a
`custom_serializer`), so its construct coverage differs from `to_json_schema` in
places. This page covers what OpenAPI adds.

## Both directions

`to_openapi(schema)` renders a schema as an OpenAPI Schema object.
`from_openapi(dict)` is the inverse: it builds a `Schema` back. Use the pair to
publish request and response schemas in the spec of an OpenAPI-described
service, straight from the validators you already run, or to build a validator
from a spec you consume. For LLM tool calling and MCP, which take JSON Schema
rather than OpenAPI, see the [LLM tool recipe](/recipes/llm-tools/).

```python
from probatio import Schema, Required, Optional, to_openapi

schema = Schema({Required("name"): str, Optional("port", default=8080): int})
to_openapi(schema)
# {'type': 'object', 'properties': {'name': {'type': 'string'}, 'port': {'type': 'integer', 'default': 8080}}, 'required': ['name'], 'additionalProperties': False}
```

A closed object emits `additionalProperties: False`, the same as `to_json_schema`.
An `ALLOW_EXTRA` object emits `additionalProperties: True`, and a `REMOVE_EXTRA`
object omits the keyword (it accepts extra keys but strips them, so the wire shape
is open). This is one of the places `to_openapi` diverges from voluptuous-openapi,
which omits the keyword on a closed object: `to_openapi` emits correct OpenAPI even
where the reference implementation does not.

Going the other way, an OpenAPI Schema object becomes a working validator.
`nullable` is read back too, so a nullable field accepts both `None` and a real
value:

```python
from probatio import from_openapi

document = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "age": {"type": "integer", "nullable": True}},
    "required": ["name"],
}
schema = from_openapi(document)
schema({"name": "Ada", "age": None})  # {'name': 'Ada', 'age': None}
schema({"name": "Ada", "age": 37})    # {'name': 'Ada', 'age': 37}
```

## The nullable keyword

`nullable` is the visible difference from JSON Schema. A value that also accepts
`None` renders as two branches in JSON Schema, but as a single `nullable: True` in
OpenAPI:

```python
from probatio import Schema, Maybe, to_json_schema, to_openapi

schema = Schema({"nickname": Maybe(str)})
to_json_schema(schema)["properties"]["nickname"]
# {'anyOf': [{'type': 'null'}, {'type': 'string'}]}
to_openapi(schema)["properties"]["nickname"]
# {'type': 'string', 'nullable': True}
```

`to_openapi` defaults to OpenAPI 3.0 (the `nullable` keyword above). Pass
`openapi_version="3.1.0"` for 3.1, which drops `nullable` and expresses
nullability the JSON Schema way instead, as an `anyOf` with a `{"type": "null"}`
branch.

## Group constraints across versions

The `Inclusive` (all-or-none) and `Exclusive` (at most one, or exactly one when
required) dict-group markers render as object-level constraints, and one of them
splits on version. `Exclusive` uses `oneOf`/`not`, which both OpenAPI versions
have. `Inclusive` maps to `dependentRequired`, which only OpenAPI 3.1 has:

```python
from probatio import Schema, Inclusive, to_openapi

schema = Schema({Inclusive("lat", "coords"): float, Inclusive("lon", "coords"): float})
to_openapi(schema, openapi_version="3.1.0")["dependentRequired"]
# {'lat': ['lon'], 'lon': ['lat']}
```

OpenAPI 3.0 has no `dependentRequired` (and silently ignores it), so there the
same all-or-none is spelled with the keywords 3.0 does have, an `allOf` entry that
accepts every member present or none present and rejects any partial combination.
The 3.1 `dependentRequired` decodes back to an `Inclusive` group through
`from_openapi`; the 3.0 form round-trips by behavior, not back to the marker.

## Customizing the output

`to_openapi` takes a `custom_serializer` hook, the same one `serialize` uses, to
override how individual nodes render. It is documented with the field-list codec
in [Field lists](/guides/field-lists/#a-custom-serializer-hook), since both codecs
share it.

## Shared with JSON Schema

Everything else is the JSON Schema codec:

- The [supported keywords](/guides/json-schema/#supported-keywords) and how each
  validator maps to them.
- The round trip is [not lossless](/guides/json-schema/#both-directions); treat it
  as "the validatable shape survives".
- `from_openapi` treats its input as [untrusted](/guides/json-schema/#untrusted-input-is-the-default-assumption):
  a catastrophic `pattern` or a pathologically deep document is refused with
  `SchemaError`, not a hang or a crash.
