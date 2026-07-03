---
title: Sequence schemas
description: How list, tuple, and set schemas validate elements, and how to pin a sequence's shape and bounds.
---

A `list`, `tuple`, or `set` schema validates a sequence: the container type must
match, and every element must match one of the element schemas. This page covers
that rule and its one classic subtlety, error paths into sequences, fixed-shape
sequences, and nesting. It builds on
[the validation model](/guides/validation-model/); the mapping side lives in
[dict schemas and markers](/guides/dict-schemas-and-markers/).

## Every element, any alternative

The schemas inside the brackets are alternatives, not positions. `Schema([int,
str])` does not mean "an int, then a str"; it means "a list where every element
is an int _or_ a str", in any order and any number:

```python
from probatio import Schema

schema = Schema([int, str])

schema([1, "a", 2])  # [1, 'a', 2]
schema([])           # []
```

Each element tries the alternatives in order and the first match wins, like
`Any`. Because a match can transform, order matters here too: with
`[Coerce(int), str]` a numeric string becomes an int before `str` gets a look.

```python
from probatio import Schema, Coerce

Schema([Coerce(int), str])(["5", "a"])  # [5, 'a']
```

An element that matches no alternative fails, and the message names the
alternative tried last:

```python
from probatio import Schema, Invalid

try:
    Schema([int, str])([1, 2.5])
except Invalid as err:
    print(err)  # expected str at '[1]'
```

Validation returns a new list; the input is not mutated. And the container is
checked strictly: a tuple, a set, or a string (even though Python treats a
string as a sequence) is not a list.

```python
from probatio import Schema, Invalid

try:
    Schema([str])("abc")
except Invalid as err:
    print(err)  # expected a list
```

## The empty sequence schema

With no alternatives there is nothing an element could match, so `Schema([])`
accepts only the empty list:

```python
from probatio import Schema, Invalid

schema = Schema([])

schema([])  # []

try:
    schema([1])
except Invalid as err:
    print(err)  # invalid value at '[0]'
```

## Tuples and sets

A `tuple` or `set` schema follows the same rule with its own container type: the
input must be a tuple (or a set), every element must match one of the
alternatives, and the result is a new container of that type.

```python
from probatio import Schema

Schema((int,))((1, 2, 3))  # (1, 2, 3)
Schema({int})({1, 2})      # {1, 2}
```

The container types do not mix:

```python
from probatio import Schema, Invalid

try:
    Schema((int,))([1, 2])
except Invalid as err:
    print(err)  # expected a tuple
```

One caveat for sets: a failing element still gets an index in the error path,
but a set has no order, so that index reflects iteration order, not a position
you can count on.

## Error paths into sequences

A failing element is reported by its index. In `error.path` the index is an
integer, and the dotted rendering shows it as `[n]`:

```python
from probatio import Schema, Invalid

schema = Schema({"ports": [int]})

try:
    schema({"ports": [80, "nope"]})
except Invalid as err:
    print(err)       # expected int at 'ports[1]'
    print(err.path)  # ['ports', 1]
```

Like a dict schema, a list schema does not stop at the first failing element;
every failure lands in the `MultipleInvalid`:

```python
from probatio import Schema, MultipleInvalid

try:
    Schema([int])(["a", "b"])
except MultipleInvalid as err:
    for sub in err.errors:
        print(sub)
    # expected int at '[0]'
    # expected int at '[1]'
```

See [error handling](/guides/error-handling/) for paths and rendering in depth.

## Fixed shape and bounds

When the positions _do_ matter, reach for `ExactSequence`: it validates a
fixed-length sequence position by position.

```python
from probatio import Schema, ExactSequence, Invalid

pair = Schema(ExactSequence([str, int]))

pair(["a", 1])  # ['a', 1]

try:
    pair(["a"])
except Invalid as err:
    print(err)  # expected a sequence of 2 items
```

For bounds rather than positions, compose with `All`: the list schema validates
the elements, then `Length` (or `NonEmpty`) checks the size of the result.

```python
from probatio import Schema, All, Length

tags = Schema(All([str], Length(min=1, max=3)))

tags(["a", "b"])  # ['a', 'b']
```

An empty list then fails the bound, not the element rule:

<!-- verify: raises MultipleInvalid -->

```python
from probatio import Schema, All, NonEmpty

Schema(All([str], NonEmpty()))([])  # value must not be empty
```

## Nesting

A sequence schema is a value like any other, so lists nest inside dicts and
dicts inside lists, and error paths follow the nesting all the way down:

```python
from probatio import Schema, Required, Invalid

schema = Schema(
    {
        Required("servers"): [
            {Required("host"): str, "ports": [int]},
        ],
    }
)

schema({"servers": [{"host": "a", "ports": [80, 443]}]})
# {'servers': [{'host': 'a', 'ports': [80, 443]}]}

try:
    schema({"servers": [{"host": "a", "ports": [80, "x"]}]})
except Invalid as err:
    print(err)       # expected int at 'servers[0].ports[1]'
    print(err.path)  # ['servers', 0, 'ports', 1]
```

## Where to next

- [The validation model](/guides/validation-model/): the mental model behind
  every schema shape.
- [Dict schemas and markers](/guides/dict-schemas-and-markers/): the mapping
  side, with `Required`, defaults, and the extra-key policy.
- [Built-in validators](/guides/validators/): `Unique`, `Sorted`, `Unordered`,
  `EnsureList`, and the rest of the collection toolbox.
