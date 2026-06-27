---
title: JSON Schema and OpenAPI
description: Render a Probatio schema as JSON Schema or OpenAPI, build one back, and stay safe doing it.
---

A Probatio schema is Python data. Other tools speak JSON Schema, OpenAPI, or the
flat field list that config frontends and tool exporters consume. The codecs
translate between them, for the constructs that map cleanly. They are exported
from the top level, so `from probatio import to_json_schema, from_json_schema`
is all you need.

## JSON Schema, both directions

`to_json_schema(schema)` renders a schema as a JSON Schema dictionary.
`from_json_schema(dict)` is the inverse: it builds a `Schema` back. Together they
round trip the parts that have a clean mapping.

```python
from probatio import Schema, Required, Optional, to_json_schema

schema = Schema({Required("name"): str, Optional("port", default=8080): int})
to_json_schema(schema)
# {'type': 'object', 'properties': {'name': {'type': 'string'}, 'port': {'type': 'integer', 'default': 8080}}, 'additionalProperties': False, 'required': ['name']}
```

Going the other way, a JSON Schema becomes a working validator. `required`
controls which keys must be present, `minimum` becomes a `Range`, and so on:

```python
from probatio import from_json_schema

document = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "age": {"type": "integer", "minimum": 0}},
    "required": ["name"],
}
schema = from_json_schema(document)
schema({"name": "Ada", "age": 37})  # {'name': 'Ada', 'age': 37}
```

A small round trip stays intact. Render a schema, build it back, validate:

```python
from probatio import Schema, Required, to_json_schema, from_json_schema

original = Schema({Required("name"): str, Required("age"): int})
rebuilt = from_json_schema(to_json_schema(original))
rebuilt({"name": "Ada", "age": 37})  # {'name': 'Ada', 'age': 37}
```

:::note
The mapping is not lossless. `to_json_schema` renders what JSON Schema can
express and turns anything it does not recognize into an open schema (`{}`).
`from_json_schema` ignores keywords it does not handle rather than rejecting
them. Treat a round trip as "the validatable shape survives", not "byte for byte
identical".
:::

## Supported keywords

`from_json_schema` understands the keywords below. A purely descriptive keyword
it does not read (`title`, `description`, `examples`) is ignored, so a partial
schema still yields a usable validator. A *restrictive* keyword it cannot honor
(`if`/`then`/`else`, `propertyNames`, `patternProperties`, `dependentRequired`,
`dependentSchemas`) is refused with a `SchemaError` rather than silently dropped,
so an untrusted schema is never quietly widened to accept what its author meant
to forbid. `to_json_schema` emits the same constructs in the other direction.

| Area    | Keywords                                                             |
| ------- | ------------------------------------------------------------------- |
| Objects | `properties`, `required`, `additionalProperties`, `minProperties`, `maxProperties` |
| Arrays  | `items`, `minItems`, `maxItems`, `prefixItems`, `uniqueItems`, `contains`, `minContains`, `maxContains` |
| Strings | `minLength`, `maxLength`, `pattern`, `format` (`date`, `date-time`, `time`, `email`, `uri`, `ipv4`, `ipv6`, `uuid`, `hostname`, `byte`), `writeOnly`, `contentEncoding` (`Base64`) |
| Numbers | `minimum`, `maximum`, `exclusiveMinimum`, `exclusiveMaximum`, `multipleOf` |
| Values  | `enum`, `const`, `not`, `type` (including a type array like `["string", "null"]`) |
| Compose | `anyOf`, `oneOf`, `allOf`, `$ref` (resolved against `$defs`/`definitions`) |

`ExactSequence` exports as `prefixItems` (with `items: false` and matching
`minItems`/`maxItems`), `Unique` as `uniqueItems`, `Contains` as `contains`,
`Equal`/`Literal` as `const`, and `NotIn` as `not` over an `enum`. The called
factory forms `Email()`/`Url()`/`FqdnUrl()` export their `format` (`email`/`uri`),
the same as the bare names. `Datetime`/`Date`/`Time` export the
`date-time`/`date`/`time` formats (a custom `strptime` format has no JSON Schema
equivalent, so it exports as a plain string). The network and identifier
validators export their standard `format`: `IPv4Address` to `ipv4`, `IPv6Address`
to `ipv6`, `UUID` to `uuid`, and `Hostname`/`Fqdn` to `hostname`; `Port` exports a
bounded integer and `MultipleOf` a `multipleOf`. `Secret` exports its inner schema
with `writeOnly: true`, and `Base64` as `contentEncoding: base64`. These decode
back into the matching validator, so they round-trip, with one known widener.
JSON Schema has a single `hostname` format, so both `Hostname` and `Fqdn` export
to it and decode back as `Hostname`, meaning a round-tripped `Fqdn` accepts a
dotless host the original would reject. Pin it with a `pattern` or an explicit
check if the distinction matters. `oneOf` decodes with its exact semantics (a
value must match exactly one branch, so one matching two or more is rejected),
unlike the looser `anyOf`.

`from_openapi` adds the OpenAPI `nullable` keyword, covered next.

:::note[Integers and booleans]
A decoded `{"type": "integer"}` validates with Python's `int`, and in Python
`bool` is a subclass of `int`. So a decoded integer schema accepts `True` as an
integer, where a strict JSON Schema validator would not. If that distinction
matters for your data, add an explicit check.
:::

## OpenAPI and the nullable keyword

`to_openapi(schema)` and `from_openapi(dict)` are the OpenAPI pair. The decoder
is the same one `from_json_schema` uses, plus the OpenAPI 3.0 `nullable` keyword.
That keyword is the visible difference. A value that also accepts `None` renders
as two branches in JSON Schema, but as a single `nullable: True` in OpenAPI:

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

`from_openapi` reads `nullable` back the way you would expect. A nullable field
accepts both `None` and a real value:

```python
from probatio import from_openapi

schema = from_openapi(
    {"type": "object", "properties": {"nickname": {"type": "string", "nullable": True}}}
)
schema({"nickname": None})   # {'nickname': None}
schema({"nickname": "ada"})  # {'nickname': 'ada'}
```

## The field list

`serialize(schema)` renders a schema as a plain field list, the shape
voluptuous-serialize produces. Config frontends and tool exporters consume it. A
mapping becomes a list of field dicts:

```python
from probatio import Schema, Required, Optional, serialize

schema = Schema({Required("name"): str, Optional("port", default=8080): int})
serialize(schema)
# [{'type': 'string', 'name': 'name', 'required': True}, {'type': 'integer', 'name': 'port', 'required': False, 'optional': True, 'default': 8080}]
```

`serialize` and `to_openapi` take a `custom_serializer` hook, called first for
each node. It returns a dict to override that node, or the `UNSUPPORTED` sentinel
to defer to the default handling. `UNSUPPORTED` is exported from the top level
and prints as itself:

```python
from probatio import UNSUPPORTED

UNSUPPORTED  # UNSUPPORTED
```

:::tip
Return `UNSUPPORTED` from your hook for the nodes you do not care about. That
keeps your custom logic small: handle the one or two constructs you need, defer
everything else.
:::

## Untrusted input is the default assumption

`from_json_schema` and `from_openapi` treat their input as untrusted. A JSON
Schema can arrive from anywhere, and two of its constructs can wreck a naive
decoder: a `pattern` that backtracks catastrophically, and a document nested deep
enough to overflow the Python stack. Both are refused with `SchemaError` rather
than hanging or crashing.

A nested unbounded quantifier like `(a+)+` is the classic catastrophic regular
expression. Probatio refuses to compile it:

<!-- verify: raises SchemaError -->
```python
from probatio import from_json_schema

from_json_schema({"type": "string", "pattern": "(a+)+$"})
```

A pathologically deep document hits the same wall: past a generous depth limit,
the decoder raises `SchemaError` instead of recursing into a `RecursionError`.

:::caution[The guards are conservative]
Both safeguards err toward refusing. An unusual but legitimate schema, a deeply
nested one or a pattern that only looks dangerous, can trip them. That is the
trade: a clean `SchemaError` you can catch beats a hang you cannot. If you
control the source and trust it, validate the result, not the schema.
:::
