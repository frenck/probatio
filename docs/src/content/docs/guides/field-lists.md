---
title: Field lists
description: Render a Probatio schema as the flat field list config frontends and tool exporters consume.
---

Some tools do not want a schema document, they want a flat list of fields to
render as a form. `serialize(schema)` produces exactly that. It is exported from
the top level: `from probatio import serialize`.

Unlike [JSON Schema](/guides/json-schema/) and [OpenAPI](/guides/openapi/), this is
not a published standard. It is the shape
[voluptuous-serialize](https://github.com/home-assistant-libs/voluptuous-serialize)
emits, an internal format from the Home Assistant ecosystem, where the config-flow
frontend turns a schema into a form. Probatio matches it byte for byte so anything
built against voluptuous-serialize keeps working on a Probatio schema. That is who
this codec is for: Home Assistant and the libraries around it. If you are not in
that world, reach for JSON Schema or OpenAPI instead.

## The field list

A mapping becomes a list of field dicts, one per key, carrying the type, the name,
and whether it is required:

```python
from probatio import Schema, Required, Optional, serialize

schema = Schema({Required("name"): str, Optional("port", default=8080): int})
serialize(schema)
# [{'type': 'string', 'name': 'name', 'required': True}, {'type': 'integer', 'name': 'port', 'required': False, 'optional': True, 'default': 8080}]
```

Each field carries what the frontend needs to render it: the `type`, the `name`,
`required`, an `optional` flag and a `default` when present, and bounds (such as
`valueMin`/`valueMax` for a `Range`) where the validator implies them.

## A custom-serializer hook

`serialize` and `to_openapi` take a `custom_serializer` hook, called first for
each node. It returns a dict to override that node, or the `UNSUPPORTED` sentinel
to defer to the default handling. `UNSUPPORTED` is exported from the top level and
prints as itself:

```python
from probatio import UNSUPPORTED

UNSUPPORTED  # UNSUPPORTED
```

:::tip
Return `UNSUPPORTED` from your hook for the nodes you do not care about. That
keeps your custom logic small: handle the one or two constructs you need, defer
everything else.
:::
