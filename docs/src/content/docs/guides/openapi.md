---
title: OpenAPI
description: Render a Probatio schema as an OpenAPI Schema object, build one back, and handle nullable.
---

OpenAPI Schema objects are JSON Schema with a few of their own rules. `to_openapi`
and `from_openapi` are the OpenAPI pair, exported from the top level. They share
the JSON Schema codec, so most of the behavior, the supported keywords, the
round-trip caveats, and the untrusted-input guards, is the same. Read [JSON
Schema](/guides/json-schema/) first; this page covers what OpenAPI adds.

## Both directions

`to_openapi(schema)` renders a schema as an OpenAPI Schema object.
`from_openapi(dict)` is the inverse: it builds a `Schema` back. This is handy for
LLM tool calling and MCP, which describe tool parameters as OpenAPI, so a Probatio
schema can become a tool signature and a tool's declared parameters can become a
validator.

```python
from probatio import Schema, Required, Optional, to_openapi

schema = Schema({Required("name"): str, Optional("port", default=8080): int})
to_openapi(schema)
# {'type': 'object', 'properties': {'name': {'type': 'string'}, 'port': {'type': 'integer', 'default': 8080}}, 'required': ['name']}
```

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
