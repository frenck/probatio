---
title: The probatio decorator
description: Validate a function's arguments straight from its type annotations, with coercion, per-parameter rules, optional return checking, and async support.
---

`@probatio` validates a callable's arguments against its type annotations before
the body runs. It reads the signature the same way `DataclassSchema` reads a
dataclass: each annotated parameter becomes a validator, and the body receives the
validated (and coerced) value.

It is the annotation-driven companion to [`validate`](/guides/custom-validators/#validating-function-arguments),
the voluptuous drop-in where you name a schema per argument by hand. Reach for
`@probatio` when your parameters are already typed and you want that typing
enforced at the boundary.

## The basics

Annotate the parameters and decorate. Nothing else is required.

```python
from probatio import probatio


@probatio
def area(width: int, height: int) -> int:
    return width * height


area(3, 4)  # 12
```

A parameter that fails its type raises `MultipleInvalid` before the body runs,
naming the parameter. It is the same exception a `Schema` raises, so one
`except` covers both.

```python
from probatio import probatio, MultipleInvalid


@probatio
def area(width: int, height: int) -> int:
    return width * height


try:
    area("wide", 4)
except MultipleInvalid as err:
    print(err)  # expected int at 'width'
```

An unannotated parameter is left alone, so `self` and `cls` need no special
handling and the decorator drops straight onto a method. A default the caller
omits is also left alone: it is not validated or coerced, the body receives it
exactly as declared, so write an already-valid default.

```python
from typing import Annotated

from probatio import probatio, Range


class Canvas:
    @probatio
    def scale(self, factor: Annotated[int, Range(min=1)]) -> int:
        return factor * 2


Canvas().scale(3)  # 6
```

## Coercion reaches the body

An annotation drives the same engine the schema builders use, so a coercing
annotation converts the value and the body receives the converted one. The
annotation says what the parameter _is_, and the type confirms what the coercer
produced.

```python
from typing import Annotated

from probatio import probatio, Coerce


@probatio
def repeat(text: str, times: Annotated[int, Coerce(int)]) -> str:
    return text * times


repeat("ab", "3")  # 'ababab'
```

The full annotation mapping is the one
[dataclasses use](/guides/dataclasses/#annotations-drive-the-validators): unions
become `Any`, `X | None` becomes `Maybe`, and a parameter typed as a dataclass
validates a mapping into an instance.

```python
from dataclasses import dataclass

from probatio import probatio


@dataclass
class Point:
    x: int
    y: int


@probatio
def distance(point: Point) -> int:
    return point.x + point.y


distance({"x": 3, "y": 4})  # 7
```

## Extra rules per parameter

The annotation gives you the type check. For anything more (a length, a range, a
pattern), pass a `{parameter: validator}` map as the first argument. It runs
after the inferred type. (If you know `DataclassSchema`, this is its
`additional_constraints` in decorator form.)

```python
from probatio import probatio, Length


@probatio({"name": Length(min=2)})
def greet(name: str) -> str:
    return f"hi {name}"


greet("ada")  # 'hi ada'
```

A constraint that names no parameter, or names a `*args`/`**kwargs`, is refused
when the function is decorated, so a typo fails loudly instead of silently doing
nothing. The packed parameters themselves are skipped entirely: an annotation on
`*args` or `**kwargs` names no single value to validate, so it is ignored and
the values pass through unchecked.

## Validating the return value

Return validation is off by default. Opt in with `returns`: pass `True` to check
the result against the `-> R` annotation, or pass a schema to check against it
directly.

```python
from typing import Annotated

from probatio import probatio, Range


@probatio(returns=True)
def clamp(value: int) -> Annotated[int, Range(min=0)]:
    return value


clamp(5)  # 5
```

A map and a return schema combine, so one decorator can cover both ends:

```python
from probatio import probatio, Length


@probatio({"name": Length(min=2)}, returns=str)
def shout(name: str) -> str:
    return name.upper()


shout("ada")  # 'ADA'
```

## Async functions

A coroutine function is validated the same way. The arguments are checked before
the call, and the result schema (if any) runs on the awaited value.

```python
import asyncio
from typing import Annotated

from probatio import probatio, Coerce


@probatio
async def fetch(user_id: Annotated[int, Coerce(int)]) -> int:
    return user_id + 1


asyncio.run(fetch("41"))  # 42
```

## Skipping validation

`@probatio` builds on `functools.wraps`, so the undecorated callable stays
reachable through the standard `__wrapped__` attribute. Call it when the input is
already trusted and you want to skip the check.

```python
from typing import Annotated

from probatio import probatio, Coerce


@probatio
def widen(value: Annotated[int, Coerce(int)]) -> int:
    return value


widen("5")             # 5, validated and coerced
widen.__wrapped__("5") # '5', straight through, no validation
```

That escape hatch frames when not to use the decorator at all. Every decorated
call pays for validation, so decorate boundaries (a request handler, a service
entry point, the public surface of a library), not hot inner functions that run
in tight loops on values already validated one frame up. When a single hot call
site sits behind an otherwise useful boundary check, `__wrapped__` skips the
cost for just that site. See [Performance](/reference/performance/) for the
cost model.

## Where to next

- [`validate`](/guides/custom-validators/#validating-function-arguments): the
  voluptuous-compatible decorator with hand-named schemas.
- [Schemas from dataclasses](/guides/dataclasses/): the same annotation engine,
  building an instance from a mapping.
- [Built-ins by role](/reference/builtins-by-role/): the validators and coercers
  to reach for in an annotation.
