---
title: Schemas from dataclasses
description: Generate a validating schema straight from a dataclass, with the field annotations driving the validators.
---

If your data already has a dataclass, you should not have to write the schema
twice. `DataclassSchema` reads a dataclass's fields and builds a schema from the
annotations: it validates a plain mapping and hands you back a constructed
instance. This is the same idea as voluptuous [PR #533](https://github.com/alecthomas/voluptuous/pull/533), with a richer type
mapping (Probatio descends into element types instead of stopping at the
container).

The same engine reads a `TypedDict`. If your shape is a dict rather than a
constructed object, see [Schemas from TypedDicts](/guides/typeddict/); this page is
about dataclasses.

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


DataclassSchema(User)({})  # required key not provided at 'name'
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

| Annotation                 | Schema                               |
| -------------------------- | ------------------------------------ |
| `int`, `str`, a plain type | the type (an `isinstance` check)     |
| `list[T]`                  | `[T]` (element type validated)       |
| `set[T]`, `frozenset[T]`   | `{T}` / `frozenset([T])`             |
| `dict[K, V]`               | `{K: V}` (key and value validated)   |
| `tuple[X, Y]`              | `ExactSequence([X, Y])` (positional) |
| `tuple[X, ...]`            | a homogeneous sequence of `X`        |
| `X \| None`                | `Maybe(X)`                           |
| `X \| Y`                   | `Any(X, Y)`                          |
| `Literal["a", "b"]`        | `In(["a", "b"])`                     |
| a nested dataclass         | its own generated schema             |
| `Any`                      | accepts any value                    |

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

The same rule can live on the field itself with `Annotated`, keeping the
constraint next to the field instead of in a separate map. The rules:

- The first argument is the type; every callable after it is applied as a
  validator, in order.
- The type is checked on the result, not the raw input, so the annotation says
  what the field _is_: a coercer runs first and the type confirms what it
  produced.
- It composes inside containers: `list[Annotated[int, Range(min=1)]]` checks
  every element.
- Metadata that is not callable is left alone, so an `Annotated` value you
  share with another tool passes through untouched.

That second rule is what keeps a coerced field honestly typed.
`Annotated[datetime, AsDatetime()]` accepts the string, parses it, and confirms
a `datetime`, instead of annotating `str` and hiding the real type in the
validator. To find the right callable to drop in here, whether it checks the
value or transforms it, see [Built-ins by role](/reference/builtins-by-role/).

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

Here is that coercer-plus-type pairing in practice:

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from probatio import DataclassSchema, AsDatetime


@dataclass
class Event:
    when: Annotated[datetime, AsDatetime()]


DataclassSchema(Event)({"when": "2020-01-01T12:00"})
# Event(when=datetime.datetime(2020, 1, 1, 12, 0))
```

A `NewType` is followed to the type it wraps, so a field typed
`UserId = NewType("UserId", int)` validates as an `int`.

## Key facets on fields

A plain type says what a field _is_. To give a field a key facet, redact it,
accept it under other names, forbid it, group it, add `Key` to its `Annotated`
metadata. It sits next to any value validators; the two do not interfere.

```python
from dataclasses import dataclass
from typing import Annotated

from probatio import DataclassSchema, Key, Length


@dataclass
class Account:
    name: str
    password: Annotated[str, Key(secret=True), Length(min=8)]  # redacted, length-checked
    user_name: Annotated[str, Key(alias=["user-name", "userName"])] = ""  # accept aliases
    is_admin: Annotated[bool, Key(forbidden=True)] = False  # reject if the caller sends it


schema = DataclassSchema(Account)
schema({"name": "a", "password": "secret123", "user-name": "frenck"})
# Account(name='a', password='secret123', user_name='frenck', is_admin=False)
```

`Key(secret=True)` redacts the field's value in validation errors. It shows up
when an error renders the offending value: the message stays useful, the secret
does not leak.

```python
from probatio import MultipleInvalid
from probatio.humanize import humanize_error

data = {"name": "a", "password": "short", "user-name": "frenck"}
try:
    schema(data)
except MultipleInvalid as err:
    print(humanize_error(data, err))
# length of value must be at least 8 at 'password'. Got <redacted>
```

`Key(alias=[...])` accepts the field under alternate input names (a bare string
works for one), emitting it under the field name; `accept_canonical=False` makes it
a strict rename. `Key(inclusive="grp")` / `Key(exclusive="grp")` group fields the
way the [dict form](/guides/dict-schemas-and-markers/) does. `Key(required=True)`
(or `required=False`) overrides the presence the field's default would imply.
`required=False` marks a field optional, so on a dataclass it still needs a
default for the constructor to fall back on; without one it raises `SchemaError`.

`Key` is a field-only spec; a plain dict schema keeps using the markers directly
(`{Secret("password"): str}`, `{Alias("user_name", "user-name"): str}`). It works
the same on a [TypedDict](/guides/typeddict/).

`forbidden` and `remove` make a key contribute nothing to the result, so on a
dataclass (whose constructor needs a value for every field) such a field must have
a default; without one it raises `SchemaError`. A TypedDict constructs nothing, so
there they need no default.

One boundary to know, on which defaults pass through the schema:

- An `optional` field, or a selected `exclusive` member, carries its default
  through the schema, so it is validated and coerced like input.
- A field the schema keeps out of the input (a `forbidden` field, a `remove`
  field, an unselected `exclusive` member) takes the dataclass's own default
  exactly as declared: no validation, no coercion.

The schema validates input, and that second group's values are not input, so
write an already-typed default for such a field; a wrong-typed one is a type
error your type-checker flags. See
[ADR-013](https://github.com/frenck/probatio/blob/main/adr/013-markers-on-annotated-fields.md)
for the model.

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

## Coercing a field's type

A field annotated with `datetime` validates by `isinstance`, so a string from
JSON or YAML is rejected. That is the safe default: probatio validates, it does
not silently transform. When you do want a field coerced, say so on the field with
an `Annotated` hint, and the coercion is scoped to exactly that field:

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from probatio import DataclassSchema, Coerce


@dataclass
class Event:
    when: Annotated[datetime, Coerce(datetime.fromisoformat)]


DataclassSchema(Event)({"when": "2020-01-01T12:00"})  # Event(when=datetime(2020, 1, 1, 12, 0))
```

The `Coerce` runs first and the `datetime` type confirms the result, so the field
stays honestly typed (see the [annotation mapping
table](#annotations-drive-the-validators)). This works the same way in a nested
dataclass field, and `additional_constraints` still layers on top. The
hand-written `Schema(datetime)` path is never affected.

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
out sooner; raise the limit with `sys.setrecursionlimit()` if you genuinely need
to go deeper.

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

## Speed

A `DataclassSchema` is the clearest case for the compiled engine. When a schema
compiles, it fuses field validation and object construction into a single generated
function with no intermediate dict, which is most of why a hot dataclass schema
validates several times faster than the interpreted one and lands close to a pure
deserializer like mashumaro while still checking every field. This happens on its
own once the schema proves hot; see [Compiled schemas](/guides/compiled-schemas/)
to opt in eagerly or read the trade-offs.

## Trusted construction, without validation

Probatio is a validation library, but there are spots where validation is not
needed: the input is your own data round-tripping back in, or it was already
validated upstream. For those, `DataclassSchema.construct` builds the instance from
trusted data and skips validation entirely.

```python
from dataclasses import dataclass

from probatio import DataclassSchema


@dataclass
class Point:
    x: int
    y: int


@dataclass
class Line:
    start: Point
    end: Point


schema = DataclassSchema(Line)
# Trusted input: build straight through, no type checks, no coercion.
schema.construct({"start": {"x": 0, "y": 0}, "end": {"x": 3, "y": 4}})
# Line(start=Point(x=0, y=0), end=Point(x=3, y=4))
```

It reads each field straight from the dict, recursing into nested dataclasses, lists
of them, `Optional` fields, and a single dataclass inside a union (like
`Comment | str`), and filling defaults, then constructs. With no checks it is faster
than validating, fast enough to beat dedicated deserializers like mashumaro on the
[performance page](/reference/performance/), because it is a purpose-built
constructor and pure Python.

The catch is in the name: it trusts you. A wrong type lands in the instance unchecked,
and it does not convert: a field typed `datetime` will hold whatever the dict held
(a string stays a string), where validation would coerce it. For input that still
needs decoding, validate.

:::caution
Use `construct` only for input you already know is correct. For anything from
outside your boundary, call the schema (`schema(data)`), which validates. A shape
the fast path does not handle (a recursive dataclass, for instance) falls back to
validating, so `construct` always returns a correct instance for trusted input,
just not always faster. `TypedDictSchema.construct` does the same, returning the
trusted dict unchanged.
:::

## Limits

A field with `init=False` is left out of the schema, since it is not a constructor
argument; it keeps whatever its default or `__post_init__` gives it. An `InitVar`
goes the other way: it is a constructor argument, so it becomes a schema key,
validated against its annotation like any field, and it feeds `__post_init__` as
usual.

```python
from dataclasses import InitVar, dataclass, field

from probatio import DataclassSchema


@dataclass
class Rect:
    width: int
    height: int
    scale: InitVar[int] = 1
    area: int = field(init=False, default=0)

    def __post_init__(self, scale: int) -> None:
        self.area = self.width * self.height * scale


DataclassSchema(Rect)({"width": 2, "height": 3, "scale": 10})
# Rect(width=2, height=3, area=60)
```

The value is not coerced between container types: a list stays a list even where
the annotation says `tuple`.
