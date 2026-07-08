---
title: Cookbook
description: Worked schema patterns for tagged unions, coercion, open mappings, key groups, recursion, and friendly errors.
---

A page of patterns you reach for again and again. Each one is a small, runnable
schema with a passing input and, where it helps, a rejected one. Copy a block,
run it, adapt it.

## Tagged union

When your data carries a "type" field that decides its shape, a `Union` with a
`discriminant` routes to the matching branch. The discriminant is called as
`discriminant(value, alternatives)` and returns the subset to try, so a bad
branch reports its own field errors instead of "matched none of the
alternatives".

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
schema({"type": "label", "text": "hi"})    # {'type': 'label', 'text': 'hi'}
```

The discriminant sees the raw input, before any validation, so a non-dict input
raises from `value.get` before the union gets to report anything. A production
discriminant should guard for that; a
`if not isinstance(value, dict): return []` up front makes the union reject a
non-dict with its own clean `Invalid` instead.

A point with a non-int coordinate fails against the point branch, not the whole
union:

<!-- verify: raises MultipleInvalid -->

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

schema({"type": "point", "x": "nope", "y": 2})
```

Deep dive: [Combinators](/guides/combinators/).

## Coercing config and environment strings

Config files and environment variables hand you strings. `Coerce(int)` turns a
numeric string into an int, `Boolean` reads the common truthy and falsy spellings,
and wrapping a coercion in `All` lets you range-check the result. Order matters:
coerce first, then validate the typed value.

```python
from probatio import Schema, Coerce, Boolean, All, Range

port = Schema(All(Coerce(int), Range(min=1, max=65535)))
port("9000")  # 9000

flag = Schema(Boolean())
flag("yes")  # True
flag("off")  # False
```

`Coerce(int)` raises cleanly when the string is not a number, so a typo in a port
does not crash with a raw `ValueError`:

<!-- verify: raises MultipleInvalid -->

```python
from probatio import Schema, Coerce, All, Range

port = Schema(All(Coerce(int), Range(min=1, max=65535)))
port("eighty")
```

:::tip
`Boolean` is a factory, so call it: `Boolean()`, matching voluptuous. Pass a
message to customize the error (`Boolean("not a flag")`). The string transforms
like `Lower` and `Strip` are plain functions instead, so use those bare.
:::

Deep dive: [Validators](/guides/validators/).

## Device and sensor conversions

Raw device and sensor readings usually need a small calculation before they are
useful: a milliunit divided down, a byte scaled to a percentage, a temperature
converted, a status code named. The arithmetic mutators compose into these without
a hand-written `Coerce(lambda ...)`, and because you supply the numbers, probatio
never has to bake in a disputed formula.

```python
from probatio import Schema, All, Divide, Scale, Remap, Clamp, Round, Map

# Milliunits to units (millivolts to volts, milliseconds to seconds).
Schema(Divide(1000))(21500)  # 21.5

# A 0..255 byte to a 0..100 percentage.
Schema(All(Remap(0, 255, 0, 100), Round(0)))(128)  # 50.0

# Celsius to Fahrenheit, the affine transform in one call (value * 9 / 5 + 32).
Schema(Scale(9, divisor=5, offset=32))(20)  # 68.0

# A device status code to a name (you own the table).
Schema(Map({0: "off", 1: "on", 2: "auto"}))(2)  # 'auto'
```

RSSI to a signal percentage is the classic case with no single agreed formula.
`Remap` lets you pick the input range, and `Clamp` keeps the result in bounds when a
reading runs past it:

```python
from probatio import Schema, All, Remap, Clamp, Round

# Linear dBm -100..-50 to 0..100%, your chosen range, clamped and rounded.
rssi = Schema(All(Remap(-100, -50, 0, 100), Clamp(0, 100), Round(0)))
rssi(-70)  # 60.0
rssi(-40)  # 100  (past the top of the range, clamped)
```

Probatio deliberately ships no `RSSIToPercentage` or `CelsiusToFahrenheit`: the
formula is a policy choice, and unit conversion is bottomless. The primitives keep
that choice in your schema, where it is readable and yours to change.

Deep dive: [Validators](/guides/validators/).

## Open mapping with typed keys and values

To describe "any string key, integer value", use a type as the dict key. A type
key validates every key of that type, which is how you accept an open mapping
without listing each name.

```python
from probatio import Schema

schema = Schema({str: int})

schema({"a": 1, "b": 2})  # {'a': 1, 'b': 2}
```

For "these known keys, plus anything else", combine literal keys with the `Extra`
catch-all. `{Extra: validator}` validates every otherwise-unmatched key. Use
`{Extra: object}` to wave anything through:

```python
from probatio import Schema, Extra

schema = Schema({"name": str, Extra: object})

schema({"name": "app", "debug": True, "retries": 3})
# {'name': 'app', 'debug': True, 'retries': 3}
```

Deep dive: [Dict schemas and markers](/guides/dict-schemas-and-markers/).

## Nested optional sections with defaults

A whole config section can be optional, holding a nested schema with its own
defaults. Give the outer `Optional` a callable `default` (here `dict`) so an
absent section becomes a fresh empty dict. The default runs through the nested
schema like any value, so an absent section comes back fully populated with the
inner defaults, the same as a section provided as an empty dict.

```python
from probatio import Schema, Optional

schema = Schema(
    {
        Optional("logging", default=dict): {
            Optional("level", default="info"): str,
            Optional("file", default="app.log"): str,
        },
    }
)

schema({})  # {'logging': {'level': 'info', 'file': 'app.log'}}
schema({"logging": {}})  # {'logging': {'level': 'info', 'file': 'app.log'}}
schema({"logging": {"level": "debug"}})
# {'logging': {'level': 'debug', 'file': 'app.log'}}
```

:::note
Use a callable default (`dict`, `list`) rather than a literal `{}` or `[]`. The
callable runs per validation, so each result gets its own fresh container instead
of sharing one mutable object across calls.
:::

Deep dive: [Dict schemas and markers](/guides/dict-schemas-and-markers/).

## Mutually exclusive and co-dependent keys

`Exclusive` ties keys into a group where at most one may appear. `Inclusive` ties
keys into a group that must appear together, all or none. Both take the group
name as their second argument.

```python
from probatio import Schema, Exclusive, Inclusive

schema = Schema(
    {
        Exclusive("token", "auth"): str,
        Exclusive("password", "auth"): str,
        Inclusive("host", "server"): str,
        Inclusive("port", "server"): int,
    }
)

schema({"token": "abc", "host": "localhost", "port": 8080})
# {'token': 'abc', 'host': 'localhost', 'port': 8080}
```

Two keys from the same exclusive group is an error:

```python
from probatio import Schema, Exclusive, Invalid

schema = Schema(
    {
        Exclusive("token", "auth"): str,
        Exclusive("password", "auth"): str,
    }
)

try:
    schema({"token": "abc", "password": "hunter2"})
except Invalid as err:
    print(err)
    # two or more values in the same group of exclusion 'auth' at '<auth>'
```

Half of an inclusive group is also an error:

```python
from probatio import Schema, Inclusive, Invalid

schema = Schema(
    {
        Inclusive("host", "server"): str,
        Inclusive("port", "server"): int,
    }
)

try:
    schema({"host": "localhost"})
except Invalid as err:
    print(err)
    # some but not all values in the same group of inclusion 'server' at '<server>'
```

Deep dive: [Dict schemas and markers](/guides/dict-schemas-and-markers/).

## At least one of a group of keys

To require that _at least one_ of several keys is present, while still allowing
more than one, use a `Required(Any(...))` key. The `Any` lists the acceptable
keys, and the mapped value validates each one that appears. This is the "one or
more" counterpart to `Exclusive` (at most one) and `Inclusive` (all or none).

```python
from probatio import Schema, Required, Any

schema = Schema(
    {
        Required(Any("email", "phone")): str,
        "name": str,
    }
)

schema({"name": "ada", "email": "a@b.c"})  # {'name': 'ada', 'email': 'a@b.c'}
```

Providing none of them fails, with the error naming the whole group:

```python
from probatio import Schema, Required, Any, Invalid

schema = Schema({Required(Any("email", "phone")): str})

try:
    schema({})
except Invalid as err:
    print(err)  # at least one of ['email', 'phone'] is required at '[Any('email', 'phone', msg=None)]'
```

That default group label is honest but ugly: the path segment renders the
`Any(...)` marker's repr, because the group has no natural key name. (The repr
leak itself is a known library issue, tracked separately.) The production form
is a custom `msg` on the marker, read back through `error_message`, which
carries the message without the path:

```python
from probatio import Schema, Required, Any, Invalid

schema = Schema(
    {Required(Any("email", "phone"), msg="provide an email or a phone number"): str}
)

try:
    schema({})
except Invalid as err:
    print(err.errors[0].error_message)  # provide an email or a phone number
```

Deep dive: [Dict schemas and markers](/guides/dict-schemas-and-markers/).

## Dropping deprecated keys

`Remove` drops matching keys from the output. The value is still validated, so a
type error is not hidden; only a value that passes is dropped. Handy for retiring
a setting without breaking configs that still carry it.

```python
from probatio import Schema, Remove

schema = Schema({"name": str, Remove("legacy_mode"): bool})

schema({"name": "app", "legacy_mode": True})  # {'name': 'app'}
```

Deep dive: [Dict schemas and markers](/guides/dict-schemas-and-markers/).

## Extending a base schema with a cross-field rule

To add keys to a shared base _and_ check a rule across the whole mapping, compose
the two: `extend` merges the new keys, and `All` layers a whole-mapping validator
on top. There is no need for `extend` to grow special cases; the combinators
already compose.

```python
from probatio import Schema, All, Invalid, Required

base = Schema({Required("min"): int})


def min_below_max(config):
    if config["min"] >= config["max"]:
        raise Invalid("min must be below max")
    return config


schema = Schema(All(base.extend({Required("max"): int}), min_below_max))

schema({"min": 1, "max": 10})  # {'min': 1, 'max': 10}
```

The whole-mapping rule runs after the keys validate:

```python
from probatio import Schema, All, Invalid, Required

base = Schema({Required("min"): int})


def min_below_max(config):
    if config["min"] >= config["max"]:
        raise Invalid("min must be below max")
    return config


schema = Schema(All(base.extend({Required("max"): int}), min_below_max))

try:
    schema({"min": 10, "max": 5})
except Invalid as err:
    print(err)  # min must be below max
```

Deep dive: [Combinators](/guides/combinators/).

## Recursive tree

`Self` references the schema being defined, which is how you validate tree-shaped
data of unbounded depth. It must sit as a direct mapping value or list element.

```python
from probatio import Schema, Required, Optional, Self

node = Schema(
    {
        Required("name"): str,
        Optional("children", default=list): [Self],
    }
)

node({"name": "root", "children": [{"name": "leaf"}]})
# {'name': 'root', 'children': [{'name': 'leaf', 'children': []}]}
```

A bad value deep in the tree is rejected with a path that points right at it:

<!-- verify: raises MultipleInvalid -->

```python
from probatio import Schema, Required, Optional, Self

node = Schema(
    {
        Required("name"): str,
        Optional("children", default=list): [Self],
    }
)

node({"name": "root", "children": [{"name": 42}]})
```

Deep dive: [Recursive schemas](/guides/recursive-schemas/).

## Friendly error messages

The default `str(error)` is precise but terse. `humanize_error` from
`probatio.humanize` renders the failure against the data, naming the path and the
offending value, which is what you want to show whoever wrote the config.

```python
from probatio import Schema, All, Coerce, Range, Invalid
from probatio.humanize import humanize_error

schema = Schema({"port": All(Coerce(int), Range(min=1, max=65535))})

bad = {"port": "70000"}
try:
    schema(bad)
except Invalid as err:
    print(humanize_error(bad, err))
    # value must be at most 65535 at 'port'. Got '70000'
```

`validate_with_humanized_errors` does the same in one call: it validates and, on
failure, raises a plain `Error` carrying the humanized message.

<!-- verify: raises Error -->

```python
from probatio import Schema, Range
from probatio.humanize import validate_with_humanized_errors

schema = Schema({"port": Range(min=1, max=65535)})

validate_with_humanized_errors({"port": 70000}, schema)
```

To replace a single validator's message with your own wording, wrap it in `Msg`:

```python
from probatio import Schema, Match, Msg, Invalid

schema = Schema(Msg(Match(r"^[a-z]+$"), "use lowercase letters only"))

try:
    schema("Nope123")
except Invalid as err:
    print(err)  # use lowercase letters only
```

Deep dive: [Error handling](/guides/error-handling/) and
[Custom error messages](/guides/custom-error-messages/).
