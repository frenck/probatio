---
title: The validation model
description: How Probatio turns a schema into a validator, and what can go inside one.
---

A schema is data that describes data. You write it with plain Python, Probatio
compiles it once into a fast validator, and then you call that validator with a
value. This page is the mental model the rest of the guides build on.

## A schema is a value

You do not call a builder API to construct a schema. You hand `Schema` an
ordinary Python object, and its shape _is_ the rule:

```python
from probatio import Schema

Schema(int)(42)          # 42
Schema("on")("on")       # 'on'
Schema([int])([1, 2, 3]) # [1, 2, 3]
Schema({"a": int})({"a": 1})  # {'a': 1}
```

Each kind of object means something:

| You write              | It means                                                                                                      |
| ---------------------- | ------------------------------------------------------------------------------------------------------------- |
| a type (`int`)         | the value must be an instance of that type                                                                    |
| a literal (`"on"`)     | the value must equal that literal                                                                             |
| a `dict`               | a mapping, each key and value validated by its own schema                                                     |
| a `list`/`tuple`/`set` | a sequence, each item matching one of the element schemas (see [sequence schemas](/guides/sequence-schemas/)) |
| a callable             | called with the value; it returns the result or raises                                                        |
| a nested `Schema`      | validated as its own schema                                                                                   |

Because a schema is just data, schemas compose: a dict can hold lists of nested
dicts, and any value position can be a validator like `All` or `Coerce`.

One type is not a bare `isinstance`: `float` honors the PEP 484 numeric tower, so
`Schema(float)(5)` accepts the `int` and returns `5.0` (`bool` excluded). This is a
deliberate deviation from voluptuous, which rejects it. See
[ADR-017](https://github.com/frenck/probatio/blob/main/adr/017-numeric-tower-for-float.md).

## Compile once, validate many

`Schema(...)` does its analysis up front. Building the schema is the expensive
step; calling it is cheap, so build a schema once and reuse it:

```python
from probatio import Schema, Required

schema = Schema({Required("name"): str})  # compiled here

for record in [{"name": "a"}, {"name": "b"}]:
    schema(record)  # cheap, repeated calls
```

Keep schemas at module scope, or build them once in a constructor, rather than
rebuilding inside a hot loop. The numbers, and the opt-in compiled mode that
goes further, live in the [performance reference](/reference/performance/) and
the [compiled schemas guide](/guides/compiled-schemas/).

## Validation returns a new value

A validator returns the validated result; it does not mutate the input. The
result can differ from the input, because validators may normalize: `Coerce`
converts types, defaults fill in absent keys, and string transforms rewrite the
value.

```python
from probatio import Schema, Coerce

schema = Schema({"port": Coerce(int)})
data = {"port": "443"}

schema(data)  # {'port': 443}
data          # {'port': '443'}  (unchanged)
```

## Failure is an exception, not a return value

A valid value comes back from the call. An invalid one raises, so there is no
"is it valid" flag to check; you validate inside a `try`, or let the error
propagate.

```python
from probatio import Schema, Invalid

schema = Schema(int)

try:
    schema("not a number")
except Invalid as err:
    print(err)  # expected int
```

Everything Probatio raises for bad _data_ is an `Invalid` (or a
`MultipleInvalid` collecting several). A broken _schema definition_, by contrast,
raises `SchemaError`, because that is a programming mistake, not bad input. See
[error handling](/guides/error-handling/) for the full picture.

## Order matters

Within `All`, validators form a pipeline: each receives the previous result,
left to right. `All(Strip, Length(min=1))` trims whitespace before it measures,
so a string of only spaces fails; swapped, the untrimmed string would slip
through. Marker defaults and group rules also have defined timing. Where order
is significant, the guides call it out, and it matches voluptuous.

## Where to next

- [Dict schemas and markers](/guides/dict-schemas-and-markers/): the mapping
  rules in depth.
- [Combinators](/guides/combinators/): `All`, `Any`, `Union`, and friends.
- [Built-in validators](/guides/validators/): the toolbox.
