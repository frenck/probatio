---
title: Comparison to alternatives
description: Where Probatio fits among Python data validation tools, and when another library is the better choice.
---

Probatio does runtime validation of arbitrary Python data. The schema is data:
plain types, dicts, lists, and callables. You build a schema from those pieces,
call it with a value, and get back the normalized value or an `Invalid` error
with a path to what went wrong. There are no model classes to declare. It is a
drop-in reimplementation of [voluptuous](https://github.com/alecthomas/voluptuous),
and it is pure Python with no native extension.

That shapes where it fits. Probatio is at home when your data is free-form dicts
and lists (config files, request bodies, payloads from another system) and you
want the schema to stay data you can build, pass around, and compose at runtime.
It is not trying to give you typed model objects. For that, other tools do a
better job, and this page says where.

## The short answer

| Pick this when                                              | Reach for      |
| ----------------------------------------------------------- | -------------- |
| You use voluptuous today and want a maintained replacement  | Probatio       |
| Your data is plain dicts and lists, schema as data          | Probatio       |
| You want typed model objects with editor and type support   | pydantic       |
| You want declarative schema classes with load and dump      | marshmallow    |
| Your contract is a JSON Schema document                     | jsonschema     |
| You are (de)serializing your own classes                    | attrs / cattrs |
| You (de)serialize dataclasses fast, in a known format       | mashumaro      |
| You just need a dict turned into a dataclass, no validation | dacite         |

## voluptuous

This is the library Probatio replaces. Same model, same public API: a schema is
data, and you validate by calling it. Probatio is the clean-room reimplementation
that is actively maintained and MIT licensed. No code was copied from voluptuous;
behavior is matched, not source.

If you already run voluptuous, the switch is usually a one-line import change.
Read [migrating from voluptuous](/getting-started/migrating-from-voluptuous/) for
what carries over and the few intentional differences.

```python
from probatio import Schema, Required, Optional

schema = Schema({Required("name"): str, Optional("age"): int})
schema({"name": "Frenck", "age": 40})
# {'name': 'Frenck', 'age': 40}
```

## pydantic

Pydantic models your data as classes built on Python type hints, with a native
(Rust) core and strong editor and type-checker support. You declare a model
class, and you get typed objects back, with autocompletion and static checking
that follow from the hints.

That is a real strength, and it is the better choice when you want typed model
objects to carry through your code and you want your editor and type checker in
on the deal.

Probatio is the better fit when your data is plain dicts and lists, when you want
the schema to be data you build and compose at runtime rather than a class you
declare, or when you are replacing voluptuous. Different shape of problem, not a
better or worse one.

On raw speed the Rust core is genuinely fast, but the advantage is not uniform, and
it is worth being precise about where it comes from. It is largest on heavy coercion
and decoding, parsing a stack of ISO datetimes and enums out of JSON, where the
native code does real work Probatio does in Python (the cross-library benchmark on
the [performance page](/reference/performance/) is exactly that kind of workload, and
pydantic v2 sits near the top of it). It shrinks on a schema dominated by your own
**custom validators**: a native core cannot run a Python validator natively, it has
to call it across the Rust boundary (pydantic does so efficiently, but it is still a
Python call), so the speedup is muted exactly where the work is your code rather than
the library's. "Faster because Rust" holds in the parsing-heavy regime, not
everywhere, and Probatio stays pure Python with no native extension to build or
install.

:::note
The two can live side by side. Use pydantic where you want typed models, use
Probatio where you validate free-form data. Picking per use case is fine.
:::

## marshmallow

`marshmallow` validates and (de)serializes through declarative schema classes: you
declare a `Schema` subclass with typed `fields`, and `load`/`dump` turn dicts into
validated data (or objects, via `@post_load`) and back. It validates, like Probatio
and pydantic, but the schema is a class you declare with explicit field objects, and
it is built around the load and dump cycle, with a long-standing ecosystem (Flask,
webargs, and the like).

Probatio is the better fit when the schema is data you build and compose at runtime
rather than a class you declare, when you validate free-form dicts, or when you are
replacing voluptuous. marshmallow fits when you want explicit schema classes and its
serialization story. Probatio is also a good deal faster on the cross-library
[benchmark](/reference/performance/), marshmallow does more per field and is pure
Python, but speed is not the main axis here; the model is.

## jsonschema

The `jsonschema` library validates data against the
[JSON Schema](https://json-schema.org) specification. If your contract already
_is_ a JSON Schema document, perhaps shared across services or languages, then a
JSON Schema validator is the honest fit. That is its job, and it does it.

Probatio is not a JSON Schema validator. It does interoperate, though: it can
read a JSON Schema into a Probatio schema and write one back out, for the
constructs that map cleanly between the two.

:::tip
See [JSON Schema](/guides/json-schema/) for `from_json_schema` and
`to_json_schema`, and for which constructs round-trip.
:::

## attrs and cattrs

`attrs` defines classes with less boilerplate, and `cattrs` structures and
unstructures those classes to and from plain data. That is class
(de)serialization: turning a dict into a typed instance and back.

That is a different job from schema-style validation of free-form data. If your
goal is to (de)serialize your own classes, attrs and cattrs fit. If your goal is
to validate arbitrary incoming data against a schema you describe as data,
Probatio fits. They can also pair up: validate the raw data with Probatio, then
structure the result into your classes with cattrs.

## mashumaro

`mashumaro` (de)serializes dataclasses to and from dicts and formats like JSON,
YAML, and msgpack. It code-generates the conversion per class, so it is fast, and
it reads the field types from the dataclass itself. Home Assistant leans on it for
exactly that: turning stored or transmitted payloads into typed dataclass
instances at speed.

Like attrs and cattrs, that is class (de)serialization driven by your declared
types, not schema validation of free-form data. Reach for mashumaro when you own
the dataclasses and want them filled from a known format quickly. Reach for
Probatio when the data is arbitrary and the schema is the thing you describe and
compose at runtime. They pair the same way: validate the incoming data with
Probatio, then hand the result to mashumaro to build your dataclasses.

The two are close on the dict-to-dataclass path, which is worth seeing precisely
because they do different amounts of work. mashumaro deserializes and largely
trusts the declared types; Probatio's `DataclassSchema` validates every field
against its type and then constructs. On a small dataclass, mashumaro builds it in
about 0.5 µs and a compiled Probatio schema in about 0.8 µs, so Probatio is within
roughly 1.3x to 1.6x while actually validating, and the gap narrows as the field
count grows. That is the trade: mashumaro is faster because it trusts the input,
Probatio costs a little more because it does not. If the input is wrong (a string
where an int belongs), mashumaro may hand you a dataclass whose values do not match
their annotations, and Probatio rejects it. Numbers, and how to run them yourself,
are on the [Performance](/reference/performance/) page (`just bench-dataclass`).

When the input _is_ trusted (your own data round-tripping back, or already validated
upstream), Probatio's opt-in
[`DataclassSchema.construct`](/guides/dataclasses/#trusted-construction-without-validation)
builds without validating, and on that path it is the fastest in the cross-library
benchmark, ahead of mashumaro and cattrs, because it generates a flat constructor per
dataclass. The one thing it does not do is decode: a `datetime` field keeps whatever
the dict held, where mashumaro converts a string to a `datetime`. So for data that
needs decoding, mashumaro is still the right reach; for already-typed trusted data,
`construct` wins.

## dacite and dataclasses-json

Both turn a dict into a dataclass. `dacite`'s `from_dict` builds an instance from a
dict with light type checking and no schema language; `dataclasses-json` adds
`from_dict`/`to_dict` (and JSON) to a dataclass through a decorator or mixin. They are
the same family as cattrs and mashumaro: dataclass (de)serialization driven by the
declared types, not schema validation of free-form data.

Reach for them when you own the dataclasses and want them filled from a dict and do
not need full validation. Probatio's `DataclassSchema` covers the same dict-to-
dataclass path with a richer type mapping and real validation, or its opt-in
`construct` for trusted input. Among the pure (de)serializers, mashumaro and cattrs
are the fast ones; on the cross-library
[benchmark](/reference/performance/) `dacite` and `dataclasses-json` are a good deal
slower, so the choice between them is about features and ergonomics, not speed.
