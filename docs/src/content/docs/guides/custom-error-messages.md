---
title: Custom error messages
description: Override a validator's message with msg, raise your own Invalid carrying structured data, and render validation errors in your own words.
---

Probatio's default messages are written for humans, but they are still
Probatio's words. Sometimes you want your own: a schema author wants one rule
to explain itself better, an application wants to render failures in its own
tone, its own UI, or its own language. This guide covers both ends: changing
the message where the schema is defined, and ignoring the message entirely to
build your own output from the structured data every error carries.

## Override the message with msg

Most validators and markers accept a `msg` argument that replaces the default
message wholesale. This is the one-line tool for the spot where the default
wording does not fit your users:

```python
from probatio import Schema, Required, Range, MultipleInvalid

schema = Schema(
    {
        Required("port", msg="a port is required"): Range(
            min=1, max=65535, msg="not a valid port number"
        ),
    }
)

try:
    schema({})
except MultipleInvalid as err:
    print(err.errors[0].error_message)  # a port is required

try:
    schema({"port": 0})
except MultipleInvalid as err:
    print(err.errors[0])  # not a valid port number at 'port'
```

The replacement is complete: `msg` becomes the error's message, and the path is
still appended by `str(error)`. Everything else about the error is unchanged;
it keeps its class (`RangeInvalid` here) and its machine-readable `code`, so
code that branches on those keeps working no matter what the message says.

`msg` changes one validator's words. If you find yourself passing `msg` to
every validator in a schema to restyle all output, you are working at the
wrong end: skip to
[rendering errors your way](#render-errors-your-way) instead.

## Raise your own Invalid

A [custom validator](/guides/custom-validators/) rejects a value by raising
`Invalid` (or a subclass), and the message is yours from the start. Beyond the
message, `Invalid` accepts the structured fields, so your error carries data
for a consumer instead of only prose:

- `code`: a stable machine-readable identifier for this kind of failure.
- `context`: a dict of structured detail, such as the limit that was exceeded.
- `translation_key` and `placeholders`: a lookup key plus the values to
  interpolate, for a consumer that renders localized messages.

```python
from probatio import Schema, Invalid, MultipleInvalid

def quiet_hour(value):
    if not isinstance(value, int) or not 0 <= value <= 23:
        raise Invalid(
            "expected an hour between 0 and 23",
            code="quiet_hour",
            context={"min": 0, "max": 23},
            translation_key="quiet_hour_out_of_range",
            placeholders={"min": 0, "max": 23},
        )
    return value

schema = Schema({"start": quiet_hour})

try:
    schema({"start": 25})
except MultipleInvalid as err:
    error = err.errors[0]
    print(error)                  # expected an hour between 0 and 23 at 'start'
    print(error.code)             # quiet_hour
    print(error.translation_key)  # quiet_hour_out_of_range
    print(error.placeholders)     # {'min': 0, 'max': 23}
```

The message is the fallback for anyone who just prints the error; the
structured fields are the contract for anyone building their own output. Fill
both and your validator works in either world.

## Render errors your way

The rendered string is for humans and makes no stability promise; the
structured attributes are the API. A consumer that wants its own output (a CLI
with its own formatting, a web API returning JSON, a UI translating messages)
reads those attributes and never touches Probatio's strings.

The pattern: catch `MultipleInvalid`, walk `errors`, and build output from
`path`, `code`, `context`, and `error_message`. `render_path` renders a path
the same way `str(error)` does, so your output stays consistent with the
library's:

```python
from probatio import Schema, MultipleInvalid
from probatio.error import render_path

schema = Schema({"server": {"port": int, "host": str}})
data = {"server": {"port": "nope", "host": 42}}

try:
    schema(data)
except MultipleInvalid as err:
    for error in sorted(err.errors, key=lambda e: str(e.path)):
        where = render_path(error.path) or "the top level"
        print(f"Problem with option '{where}': {error.error_message}.")
    # Problem with option 'server.host': expected str.
    # Problem with option 'server.port': expected int.
```

For an API, `as_dict()` serializes the structured layer of every error in one
call, ready for a JSON response body:

```python
import json
from probatio import Schema, MultipleInvalid

schema = Schema({"port": int})

try:
    schema({"port": "nope"})
except MultipleInvalid as err:
    body = json.dumps(err.as_dict())
    print(body)
    # {"errors": [{"code": "type", "message": "expected int", "path": ["port"],
    #   "secret": false, "context": {"expected": "int"}, "translation_key": null,
    #   "placeholders": {}}]}
```

For translations, branch on `code`. Every built-in error carries one (the
[errors reference](/reference/errors/) lists them per class), so a lookup
table maps failures to your own language, with `context` filling the holes and
the original message as the fallback for codes you have not translated:

```python
from probatio import Schema, MultipleInvalid

DUTCH = {
    "type": "verwacht een waarde van type {expected}",
    "required": "deze optie is verplicht",
}

def render_dutch(error):
    template = DUTCH.get(error.code)
    if template is None:
        return error.error_message
    return template.format(**error.context)

schema = Schema({"port": int, "host": str})

try:
    schema({"port": "nope"})
except MultipleInvalid as err:
    print(render_dutch(err.errors[0]))  # verwacht een waarde van type int
```

Two honest notes on the current state. The built-ins fill `context` where
there is an obvious payload (a type error carries `expected`), but not yet
everywhere; a template that needs a value the context does not carry has to
fall back to the original message. And `translation_key` / `placeholders` are
populated only by errors you raise yourself; the built-ins leave them empty
for now, so `code` is the key to branch on today.

## Where to next

- [Custom validators](/guides/custom-validators/): the validator side of
  raising your own errors.
- [Error handling](/guides/error-handling/): paths, `MultipleInvalid`, and
  catching specific kinds.
- [Errors reference](/reference/errors/): every error class, its `code`, and
  the fields on `Invalid`.
