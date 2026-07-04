---
title: Troubleshooting
description: The common surprises when using Probatio, and how to deal with each.
---

A short list of the things that trip people up, with the symptom first and the
fix second. Most of them are points where Probatio matches voluptuous exactly,
so the fix is the same one you would reach for there.

## My test asserting the voluptuous error string broke

The number-one migration symptom. Probatio renders errors with a dotted path
(`expected int at 'server.port'`) where voluptuous rendered
`expected int for dictionary value @ data['server']['port']`. That is a
deliberate deviation, listed on the
[compatibility matrix](/reference/compatibility-matrix/), not a bug to report.

Do not assert on `str(err)`. Assert on the structured attributes, which match
voluptuous exactly: `path`, `error_message` (the bare message without the
path), and the exception class.

```python
from probatio import Schema, MultipleInvalid

schema = Schema({"server": {"port": int}})

try:
    schema({"server": {"port": "nope"}})
except MultipleInvalid as err:
    print(err)                          # expected int at 'server.port'
    print(err.errors[0].path)           # ['server', 'port']
    print(err.errors[0].error_message)  # expected int
```

## My extra keys were rejected

A key the schema does not name is rejected by default, matching voluptuous.
The first hour with a real payload usually surfaces this. Allow extras
schema-wide with `extra=ALLOW_EXTRA`, or per key with the `Extra` catch-all
(`{Extra: object}`), which the
[dict schemas guide](/guides/dict-schemas-and-markers/) covers in full.

```python
from probatio import Schema, Invalid, ALLOW_EXTRA

strict = Schema({"name": str})

try:
    strict({"name": "app", "debug": True})
except Invalid as err:
    print(err)  # not a valid option at 'debug'

relaxed = Schema({"name": str}, extra=ALLOW_EXTRA)
relaxed({"name": "app", "debug": True})  # {'name': 'app', 'debug': True}
```

## I caught `Invalid` but got a `MultipleInvalid`

A `Schema` call always wraps its failures in `MultipleInvalid`, even when there
is only one. `MultipleInvalid` is itself an `Invalid`, so `except Invalid`
catches it; the individual failures are in `.errors`.

```python
from probatio import Schema, Invalid, MultipleInvalid

schema = Schema(int)

try:
    schema("nope")
except Invalid as err:           # catches MultipleInvalid too
    print(type(err).__name__)    # MultipleInvalid
    print(err.errors[0].msg)     # expected int
```

To branch on a specific kind of failure (like `RangeInvalid`), inspect
`err.errors[0]`, not the `MultipleInvalid` itself.

## `SchemaError` from a wrapped `Self`

`Self` works as a direct mapping value or list element, and as a branch of a
combinator (`Any(Self, "stop")`, `All(Self, ...)`). It does not work inside a
plain wrapping validator like `Maybe`, which compiles it outside the recursive
context and raises:

<!-- verify: raises SchemaError -->

```python
from probatio import Schema, Maybe, Self

Schema({"next": Maybe(Self)})  # SchemaError
```

For an optional recursive key, mark the key `Optional`, do not wrap the value:

```python
from probatio import Schema, Optional, Required, Self

schema = Schema({Required("value"): int, Optional("next"): Self})

schema({"value": 1, "next": {"value": 2}})  # {'value': 1, 'next': {'value': 2}}
```

## My custom validator's `ValueError` message has a `not a valid value:` prefix

A plain `ValueError` from a callable is kept, but reported as
`not a valid value: <your message>`. The reason is preserved; the prefix is not.
Raise `Invalid` with your own message to control it exactly, with no prefix:

```python
from probatio import Schema, Invalid

def even(value):
    if value % 2:
        raise Invalid("must be even")
    return value

try:
    Schema(even)(3)
except Invalid as err:
    print(err.errors[0].msg)  # must be even
```

## `Remove` dropped my key, but a bad value still errored

`Remove` validates the value before dropping it. Only a value that validates is
removed; a value that fails its schema is reported, the same as any other key.
That is voluptuous behavior, not a Probatio quirk.

```python
from probatio import Schema, Remove

schema = Schema({"keep": int, Remove("drop"): str})

schema({"keep": 1, "drop": "x"})  # {'keep': 1}
```

## `data is nested too deeply for this recursive schema`

A recursive `Self` schema has a depth guard, so cyclic or pathologically deep
data raises a clean `Invalid` instead of crashing the interpreter with a
`RecursionError`. The limit scales with the interpreter's recursion limit. Real
data is nowhere near it; if you knowingly need deeper, raise the interpreter's
recursion limit with `sys.setrecursionlimit()` before validating.

## A difference from voluptuous that is not documented

Probatio targets behavioral compatibility, and the handful of intentional
differences are listed on the [compatibility page](/getting-started/compatibility/)
and the [compatibility matrix](/reference/compatibility-matrix/). Anything else is
a bug; please [open an issue](https://github.com/frenck/probatio/issues) with a
small reproduction.
