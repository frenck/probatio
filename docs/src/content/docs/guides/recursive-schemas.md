---
title: Recursive schemas
description: Use Self to validate tree-shaped and nested-recursive data, with a depth guard that turns runaway nesting into a clean error.
---

Some data refers to its own shape. A comment has replies, and each reply is a
comment. A tree node has children, and each child is a node. You cannot write
that with a schema that names itself, because the schema is not finished being
defined yet. `Self` is the way out: inside a schema it means "validate against
the whole enclosing schema."

## Self refers to the enclosing schema

Import `Self` and use it as a value, the same way you would use any validator.
While the schema compiles, `Self` resolves to the schema being built, so it can
appear inside its own definition.

```python
from probatio import Schema, Self, Required, Optional

comment = Schema(
    {
        Required("text"): str,
        Optional("replies", default=list): [Self],
    }
)

comment({"text": "hi"})  # {'text': 'hi', 'replies': []}
```

`replies` is a list of `Self`, so every reply is validated against the comment
schema again, all the way down:

```python
from probatio import Schema, Self, Required, Optional

comment = Schema(
    {
        Required("text"): str,
        Optional("replies", default=list): [Self],
    }
)

data = {
    "text": "top",
    "replies": [
        {"text": "first"},
        {"text": "second", "replies": [{"text": "nested"}]},
    ],
}

comment(data)  # {'text': 'top', 'replies': [{'text': 'first', 'replies': []}, {'text': 'second', 'replies': [{'text': 'nested', 'replies': []}]}]}
```

Recursion follows the data. A finite structure validates fine, because each
level is just another call into the same compiled schema, up to the depth guard
described below. Real data is nowhere near that limit; if you knowingly need
deeper, raise `sys.setrecursionlimit`, since the guard scales with it.

## Self in a combinator

`Self` works as a direct mapping value or sequence element, like `[Self]` above
or `{"child": Self}`, and also as a branch of a combinator, so a key can recurse
or take an alternative. `Any(Self, "stop")` means "another level, or the literal
`stop`":

```python
from probatio import Schema, Self, Any

tree = Schema({"value": int, "next": Any(Self, "stop")})

tree({"value": 1, "next": {"value": 2, "next": "stop"}})
# {'value': 1, 'next': {'value': 2, 'next': 'stop'}}
```

`All(Self, ...)` works the same way, chaining the recursive check with another
schema. `Self` has to be a *direct* branch of the combinator, as above. Buried
inside a structure that is a branch (`Any({"inner": Self}, ...)`), it binds to that
structure rather than the whole schema, so keep it at the top of the branch.

The one place `Self` does not reach is a plain wrapping validator like `Maybe`,
which compiles its inner schema outside any combinator, so `Self` has nothing to
resolve to and it raises `SchemaError` at build time:

<!-- verify: raises SchemaError -->
```python
from probatio import Schema, Self, Maybe

Schema({"next": Maybe(Self)})  # SchemaError
```

For "this key or nothing," make the key `Optional` rather than wrapping `Self` in
`Maybe`:

```python
from probatio import Schema, Self, Required, Optional

linked = Schema(
    {
        Required("value"): int,
        Optional("next"): Self,
    }
)

linked({"value": 1, "next": {"value": 2}})  # {'value': 1, 'next': {'value': 2}}
```

## The depth guard

Recursive schemas meet a classic problem: cyclic data, or data nested so deep
that validating it blows the call stack. voluptuous lets that surface as a
`RecursionError`, which is an interpreter-level crash, not a validation result.
Probatio does not. It counts the `Self` recursion depth and, past a limit,
raises a clean `Invalid` that you catch alongside every other validation error.

The limit is a fraction of the interpreter's recursion limit, read live. So if
you genuinely have deep data, raising `sys.setrecursionlimit` scales the guard
with it; you are not boxed in by a hard-coded number. Keep that within reason,
though: past a point the operating system's own stack, not the recursion limit, is
the ceiling, so an extreme limit can still overflow.

Here is a node schema fed 5000 levels of nesting, built in a loop. It comes back
as a `MultipleInvalid`, the same type you already handle:

```python
from probatio import Schema, Self, Required, Optional, MultipleInvalid

node = Schema(
    {
        Required("value"): int,
        Optional("children", default=list): [Self],
    }
)

data = {"value": 0, "children": []}
cursor = data
for depth in range(1, 5000):
    child = {"value": depth, "children": []}
    cursor["children"] = [child]
    cursor = child

try:
    node(data)
except MultipleInvalid as err:
    print(err.errors[0].msg)  # data is nested too deeply for this recursive schema
```

The same guard catches cyclic data, where a structure points back at itself and
would otherwise recurse forever. Either way you get an `Invalid`, never a
`RecursionError`, so untrusted input cannot crash validation.

## Where to next

- [Dict schemas and markers](/guides/dict-schemas-and-markers/): `Required` and
  `Optional`, used heavily above.
- [Custom validators](/guides/custom-validators/): the callable contract `Self`
  builds on.
- [The validation model](/guides/validation-model/): how a schema compiles once
  and validates many times.
