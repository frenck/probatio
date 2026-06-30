---
title: Error handling
description: Invalid, MultipleInvalid, error paths, humanized messages, and the structured layer.
---

When data does not match, Probatio raises. This page covers what it raises, how
to read the path to the offending value, how to collect every error at once, and
how to turn an error into something a person or a machine can use.

## One base: Invalid

Everything Probatio raises for bad data is an `Invalid` or a subclass. Catching
`Invalid` catches them all, so you rarely need to name a specific subclass unless
you want to branch on the kind of failure.

```python
from probatio import Schema, Invalid

schema = Schema(int)

try:
    schema("nope")
except Invalid as err:
    print(err)  # expected int
```

A broken schema _definition_ is different: that raises `SchemaError`, because it
is a programming mistake, not bad input. The two never overlap.

## The path to the value

An error knows where in the data it happened. `str(error)` appends that path, and
`error.path` is the list of keys and indices to walk:

```python
from probatio import Schema, Invalid

schema = Schema({"server": {"ports": [int]}})

try:
    schema({"server": {"ports": [80, "nope"]}})
except Invalid as err:
    print(err)        # expected int @ data['server']['ports'][1]
    print(err.path)   # ['server', 'ports', 1]
```

`error.path` is the machine-readable form; follow it into the original data to
find the exact value that failed.

## Many errors at once

A schema does not stop at the first problem. It collects every failure into a
`MultipleInvalid`, which is itself an `Invalid`. Its `errors` list holds the
individual failures:

```python
from probatio import Schema, MultipleInvalid

schema = Schema({"a": int, "b": int})

try:
    schema({"a": "x", "b": "y"})
except MultipleInvalid as err:
    print(len(err.errors))  # 2
    for sub in err.errors:
        print(sub.path)     # ['a'] then ['b']
```

For convenience, a `MultipleInvalid` proxies its first error, so `error.msg` and
`error.path` read the first failure without reaching into `errors`.

## Readable messages

`humanize_error` renders an error against the data, naming the value that failed.
It lives in `probatio.humanize`:

```python
from probatio import Schema, Invalid
from probatio.humanize import humanize_error

data = {"port": "nope"}
schema = Schema({"port": int})

try:
    schema(data)
except Invalid as err:
    print(humanize_error(data, err))  # expected int for dictionary value @ data['port']. Got 'nope'
```

`validate_with_humanized_errors(data, schema)` (also in `probatio.humanize`) does
both steps: it validates and, on failure, raises `Error` carrying the humanized
message.

## Catching a specific kind

The subclasses let you branch on what went wrong. They mirror voluptuous, so
`TypeInvalid`, `RangeInvalid`, `LengthInvalid`, `CoerceInvalid`, and the rest are
all there. A schema always raises `MultipleInvalid` at the top, so you branch on
the individual errors inside it:

```python
from probatio import Schema, Range, MultipleInvalid
from probatio.error import RangeInvalid

schema = Schema(Range(min=0, max=10))

try:
    schema(99)
except MultipleInvalid as err:
    first = err.errors[0]
    print(isinstance(first, RangeInvalid))  # True
    print(first.error_message)              # value must be at most 10
```

`error_message` is the bare message without the path; `msg` is the same text.
The [errors reference](/reference/errors/) lists the whole hierarchy.

## The structured layer

On top of the voluptuous-compatible fields, every error carries a structured,
machine-readable layer: a stable `code` and a `context` dict, both filled in by
the built-in validators, plus `translation_key` and `placeholders` slots for
localization. The built-ins leave those two empty; they are there for code that
raises its own `Invalid` to carry localization data through. `as_dict()`
serializes the whole layer, which is handy for an API that returns validation
errors as JSON.

```python
from probatio import Schema, Invalid

schema = Schema({"port": int})

try:
    schema({"port": "nope"})
except Invalid as err:
    first = err.errors[0]
    print(first.code)               # type
    print(first.as_dict()["path"])  # ['port']
```

The legacy fields (`msg`, `path`, `error_message`) are untouched by this layer,
so nothing about the voluptuous-compatible behavior changes; the structured data
is purely additive.
