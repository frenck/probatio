---
title: Schemas from TypedDicts
description: Generate a validating schema straight from a TypedDict, with the field annotations driving the validators and the typed dict coming back out.
---

A `TypedDict` describes the shape of a plain dict: which keys it has and what
each value is typed as. `TypedDictSchema` reads that shape and builds a schema
from it, so you validate against the keys you already declared instead of writing
the schema twice.

The annotation engine is shared with [dataclasses](/guides/dataclasses/), but the
two are different tools for different jobs. A dataclass schema validates a mapping
and hands you back a constructed instance. A TypedDict is a plain dict at runtime,
so a TypedDict schema validates the mapping and returns it unchanged, just typed.
Dict in, dict out, at no construction cost.

## The basics

Pass a `TypedDict` type to `TypedDictSchema`. The validated mapping comes back as
is, and your type checker sees it as the `TypedDict`, so `result["port"]` is an
`int` to the type checker with nothing extra at runtime.

```python
from typing import TypedDict

from probatio import TypedDictSchema


class Config(TypedDict):
    port: int
    host: str


schema = TypedDictSchema(Config)
schema({"port": 8080, "host": "nas"})  # {'port': 8080, 'host': 'nas'}
```

By default every key is required, and a missing one is reported like any other
validation error:

<!-- verify: raises MultipleInvalid -->

```python
from typing import TypedDict

from probatio import TypedDictSchema


class Config(TypedDict):
    port: int
    host: str


TypedDictSchema(Config)({"port": 8080})  # required key not provided at 'host'
```

The keys are closed: an unknown key is rejected, the same as the default dict
schema. Pass `extra=ALLOW_EXTRA` (keyword-only) to keep unknown keys instead.

## Required and optional keys

A `TypedDict` carries its own notion of which keys are required, and the schema
honors it. A `total=False` class makes every key optional; `Required` and
`NotRequired` set it per key. An optional key that is absent is simply left out of
the result, no default is invented. Because requiredness comes from the
`TypedDict` itself, there is no `required` argument to override it, unlike
`DataclassSchema`.

```python
from typing import TypedDict, NotRequired

from probatio import TypedDictSchema


class Server(TypedDict):
    name: str
    port: NotRequired[int]


schema = TypedDictSchema(Server)
schema({"name": "nas", "port": 22})  # {'name': 'nas', 'port': 22}
schema({"name": "nas"})              # {'name': 'nas'}
```

A `total=False` class flips the default, so nothing is required:

```python
from typing import TypedDict

from probatio import TypedDictSchema


class Partial(TypedDict, total=False):
    a: int
    b: str


TypedDictSchema(Partial)({})  # {}
```

## Annotations drive the validators

Each field's annotation becomes a validator. The mapping is deep, not just the
container type: a parameterized generic keeps its element types, a union with
`None` becomes `Maybe`, and a nested `TypedDict` (or dataclass) recurses into its
own schema. The full table is the same one
[dataclasses use](/guides/dataclasses/#annotations-drive-the-validators).

```python
from typing import TypedDict

from probatio import TypedDictSchema


class Config(TypedDict):
    port: int
    host: str


class Service(TypedDict):
    name: str
    config: Config


TypedDictSchema(Service)({"name": "web", "config": {"port": 80, "host": "nas"}})
# {'name': 'web', 'config': {'port': 80, 'host': 'nas'}}
```

For anything beyond the type check (a length, a range, a pattern), the same two
options as dataclasses apply: pass `additional_constraints`, a map from key to a
validator that runs after the type check, or put the rule on the field with
`Annotated`.

```python
from typing import TypedDict

from probatio import TypedDictSchema, Length


class Config(TypedDict):
    port: int
    host: str


schema = TypedDictSchema(Config, {"host": Length(min=2)})
schema({"port": 8080, "host": "nas"})  # {'port': 8080, 'host': 'nas'}
```

With `Annotated`, the rule lives on the field itself, next to the type:

```python
from typing import Annotated, TypedDict

from probatio import TypedDictSchema, Range


class Net(TypedDict):
    port: Annotated[int, Range(min=1, max=65535)]


TypedDictSchema(Net)({"port": 8080})  # {'port': 8080}
```

## The functional form

`create_typeddict_schema(typeddict_type, additional_constraints=None)` builds the
same schema without the class wrapper. It returns a plain `Schema`, so it does not
carry the `TypedDict` type for the type checker the way `TypedDictSchema` does.

```python
from typing import TypedDict

from probatio import create_typeddict_schema


class Config(TypedDict):
    port: int
    host: str


create_typeddict_schema(Config)({"port": 8080, "host": "nas"})
# {'port': 8080, 'host': 'nas'}
```

## What carries over from dataclasses

The two share the annotation engine, so the [dataclasses
guide](/guides/dataclasses/) covers the rest, and it all behaves the same with a
`TypedDict`:

- The [annotation mapping table](/guides/dataclasses/#annotations-drive-the-validators).
- [Coercing a field's type](/guides/dataclasses/#coercing-a-fields-type) with an
  `Annotated` hint.
- [Recursive](/guides/dataclasses/#recursive-dataclasses) and mutually recursive
  types, with the same depth guard.
- [Discriminated unions](/guides/dataclasses/#discriminated-unions) over a shared
  literal tag.
- [Key facets on fields](/guides/dataclasses/#key-facets-on-fields): `Key(...)` in
  the `Annotated` metadata to redact, alias, group, forbid, or override the presence
  of a field.

The one difference is the result: a dataclass schema constructs an instance, a
TypedDict schema returns the validated dict. Because nothing is constructed, a
`TypedDict` also accepts `Key(forbidden=True)`/`Key(remove=True)` fields with no
default (they simply shape the validated dict), where a dataclass would need one.

## Speed

The [compiled engine](/guides/compiled-schemas/) applies here too:
`TypedDictSchema` takes the same `compile=True` flag and `.compile()` method,
and under the default policy a hot schema compiles itself. The trusted escape
hatch also carries over: `TypedDictSchema.construct(data)` skips validation and,
since nothing is constructed, returns the dict unchanged (see
[trusted construction](/guides/dataclasses/#trusted-construction-without-validation)).

```python
from typing import TypedDict

from probatio import TypedDictSchema


class Point(TypedDict):
    x: int
    y: int


POINT = TypedDictSchema(Point).compile()
POINT({"x": 1, "y": 2})  # {'x': 1, 'y': 2}
```

## Limits

The value is not coerced between container types: a list stays a list even where
the annotation says `tuple`.
