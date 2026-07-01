---
title: Dict schemas and markers
description: Required and optional keys, defaults, extra-key policy, and key groups.
---

A `dict` schema validates a mapping: each key in the schema describes a key that
may appear in the data, and its value is the schema for that key's value. Markers
are special keys that carry intent, such as "this key is required" or "fill this
in when it is absent."

## Required and optional keys

By default a literal key is allowed but not required, and an unknown key is
rejected. `Required` and `Optional` make the intent explicit:

```python
from probatio import Schema, Required, Optional

schema = Schema(
    {
        Required("name"): str,
        Optional("nickname"): str,
    }
)

schema({"name": "Frenck"})  # {'name': 'Frenck'}
```

Leaving out a required key fails:

```python
from probatio import Schema, Required, Invalid

schema = Schema({Required("name"): str})

try:
    schema({})
except Invalid as err:
    print(err)  # required key not provided @ data['name']
```

A marker compares and hashes by its key, so `Required("name")` and `"name"` are
the same dict key. You annotate a key without changing how it is matched.

## Defaults

`Optional` (and `Required`) take a `default`. When the key is absent, the default
fills it in. A callable default is called each time, which is how you get a fresh
list or dict per validation rather than a shared one:

```python
from probatio import Schema, Optional

schema = Schema(
    {
        Optional("port", default=8080): int,
        Optional("tags", default=list): [str],
    }
)

schema({})  # {'port': 8080, 'tags': []}
```

A callable default may return `UNDEFINED` to decline: the key is then left absent,
exactly as if it had no default. This is useful for a default that depends on
runtime context (the active platform, which plugins are loaded), where sometimes
no value should be supplied:

```python
from probatio import Schema, Optional, UNDEFINED

context = {"fast": True}


def speed_default():
    return 80 if context["fast"] else UNDEFINED


schema = Schema({Optional("speed", default=speed_default): int})

print(schema({}))  # {'speed': 80}
context["fast"] = False
print(schema({}))  # {}
```

For a `Required` key a declining default leaves the key missing, so it is reported
as a missing required key.

## The extra-key policy

What happens to a key the schema does not mention is controlled by the `extra`
argument to `Schema`. By default unknown keys are rejected:

```python
from probatio import Schema, Invalid

schema = Schema({"name": str})

try:
    schema({"name": "app", "debug": True})
except Invalid as err:
    print(err)  # not a valid option @ data['debug']
```

When a rejected key looks like a misspelling of one the schema knows, the error
points at the closest matches and carries them on the error as
`ExtraKeysInvalid.candidates`, so a tool can show "did you mean ...?" without
recomputing it:

```python
from probatio import Schema, Invalid

schema = Schema({"name": str, "email": str})

try:
    schema({"nmae": "app"})
except Invalid as err:
    error = err.errors[0]
    print(error)            # not a valid option, did you mean 'name'? @ data['nmae']
    print(error.candidates)  # ['name']
```

The three policies are `PREVENT_EXTRA` (the default), `ALLOW_EXTRA` (keep unknown
keys untouched), and `REMOVE_EXTRA` (drop them from the result):

```python
from probatio import Schema, ALLOW_EXTRA, REMOVE_EXTRA

Schema({"name": str}, extra=ALLOW_EXTRA)({"name": "app", "x": 1})   # {'name': 'app', 'x': 1}
Schema({"name": str}, extra=REMOVE_EXTRA)({"name": "app", "x": 1})  # {'name': 'app'}
```

For finer control than a whole-schema policy, `Extra` is a catch-all key:
`{Extra: validator}` validates every otherwise-unmatched key against `validator`.
Use `{Extra: object}` to allow anything.

```python
from probatio import Schema, Extra

schema = Schema({"name": str, Extra: int})

schema({"name": "app", "a": 1, "b": 2})  # {'name': 'app', 'a': 1, 'b': 2}
```

## Removing keys

`Remove` drops matching keys from the output. The value is still validated; only
a value that validates is dropped, so `Remove` does not hide a type error.

```python
from probatio import Schema, Remove

schema = Schema({"keep": int, Remove("drop"): str})

schema({"keep": 1, "drop": "gone"})  # {'keep': 1}
```

## Forbidding keys

`Forbidden` is the inverse of `Required`: the key must _not_ be present. If it
appears, validation fails with "key not allowed". The mapped value is never
looked at, so the idiom is to map it to `object`.

```python
from probatio import Schema, Required, Forbidden

schema = Schema({Required("id"): int, Forbidden("password"): object})

schema({"id": 1})  # {'id': 1}
```

A present forbidden key fails:

<!-- verify: raises MultipleInvalid -->

```python
from probatio import Schema, Forbidden

schema = Schema({Forbidden("password"): object})

schema({"password": "secret"})  # key not allowed @ data['password']
```

It composes with `extend`, so a base schema can be tightened to forbid a key it
used to allow.

## Aliasing keys

`Alias` accepts a value under more than one name and stores it under a single
canonical name. It is the answer when a source spells a key differently from your
target: a kebab-case config key for a snake_case field, or a reserved word like
`class`. The first argument is the canonical name (used in the output), and the
rest are aliases accepted in the input.

```python
from probatio import Schema, Alias

schema = Schema({Alias("user_name", "user-name", "userName"): str})

schema({"user-name": "ada"})  # {'user_name': 'ada'}
schema({"userName": "ada"})   # {'user_name': 'ada'}
schema({"user_name": "ada"})  # {'user_name': 'ada'}
```

The canonical name is accepted as an input name too, and leads the search, so it
wins when it and an alias both appear. Among aliases, the first one in the order
you listed wins. Pass `accept_canonical=False` for a strict rename that accepts
only the aliases:

```python
from probatio import Schema, Alias

schema = Schema({Alias("name", "alias", accept_canonical=False): str})

schema({"alias": "ada"})  # {'name': 'ada'}
schema({"name": "ada"})   # {} (the canonical name is not an input name here)
```

An aliased key is optional by default (its `default` applies when absent under
every name); pass `required=True` to demand one of its names. An alias that names
another key in the schema, or that two keys share, is rejected at build time, so
an ambiguous schema fails fast rather than at validation.

## Redacting secret values

`Secret` marks a key whose value is a credential, so a validation failure under it
is redacted: the error still reports the path and the reason, but shows
`<redacted>` instead of the offending value (in `Invalid` rendering and
`humanize_error`). The value passes through validation unchanged; `Secret` marks
the key, it does not transform the value.

```python
from probatio import Schema, Required, Secret
from probatio.humanize import humanize_error
from probatio.error import MultipleInvalid

schema = Schema({Required(Secret("password")): int})
data = {"password": "hunter2"}
try:
    schema(data)
except MultipleInvalid as err:
    print(humanize_error(data, err))
    # expected int for dictionary value @ data['password']. Got <redacted>
```

Secrecy is an independent facet, so it composes with the presence markers by
nesting: `Optional(Secret("password"))` (equivalently `Secret(Optional("password"))`)
is an optional, redacted key. Order does not matter. The marker names a concrete
key, so `Secret(str)` (a type key) is refused at build time.

Redaction covers validation errors only, the output a schema controls, not values
you log yourself elsewhere. The `secret` flag also rides on each error
(`err.errors[0].secret`, and in `as_dict()`), so a consumer building its own output
can redact the same values. The [security guide](/project/security/) covers the
threat model.

## Type and callable keys

A key does not have to be a literal. A type key validates _every_ key of that
type, which is how you describe an open mapping like "string keys, integer
values":

```python
from probatio import Schema

schema = Schema({str: int})

schema({"a": 1, "b": 2})  # {'a': 1, 'b': 2}
```

A key that fails the type is reported against that key, the same way voluptuous
does:

```python
from probatio import Schema, Invalid

schema = Schema({str: int})

try:
    schema({1: 2})
except Invalid as err:
    print(err)  # expected str @ data[1]
```

## Co-dependent and exclusive keys

`Inclusive` ties keys into a group that must appear together, all or none.
`Exclusive` ties keys into a group where at most one may appear. Both take the
group name as their second argument.

```python
from probatio import Schema, Inclusive

schema = Schema(
    {
        Inclusive("lat", "coords"): float,
        Inclusive("lon", "coords"): float,
    }
)

schema({"lat": 52.1, "lon": 5.1})  # {'lat': 52.1, 'lon': 5.1}
```

Providing only part of an inclusive group fails, and the error points at the
group, not a single key:

```python
from probatio import Schema, Inclusive, Invalid

schema = Schema(
    {
        Inclusive("lat", "coords"): float,
        Inclusive("lon", "coords"): float,
    }
)

try:
    schema({"lat": 52.1})
except Invalid as err:
    print(err)  # some but not all values in the same group of inclusion 'coords' @ data[<coords>]
```

An exclusive group is optional by default (none of its keys is fine). Two flags
change what an empty group does. `required=True` makes the group demand exactly
one key:

<!-- verify: raises MultipleInvalid -->

```python
from probatio import Schema, Exclusive

schema = Schema(
    {
        Exclusive("token", "auth", required=True): str,
        Exclusive("password", "auth", required=True): str,
    }
)

schema({})  # exactly one of ['token', 'password'] is required @ data[<auth>]
```

A `default` fills its member in when the group is empty (and wins over
`required`, since a default already satisfies the group):

```python
from probatio import Schema, Exclusive

schema = Schema(
    {
        Exclusive("mode", "m", default="auto"): str,
        Exclusive("custom", "m"): str,
    }
)

schema({})  # {'mode': 'auto'}
```

Both are group-level: set either on any member and it governs the whole group.

## Marking required across a whole schema

Instead of wrapping every key in `Required`, pass `required=True` to `Schema` to
make every key required by default; individual `Optional` keys still opt out.

```python
from probatio import Schema, Optional

schema = Schema({"a": int, Optional("b"): int}, required=True)

schema({"a": 1})  # {'a': 1}
```
