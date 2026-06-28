---
title: API reference
description: The public surface of Probatio, grouped by what each name does.
---

This is the public surface of `probatio`. It mirrors voluptuous, so the names
and signatures match what you already know. Everything here is importable
straight from `probatio` (for example `from probatio import Schema, All, Range`),
except the error-humanizing helpers, which live in `probatio.humanize`.

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

`Schema` also has convenience loaders that parse and validate in one step:
`schema.load_json(source)`, `schema.load_yaml(source)`, `schema.load_toml(source)`,
and `schema.load(source, format=None)`.

## Markers

Markers are dictionary keys that carry intent. Each compares and hashes by its
underlying key, so it can stand in for the bare key.

- `Required(key, msg=None, default=UNDEFINED, description=None)`: the key must be present.
- `Optional(key, msg=None, default=UNDEFINED, description=None)`: the key may be present; a `default` fills it in when absent.
- `Remove(key)`: drop matching keys from the validated output.
- `Forbidden(key, msg=None, description=None)`: the key must not be present; if it appears, validation fails with "key not allowed". The mapped value is ignored, so the idiom is `{Forbidden("password"): object}`.
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

The leaf validators, grouped by category. Select a category to expand it. Every
name is importable straight from `probatio`.

<details>
<summary>Type and value</summary>

- `Coerce(type, msg=None)`: convert with `type(value)`, failing cleanly as
  `CoerceInvalid`.
- `Boolean(msg=None, clsoverride=None)`: a factory returning a validator that
  reads common truthy/falsy strings (`"yes"`, `"off"`) as a `bool`. Call it:
  `Boolean()`.
- `Literal(lit)`: require the value to equal a literal, returning the literal.
- `Equal(target, msg=None)`: require the value to equal `target`.
- `In(container, msg=None)`: the value must be a member of `container`.
- `NotIn(container, msg=None)`: the value must not be a member of `container`.
- `Contains(item, msg=None)`: the value (a collection) must contain `item`.
- `Match(pattern, msg=None)`: the value must match a regular expression.

</details>

<details>
<summary>Numbers</summary>

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
- `Percentage(msg=None)`: a number or `"NN%"` string in 0 to 100, returned as a
  `float`.
- `Byte(msg=None)`, `SmallFloat(msg=None)`: a number in 0 to 255, or in 0 to 1.
- `Latitude(msg=None)`, `Longitude(msg=None)`: a coordinate in -90 to 90, or -180
  to 180.

</details>

<details>
<summary>Collections and structure</summary>

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

</details>

<details>
<summary>Strings</summary>

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
- `HexColor(normalize=True, upper=False, msg=None)`: a hex color string (`#rgb` or
  `#rrggbb`), lower-cased by default (`upper=True` for uppercase, `normalize=False`
  to leave it unchanged).

</details>

<details>
<summary>Date and time</summary>

- `Datetime(format=None, msg=None)`: validate a datetime string (default ISO
  8601).
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
- `Duration(msg=None)`: parse a duration (timedelta, seconds, `H:MM[:SS]`, or a
  mapping) to a `timedelta`.
- `TimeZone(msg=None)`: validate an IANA zone name, returned as
  `zoneinfo.ZoneInfo`.
- `Epoch(unit="seconds", msg=None)`: parse a Unix timestamp (`int` or `float`,
  `unit="seconds"` or `"milliseconds"`) into a timezone-aware UTC `datetime`.

</details>

<details>
<summary>Filesystem</summary>

- `IsDir(msg=None)`: an existing directory path.
- `IsFile(msg=None)`: an existing file path.
- `PathExists(msg=None)`: a path that exists, of any kind.
- `IsSymlink(msg=None)`: an existing symbolic link.
- `IsSocket(msg=None)`: an existing socket.
- `IsFifo(msg=None)`: an existing named pipe (FIFO).
- `IsBlockDevice(msg=None)`: an existing block device.

</details>

<details>
<summary>Network and identifiers</summary>

These are Probatio additions (voluptuous has no equivalent). The typed ones
coerce to their natural Python object; the format checks pass the string through.

- `IPv4Address(msg=None)`: an IPv4 address, returned as `ipaddress.IPv4Address`.
- `IPv6Address(msg=None)`: an IPv6 address, returned as `ipaddress.IPv6Address`.
- `IPAddress(msg=None)`: an IP address of either version.
- `IPNetwork(msg=None)`: a CIDR network (host bits allowed), returned as an
  `ipaddress` network.
- `MacAddress(normalize=True, upper=False, separator=":", msg=None)`: a MAC
  address, normalized to `aa:bb:cc:dd:ee:ff` by default. `upper=True` uppercases,
  `separator=` sets the separator (`""` for bare hex), and `normalize=False`
  returns the input unchanged.
- `UUID(msg=None, version=None)`: a UUID, returned as `uuid.UUID`; `version` pins
  the version.
- `ULID(msg=None)`: a ULID (26 Crockford base32 characters), normalized to upper
  case.
- `Hostname(msg=None)`: a hostname (RFC 1123); a bare label like `localhost` is
  valid.
- `Fqdn(msg=None)`: a fully-qualified domain name (a dotted hostname).
- `Port(msg=None)`: a port number (1 to 65535), returned as an `int`.

</details>

<details>
<summary>Secrets</summary>

- `Secret(schema=object, msg=None)`: validate against `schema`, then wrap the
  value in a `SecretValue`. A failure is reported without echoing the value.
- `SecretValue`: the carrier; hides its value in `repr`/`str`, read it back with
  `.get_secret_value()`.

</details>

<details>
<summary>Encoding</summary>

- `JSONString(schema=None, msg=None)`: parse a JSON string, optionally validating
  the decoded value against `schema`.
- `YAMLString(schema=None, msg=None)`: parse a YAML string (safe-load, needs a YAML
  backend), optionally validating the decoded value.
- `Base64(msg=None)`, `Hex(msg=None)`: validate a Base64 or hexadecimal string,
  returning it unchanged.
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

</details>

<details>
<summary>Truthiness</summary>

- `IsTrue(msg=None)`: the value must be truthy.
- `IsFalse(msg=None)`: the value must be falsy.

</details>

<details>
<summary>Cross-field rules</summary>

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
- `Immutable(*fields, msg=None)`: reject a change to a field between the previous
  value (from `current_context()`) and the new one.
- `WriteOnce(*fields, msg=None)`: allow a field to be set once (from absent or
  `None`), then reject a later change.

</details>

<details>
<summary>Defaults and messages</summary>

- `DefaultTo(default, msg=None)`: replace `None` with a default.
- `SetTo(value)`: ignore the input and always produce a fixed value.
- `Msg(validator, msg, cls=None)`: wrap a validator and replace its failure
  message.

</details>

## Decorators and helpers

- `validate(*args, **kwargs)`: decorator validating a function's arguments (and
  `__return__`).
- `raises(exc, msg=None, regex=None)`: context manager asserting a block raises
  `exc`, optionally matching it.

```python
from probatio import validate

@validate(arg1=int, arg2=int, __return__=int)
def multiply(arg1, arg2):
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

- `humanize_error(data, validation_error, max_sub_error_length=..., *, locator=None)`: render an error against the data as a readable string, naming the offending value. With a `locator` (a callable mapping an error `path` to a `Location`, such as the one from `load_yaml_with_locations`), each line gains its source position.
- `validate_with_humanized_errors(data, schema, ...)`: validate, raising `Error` with a humanized message on failure.
- `Location`: a source position (`line`, `column`, `file`) a locator returns; renders as `file:line:column`.

## Schema interchange

Probatio converts schemas to and from JSON Schema and OpenAPI, for the
constructs that map cleanly (see the [JSON Schema
guide](/guides/json-schema/) for the supported keywords, and [Field
lists](/guides/field-lists/) for the `serialize` shape):

- `to_json_schema(schema)` / `from_json_schema(dict)`
- `to_openapi(schema, *, custom_serializer=None, openapi_version="3.0")` / `from_openapi(dict)`
- `serialize(schema, *, custom_serializer=None)`: render a schema as a plain field list. A `custom_serializer` is a callable that returns a node, or `UNSUPPORTED` to defer to the built-in handling.
- `UNSUPPORTED`: the sentinel a `custom_serializer` returns to defer.

`from_json_schema` treats its input as untrusted: it refuses a catastrophically
backtracking `pattern` and a pathologically deep document rather than hanging or
overflowing the stack.

## Dataclasses

Probatio builds a schema from a dataclass, driven by its field annotations (see
the [dataclasses guide](/guides/dataclasses/)):

- `DataclassSchema(dataclass_type, additional_constraints=None, *, required=False, extra=PREVENT_EXTRA)`: a `Schema` that validates a mapping and constructs an instance of `dataclass_type`.
- `create_dataclass_schema(dataclass_type, additional_constraints=None, *, required=False, extra=PREVENT_EXTRA)`: the functional form, returning the same `Schema`.
- `is_dataclass(obj)`: the standard-library check, re-exported.
- `TypedDictSchema(typeddict_type, additional_constraints=None, *, extra=PREVENT_EXTRA)`: a `Schema` that validates a mapping against a `TypedDict` and returns it typed as that `TypedDict` (nothing is constructed).
- `create_typeddict_schema(typeddict_type, additional_constraints=None, *, extra=PREVENT_EXTRA)`: the functional form, returning the same `Schema`.

A field without a default is `Required`, one with a `default`/`default_factory`
is `Optional`. Annotations map deeply (`list[str]` to `[str]`, `X | None` to
`Maybe(X)`, a nested dataclass to its own schema); `additional_constraints` adds
a per-field validator with `All`.

## Type registry and self-validation

Two Probatio additions let a type carry its own validator, so a type validates by
more than `isinstance`:

- `__probatio_validate__`: a classmethod a type can define to validate (and coerce) a value itself. Whenever that type is compiled as a bare schema, Probatio calls `Type.__probatio_validate__(value)` instead of an `isinstance` check and uses the return value. Works anywhere a type is used, including a hand-written `Schema(Type)`. See the [custom validators guide](/guides/custom-validators/).
- `register_type(cls, validator)`: register a validator for `cls`, consulted when `cls` appears as a field annotation while building a dataclass or TypedDict schema (it takes precedence over the type's own check there). A hand-written `Schema(cls)` is not affected. `clear_type_registry()` empties the registry. See the [dataclasses guide](/guides/dataclasses/).
- `type_registry(registrations)`: a context manager that applies a mapping of `{type: validator}` for the duration of a `with` block, then restores the previous state. Async- and thread-safe, so a library should prefer it over the process-wide `register_type`.

## Loading and dumping

Probatio reads and writes JSON, YAML, and TOML, using a fast backend when one is
installed. JSON read and write and TOML read work on the standard library; YAML
(read and write) and TOML write need an optional extra (see
[Installation](/getting-started/installation/)).

- `load(source, format=None, *, options=None)`, `load_json`, `load_yaml`, `load_toml`: `source` is a string or bytes of content, a `pathlib.Path`, or an open file. `load` auto-detects the format from a path suffix. `options` is forwarded to the active backend (for example a YAML spec switch).
- `load_yaml_with_locations(source, *, options=None)`: like `load_yaml`, but returns `(data, locator)`, where the locator maps an error `path` to a source `Location`. Needs the YAMLRocks backend.
- `dump(value, format)`, `dump_json`, `dump_yaml`, `dump_toml`: each takes a `default` keyword for non-native values and an `options` mapping forwarded to the active backend.
- `set_default_options(format, *, load=None, dump=None)`: set process-wide default backend options for a format (clear with `clear_default_options()`). `default_options(format, *, load=None, dump=None)` is the scoped, async/thread-safe context-manager form. A call's own `options` win over a scoped default, which wins over the process-wide one.
