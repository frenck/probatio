---
title: Value metadata
description: Metadata a value carries beside its contents, how a type opts in, and how Probatio keeps it across a rebuild.
---

Some data arrives knowing more about itself than its contents say. A YAML loader
knows the file and the line every mapping came from. A request parser knows
which part of a multipart body a field was in. A migration knows a key used to
be spelled differently. That knowledge belongs to the value, not to the schema,
and it is exactly what a good error message needs.

Validation is hostile to it. A mapping or sequence schema rebuilds its input, so
whatever the original held beside its items does not come along. Value metadata
is Probatio's answer: a small, defined model for that knowledge, carried across
every rebuild that produces the value's own type. (A rebuild that does not keep
the type cannot keep the metadata either; that and the other edges are covered
below.)

:::note[Not `Annotated` metadata]
This page is about metadata on a _value_. The extra arguments of an
`Annotated[...]` type hint are also called metadata; Probatio reads those as
validators and markers for a field, as described in the
[dataclasses guide](/guides/dataclasses/). The two are unrelated.
:::

## What validation loses

Here is a `dict` subclass that records the line it was loaded from, the shape a
YAML loader produces:

```python
from probatio import Schema


class Node(dict):
    __slots__ = ("line",)


node = Node({"name": "kitchen"})
node.line = 12

validated = Schema({"name": str})(node)

type(validated) is Node  # True
hasattr(validated, "line")  # False
```

The class survived. The line did not. Probatio preserves a `dict` subclass as
its own class (voluptuous does too), but the rebuilt container is a _fresh,
empty_ instance of that class: the items are copied over one at a time, and
nothing else is. The loss happens at every nesting depth, for every schema shape
that rebuilds, so no amount of care at the call site reaches it.

What that costs is a message. "option 'old_name' is deprecated" is worth
reading; "option 'old_name' is deprecated, at configuration.yaml line 12" is
worth acting on. The second one needs the line to survive validation.

## The model

`Metadata` is what a value carries: an immutable mapping of `str` keys to
anything. Build one from a mapping, from keyword arguments, or from both.

```python
from probatio import Metadata

where = Metadata(file="configuration.yaml", line=12)

where["line"]  # 12
dict(where)  # {'file': 'configuration.yaml', 'line': 12}
```

It reads like any mapping (`in`, `len`, `get`, iteration) and it cannot be
changed. To add to it, `merge` returns a new `Metadata`, leaving the original
alone:

```python
from probatio import Metadata

where = Metadata(file="configuration.yaml", line=12)
moved = where.merge(line=14)

moved["line"]  # 14
where["line"]  # 12
```

The immutability is load-bearing. Probatio hands the _same_ `Metadata` object
to a rebuilt container rather than copying it, which is what keeps the carry
cheap. That is only safe because nothing can change it afterwards through either
reference, so the guarantee is enforced rather than advised: the keys and values
are copied into a mapping no one else holds, reachable only read-only.

What cannot change is the mapping: which keys it holds, and the value each one
is bound to. The values themselves are stored as given, not copied, so a
mutable value such as a list is still that same list, and changing it in place
changes what every value sharing the `Metadata` reports. Use immutable values
(a tuple rather than a list, for example) for metadata that must stay as it was.

A value carries its metadata in one attribute, `__probatio_metadata__`,
also exported as `METADATA_ATTR`. That attribute is the whole protocol: no
registration, no base class, no method to implement.

## Opting a type in

A type opts in by making room for that attribute. There are two ways, and what
they have in common is that the attribute is somewhere the value simply holds it.

For a `__slots__` type, it is one line:

```python
from probatio import add_metadata, metadata_of


class Node(dict):
    __slots__ = ("__probatio_metadata__",)


metadata_of(add_metadata(Node(), line=1))["line"]  # 1
```

For a type whose instances have an ordinary `__dict__`, there is nothing to do
at all. It already has somewhere to put it:

```python
from probatio import add_metadata, metadata_of


class Node(dict):
    """No __slots__, so instances take arbitrary attributes."""


metadata_of(add_metadata(Node(), line=2))["line"]  # 2
```

There is no third way, and a property of that name is specifically not one.

```python
from probatio import Schema, add_metadata, metadata_of


class Property(dict):
    """Not a carrier: the attribute is a call, not a place."""

    __slots__ = ("_where",)

    @property
    def __probatio_metadata__(self):
        return getattr(self, "_where", None)

    @__probatio_metadata__.setter
    def __probatio_metadata__(self, metadata):
        object.__setattr__(self, "_where", metadata)


node = add_metadata(Property({"name": "kitchen"}), line=12)

validated = Schema({"name": str})(node)

metadata_of(validated)  # None, the carry declined to run the setter
```

Probatio writes the attribute on a value it has just validated, so it will only
do that when the write _is_ a write: a slot, or an instance `__dict__` entry. A
property takes it as a call instead, and a setter receives the container itself.
It could add a key a mapping schema never saw, or replace an item a sequence
schema just checked, and the schema would then return content it never approved.
Probatio cannot tell a well-behaved setter from that one, so it runs neither.

`supports_metadata` answers exactly this question, and reports `False` for a
property, for any other descriptor you wrote, and for a type that overrides
`__setattr__`. A type that keeps the metadata under names of its own should add
the slot and write into it, rather than build a view over the old fields.

:::caution[If you were relying on a property]
The attribute has to be somewhere the value can simply hold it. Keep the fields
you have, add the slot beside them, and have whatever populates the old fields
populate the metadata too.
:::

:::note[Why there is no mixin to inherit]
A base class would be the obvious convenience, and it is not offered on purpose.
`class Node(dict, Mixin)` with a non-empty `__slots__` on the mixin is a Python
layout conflict, so a shipped base class would fail for exactly the `dict` and
`list` subclasses this exists to serve. The attribute is the protocol instead.
:::

## Where Probatio carries it

Every place Probatio rebuilds a _container_ moves the original's metadata onto
the rebuilt one:

- a `dict` subclass rebuilt by a mapping schema,
- a `list`, `tuple`, or `set` subclass rebuilt by a sequence schema,
- `ExactSequence`.

`Object` carries too. It does not rebuild a container, it constructs a new
object out of the validated attributes, so its metadata rides along the same way.

Every one of these carries under the same condition: the write has to land in the
attribute itself. That is worked out once per type and then cached, so it costs a
dictionary lookup per rebuilt value.

Nesting works at any depth, because each level is carried as it is rebuilt:

```python
from probatio import Schema, add_metadata, metadata_of


class Node(dict):
    __slots__ = ("__probatio_metadata__",)


class NodeList(list):
    __slots__ = ("__probatio_metadata__",)


port = add_metadata(Node({"port": 8123}), line=3)
servers = add_metadata(NodeList([port]), line=2)
config = add_metadata(Node({"servers": servers}), line=1)

validated = Schema({"servers": [{"port": int}]})(config)

metadata_of(validated)["line"]  # 1
metadata_of(validated["servers"])["line"]  # 2
metadata_of(validated["servers"][0])["line"]  # 3
```

Mapping keys keep their own. A key is passed through to the rebuilt mapping
rather than reconstructed, so a key object arrives with all the metadata it
carried:

```python
from probatio import Schema, add_metadata, metadata_of


class Node(dict):
    __slots__ = ("__probatio_metadata__",)


class Key(str):
    __slots__ = ("__probatio_metadata__",)


key = add_metadata(Key("name"), line=5)
validated = Schema({"name": str})(Node({key: "kitchen"}))

[metadata_of(key)["line"] for key in validated]  # [5]
```

That holds while the key survives as itself, which covers a literal key and a type
key. A key schema that _builds_ a new key, such as `Coerce(str)`, produces a
different object, and the metadata belonged to the old one:

```python
from probatio import Coerce, Schema, add_metadata, metadata_of


class Key(str):
    __slots__ = ("__probatio_metadata__",)


validated = Schema({Coerce(str): str})({add_metadata(Key("name"), line=5): "kitchen"})

[metadata_of(key) for key in validated]  # [None]
```

## Reading and adding from a validator

Four helpers are the whole validator-facing API. `add_metadata` merges metadata
into what a value already carries and returns the value, so it reads well as the
last line of a validator:

```python
from probatio import Schema, add_metadata, metadata_of


class Node(dict):
    __slots__ = ("__probatio_metadata__",)


def mark_checked(value):
    return add_metadata(value, checked=True)


validated = Schema(mark_checked)(Node({"port": 8123}))

metadata_of(validated)["checked"]  # True
```

`metadata_of` reads it back, returning `None` when there is none. It
always returns a `Metadata`, even when the value stores a plain mapping in
the attribute, so a caller has one shape to work with, and it raises `TypeError`
for a value holding something that is not a mapping at all.
`supports_metadata` answers whether adding metadata to a value would stick:

```python
from probatio import supports_metadata


class Node(dict):
    __slots__ = ("__probatio_metadata__",)


supports_metadata(Node())  # True
supports_metadata({})  # False
supports_metadata("kitchen")  # False
```

It reports whether the attribute is somewhere the value simply holds it, which is
the same question Probatio asks before carrying. A property reports `False` whether
or not it has a setter, and so does any other descriptor you wrote or a type that
overrides `__setattr__`. The one thing it cannot see is whether a write that does
land will be kept, since only reading it back shows that.

`carry_metadata` is for a validator that builds a new container itself.
Probatio carries metadata across the rebuilds it performs, but a
transformation you write is yours to carry:

```python
from probatio import Schema, add_metadata, metadata_of, carry_metadata


class Node(dict):
    __slots__ = ("__probatio_metadata__",)


def drop_empty(value):
    kept = type(value)((key, item) for key, item in value.items() if item)
    return carry_metadata(value, kept)


config = add_metadata(Node({"name": "kitchen", "alias": ""}), line=7)
validated = Schema(drop_empty)(config)

dict(validated)  # {'name': 'kitchen'}
metadata_of(validated)["line"]  # 7
```

Because the engine propagates whatever it finds, metadata a validator adds
survives every container rebuild above it, and the order in `All` does not
matter. Both of these end with the loader's metadata and the validator's own:

```python
from probatio import All, Schema, add_metadata, metadata_of


class Node(dict):
    __slots__ = ("__probatio_metadata__",)


def mark_checked(value):
    return add_metadata(value, checked=True)


after = Schema(All({"port": int}, mark_checked))
before = Schema(All(mark_checked, {"port": int}))

dict(metadata_of(after(add_metadata(Node({"port": 8123}), line=1))))
# {'line': 1, 'checked': True}
dict(metadata_of(before(add_metadata(Node({"port": 8123}), line=1))))
# {'line': 1, 'checked': True}
```

That is what makes the error message from the start of this page possible. The
check runs after the mapping schema has rebuilt the config, and the metadata
is still there to read:

```python
from probatio import All, Invalid, MultipleInvalid, Schema, add_metadata, metadata_of


class Node(dict):
    __slots__ = ("__probatio_metadata__",)


def no_deprecated_options(value):
    if "old_name" not in value:
        return value
    where = metadata_of(value)
    if where is None:
        raise Invalid("option 'old_name' is deprecated, use 'name'")
    raise Invalid(
        f"option 'old_name' is deprecated, use 'name', "
        f"at {where['file']} line {where['line']}"
    )


schema = Schema(All({"old_name": str}, no_deprecated_options))
config = add_metadata(Node({"old_name": "kitchen"}), file="configuration.yaml", line=12)

try:
    schema(config)
except MultipleInvalid as err:
    print(err)
    # option 'old_name' is deprecated, use 'name', at configuration.yaml line 12
```

## The limits

Value metadata is deliberately narrow, and the edges are worth knowing before
you rely on it.

**A value that cannot hold an attribute cannot carry metadata.** A plain `dict`, a
`str`, an `int`: none of them make room for one. `add_metadata` and
`carry_metadata` return such a value unchanged rather than raise, so a
validator can call them without knowing what it was handed. The cost is that a
genuine mistake is quiet, which is what `supports_metadata` exists to check
for:

```python
from probatio import add_metadata, metadata_of

config = {"port": 8123}

add_metadata(config, line=1)  # {'port': 8123}
metadata_of(config)  # None
```

**A validator that destroys the type destroys the metadata with it.**
Returning `dict(value)`, a comprehension, or an accumulator produces a plain
`dict` or `list`, and no engine change can heal that. The fix is
`carry_metadata`, applied where the validator is written, as in `drop_empty`
above.

**`Coerce(dict)` loses it, correctly.** It is asked for a plain `dict` and it
returns one, and a plain `dict` holds no attributes. That is the coercion doing
its job, not a gap.

**A rebuild replaces rather than merges.** The engine moves the source's
metadata onto the rebuilt value, overwriting any the fresh instance gave
itself in its own constructor. The rebuilt value stands in for the original, so
the original's metadata is the right one to keep. A source carrying none leaves the
new instance's own alone.

```python
from probatio import Schema, add_metadata, metadata_of


class Stamped(dict):
    __slots__ = ("__probatio_metadata__",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_metadata(self, origin="constructor")


node = add_metadata(Stamped({"port": 8123}), origin="configuration.yaml")
validated = Schema({"port": int})(node)

metadata_of(validated)["origin"]  # 'configuration.yaml'
```

**Metadata is shared, not copied.** The rebuilt value gets the same
`Metadata` object as the original, which is safe because a `Metadata` cannot be
changed to hold other keys or other values. A mutable value inside it is shared
the same way, as [the model](#the-model) explains:

```python
from probatio import Schema, add_metadata, metadata_of


class Node(dict):
    __slots__ = ("__probatio_metadata__",)


node = add_metadata(Node({"port": 8123}), line=1)
validated = Schema({"port": int})(node)

metadata_of(validated) is metadata_of(node)  # True
```

It is also not general instance state. Probatio copies this one
attribute and nothing else, so a subclass keeping a cache, a lock, or a parent
pointer does not have it silently duplicated onto a new object.

## What it costs

The carry is one attribute read and one attribute write, once per rebuilt
container. A plain `dict` or `list` never reaches it at all: those paths return
the container they built without a carry.

Measured on CPython 3.14, per call to `carry_metadata`:

- a subclass that does not opt in: **35 ns**,
- a slot carrier with the metadata set: **66 ns**,
- a slot carrier declared but _not_ set on this value: **125 ns**, because the slot
  descriptor exists and raises on the read,
- a value Probatio will not carry onto, such as a property carrier: **34 ns**, the
  cost of the check that declines it.

The third of those is worth designing around: if a type declares the slot on
every value but sets it on only some, the unset ones are the expensive case, not
the cheap one, so a slot carrier should have it set on every value. A carrier
that keeps the attribute in an instance `__dict__` does not have this cost: there
an unset attribute is the cheap case, about 47 ns.

In aggregate, on a 1500-entry nested config (1502 rebuilt containers), the carry
costs roughly 55 ns per container, about 0.08 ms for the whole document.

## Where to next

- [Custom validators](/guides/custom-validators/): the callables that `add_metadata`
  and `carry_metadata` are written inside.
- [The validation model](/guides/validation-model/): why a returned value can
  differ from the input, and what rebuilding means.
- [Home Assistant](/recipes/home-assistant/): the case this was built for, with
  a YAML node class opting in.
