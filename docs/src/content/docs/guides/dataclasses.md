---
title: Schemas from dataclasses and TypedDicts
description: Generate a validating schema straight from a dataclass or a TypedDict, with the field annotations driving the validators.
---

If your data already has a dataclass, you should not have to write the schema
twice. `DataclassSchema` reads a dataclass's fields and builds a schema from the
annotations: it validates a plain mapping and hands you back a constructed
instance. This is the same idea as voluptuous [PR #533](https://github.com/alecthomas/voluptuous/pull/533), with a richer type
mapping (Probatio descends into element types instead of stopping at the
container).

## The basics

Pass a dataclass type to `DataclassSchema`. A field without a default is
required; a field with a default (or `default_factory`) is optional, and the
default fills in when the key is absent.

```python
from dataclasses import dataclass

from probatio import DataclassSchema


@dataclass
class User:
    name: str
    age: int = 18


schema = DataclassSchema(User)
schema({"name": "ada"})  # User(name='ada', age=18)
```

The result is a real `User`, not a dict. A missing required field is reported
like any other validation error:

<!-- verify: raises MultipleInvalid -->
```python
from dataclasses import dataclass

from probatio import DataclassSchema


@dataclass
class User:
    name: str
    age: int = 18


DataclassSchema(User)({})  # required key not provided @ data['name']
```

## Annotations drive the validators

The mapping is deep, not just the container type. A parameterized generic keeps
its element types, a union with `None` becomes `Maybe`, and a nested dataclass
recurses into its own schema.

```python
from dataclasses import dataclass, field

from probatio import DataclassSchema


@dataclass
class Address:
    street: str
    number: int = 0


@dataclass
class Person:
    name: str
    tags: list[str] = field(default_factory=list)
    home: Address | None = None


schema = DataclassSchema(Person)
schema({"name": "ada", "tags": ["x"], "home": {"street": "Main", "number": 5}})
# Person(name='ada', tags=['x'], home=Address(street='Main', number=5))
```

The full set of mappings:

| Annotation | Schema |
| --- | --- |
| `int`, `str`, a plain type | the type (an `isinstance` check) |
| `list[T]` | `[T]` (element type validated) |
| `set[T]`, `frozenset[T]` | `{T}` / `frozenset([T])` |
| `dict[K, V]` | `{K: V}` (key and value validated) |
| `tuple[X, Y]` | `ExactSequence([X, Y])` (positional) |
| `tuple[X, ...]` | a homogeneous sequence of `X` |
| `X \| None` | `Maybe(X)` |
| `X \| Y` | `Any(X, Y)` |
| `Literal["a", "b"]` | `In(["a", "b"])` |
| a nested dataclass | its own generated schema |
| `Any` | accepts any value |

A tuple field accepts a list or a tuple, since a sequence arrives as a list from
JSON, and keeps whichever you gave it.

## Layering extra rules

The annotation gives you the type check. For anything beyond that (a length, a
range, a regular expression), pass `additional_constraints`: a map from field
name to a validator that runs after the type check.

```python
from dataclasses import dataclass

from probatio import DataclassSchema, Length


@dataclass
class User:
    name: str


schema = DataclassSchema(User, {"name": Length(min=2)})
schema({"name": "ada"})  # User(name='ada')
```

The same rule can live on the field itself with `Annotated`. The first argument
is the type, and any callable after it is applied as a validator, in order, after
the type check. This keeps the constraint next to the field instead of in a
separate map, and it composes inside containers (`list[Annotated[int, Range(min=1)]]`
checks every element). Metadata that is not callable is left alone, so an
`Annotated` value you share with another tool passes through untouched.

```python
from dataclasses import dataclass
from typing import Annotated

from probatio import DataclassSchema, Length, Range


@dataclass
class User:
    name: Annotated[str, Length(min=2)]
    age: Annotated[int, Range(min=0)] = 0


schema = DataclassSchema(User)
schema({"name": "ada", "age": 30})  # User(name='ada', age=30)
```

A `NewType` is followed to the type it wraps, so a field typed
`UserId = NewType("UserId", int)` validates as an `int`.

## The functional form and the helper

`create_dataclass_schema(dataclass_type, additional_constraints=None)` builds the
same schema without the class wrapper, and `is_dataclass` is the standard-library
check, re-exported so you do not have to import it separately.

Both `DataclassSchema` and `create_dataclass_schema` also take keyword-only
`required` and `extra` arguments, passed straight through to `Schema`, so you can,
for example, accept and keep unknown keys with `extra=ALLOW_EXTRA`.

```python
from dataclasses import dataclass

from probatio import create_dataclass_schema, is_dataclass


@dataclass
class User:
    name: str


is_dataclass(User)  # True
create_dataclass_schema(User)({"name": "ada"})  # User(name='ada')
```

## Coercing a type wherever it appears

A field annotated with `datetime` validates by `isinstance`, so a string from
JSON or YAML is rejected. That is the safe default: probatio validates, it does
not silently transform. When you do want a type coerced, register a validator for
it once, and every field of that type (including fields of nested dataclasses)
picks it up while the schema is built.

```python
from dataclasses import dataclass
from datetime import datetime

from probatio import DataclassSchema, Coerce, register_type, clear_type_registry


@dataclass
class Event:
    when: datetime


register_type(datetime, Coerce(datetime.fromisoformat))
DataclassSchema(Event)({"when": "2020-01-01T12:00"})  # Event(when=datetime(2020, 1, 1, 12, 0))
clear_type_registry()  # reset, so the rest of this page is unaffected
```

The registration is read when the schema is built and baked in, so a schema does
not change once constructed. `register_type` sets it process-wide (for an
application's entry point); a library should prefer the `type_registry` context
manager, which scopes the registrations to a `with` block. A use-site validator
(an `Annotated` hint or `additional_constraints`) still applies on top, so the
type is coerced first and the extra rule checks the result. The hand-written
`Schema(datetime)` path is never affected; only annotation-driven building reads
the registry.

## Recursive dataclasses

A dataclass whose field refers back to itself (a tree node, a linked list) is
supported: the field validates against the same schema, all the way down, and
each level is constructed. Mutually recursive dataclasses (two types that point at
each other) work the same way.

```python
from __future__ import annotations

from dataclasses import dataclass, field

from probatio import DataclassSchema


@dataclass
class Tree:
    name: str
    children: list[Tree] = field(default_factory=list)


DataclassSchema(Tree)({"name": "root", "children": [{"name": "leaf"}]})
# Tree(name='root', children=[Tree(name='leaf', children=[])])
```

Recursion follows the data, with the same depth guard as `Self`: cyclic or
pathologically deep input raises a clean `Invalid`, never a `RecursionError`. A
recursive dataclass level does more work than a bare `Self` level, so it bottoms
out sooner; raise `sys.setrecursionlimit` if you genuinely need to go deeper.

## Discriminated unions

A field that is a union of dataclasses sharing a literal tag field becomes a
discriminated union: the tag picks the one branch to validate, rather than trying
each member in order. The branch is chosen by the tag, so a failure reports that
branch's error instead of a vague "matched no member".

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from probatio import DataclassSchema


@dataclass
class Circle:
    kind: Literal["circle"]
    radius: int


@dataclass
class Square:
    kind: Literal["square"]
    side: int


@dataclass
class Shape:
    shape: Circle | Square


DataclassSchema(Shape)({"shape": {"kind": "square", "side": 3}})
# Shape(shape=Square(kind='square', side=3))
```

The tag field must be a single-value `Literal` present on every member, with a
distinct value per member. Without one (or if a member is not a dataclass), the
union stays an ordinary "try each" `Any`. An unknown tag value falls back to
trying every member, so it still fails cleanly rather than silently.

## From a TypedDict

`TypedDictSchema` does the same for a `TypedDict`, sharing the annotation mapping
above. The difference is the output: a `TypedDict` is a plain dict at runtime, so
the validated mapping comes back unchanged, with nothing constructed. The schema
is generic in the `TypedDict`, so the result is typed as that `TypedDict`: your
type checker sees the real keys, at no runtime cost.

```python
from typing import TypedDict

from probatio import TypedDictSchema


class Config(TypedDict):
    port: int
    host: str


schema = TypedDictSchema(Config)
schema({"port": 8080, "host": "nas"})  # {'port': 8080, 'host': 'nas'}, typed as Config
```

A field in the TypedDict's required keys is required, the rest optional;
`total=False` and `Required`/`NotRequired` are honored, and the keys are closed
(an unknown key is rejected, like the default dict schema). Nested TypedDicts,
recursive ones, `additional_constraints`, and `Annotated` inline validators all
work the same as for a dataclass. Since the result is just the validated dict,
`result["port"]` access keeps working, so it layers types onto dict-shaped data
without changing how that data is used.

## Limits

A field with `init=False` is left out of the schema, since it is not a constructor
argument. The value is not coerced between container types: a list stays a list
even where the annotation says `tuple`.
