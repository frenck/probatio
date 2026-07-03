---
title: Quick start
description: From nothing to a working schema, and what to read next.
---

A schema describes the shape of valid data. You build one from plain Python
types and a few helpers, then call it with a value. A valid value comes back
(possibly normalized); an invalid one raises an error that points at what went
wrong.

## Your first schema

```python
from probatio import Schema, Required, Optional

schema = Schema(
    {
        Required("name"): str,
        Optional("port", default=8080): int,
    }
)

schema({"name": "app"})  # {'name': 'app', 'port': 8080}
```

Two things happened there. `name` was required, so leaving it out would fail.
`port` was optional with a default, so it was filled in. The result is a new
dict; the input is not mutated.

## Normalizing as you validate

A schema does not only check, it can convert. `Coerce` turns the value into a
type, and the converted value is what you get back:

```python
from probatio import Schema, Coerce, All, Range

port = Schema(All(Coerce(int), Range(min=1, max=65535)))

port("443")  # 443
```

`All` runs its validators in order and feeds each result into the next, so the
string becomes an int and then the int is range-checked.

## Handling failures

When validation fails, the schema raises `MultipleInvalid` (a subclass of
`Invalid`) with a path to the value that did not match:

```python
from probatio import Schema, Invalid

schema = Schema({"port": int})

try:
    schema({"port": "nope"})
except Invalid as err:
    print(err)  # expected int at 'port'
```

Catching `Invalid` catches every validation error, because everything Probatio
raises for bad data is a subclass of it. The [error handling
guide](/guides/error-handling/) goes deeper into paths, multiple errors at once,
and human-readable messages.

## Where to next

- [Migrating from voluptuous](/getting-started/migrating-from-voluptuous/): swap
  your imports and keep your schemas.
- [The validation model](/guides/validation-model/): how schemas are built and
  what can go inside one.
- [Dict schemas and markers](/guides/dict-schemas-and-markers/): required and
  optional keys, defaults, and extra-key policy.
- [Validating a config file](/recipes/config-file/): a worked end-to-end example.
- [API reference](/reference/): the full public surface.
