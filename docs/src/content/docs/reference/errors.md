---
title: Errors
description: The error hierarchy Probatio raises, the fields on Invalid, and the default code for every semantic subclass.
---

This page is the reference for what Probatio raises. For the how-to (catching,
reading paths, humanizing), see the [error handling guide](/guides/error-handling/).

## The error model

Everything Probatio raises descends from one base, `Error`. Below it sit two
unrelated kinds of failure: a broken schema and bad data.

- `Error`: the base for everything Probatio raises. Catch this to catch all of it.
- `SchemaError`: the schema *definition* is wrong. That is a programming mistake,
  not bad input, so it is kept separate from `Invalid`.
- `Invalid`: the data did not match the schema. Carries a `path` to the offending
  value.
- `MultipleInvalid`: a collection of `Invalid` errors from one validation pass. It
  is itself an `Invalid`, and it proxies its first error, so `msg`, `path`,
  `code`, and the rest read the first failure without reaching into `errors`.

A `Schema` always raises `MultipleInvalid` at the top, even for a single failure.
So when you catch one, the individual failures live in `err.errors`, and
`err.errors[0]` is the first.

## The fields on Invalid

Every `Invalid` carries two layers. The voluptuous-compatible layer (`msg`,
`path`, `error_message`, `error_type`) keeps its original wording and behavior, so
code that string-matches it still works. The structured layer (`code`, `context`,
`translation_key`, `placeholders`, `as_dict()`) is additive: it changes none of
the legacy output.

- `msg`: the human-readable message.
- `path`: the list of keys and indices to walk to the offending value.
- `error_message`: the bare message, without the path appended.
- `error_type`: the kind of value that failed, such as `dictionary value` (may be
  `None`).
- `code`: the stable machine-readable code (the class default unless overridden).
- `context`: a dict of structured detail about the failure, such as the expected
  type.
- `translation_key`: an optional key for localizing the message (may be `None`).
- `placeholders`: values to interpolate into a translated message.
- `as_dict()`: the structured layer rendered as a serializable dict, handy for a
  JSON API.

Reading `.path`, `.code`, and `.as_dict()` off a caught error. Remember the
schema raises `MultipleInvalid`, so reach into `err.errors[0]`:

```python
from probatio import Schema, MultipleInvalid

schema = Schema({"server": {"ports": [int]}})

try:
    schema({"server": {"ports": [80, "nope"]}})
except MultipleInvalid as err:
    first = err.errors[0]
    print(first.path)             # ['server', 'ports', 1]
    print(first.code)             # type
    print(first.as_dict()["context"])  # {'expected': 'int'}
```

On a `MultipleInvalid`, `as_dict()` renders the whole collection instead, under an
`errors` key:

```python
from probatio import Schema, MultipleInvalid

schema = Schema({"a": int})

try:
    schema({"a": "x"})
except MultipleInvalid as err:
    print(err.as_dict()["errors"][0]["code"])  # type
```

## Semantic subclasses

The subclasses let callers branch on what went wrong. They mirror voluptuous, so
the names match what you already catch. Each carries a stable `default_code`.

Each entry shows the class, its meaning, and its `default_code` in parentheses.

- `RequiredFieldInvalid` (`required`): a required key was missing from the data.
- `ObjectInvalid` (`object`): the value is not the expected object.
- `DictInvalid` (`not_a_dictionary`): the value is not a dictionary.
- `ExtraKeysInvalid` (`extra_keys_not_allowed`): a key matched no schema key under
  `PREVENT_EXTRA`; carries `candidates`, the close matches.
- `SequenceTypeInvalid` (`not_a_sequence`): the value is not the expected sequence
  type (list, tuple, set).
- `TypeInvalid` (`type`): the value is not of the expected type.
- `ValueInvalid` (`value`): a validator rejected the value.
- `ScalarInvalid` (`not_valid`): the value does not match a scalar literal.
- `LiteralInvalid` (`not_valid`): the value does not match a `Literal`.
- `CoerceInvalid` (`coerce`): a value could not be coerced to the requested type;
  for an `Enum` with string values, carries `candidates`, the close matches.
- `AnyInvalid` (`no_match`): the value matched none of the candidates.
- `AllInvalid` (`all`): the value failed one of a chain of validators.
- `MatchInvalid` (`match`): the value does not match the expected pattern.
- `RangeInvalid` (`range`): the value falls outside the allowed range.
- `LengthInvalid` (`length`): the value's length falls outside the allowed bounds.
- `InInvalid` (`not_in_list`): the value is not a member of the allowed set;
  carries `candidates`, the close matches among string members.
- `NotInInvalid` (`in_list`): the value is a member of a disallowed set.
- `ContainsInvalid` (`contains`): the collection does not contain the required
  element.
- `ExactSequenceInvalid` (`exact_sequence`): the sequence does not match the
  expected exact sequence.
- `ExclusiveInvalid` (`exclusive`): more than one key from a mutually exclusive
  group was provided.
- `InclusiveInvalid` (`inclusive`): some, but not all, keys from a co-dependent
  group were provided.
- `TrueInvalid` (`not_true`): the value is not truthy.
- `FalseInvalid` (`not_false`): the value is not falsy.
- `BooleanInvalid` (`boolean`): the value could not be read as a boolean.
- `UrlInvalid` (`url`): the value is not a valid URL.
- `EmailInvalid` (`email`): the value is not a valid email address.
- `DirInvalid` (`not_a_directory`): the value is not an existing directory.
- `FileInvalid` (`not_a_file`): the value is not an existing file.
- `PathInvalid` (`not_a_path`): the value is not an existing path.
- `SymlinkInvalid` (`not_a_symlink`): the value is not an existing symbolic link.
- `SocketInvalid` (`not_a_socket`): the value is not an existing socket.
- `FifoInvalid` (`not_a_fifo`): the value is not an existing named pipe (FIFO).
- `BlockDeviceInvalid` (`not_a_block_device`): the value is not an existing block
  device.
- `DatetimeInvalid` (`datetime`): the value is not a valid datetime.
- `DateInvalid` (`date`): the value is not a valid date.
- `TimeInvalid` (`time`): the value is not a valid time of day.
- `DurationInvalid` (`duration`): the value is not a valid duration.
- `TimeZoneInvalid` (`time_zone`): the value is not a valid IANA time zone.
- `IpInvalid` (`ip`): the value is not a valid IP address or network.
- `MacAddressInvalid` (`mac_address`): the value is not a valid MAC address.
- `UuidInvalid` (`uuid`): the value is not a valid UUID.
- `HostnameInvalid` (`hostname`): the value is not a valid hostname or domain name.
- `SlugInvalid` (`slug`): the value is not a valid slug.
- `MultipleOfInvalid` (`multiple_of`): the value is not a multiple of the factor.
- `SecretInvalid` (`secret`): the value behind a `Secret` failed its inner schema.
- `JsonInvalid` (`json`): the value is not valid JSON.
- `YamlInvalid` (`yaml`): the value is not valid YAML.
- `NotEnoughValid` (`not_enough_valid`): too few of a `SomeOf` group's validators
  passed.
- `TooManyValid` (`too_many_valid`): too many of a `SomeOf` group's validators
  passed.

:::note
`ScalarInvalid` and `LiteralInvalid` share the code `not_valid`. The `code` is a
classification, not a unique identifier per class. Branch on the exception type
when you need to tell them apart.
:::

The subclasses live in `probatio.error`. Catch them there:

```python
from probatio import Schema, Range, MultipleInvalid
from probatio.error import RangeInvalid

schema = Schema(Range(min=0, max=10))

try:
    schema(99)
except MultipleInvalid as err:
    first = err.errors[0]
    print(isinstance(first, RangeInvalid))  # True
    print(first.code)                        # range
```
