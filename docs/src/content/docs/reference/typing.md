---
title: Typing
description: What static type checking does and does not give you when you validate with Probatio.
---

Probatio is typed, and it ships its types. What that buys you is honest but
limited: your calls into Probatio are checked, but the _result_ of a validation
is not a statically known shape. This page spells out the difference, so you
know what the type checker is actually doing for you.

## Probatio ships its types

The package includes a `py.typed` marker, so type checkers read Probatio's own
annotations instead of treating it as untyped. Probatio itself is checked in CI
with both [mypy](https://mypy-lang.org/) and [ty](https://github.com/astral-sh/ty),
under mypy's strict mode. The public API carries annotations, and they are kept
honest by those runs.

That means when you call a validator or build a schema, the checker sees real
signatures and flags the obvious mistakes.

```python
from probatio import Range

Range(min=0, max=10)  # checked: a Range validator
```

## A schema cannot describe its result

Here is the part to be clear about. A schema is arbitrary data: a type, a
literal, a callable, a nested container, any combination. The validated result
depends on what that data says at runtime, including normalization like `Coerce`
and default values. A static checker cannot read a schema value and work out the
shape it produces.

So `Schema.__call__` returns `Any`. The checker will not infer that
`schema({"name": "app"})` gave you a dict with a `name` key of type `str`. It
gives you back something untyped, and from there you are on your own.

```python
from probatio import Schema, Required

schema = Schema({Required("name"): str})
result = schema({"name": "app"})  # result is typed as Any
result  # {'name': 'app'}
```

Probatio validates at runtime. It checks that the data matches the schema, and
raises if it does not. It does not hand you a statically typed model the way a
model-class library (something built on dataclasses or a model base class) does.
The guarantee is a runtime one.

:::note
This is not a Probatio shortcoming to be fixed later. It follows from the design:
a schema is a value, not a type declaration, so its result type is not knowable
to a checker. voluptuous works the same way.
:::

If you want a statically typed object after validation, construct it yourself
from the validated data. Probatio confirms the data is well-formed; you turn it
into a typed object:

```python
from dataclasses import dataclass
from probatio import Schema, Required

@dataclass
class Config:
    name: str
    port: int

schema = Schema({Required("name"): str, Required("port"): int})

def load(raw: object) -> Config:
    """Validate, then build a typed object the checker understands."""
    data = schema(raw)  # runtime-checked, typed Any
    return Config(name=data["name"], port=data["port"])

load({"name": "app", "port": 8080})  # Config(name='app', port=8080)
```

After the `Config(...)` line the checker knows the type again, because you told
it. The validation guarantees the values are present and of the right kind at
runtime, so the construction is safe.

## Typed results with `DataclassSchema`

There is a shorter path that does the same thing for you. `DataclassSchema` reads
a dataclass and builds the schema from its annotations, and it is generic in the
dataclass type, so the checker infers the result. `DataclassSchema(Config)` is a
`DataclassSchema[Config]`, and calling it is typed as returning a `Config`, not
`Any`:

```python
from dataclasses import dataclass
from probatio import DataclassSchema

@dataclass
class Config:
    name: str
    port: int = 8080

schema = DataclassSchema(Config)
config = schema({"name": "app"})  # config is typed as Config
config.port  # 8080, and the checker knows .port is an int
```

This carries a static type because the schema came from a type (the dataclass)
rather than arbitrary data. You write the shape once, as the dataclass, and get
both the runtime validation and the static type from it. See [schemas from
dataclasses](/guides/dataclasses/) for the full field mapping.

## Typed results with `TypedDictSchema`

`TypedDictSchema` does the same from a `TypedDict`, and it is the interesting case
for typing. A `TypedDict` is a plain dict at runtime, so there is nothing to
construct: the validated dict _is_ the result, and the schema is generic, so the
checker types it as the `TypedDict`. You get the static type at no runtime cost,
and `result["key"]` access keeps working, because it really is a dict.

```python
from typing import TypedDict
from probatio import TypedDictSchema

class Config(TypedDict):
    name: str
    port: int

schema = TypedDictSchema(Config)
config = schema({"name": "app", "port": 8080})  # typed as Config
config["port"]  # 8080, and the checker knows it is an int
```

So there are two ways to get a typed result, and they differ in what comes back.
`DataclassSchema` constructs an instance (attribute access, a real type, a
construction cost). `TypedDictSchema` returns the validated dict unchanged, typed
as the `TypedDict` (dict access, zero construction). Reach for the dataclass when
you want an object, the TypedDict when you want typed dict-shaped data without
changing how that data is used. Both are checked: the checker knows the keys, and
flags an unknown one.

## `Schemable`

`Schemable` is the type alias for "anything you can use as a schema". It is
defined as an alias of `Any`:

```text
type Schemable = Any
```

It is exposed so you can annotate code that accepts or stores schemas, mirroring
voluptuous. Because a schema can be any of the accepted forms (a type, a literal,
a callable, a container, a nested `Schema`), there is no narrower type that fits,
so the alias is `Any`. Use it for intent and readability, not for narrowing:

```python
from probatio import Schema, Schemable

def make_validator(definition: Schemable) -> Schema:
    """Build a Schema from any schemable definition."""
    return Schema(definition)

make_validator({"port": int})  # a compiled Schema
```

The annotation documents what the argument is for. It does not constrain it
beyond what `Any` allows.

## The rest of the API is typed

Everything you call is annotated, so the call sites are checked even though the
validated result is not. The validators, the markers, the combinators, the error
classes: all carry signatures. Passing the wrong kind of argument to a validator,
or mishandling an error, is caught.

```python
from probatio import All, Coerce, Range, Schema

schema = Schema(All(Coerce(int), Range(min=0)))  # all checked at the call site
schema("42")  # 42
```

## What you get, and what you do not

What static typing gives you here:

- Probatio's public API is annotated and ships `py.typed`, so your editor and
  type checker see it.
- Calls into Probatio (building schemas, calling validators, catching errors)
  are checked against real signatures.
- Probatio's own code is checked under strict mypy and under ty in CI.

What it does not give you:

- A statically typed result. `schema(data)` returns `Any`; the checker does not
  know the shape of what comes back.
- Compile-time verification of a schema's structure against your data's type.
  That check happens at runtime, when you call the schema.
- A typed model object for free, with two exceptions: `DataclassSchema` is generic
  and returns its dataclass type, and `TypedDictSchema` is generic and returns its
  TypedDict type (the validated dict, typed, at no construction cost). For a plain
  `Schema`, build the typed object from the validated data yourself.

:::tip
Validate at the boundary, construct your typed object right after, and keep the
typed object for the rest of the program. You get the runtime guarantee from
Probatio and the static guarantee from your own type.
:::
