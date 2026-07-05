---
title: API reference
description: The public surface of Probatio, grouped by what each name does.
---

This is the public surface of `probatio`. It mirrors voluptuous, so the names
and signatures match what you already know. Everything here is importable
straight from `probatio` (for example `from probatio import Schema, All, Range`),
except `humanize_error` and `validate_with_humanized_errors`, which live in
`probatio.humanize`.

## Schema

```python
class Schema:
    def __init__(self, schema, required=False, extra=PREVENT_EXTRA): ...
    def __call__(self, data): ...
    def extend(self, schema, required=None, extra=None) -> Schema: ...
    @classmethod
    def infer(cls, data, **kwargs) -> Schema: ...
```

`Schema` compiles a validation definition once, then validates values when
called, returning the normalized result or raising `MultipleInvalid`. `required`
and `extra` are positional, matching voluptuous. `extend` returns a new schema
with another mapping's keys merged in (nested mappings merge recursively). Two
schemas compare equal when their definitions match, regardless of dict key order.

`Schema.infer(data)` builds a schema from concrete example data: each value
becomes its type, recursing into mappings and lists, so an API response can seed a
schema. Keyword arguments pass through to `Schema`.

```python
from probatio import Schema, Required

Schema.infer({"name": "app", "port": 80})  # == Schema({Required("name"): str, Required("port"): int})
```

A schema is built from plain Python: a type (`int`), a literal (`"on"`), a
callable, a `dict`, a `list`/`tuple`/`set`, a nested `Schema`, or any validator
below.

```python
from probatio import Schema, Required, Optional

schema = Schema({Required("name"): str, Optional("port", default=8080): int})
schema({"name": "app"})  # {'name': 'app', 'port': 8080}
```

Probatio validates parsed Python objects; parsing stays with the caller. Parse
your JSON, YAML, or TOML with the library of your choice, then hand the result to
the schema (`schema(json.loads(source))`).

## Markers

Markers are dictionary keys that carry intent. Each compares and hashes by its
underlying key, so it can stand in for the bare key.

- `Required(key, msg=None, default=UNDEFINED, description=None)`: the key must be present.
- `Optional(key, msg=None, default=UNDEFINED, description=None)`: the key may be present; a `default` fills it in when absent.
- `Remove(key)`: drop matching keys from the validated output.
- `Forbidden(key, msg=None, description=None)`: the key must not be present; if it appears, validation fails with "key not allowed". The mapped value is ignored, so the idiom is `{Forbidden("password"): object}`.
- `Secret(key, msg=None, description=None)`: redact the key's value from validation error output (`<redacted>` instead of the value). Composes with the presence markers by nesting, so `Optional(Secret("password"))` is an optional, redacted key. A Probatio addition (see [dict schemas and markers](/guides/dict-schemas-and-markers/#redacting-secret-values)).
- `Inclusive(key, group_of_inclusion, msg=None, default=UNDEFINED, description=None)`: all keys sharing a group must appear together, or none.
- `Exclusive(key, group_of_exclusion, msg=None, description=None, *, required=False, default=UNDEFINED)`: at most one key from a group may appear. `required=True` makes the group demand exactly one key; a `default` fills that member in when the group is empty (and satisfies the group, so it wins over `required`). Both are group-level.
- `Extra`: a catch-all key. `{Extra: validator}` validates every otherwise-unmatched key.
- `Alias(key, *aliases, accept_canonical=True, required=False, default=UNDEFINED, msg=None, description=None)`: accept the value under any of the alias names and emit it under the canonical `key`. The names are tried in order, first one present wins; `accept_canonical=False` makes it a strict rename that accepts only the aliases. A Probatio addition (see [dict schemas and markers](/guides/dict-schemas-and-markers/)).
- `Marker`: the base class the markers above derive from, exposed for `isinstance` checks and custom markers.
- `Self`: a sentinel that refers to the enclosing schema, for recursive structures. Works as a mapping value, a sequence element, or a direct combinator branch. See [recursive schemas](/guides/recursive-schemas/).

The extra-key policy is set with the `extra` argument to `Schema`:

- `PREVENT_EXTRA` (the default): reject keys not in the schema.
- `ALLOW_EXTRA`: keep them untouched.
- `REMOVE_EXTRA`: drop them from the output.

## Constants and sentinels

- `UNDEFINED`: the "no value" sentinel for marker defaults.
- `Undefined`: the type of `UNDEFINED`, for `isinstance` checks.
- `default_factory(value)`: normalize a marker default into a zero-argument
  factory (the voluptuous helper).
- `Schemable`: the type alias for anything `Schema` accepts, for annotations.
- `__version__`: the installed Probatio version string.

## Combinators

- `All(*validators, msg=None, required=False)`: every validator must pass, the output of each feeding the next. Aliased as `And`.
- `Any(*validators, msg=None, required=False)`: the first validator that accepts the value wins. Aliased as `Or`.
- `Union(*validators, msg=None, required=False, discriminant=None)`: like `Any`, but a `discriminant(value, validators)` can narrow which validators to try, for a tagged union. Aliased as `Switch`.
- `SomeOf(validators, min_valid=None, max_valid=None, msg=None, required=False)`: the value must pass between `min_valid` and `max_valid` of the validators. Raises `NotEnoughValid` or `TooManyValid`.

```python
from probatio import All, Any, SomeOf, Range, Schema

Schema(All(str, str.strip))("  hi  ")            # 'hi'
Schema(Any(int, str))("a")                       # 'a'
Schema(SomeOf(min_valid=2, validators=[Range(1, 5), int, 3]))(3)  # 3
```

A `Union` discriminant picks the branch instead of trying every alternative:

```python
from probatio import Schema, Union

def by_type(value, alternatives):
    return [a for a in alternatives if a["type"] == value.get("type")]

schema = Schema(
    Union({"type": "a", "v": int}, {"type": "b", "v": str}, discriminant=by_type)
)
schema({"type": "a", "v": 1})  # {'type': 'a', 'v': 1}
```

## Validators

The leaf validators, grouped by category. Every name is importable straight
from `probatio`.

### Type and value

- `Coerce(type, msg=None)`: convert with `type(value)`, failing cleanly as
  `CoerceInvalid`.
- `Boolean(msg=None, clsoverride=None)`: a factory returning a validator that
  reads common truthy/falsy strings (`"yes"`, `"off"`) as a `bool`. Call it:
  `Boolean()`.
- `Literal(lit)`: require the value to equal a literal, returning the literal.
- `Equal(target, msg=None)`: require the value to equal `target`.
- `In(container, msg=None, *, fold_case=False, space=None)`: the value must be a
  member of `container`. `fold_case` matches case-insensitively; `space` collapses
  each whitespace run in a string to the given character; either returns the
  normalized value. A missed string value suggests the closest members (`did you
mean ...?`) and records them on the error's `candidates`.
- `NotIn(container, msg=None)`: the value must not be a member of `container`.
- `Contains(item, msg=None)`: the value (a collection) must contain `item`.
- `Match(pattern, msg=None)`: the value must match a regular expression.

### Numbers

- `Range(min=None, max=None, min_included=True, max_included=True, msg=None)`:
  numeric bounds, inclusive by default.
- `Clamp(min=None, max=None, msg=None)`: pin a value into a range instead of
  failing.
- `Number(precision=None, scale=None, msg=None, yield_decimal=False)`: validate a
  numeric string, checking precision/scale.
- `Positive(msg=None)`, `Negative(msg=None)`, `NonNegative(msg=None)`: sign
  conveniences (`> 0`, `< 0`, `>= 0`) over `Range`.
- `MultipleOf(factor, msg=None)`: require a number to be an integer multiple of
  `factor`.
- `Percentage(msg=None)`: validate a number or `"NN%"` string in 0 to 100, returned
  unchanged. `FromPercentage(msg=None)` parses it to a `float`.
- `Byte(msg=None)`, `SmallFloat(msg=None)`: a number in 0 to 255, or in 0 to 1.
- `Latitude(msg=None)`, `Longitude(msg=None)`: a coordinate in -90 to 90, or -180
  to 180.

### Collections and structure

- `Length(min=None, max=None, msg=None)`: bound the length of a sized value.
- `Unique(msg=None)`: require all items to be distinct.
- `Set(msg=None)`: convert an iterable into a `set`.
- `ExactSequence(validators, msg=None)`: validate a fixed-length sequence, position
  by position.
- `Unordered(validators, msg=None)`: validate a sequence whose items may appear in
  any order.
- `Object(schema, cls=UNDEFINED)`: validate an object's attributes like a mapping,
  rebuilding the same type. `cls` pins the class.
- `Maybe(validator, msg=None)`: allow `None`, otherwise validate against
  `validator`.
- `EnsureList()`: wrap a scalar in a list; a list passes through, `None` becomes
  `[]`.
- `NonEmpty(msg=None)`: require a sized value (string, list, mapping) to not be
  empty.
- `Sorted(msg=None)`: require a sequence to be in ascending order.

```python
from probatio import Object, Schema, Unordered

Schema(Unordered([str, int]))([1, "a"])   # [1, 'a']

class Point:
    def __init__(self, x, y):
        self.x, self.y = x, y

result = Schema(Object({"x": int, "y": int}))(Point(1, 2))  # validates the attributes
result.x  # 1
```

### Strings

The transforms are plain functions; use them bare (`Lower`, not `Lower()`).

- `Lower`, `Upper`, `Capitalize`, `Title`, `Strip`: case and whitespace
  transforms.
- `Replace(pattern, substitution, msg=None)`: replace every match of a regular
  expression in a string.
- `Email()`, `Url()`, `FqdnUrl()`: format validators that avoid backtracking
  regular expressions.
- `Slug(msg=None)`: validate a slug (lowercase alphanumerics, hyphen/underscore
  separators).
- `IsRegex(msg=None)`: the value is itself a compilable regular expression.
- `Alpha`, `Alphanumeric`, `ASCII`, `PrintableASCII`, `NoWhitespace` (each
  `(msg=None)`): ASCII character-class checks (letters, letters and digits, ASCII,
  printable ASCII, no whitespace).
- `StartsWith(prefix, msg=None)`, `EndsWith(suffix, msg=None)`: the string starts
  with or ends with a fixed affix.
- `ByteLength(min=None, max=None, msg=None)`: bound the UTF-8 byte length (not the
  code-point count).
- `HexColor(msg=None)`: validate a hex color string (`#rgb` or `#rrggbb`), returned
  unchanged. Compose with `Lower` (or `Upper`) to fold case: `All(HexColor(), Lower)`.

### Date and time

- `Datetime(format=None, msg=None)`: validate a datetime string against a
  `strptime` format, default `%Y-%m-%dT%H:%M:%S.%fZ`, matching voluptuous. Use
  `AsDatetime` for ISO 8601 parsing.
- `Date(format=None, msg=None)`: validate a date string (default `%Y-%m-%d`).
- `Time(format=None, msg=None)`: validate a time-of-day string (default
  `%H:%M:%S`).
- `AsDatetime(format=None, require_timezone=False, msg=None)`: parse a string to a
  `datetime.datetime`. ISO 8601 by default, or a `strptime` `format=`. With
  `require_timezone`, a naive result is rejected.
- `AsDate(format=None, msg=None)`: parse a string to a `datetime.date` (ISO 8601 by
  default, or a `strptime` `format=`).
- `AsTime(format=None, msg=None)`: parse a string to a `datetime.time` (ISO 8601 by
  default, or a `strptime` `format=`).
- `Duration(msg=None)`: validate a duration (timedelta, seconds as an
  int/float/string, `H:MM[:SS]`, an ISO 8601 duration like `P1DT2H30M`, or a mapping),
  returning the value unchanged.
- `AsTimedelta(msg=None)`: parse the same duration forms to a `datetime.timedelta`
  (the object-returning sibling of `Duration`).
- `TimeZoneInfo(msg=None)`: validate an IANA zone name, returning it unchanged. Object
  via `Coerce(zoneinfo.ZoneInfo)`.
- `TimeZone(msg=None)`: validate a fixed UTC offset (`+01:00`, `Z`, `UTC`), returning it
  unchanged.
- `AsTimezone(msg=None)`: parse a fixed UTC offset to a `datetime.timezone` (the
  object-returning sibling of `TimeZone`).
- `FromEpoch(unit="seconds", msg=None)`: parse a Unix timestamp (`int` or `float`,
  `unit="seconds"` or `"milliseconds"`) into a timezone-aware UTC `datetime`.

### Filesystem

- `IsDir(msg=None)`: an existing directory path.
- `IsFile(msg=None)`: an existing file path.
- `PathExists(msg=None)`: a path that exists, of any kind.
- `IsSymlink(msg=None)`: an existing symbolic link.
- `IsSocket(msg=None)`: an existing socket.
- `IsFifo(msg=None)`: an existing named pipe (FIFO).
- `IsBlockDevice(msg=None)`: an existing block device.

### Network and identifiers

These are Probatio additions (voluptuous has no equivalent). They validate and
return the value unchanged; wrap with `Coerce(the type)` when you want the parsed
Python object.

- `IPv4Address(msg=None)`: an IPv4 address string. Object via
  `Coerce(ipaddress.IPv4Address)`.
- `IPv6Address(msg=None)`: an IPv6 address string. Object via
  `Coerce(ipaddress.IPv6Address)`.
- `IPAddress(msg=None)`: an IP address of either version. Object via
  `Coerce(ipaddress.ip_address)`.
- `IPNetwork(msg=None)`: a CIDR network (host bits allowed), returned unchanged (not
  normalized). Object via `Coerce(lambda v: ipaddress.ip_network(v, strict=False))`
  (plain `ip_network` defaults to `strict=True` and would reject host bits).
- `MacAddress(msg=None)`: validate a MAC address (common separators and bare hex),
  returned unchanged.
- `NormalizeMacAddress(upper=False, separator=":", msg=None)`: validate and return a
  canonical MAC (`aa:bb:cc:dd:ee:ff` by default; `upper=True` uppercases, `separator=`
  sets the separator, `""` for bare hex).
- `UUID(msg=None, version=None)`: a UUID string, returned unchanged; `version` pins
  the version. Object via `Coerce(uuid.UUID)`.
- `ULID(msg=None)`: validate a ULID (26 Crockford base32 characters, either case),
  returned unchanged. Compose with `Upper` for the canonical upper case.
- `Hostname(msg=None)`: a hostname (RFC 1123); a bare label like `localhost` is
  valid.
- `Fqdn(msg=None)`: a fully-qualified domain name (a dotted hostname).
- `Port(msg=None)`: a port number (1 to 65535), returned as an `int`.

### Encoding

- `JSONString(schema=None, msg=None)`: validate a JSON string (optionally the decoded
  value against `schema`), returning the string unchanged.
- `FromJSONString(schema=None, msg=None)`: parse a JSON string to the decoded value
  (the decoding sibling of `JSONString`), optionally validating it against `schema`.
- `Base64(msg=None)`, `Hex(msg=None)`: validate a Base64 or hexadecimal string,
  returning it unchanged.
- `HexInt(msg=None)`: parse a hexadecimal integer (a string like `"0x1A"` or `"1a"`,
  or an `int`) to an `int`.
- `CreditCard(normalize=True, msg=None)`: a credit card number that passes the Luhn
  checksum (12 to 19 digits, spaces or hyphens allowed). Normalized to bare digits
  by default; `normalize=False` returns the value unchanged.
- `IBAN(normalize=True, msg=None)`: an IBAN that passes the ISO 13616 mod-97
  checksum (spaces allowed; the per-country length is not checked). Normalized to
  the compact, upper-cased form by default; `normalize=False` returns it unchanged.
- `DataURI(msg=None)`: an RFC 2397 data URI (`data:[<mediatype>][;base64],<data>`),
  validating the Base64 payload when declared.
- `E164(normalize=True, msg=None)`: a phone number in international E.164 format
  (`+` then up to 15 digits). A format check, not a check that the number is
  dialable. Grouping characters are stripped by default; `normalize=False` rejects
  them and returns the value unchanged.

### Truthiness

- `IsTrue(msg=None)`: the value must be truthy.
- `IsFalse(msg=None)`: the value must be falsy.

### Cross-field rules

Apply these after a dict schema with `All`; they inspect the whole mapping.

- `RequiredWith(trigger, *required, mode="any", msg=None)`: require keys when the
  trigger key is present. `trigger` may be a list of keys, combined by `mode`
  (`"any"` or `"all"`).
- `RequiredWithout(trigger, *required, mode="any", msg=None)`: require keys when the
  trigger key is absent (the mirror of `RequiredWith`).
- `RequiredIf(conditions, *required, mode="all", msg=None)`: require keys when the
  `{key: value}` conditions hold, combined by `mode` (`"all"` or `"any"`).
- `Check(predicate, msg)`: run a predicate over the value; falsy or raising reports
  `msg`.
- `AtLeastOne(*keys, msg=None, require_mapping=True)`: at least one of the keys
  must be present in the mapping.
- `AtMostOne(*keys, msg=None, require_mapping=True)`: at most one of the keys may be
  present.
- `ExactlyOne(*keys, msg=None, require_mapping=True)`: exactly one of the keys must
  be present.
- `AllOrNone(*keys, msg=None, require_mapping=True)`: all of the keys must be present
  together, or none of them.
- `Immutable(*fields, msg=None)`: reject a change to a field between the previous
  value (from `current_context()`) and the new one.
- `WriteOnce(*fields, msg=None)`: allow a field to be set once (from absent or
  `None`), then reject a later change.

### Defaults and messages

- `DefaultTo(default, msg=None)`: replace `None` with a default.
- `SetTo(value)`: ignore the input and always produce a fixed value.
- `Msg(validator, msg, cls=None)`: wrap a validator and replace its failure
  message.

## Decorators and helpers

- `probatio(constraints=None, returns=None)`: decorator validating a callable's
  arguments from their annotations (sync or async). `constraints` is a
  `{parameter: validator}` map layered after the inferred type; `returns` opts into
  result validation (`True` uses the `-> R` annotation, or pass a schema). See [the
  probatio decorator](/guides/probatio-decorator/).
- `validate(*args, **kwargs)`: decorator validating a function's arguments (and
  `__return__`) against hand-named schemas (the voluptuous drop-in).
- `raises(exc, msg=None, regex=None)`: context manager asserting a block raises
  `exc`, optionally matching it.
- `message(default=None, cls=None, *, translation_key=None)`: decorator turning
  a function that raises `ValueError` into a validator factory (the voluptuous
  helper). The decorated function becomes a factory: call it to get the
  validator (`Schema(isint())`, not `Schema(isint)`), optionally passing a
  per-use message and `Invalid` subclass.
- `truth(func)`: decorator turning a predicate into a validator (the voluptuous
  helper). A truthy result returns the value unchanged; a falsy one fails as
  "not a valid value". Use the decorated function directly: `Schema(isdir)`.
- `current_context()`: the `context` value of the active
  `schema(data, context=...)` call, or `None` outside one. Lets a custom
  validator read call-time state, such as the previous value `Immutable`
  compares against. See the
  [custom validators guide](/guides/custom-validators/).

```python
from typing import Annotated

from probatio import probatio, Range

@probatio(returns=True)
def multiply(arg1: int, arg2: int) -> Annotated[int, Range(min=0)]:
    return arg1 * arg2

multiply(3, 4)  # 12
```

## Errors

Every failure is an `Invalid` (or a `MultipleInvalid` collecting several). The
subclasses let callers catch by kind; all of them carry a `path` to the offending
value and render it in `str(error)`.

- `Error`: base for everything Probatio raises.
- `SchemaError`: the schema definition itself is invalid (a programming error).
- `Invalid`: a single validation failure, with a `path`.
- `MultipleInvalid`: a collection of `Invalid` errors, proxying the first.

Semantic subclasses let callers catch by kind: `TypeInvalid`, `RangeInvalid`,
`CoerceInvalid`, `RequiredFieldInvalid`, `ExtraKeysInvalid` (which carries
`.candidates`, the close-match suggestions for an unknown key), and many more. The
[errors reference](/reference/errors/) lists every subclass with its stable
`code`.

## Humanizing errors

In `probatio.humanize`:

- `humanize_error(data, validation_error, max_sub_error_length=..., *, locator=None)`: render an error against the data as a readable string, naming the offending value. With a `locator` (a callable you supply that maps an error `path` to a `Location`, typically backed by a location-aware loader), each line gains its source position.
- `validate_with_humanized_errors(data, schema, ...)`: validate, raising `Error` with a humanized message on failure.

Importable straight from `probatio` (it lives in `probatio.error`, not
`probatio.humanize`):

- `Location`: a source position (`line`, `column`, `file`) a locator returns; renders as `file:line:column`.

## Schema interchange

Probatio converts schemas to and from JSON Schema and OpenAPI, for the
constructs that map cleanly (see the [JSON Schema
guide](/guides/json-schema/) for the supported keywords, and [Field
lists](/guides/field-lists/) for the `to_field_list` shape):

- `to_json_schema(schema)` / `from_json_schema(dict)`
- `to_openapi(schema, *, custom_serializer=None, openapi_version="3.0")` / `from_openapi(dict)`
- `to_field_list(schema, *, custom_serializer=None)`: render a schema as a plain field list (no inverse; the format is one-way). A `custom_serializer` is a callable that returns a node, or `UNSUPPORTED` to defer to the built-in handling.
- `UNSUPPORTED`: the sentinel a `custom_serializer` returns to defer.

`from_json_schema` treats its input as untrusted: it refuses a catastrophically
backtracking `pattern` and a pathologically deep document rather than hanging or
overflowing the stack.

## Dataclasses

Probatio builds a schema from a dataclass or a `TypedDict`, driven by its field
annotations (see the [dataclasses guide](/guides/dataclasses/) and the [TypedDicts
guide](/guides/typeddict/)):

- `DataclassSchema(dataclass_type, additional_constraints=None, *, required=False, extra=PREVENT_EXTRA)`: a `Schema` that validates a mapping and constructs an instance of `dataclass_type`.
- `create_dataclass_schema(dataclass_type, additional_constraints=None, *, required=False, extra=PREVENT_EXTRA)`: the functional form, returning the same `Schema`.
- `is_dataclass(obj)`: the standard-library check, re-exported.
- `TypedDictSchema(typeddict_type, additional_constraints=None, *, extra=PREVENT_EXTRA)`: a `Schema` that validates a mapping against a `TypedDict` and returns it typed as that `TypedDict` (nothing is constructed).
- `create_typeddict_schema(typeddict_type, additional_constraints=None, *, extra=PREVENT_EXTRA)`: the functional form, returning the same `Schema`.
- `Key(secret=False, alias=None, accept_canonical=True, forbidden=False, remove=False, inclusive=None, exclusive=None, required=None, description=None, msg=None)`: configure the marker a builder generates for an `Annotated` field, so a dataclass or `TypedDict` field carries the marker behavior (secret, alias, forbidden, remove, group membership, and the rest) without a hand-written dict schema. See the [dataclasses guide](/guides/dataclasses/).

A field without a default is `Required`, one with a `default`/`default_factory`
is `Optional`. Annotations map deeply (`list[str]` to `[str]`, `X | None` to
`Maybe(X)`, a nested dataclass to its own schema); `additional_constraints` adds
a per-field validator with `All`.

## Self-validation

A type can carry its own validator, so it validates by more than `isinstance`:

- `__probatio_validate__`: a classmethod a type can define to validate (and coerce) a value itself. Whenever that type is compiled as a bare schema, Probatio calls `Type.__probatio_validate__(value)` instead of an `isinstance` check and uses the return value. Works anywhere a type is used, including a hand-written `Schema(Type)`. See the [custom validators guide](/guides/custom-validators/).

## Compile policy

A hot schema compiles itself into a specialized validator; these names control
that process-wide (see [Compiled schemas](/guides/compiled-schemas/)):

- `CompilePolicy`: the policy enum: `OFF`, `ON`, and `AUTO` (the default, which
  compiles a schema once it runs hot).
- `get_compile_policy()`: return the active policy.
- `set_compile_policy(policy)`: set the process-wide policy.

## Build policy

Whether a schema compiles its declaration at construction or defers it to first
validation; these names control that process-wide (see [Lazy
building](/guides/lazy-building/)):

- `BuildPolicy`: the policy enum: `EAGER` (the default, compile at construction,
  matching voluptuous) and `LAZY` (defer to first validation, so a schema built but
  never validated never compiles). Under `LAZY` a definition error raises at first
  use rather than at construction.
- `get_build_policy()`: return the active policy.
- `set_build_policy(policy)`: set the process-wide policy.

## Loading and dumping

Probatio validates parsed Python objects; parsing and serialization stay with the
caller. Parse with the library of your choice, then validate the result, and
serialize a validated value with your own dumper (see the [loading and dumping
guide](/guides/loading-and-dumping/)).
