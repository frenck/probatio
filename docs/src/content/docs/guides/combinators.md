---
title: Combinators
description: Build validators from other validators with All, Any, Union, and SomeOf.
---

Combinators take other validators and combine them. They are how you express
"all of these", "any of these", or "enough of these", and they nest freely
inside dict and list schemas.

## All: every validator, in order

`All` runs its validators left to right, feeding each result into the next. It
is both an "and" and a pipeline: the value is transformed as it passes through.

```python
from probatio import Schema, All, Coerce, Range

schema = Schema(All(Coerce(int), Range(min=1, max=65535)))

schema("443")  # 443
```

Order matters. `All(Coerce(int), Range(min=0))` coerces the string to an int and
then range-checks it; swapping them would range-check a string. `And` is an alias
for `All`.

## Any: the first that matches

`Any` returns the result of the first validator that accepts the value, and fails
only when none do.

```python
from probatio import Schema, Any

schema = Schema(Any(int, str))

schema(5)    # 5
schema("a")  # 'a'
```

When nothing matches and every branch names something concrete (a type, `None`,
or a literal), `Any` lists the alternatives, so the message tells you what was
expected:

```python
from probatio import Schema, Any, Invalid

try:
    Schema(Any(int, str, None))(1.5)
except Invalid as err:
    print(err)  # expected int or str or None
```

This is a Probatio improvement over voluptuous, which reports only the first
branch (see [issue #412](https://github.com/alecthomas/voluptuous/issues/412)).
When a branch is an arbitrary validator (a `Range`, a callable) there is no clean
label, so `Any` falls back to the error from the branch that got furthest (the
deepest path), which is usually the most useful one. Pass `msg` to replace the
message with your own:

```python
from probatio import Schema, Any, Invalid

schema = Schema(Any("red", "green", "blue", msg="not a known color"))

try:
    schema("mauve")
except Invalid as err:
    print(err)  # not a known color
```

`Or` is an alias for `Any`.

## Union and Switch: pick a branch

`Union` is like `Any`, but a `discriminant` can narrow which branches to try
instead of attempting every one. The discriminant is called as
`discriminant(value, validators)` and returns the subset to try, which is how you
validate a tagged union by its tag:

```python
from probatio import Schema, Union

def by_type(value, alternatives):
    return [a for a in alternatives if a["type"] == value.get("type")]

schema = Schema(
    Union(
        {"type": "point", "x": int, "y": int},
        {"type": "label", "text": str},
        discriminant=by_type,
    )
)

schema({"type": "point", "x": 1, "y": 2})  # {'type': 'point', 'x': 1, 'y': 2}
```

The win is the error message: with a discriminant, a bad `point` reports the
problem with its own fields, rather than "matched none of the alternatives."
Note that the discriminant sees the raw input, and the one above assumes a
mapping; a production discriminant should also handle a non-mapping value.
`Switch` is an alias for `Union`.

## SomeOf: enough of them

`SomeOf` requires the value to pass a bounded number of its validators. Give at
least one of `min_valid` and `max_valid`.

```python
from probatio import Schema, SomeOf, Range

schema = Schema(SomeOf(min_valid=2, validators=[Range(1, 5), int, 3]))

schema(3)  # 3
```

Too few passes raises [`NotEnoughValid`](/reference/errors/); too many raises
[`TooManyValid`](/reference/errors/). Like `All`, each validator's output feeds
the next.

## Combinators nest

Combinators are validators, so they go anywhere a validator goes: as a dict
value, a list element, or inside another combinator.

```python
from probatio import Schema, All, Any, Coerce, Range, Required

schema = Schema(
    {
        Required("level"): Any("low", "high", All(Coerce(int), Range(min=0, max=10))),
    }
)

schema({"level": "high"})  # {'level': 'high'}
schema({"level": "7"})     # {'level': 7}
```

## Passing options through

`All`, `Any`, `Union`, and `SomeOf` accept `required=True`, which propagates into
any mapping sub-schemas they wrap (so the nested dicts treat their keys as
required). Other keyword arguments are accepted and ignored, matching voluptuous.
