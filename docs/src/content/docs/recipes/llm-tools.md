---
title: LLM tool calling and MCP
description: One Probatio schema as both the tool's JSON Schema definition and the validator for the model's arguments.
---

LLM tool calling runs on JSON Schema: an Anthropic tool declares its parameters
as an `input_schema`, an MCP tool as an `inputSchema`, both plain JSON Schema
documents. And the arguments the model sends back are untrusted input that you
should validate before executing anything. That is one schema doing two jobs,
and Probatio covers both directions: `to_json_schema` renders the tool
definition, and calling the schema validates the arguments.

## Define the tool once

```python
from probatio import Schema, Required, Optional, All, In, Range, to_json_schema

get_weather = Schema(
    {
        Required("location", description="City name, like 'Amsterdam'"): str,
        Optional("unit", default="celsius"): In(["celsius", "fahrenheit"]),
        Optional("days", default=1): All(int, Range(min=1, max=14)),
    }
)

to_json_schema(get_weather)
# {'type': 'object', 'properties': {'location': {'type': 'string', 'description': "City name, like 'Amsterdam'"}, 'unit': {'enum': ['celsius', 'fahrenheit'], 'default': 'celsius'}, 'days': {'type': 'integer', 'minimum': 1, 'maximum': 14, 'default': 1}}, 'additionalProperties': False, 'required': ['location']}
```

The `description` on a marker flows into the JSON Schema, and the model reads
it, so write it for the model. The output also carries
`additionalProperties: False`, which strict tool use requires.

## Use it as the tool definition

The rendered dict goes straight into an Anthropic `tools` entry as
`input_schema`:

<!-- verify: skip -->

```python
import anthropic

client = anthropic.Anthropic()
response = client.messages.create(
    model="claude-opus-4-8",
    max_tokens=1024,
    tools=[
        {
            "name": "get_weather",
            "description": "Get the weather forecast for a city.",
            "input_schema": to_json_schema(get_weather),
        }
    ],
    messages=[{"role": "user", "content": "What is the weather in Amsterdam?"}],
)
```

An MCP server is the same move with a different key: the dict becomes the
tool's `inputSchema` in its tool listing.

## Validate the model's arguments

When the model calls the tool, run its arguments through the same schema
before executing. Valid arguments come back normalized, with the defaults
filled in:

```python
get_weather({"location": "Amsterdam"})
# {'location': 'Amsterdam', 'unit': 'celsius', 'days': 1}
```

Bad arguments fail with a path-precise error. Feed that message back to the
model as the tool result (with `is_error` set) and it will correct itself:

```python
from probatio import MultipleInvalid

try:
    get_weather({"location": "Amsterdam", "days": 30})
except MultipleInvalid as err:
    print(err)  # value must be at most 14 at 'days'
```

One schema, both directions: the definition the model sees and the validation
its output gets cannot drift apart, because they are the same object.

## When the schema comes from elsewhere

Sometimes the JSON Schema is not yours: a tool listed by an MCP server you
consume, or a tool definition stored as JSON. `from_json_schema` turns it into
a validator, treating the document as untrusted (a catastrophic `pattern` or a
pathologically deep document is refused with `SchemaError`):

```python
from probatio import from_json_schema

document = {
    "type": "object",
    "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1}},
    "required": ["query"],
}
validate_args = from_json_schema(document)
validate_args({"query": "probatio", "limit": 5})  # {'query': 'probatio', 'limit': 5}
```

## Where to next

- [JSON Schema](/guides/json-schema/): the full keyword mapping, round-trip
  caveats, and the untrusted-input guards.
- [Validating API requests](/recipes/web-api/): the same validate-or-reject
  flow at an HTTP boundary.
- [Error handling](/guides/error-handling/): shaping the failure you feed back
  to the model.
