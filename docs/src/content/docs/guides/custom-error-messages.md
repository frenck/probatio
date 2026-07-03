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
    #   "secret": false, "context": {"expected": "int"},
    #   "translation_key": "expected_type",
    #   "placeholders": {"expected": "int"}}]}
```

For translations, branch on `translation_key`. Every built-in error carries
one, naming the exact sentence, together with `placeholders`, the raw values
that sentence interpolates (the
[translation keys reference](/reference/translation-keys/) lists every key and
its English template). A lookup table maps sentences to your own language,
with the original message as the fallback for keys you have not translated:

```python
from probatio import Schema, MultipleInvalid

DUTCH = {
    "expected_type": "verwacht een waarde van type {expected}",
    "required": "deze optie is verplicht",
    "length_min": "lengte moet minimaal {min} zijn",
}

def render_dutch(error):
    template = DUTCH.get(error.translation_key)
    if template is None:
        return error.error_message
    return template.format(**error.placeholders)

schema = Schema({"port": int, "host": str})

try:
    schema({"port": "nope"})
except MultipleInvalid as err:
    print(render_dutch(err.errors[0]))  # verwacht een waarde van type int
```

One sentence, one key: where two validators produce the same wording (the dict
engine and the key groups both say "expected a mapping"), they share the key,
so one translation covers both. `code` still identifies the _kind_ of failure
and is the better branch point for behavior; `translation_key` identifies the
_sentence_ and is the branch point for wording.

### Suggestions compose on top

Some errors carry a "did you mean ...?" suggestion (an unknown key close to a
known one, for example; the [errors reference](/reference/errors/) marks which
classes). The suggestion is _not_ part of the base sentence: the key names the
sentence without it, and the close matches live on `context["candidates"]` as
a raw list. Probatio's own English output appends the fragment (its template
is the `did_you_mean` key), and `error_message` always includes it, so the
fallback path keeps suggestions for free. A renderer working from keys has to
compose the fragment itself, or the suggestion is silently dropped:

```python
from probatio import Schema, MultipleInvalid

DUTCH = {
    "not_a_valid_option": "geen geldige optie",
    "did_you_mean": ", bedoelde je {candidates}?",
}

def render_dutch(error):
    text = DUTCH.get(error.translation_key)
    if text is None:
        return error.error_message
    text = text.format(**error.placeholders)
    candidates = error.context.get("candidates")
    if candidates:
        joined = " of ".join(repr(name) for name in candidates)
        text += DUTCH["did_you_mean"].format(candidates=joined)
    return text

schema = Schema({"name": str, "email": str})

try:
    schema({"nmae": "app"})
except MultipleInvalid as err:
    print(render_dutch(err.errors[0]))  # geen geldige optie, bedoelde je 'name'?
```

The list joining (the "of"/"or" between candidates) is deliberately yours: it
is language, and the raw list gives you full control over it.

## Where to next

- [Custom validators](/guides/custom-validators/): the validator side of
  raising your own errors.
- [Error handling](/guides/error-handling/): paths, `MultipleInvalid`, and
  catching specific kinds.
- [Errors reference](/reference/errors/): every error class, its `code`, and
  the fields on `Invalid`.
- [Translation keys](/reference/translation-keys/): every key the built-ins
  emit, with its English template.
