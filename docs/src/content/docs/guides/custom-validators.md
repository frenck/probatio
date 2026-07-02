---
title: Custom validators
description: Write your own validators as plain callables, reject with Invalid, transform on the way through, and reshape failure messages.
---

The built-in toolbox covers a lot, but eventually you need a rule that is yours.
In Probatio that rule is just a function. Any callable is a validator: it
receives the value and returns the result, or raises to reject it. There is no
base class to inherit and no interface to implement.

## A callable is a validator

Put a function anywhere a validator goes. It is called with the value, and what
it returns becomes the validated result.

```python
from probatio import Schema

def double(value):
    return value * 2

schema = Schema(double)

schema(21)  # 42
```

That is the whole contract. Return a value to accept, raise to reject.

## Rejecting with Invalid

To reject a value, raise `Invalid` with a message. The message is what the
caller sees, and Probatio attaches the path to the offending value for you.

```python
from probatio import Schema, Invalid, Required, MultipleInvalid

def even(value):
    if value % 2 != 0:
        raise Invalid("must be even")
    return value

schema = Schema({Required("count"): even})

schema({"count": 4})  # {'count': 4}
```

When the value fails, the message lands inside the usual error, pointing at the
key that broke:

```python
from probatio import Schema, Invalid, Required, MultipleInvalid

def even(value):
    if value % 2 != 0:
        raise Invalid("must be even")
    return value

schema = Schema({Required("count"): even})

try:
    schema({"count": 3})
except MultipleInvalid as err:
    print(err)  # must be even for dictionary value @ data['count']
```

## A plain ValueError works too

You do not have to import `Invalid` for the simple cases. If your callable
raises a `ValueError`, Probatio catches it and turns it into an `Invalid`. This
is on purpose: a lot of standard-library and third-party functions already raise
`ValueError` on bad input, so they drop straight in as validators.

```python
from probatio import Schema, MultipleInvalid

def port(value):
    number = int(value)  # raises ValueError on "nope"
    if not 0 < number <= 65535:
        raise ValueError("out of range")
    return number

schema = Schema(port)

schema("443")  # 443
```

The catch keeps the `ValueError` reason, appending it after `not a valid value: `
(a carry-forward of voluptuous [issue #417](https://github.com/alecthomas/voluptuous/issues/417), where the reason was dropped):

```python
from probatio import Schema, MultipleInvalid

def port(value):
    number = int(value)
    if not 0 < number <= 65535:
        raise ValueError("out of range")
    return number

schema = Schema(port)

try:
    schema("99999")
except MultipleInvalid as err:
    print(err)  # not a valid value: out of range
```

:::tip
Raise `ValueError` for the convenience: the reason is preserved, but it always
carries the `not a valid value: ` prefix. Raise `Invalid` when you want full
control of the message the caller reads, with no prefix.
:::

## Transforming the value

A validator does not have to return the input untouched. Returning a different
value is how you normalize: trim, lowercase, parse, canonicalize. The schema
hands back what you return, and the original input stays as it was (see
[the validation model](/guides/validation-model/)).

```python
from probatio import Schema

def to_slug(value):
    return value.strip().lower().replace(" ", "-")

schema = Schema(to_slug)

schema("  Hello World  ")  # 'hello-world'
```

## Reshaping the message with Msg

Sometimes the validator you want to reuse already raises a fine error, just not
the one you want here. `Msg(validator, msg, cls=None)` wraps a validator and
replaces its failure message. Pass `cls` to also swap the error class, so
callers can catch your failure by type.

```python
from probatio import Schema, Msg, Match, MultipleInvalid

schema = Schema(Msg(Match(r"^[a-z]+$"), "lowercase letters only"))

schema("frenck")  # 'frenck'
```

On failure the wrapped validator's own message is gone, replaced by yours:

```python
from probatio import Schema, Msg, Match, MultipleInvalid

schema = Schema(Msg(Match(r"^[a-z]+$"), "lowercase letters only"))

try:
    schema("ABC")
except MultipleInvalid as err:
    print(err)  # lowercase letters only
```

With `cls`, the raised error is your own subclass, which a caller can catch
specifically:

```python
from probatio import Schema, Msg, Match, Invalid, MultipleInvalid

class BadName(Invalid):
    """The name does not look right."""

schema = Schema(Msg(Match(r"^[a-z]+$"), "lowercase letters only", cls=BadName))

try:
    schema("ABC")
except MultipleInvalid as err:
    print(type(err.errors[0]).__name__)  # BadName
```

## Composing with All

Custom validators are validators, so they nest like any other. Drop them into
`All` to chain a normalize step in front of your check, and the result of each
validator feeds the next (see [combinators](/guides/combinators/)).

```python
from probatio import Schema, All, Strip, Lower, Invalid, Required, MultipleInvalid

def not_empty(value):
    if not value:
        raise Invalid("must not be empty")
    return value

schema = Schema({Required("name"): All(Strip, Lower, not_empty)})

schema({"name": "  Frenck  "})  # {'name': 'frenck'}
```

`Strip` and `Lower` normalize the value before `not_empty` ever sees it, so a
field of only spaces collapses to an empty string and is rejected:

```python
from probatio import Schema, All, Strip, Lower, Invalid, Required, MultipleInvalid

def not_empty(value):
    if not value:
        raise Invalid("must not be empty")
    return value

schema = Schema({Required("name"): All(Strip, Lower, not_empty)})

try:
    schema({"name": "   "})
except MultipleInvalid as err:
    print(err)  # must not be empty for dictionary value @ data['name']
```

## Parameterizing a validator

A validator that needs a setting is just a function that returns a function. The
outer call captures the parameter, the inner function does the check. This is how
every built-in factory works, `Range(min=...)` and `Length(max=...)` included.

```python
from probatio import Schema, Invalid, MultipleInvalid

def at_least(minimum):
    def check(value):
        if value < minimum:
            raise Invalid(f"must be at least {minimum}")
        return value
    return check

schema = Schema(at_least(18))
schema(21)  # 21

try:
    schema(16)
except MultipleInvalid as err:
    print(err)  # must be at least 18
```

A class with a `__call__` method works the same way and is handier when the
validator carries several settings or wants a readable `repr`:

```python
from probatio import Schema, Invalid, MultipleInvalid

class AtLeast:
    def __init__(self, minimum):
        self.minimum = minimum

    def __call__(self, value):
        if value < self.minimum:
            raise Invalid(f"must be at least {self.minimum}")
        return value

Schema(AtLeast(18))(21)  # 21
```

## A type that validates itself

A bare type used as a schema validates by `isinstance`. For a type whose runtime
value differs from its raw form, that is the wrong check. An enum is the clear
case: its value is the string a loader gives you, but `isinstance` accepts only an
already-built member. So Probatio treats an enum class as a schema specially: it
accepts a member or any of the enum's values, and returns the member.

```python
import enum

from probatio import Schema


class Color(enum.Enum):
    RED = "red"
    BLUE = "blue"


schema = Schema(Color)
schema("red")       # Color.RED
schema(Color.BLUE)  # Color.BLUE
```

Your own types can opt into the same treatment with a `__probatio_validate__`
classmethod. When that type is a schema, Probatio calls the method instead of the
`isinstance` check. The method validates (and may normalize) the raw value, and
raises `Invalid` to reject it, like any validator.

```python
from typing import Any

from probatio import Schema, Invalid


class Slug:
    def __init__(self, value: str) -> None:
        self.value = value

    @classmethod
    def __probatio_validate__(cls, value: Any) -> "Slug":
        if not isinstance(value, str):
            raise Invalid("expected a string slug")
        return cls(value.lower())


Schema(Slug)("Hello").value  # 'hello'
```

This keeps the "how do I validate a raw value of myself" knowledge on the type,
instead of wrapping every use in a `Coerce`. It is the principled way to make a
domain type a first-class schema. For a type you do not own, reach for `Coerce` or
a small validator function instead.

## Validating against call-time context

Some checks depend on state known only when you validate, not when you build the
schema: a set of allowed values from a request, the current user's permissions, a
list from the database. Pass it as `context` to the call, and a validator reads it
with `current_context()`. One compiled schema then serves many calls with
different state, instead of rebuilding the schema each time.

```python
from probatio import Schema, Required, current_context, Invalid


def allowed(value):
    context = current_context() or {}
    if value not in context.get("allowed", ()):
        raise Invalid(f"{value!r} is not allowed")
    return value


schema = Schema({Required("entity"): allowed})
schema({"entity": "light.kitchen"}, context={"allowed": {"light.kitchen"}})
```

The context is set for the duration of the call and visible to every validator it
reaches, including nested schemas. A nested schema that passes its own `context`
overrides it for that subtree; one that passes none inherits the enclosing call's.
Without a `context`, `current_context()` is `None`, so a validator that reads it
decides what an absent context means. It is async- and thread-safe, and a plain
`schema(data)` call sets nothing.

## Validating function arguments

`validate` is a decorator that checks a function's arguments (and, with the
`__return__` key, its return value) against schemas, the same way a `Schema`
checks data. A bad argument raises, so the body only runs on valid input. For the
annotation-driven, async-capable version that reads the schemas from the
signature, see [the probatio decorator](/guides/probatio-decorator/).

```python
from probatio import validate, MultipleInvalid

@validate(width=int, height=int, __return__=int)
def area(width, height):
    return width * height

area(3, 4)  # 12

try:
    area("wide", 4)
except MultipleInvalid as err:
    print(err)  # expected int for dictionary value @ data['width']
```

The `raises` context manager is the companion test helper: it asserts a block
raises a given error (optionally matching the message), which is how the examples
here check the rejection path.

```python
from probatio import Schema, MultipleInvalid, raises

schema = Schema(int)
with raises(MultipleInvalid, "expected int"):
    schema("nope")
```

## Where to next

- [The validation model](/guides/validation-model/): why a returned value can
  differ from the input.
- [Combinators](/guides/combinators/): `All`, `Any`, and friends.
- [Recursive schemas](/guides/recursive-schemas/): validators that refer back to
  their own schema.
