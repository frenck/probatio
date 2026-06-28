---
title: voluptuous compatibility
description: A name-by-name map of voluptuous's public API and its status in Probatio, including the few intentional deviations.
---

The drop-in promise is the point of Probatio. This page makes it checkable. Below
is voluptuous's meaningful public surface, name by name, with its status in
Probatio and a short note. Presence was confirmed with `hasattr(probatio, name)`
against voluptuous 0.16.0, not from memory.

The status column uses three values:

- **Supported**: same name, same behavior.
- **Supported, with deviation**: present and compatible, but Probatio behaves
  differently in one documented way. Each one is a deliberate improvement.
- **Not mirrored**: Probatio does not expose this name. For everything on this
  page that is "not mirrored", the reason is that the name is not part of
  voluptuous's intended public API. See [What Probatio does not
  mirror](#what-probatio-does-not-mirror).

For the narrative version, read [Migrating from
voluptuous](/getting-started/migrating-from-voluptuous/) and
[Compatibility](/getting-started/compatibility/).

## Schema and constants

| Name | Status | Notes |
| --- | --- | --- |
| `Schema` | Supported | Same calling convention, including positional `required`/`extra`. |
| `Schemable` | Supported | The type alias for anything `Schema` accepts. |
| `ALLOW_EXTRA` | Supported | Extra-key policy constant. |
| `PREVENT_EXTRA` | Supported | The default extra-key policy. |
| `REMOVE_EXTRA` | Supported | Extra-key policy constant. |
| `UNDEFINED` | Supported | The "no value" sentinel for marker defaults. |
| `Undefined` | Supported | The type of `UNDEFINED`. |
| `default_factory` | Supported | Wraps a callable as a marker default factory. |

## Markers

| Name | Status | Notes |
| --- | --- | --- |
| `Marker` | Supported | Base class for all markers. |
| `Required` | Supported | The key must be present. |
| `Optional` | Supported | The key may be present; `default` fills it in. |
| `Remove` | Supported | Drop matching keys from the output. |
| `Extra` | Supported | The catch-all key. |
| `Inclusive` | Supported | Keys in a group appear together or not at all. |
| `Exclusive` | Supported | At most one key from a group. |
| `Self` | Supported, with deviation | Recursive schema reference. See [Intentional deviations](#intentional-deviations). |

## Combinators

| Name | Status | Notes |
| --- | --- | --- |
| `All` | Supported | Every validator must pass, output feeding the next. |
| `Any` | Supported | First accepting validator wins. |
| `And` | Supported | Alias of `All`. |
| `Or` | Supported | Alias of `Any`. |
| `Union` | Supported | Like `Any`, with an optional `discriminant`. |
| `Switch` | Supported | Alias of `Union`. |
| `SomeOf` | Supported | Pass between `min_valid` and `max_valid` of the validators. |

## Validators

| Name | Status | Notes |
| --- | --- | --- |
| `Coerce` | Supported | Convert with `type(value)`. |
| `Boolean` | Supported | Factory (`Boolean()`), as in voluptuous. Reads truthy/falsy strings as `bool`. |
| `Literal` | Supported | Require equality with a literal. |
| `Equal` | Supported | Require equality with a target. |
| `In` | Supported | Membership in a container. |
| `NotIn` | Supported | Non-membership in a container. |
| `Contains` | Supported | A collection must contain an item. |
| `Match` | Supported | Match a regular expression. |
| `Replace` | Supported | Replace regex matches in a string. |
| `Range` | Supported | Numeric bounds, inclusive by default. |
| `Clamp` | Supported | Pin a value into a range. |
| `Number` | Supported | Validate a numeric string, optionally precision and scale. |
| `Length` | Supported | Bound the length of a sized value. |
| `Unique` | Supported | Require distinct items. |
| `Set` | Supported | Convert an iterable into a `set`. |
| `ExactSequence` | Supported | Validate a fixed-length sequence by position. |
| `Unordered` | Supported | Validate a sequence in any order. |
| `Object` | Supported | Validate an object's attributes like a mapping. |
| `Maybe` | Supported | Allow `None`, otherwise validate. |
| `Lower` | Supported | Lowercase transform. |
| `Upper` | Supported | Uppercase transform. |
| `Capitalize` | Supported | Capitalize transform. |
| `Title` | Supported | Title-case transform. |
| `Strip` | Supported | Whitespace-strip transform. |
| `Email` | Supported | Backtracking-safe email format check. |
| `Url` | Supported | Backtracking-safe URL format check. |
| `FqdnUrl` | Supported | URL with a fully qualified domain. |
| `Datetime` | Supported | Validate a datetime string (default ISO 8601). |
| `Date` | Supported | Validate a date string (default `%Y-%m-%d`). |
| `IsDir` | Supported | An existing directory path. |
| `IsFile` | Supported | An existing file path. |
| `PathExists` | Supported | A path that exists. |
| `IsTrue` | Supported | The value must be truthy. |
| `IsFalse` | Supported | The value must be falsy. |
| `DefaultTo` | Supported | Replace `None` with a default. |
| `SetTo` | Supported | Always produce a fixed value. |
| `Msg` | Supported | Replace a validator's failure message. |

## Error classes

| Name | Status | Notes |
| --- | --- | --- |
| `Error` | Supported | Base for everything Probatio raises. |
| `SchemaError` | Supported | The schema definition itself is invalid. |
| `Invalid` | Supported | A single validation failure, with a `path`. |
| `MultipleInvalid` | Supported, with deviation | Collects several errors and proxies the first. See note below. |
| `RequiredFieldInvalid` | Supported | Semantic subclass of `Invalid`. |
| `ObjectInvalid` | Supported | Semantic subclass of `Invalid`. |
| `DictInvalid` | Supported | Semantic subclass of `Invalid`. |
| `SequenceTypeInvalid` | Supported | Semantic subclass of `Invalid`. |
| `TypeInvalid` | Supported | Semantic subclass of `Invalid`. |
| `ValueInvalid` | Supported | Semantic subclass of `Invalid`. |
| `ScalarInvalid` | Supported | Semantic subclass of `Invalid`. |
| `LiteralInvalid` | Supported | Semantic subclass of `Invalid`. |
| `CoerceInvalid` | Supported | Semantic subclass of `Invalid`. |
| `AnyInvalid` | Supported | Semantic subclass of `Invalid`. |
| `AllInvalid` | Supported | Semantic subclass of `Invalid`. |
| `MatchInvalid` | Supported | Semantic subclass of `Invalid`. |
| `RangeInvalid` | Supported | Semantic subclass of `Invalid`. |
| `LengthInvalid` | Supported | Semantic subclass of `Invalid`. |
| `InInvalid` | Supported | Semantic subclass of `Invalid`. |
| `NotInInvalid` | Supported | Semantic subclass of `Invalid`. |
| `ContainsInvalid` | Supported | Semantic subclass of `Invalid`. |
| `ExactSequenceInvalid` | Supported | Semantic subclass of `Invalid`. |
| `ExclusiveInvalid` | Supported | Semantic subclass of `Invalid`. |
| `InclusiveInvalid` | Supported | Semantic subclass of `Invalid`. |
| `TrueInvalid` | Supported | Semantic subclass of `Invalid`. |
| `FalseInvalid` | Supported | Semantic subclass of `Invalid`. |
| `BooleanInvalid` | Supported | Semantic subclass of `Invalid`. |
| `UrlInvalid` | Supported | Semantic subclass of `Invalid`. |
| `EmailInvalid` | Supported | Semantic subclass of `Invalid`. |
| `DirInvalid` | Supported | Semantic subclass of `Invalid`. |
| `FileInvalid` | Supported | Semantic subclass of `Invalid`. |
| `PathInvalid` | Supported | Semantic subclass of `Invalid`. |
| `DatetimeInvalid` | Supported | Semantic subclass of `Invalid`. |
| `DateInvalid` | Supported | Semantic subclass of `Invalid`. |
| `NotEnoughValid` | Supported | Raised by `SomeOf`. |
| `TooManyValid` | Supported | Raised by `SomeOf`. |

:::note
`MultipleInvalid` carries an extra `error_type` attribute that proxies the first
error's type, where voluptuous has no such attribute. It is additive, so it does
not break voluptuous code: code that never touched `error_type` keeps working,
and code that reads it gets the first error's `error_type`.
:::

## Helpers

| Name | Status | Notes |
| --- | --- | --- |
| `validate` | Supported | Decorator that validates a function's arguments and `__return__`. |
| `message` | Supported | Decorator turning a `ValueError`-raising function into a configurable validator factory. |
| `truth` | Supported | Decorator turning a predicate into a validator that returns the value when truthy. |
| `raises` | Supported | Context manager asserting a block raises a given exception. |
| `humanize_error` | Supported | In `probatio.humanize`. Render an error against the data. |
| `validate_with_humanized_errors` | Supported | In `probatio.humanize`. Validate, raising a humanized message. |

## Additions beyond voluptuous

These names and options are not in voluptuous; they are Probatio additions, so
they do not affect the drop-in promise (existing code keeps working). Each
carries forward an upstream request.

- `Forbidden`: a marker requiring a key to be absent
  (`{Forbidden("password"): object}`). Carries forward [issue #193](https://github.com/alecthomas/voluptuous/issues/193).
- `Alias`: a key marker accepting a value under one or more alias names and
  emitting it under a canonical name (`{Alias("user_name", "user-name"): str}`).
  Multiple aliases, first-present-wins by declaration order, optional strict
  rename. voluptuous has no equivalent.
- `DataclassSchema`, `create_dataclass_schema`, `is_dataclass`: build a schema
  from a dataclass, validate a mapping, and construct an instance. Carries forward
  draft [PR #533](https://github.com/alecthomas/voluptuous/pull/533).
- `TypedDictSchema`, `create_typeddict_schema`: build a schema from a TypedDict and
  return the validated mapping typed as that TypedDict (nothing constructed, since
  a TypedDict is a plain dict at runtime). voluptuous has no equivalent.
- `Exclusive(..., required=True)`: an exclusive group must hold exactly one key
  (an empty group is an error). Carries forward [issue #115](https://github.com/alecthomas/voluptuous/issues/115).
- `Exclusive(..., default=...)`: fill a group member when the exclusive group is
  empty. Carries forward [issue #245](https://github.com/alecthomas/voluptuous/issues/245).
- `IPv4Address`, `IPv6Address`, `IPAddress`, `IPNetwork`, `MacAddress`, `UUID`,
  `Hostname`, `Fqdn`, `Port`: network and identifier validators; the typed ones
  coerce to their Python object. Common across ecosystems, reinvented across Home
  Assistant and ESPHome.
- `Time`, `Duration`, `TimeZone`: time-of-day (the sibling of `Date`/`Datetime`),
  duration parsing to `timedelta`, and an IANA zone to `zoneinfo.ZoneInfo`. `Time`
  is voluptuous [issue #335](https://github.com/alecthomas/voluptuous/issues/335); the others recur across ecosystems.
- `AsDatetime`, `AsDate`, `AsTime`: the object-returning siblings of
  `Datetime`/`Date`/`Time`, parsing the string to a `datetime`/`date`/`time`
  instead of passing it through. ISO 8601 by default (standard library only, for
  deterministic results), or a `strptime` format. `AsDatetime` can require a
  timezone-aware result.
- `Epoch`: parse a Unix timestamp (seconds or milliseconds) into a
  timezone-aware UTC `datetime`. Common in APIs and device payloads.
- `EnsureList`, `Slug`, `Positive`, `Negative`, `NonNegative`, `MultipleOf`,
  `Percentage`: list-wrapping, slug format, sign conveniences, integer-multiple,
  and a 0 to 100 percentage. Common config helpers.
- `Secret`, `SecretValue`: wrap a validated value in a carrier that hides it from
  `repr`/`str`/errors, so credentials do not leak into logs. Like pydantic's
  `SecretStr`; voluptuous has no equivalent.
- `NonEmpty`, `Byte`, `SmallFloat`, `IsRegex`: a non-empty check, 0 to 255 and 0
  to 1 bounded numbers, and a "value is a compilable regex" check.
- `JSONString`, `YAMLString`: parse a JSON or YAML string and optionally validate
  the decoded value. YAML uses the safe loader.
- `IsSymlink`, `IsSocket`, `IsFifo`, `IsBlockDevice`: filesystem predicates for the
  special file types, alongside `IsDir`/`IsFile`.
- `Alpha`, `Alphanumeric`, `ASCII`, `PrintableASCII`, `NoWhitespace`,
  `StartsWith`, `EndsWith`, `ByteLength`, `HexColor`: character-class and affix
  string checks, UTF-8 byte length, and a hex color.
- `Base64`, `Hex`, `Sorted`, `ULID`, `Latitude`, `Longitude`: base64/hex
  validation, an ascending-order check, a ULID, and geographic coordinate bounds.
- `CreditCard`, `IBAN`, `DataURI`, `E164`: format and checksum validators (Luhn,
  ISO 13616 mod-97, RFC 2397 data URIs, international phone format). Pure checks, no
  network or extra dependency. voluptuous has none of these.
- `RequiredWith`, `RequiredWithout`, `RequiredIf`, `Check`: cross-field rules over a
  whole mapping (used after a dict schema with `All`), for conditional requirements
  (on a key's presence, absence, or value, combined with an any/all mode) and an
  arbitrary predicate. voluptuous has no equivalent.
- `AtLeastOne`, `AtMostOne`, `ExactlyOne`: key-group presence rules over a mapping,
  for how many of a set of keys may or must appear. The dict-level form of
  `Inclusive`/`Exclusive`. Home Assistant rolls its own `has_at_least_one_key`;
  voluptuous has no equivalent.
- `Immutable`, `WriteOnce`: transition rules that compare new data against its
  previous value (passed as the call's `context`), rejecting a change to an
  immutable field or a second write to a write-once one. voluptuous has no
  equivalent.
- `ExtraKeysInvalid` with `.candidates`: an unknown key under `PREVENT_EXTRA`
  reports the closest known keys ("did you mean ...?") and carries them on the
  error, instead of a bare "extra keys not allowed". ESPHome forks voluptuous
  internals for this; first-class here, so any consumer gets the suggestion.
- `__probatio_validate__`: a protocol a type defines (a classmethod) to validate a
  raw value of itself, used in place of the bare `isinstance` check when that type
  is a schema. `EnumInvalid` is the error its built-in consumer (an enum class)
  raises. voluptuous has no such hook.
- `register_type`, `type_registry`, `clear_type_registry`: a registry mapping a
  type to a validator, consulted by the annotation-driven builders (the dataclass
  schema today) so coercion of a type like `datetime` is opt-in and applies
  wherever the type appears. Process-wide or scoped to a `with` block. voluptuous
  has no equivalent.
- `current_context` with `schema(data, context=...)`: an optional call argument
  that hands per-call state to validators that read `current_context()`, so one
  compiled schema validates against state known only at call time. Additive (a
  plain `schema(data)` is unchanged). voluptuous has no equivalent.

## Intentional deviations

Compatibility is the target, so this list is short. Each entry is a deliberate
improvement over a sharp edge, not a regression.

Each entry reads the same way: the behavior, then what voluptuous does, then what
Probatio does.

- **Recursive `Self` on cyclic or very deep data.** voluptuous crashes with
  `RecursionError`. Probatio raises a clean `Invalid` with a path, caught with the
  rest of your errors. The depth limit tracks a fraction of the interpreter's
  recursion limit, so raising `sys.setrecursionlimit` allows deeper data, up to the
  point where the operating system's own stack is the real ceiling; past that a
  very high limit can still overflow, so keep the limit within reason.
- **`from_json_schema` on untrusted input.** voluptuous can hang or overflow the
  stack. Probatio refuses a catastrophically backtracking `pattern` and a
  pathologically deep document with `SchemaError`.
- **`MultipleInvalid.error_type`.** voluptuous has no such attribute. Probatio
  proxies the first error's type. Additive, so existing code is unaffected.
- **Missing complex required key (`Required(Any("a", "b"))`).** voluptuous reports
  it twice (the "at least one of [...]" error plus a redundant "required key not
  provided"). Probatio reports the single meaningful error; the first error matches
  voluptuous.
- **Non-dict `Mapping` input (a `MappingProxyType`, a multidict, a custom
  mapping).** voluptuous rejects it with "expected a dictionary". Probatio
  validates any object implementing the `Mapping` protocol and returns a plain
  `dict`. A strict superset, so existing dict code is unaffected.
- **A callable validator raising `ValueError("reason")`.** voluptuous reports a
  bare "not a valid value", dropping the reason. Probatio appends it: "not a valid
  value: reason". A `ValueError` with no message stays bare.
- **An enum member as a schema or mapping key (`{Color.RED: str}`).** voluptuous
  rejects it with `SchemaError` (added upstream in [PR #537](https://github.com/alecthomas/voluptuous/pull/537), not yet released).
  Probatio accepts it: a member is matched by equality as a scalar, and works as a
  literal key, with `Required`/`Optional`, and as a value.
- **An enum class as a schema (`Schema(Color)`).** voluptuous treats it as a type
  and validates by `isinstance`, so it accepts only an already-built member and
  rejects the member's value. Probatio accepts a member unchanged or any value that
  maps to one, returning the member, so the string a loader hands you (`"red"`)
  validates and you get `Color.RED` back. A strict widening: input that was valid
  before still is, and the rejection now carries the list of valid values.
  Acceptance is whatever the enum's own constructor allows, so an `IntEnum` takes a
  numeric equivalent (`1.0`, `True`) and an `IntFlag` builds a combined value from
  any integer (`Schema(Perm)(3)` is `Perm.R | Perm.W`), the same as `Coerce` of
  that enum. Use an explicit `In([...])` when you need to accept only the exact
  listed members.
- **A built-in validator on a wrong-typed value (`Replace("a", "b")(42)`,
  `Number()(None)`).** voluptuous leaks a raw `TypeError`/`ValueError` from the
  underlying call (fixed upstream in [PR #540](https://github.com/alecthomas/voluptuous/pull/540) and [PR #539](https://github.com/alecthomas/voluptuous/pull/539), not yet released).
  Probatio raises a clean `Invalid` (a `MatchInvalid` for `Replace`, an `Invalid`
  for `Number`).
- **A signaling `Decimal` (`Decimal("sNaN")`) compared by a numeric validator
  (`Range`, `In`, `Equal`, `MultipleOf`).** A signaling NaN raises
  `decimal.InvalidOperation` on any comparison, which voluptuous leaks. Probatio
  catches the `ArithmeticError` and reports a clean `Invalid` (the value fails the
  check), so a crafted value cannot leak a raw exception.
- **A quoted email local part (`"a..b"@example.com`).** voluptuous's email regex
  accepts the RFC quoted-string form of the local part; Probatio's `Email` does
  not (it validates the common unquoted form with plain string checks, no
  backtracking regex). The quoted form is effectively never used in configuration.
- **`extend` with another `Schema` (`base.extend(other_schema)`).** voluptuous
  raises `AssertionError` (added upstream in [PR #538](https://github.com/alecthomas/voluptuous/pull/538), not yet released). Probatio
  merges the extension's keys with its `required` intent preserved (recursively);
  its `extra` must match the result's, so pass its `.schema` dict for a raw merge.
- **A list with several failing items (`[{"name": str}]` against two bad items).**
  voluptuous stops at the first failing nested item, reporting one error (open
  request, [issue #171](https://github.com/alecthomas/voluptuous/issues/171)). Probatio reports every failing item, each with its index in
  the path. Existing error-iterating code is unaffected.
- **A set schema with a transforming element (`{Coerce(int)}`).** voluptuous
  returns the set with its elements untransformed (bug, [issue #400](https://github.com/alecthomas/voluptuous/issues/400)). Probatio
  applies the element schema to set items like it does to a list, so a `Coerce`
  actually coerces.
- **A failing `Any` whose branches are all concrete (`Any(int, str, None)`).**
  voluptuous reports only the first branch ("expected int") or "not a valid value"
  (open request, [issue #412](https://github.com/alecthomas/voluptuous/issues/412)). Probatio lists every expected branch ("expected int
  or str or None") as `AnyInvalid`. A branch that is an arbitrary validator has no
  label, so `Any` still surfaces that branch's error.
- **An unknown key under `PREVENT_EXTRA` (`{"name": str}` given `{"nmae": ...}`).**
  voluptuous raises a bare `Invalid("extra keys not allowed")`. Probatio raises
  `ExtraKeysInvalid("not a valid option, did you mean 'name'?")`, carrying the
  close matches on `.candidates`. The stable `code` stays `extra_keys_not_allowed`,
  so code matching on it is unaffected; only the rendered string changed.
- **Keyword parameter names.** Probatio renames a few of voluptuous's parameters
  for clarity: `Lower`, `Upper`, `Capitalize`, `Title`, `Strip` take
  `value` (voluptuous `v`); `Marker`/`Remove` take `schema` (voluptuous `schema_`);
  `Msg` takes `validator` (voluptuous `schema`); `DefaultTo` takes `default`
  (voluptuous `default_value`). Positional calls are unaffected; only keyword
  callers using the old names need to update.
- **`Inclusive` positional argument order.** Probatio is
  `Inclusive(key, group, msg=None, default=UNDEFINED, description=None)`, matching
  the other markers; voluptuous puts `description` before `default`. Pass `default`
  and `description` by keyword to be safe across both.
- **`discriminant` on `All`/`Any`.** A tagged-union discriminant is honored on
  `Union` (alias `Switch`), not on `All`/`Any`; passing it to `All`/`Any` has no
  effect. Use `Union` for a discriminated union.
- **An `ExactSequence` element error carries the element's index in the path**
  (`@ data[1]`), where voluptuous reports the bare parent path. Probatio's path is
  more precise; existing path-walking code sees a deeper path.
- **The order of multiple missing-required-key errors** is the schema's definition
  order in Probatio, and hash (set) order in voluptuous. The first error still
  matches whenever any non-missing error is present; only the ordering among
  several all-missing keys differs.

These match what the [Compatibility](/getting-started/compatibility/) and
[Migrating from voluptuous](/getting-started/migrating-from-voluptuous/) pages
describe. If you hit a difference that is not here, treat it as a bug.

## What Probatio does not mirror

Voluptuous has no `__all__`, so `dir(voluptuous)` returns everything the module
happens to import: standard-library modules, regex constants, and internal
helpers, none of which are part of its intended public API. Probatio defines an
explicit `__all__` and does not re-export these. Reaching for one of them was
already reaching into voluptuous internals.

The notable names, so you are not surprised:

- `Enum`: the standard-library `enum.Enum`, leaked into the namespace. Reach for
  `import enum`.
- `Decimal`, `InvalidOperation`: the standard-library `decimal` types. Reach for
  `from decimal import Decimal`.
- `Generator`: `collections.abc.Generator`. Reach for
  `from collections.abc import Generator`.
- `collections`, `datetime`, `inspect`, `itertools`, `os`, `re`, `sys`, `typing`,
  `urlparse`: imported standard-library modules. Import them yourself.
- `DOMAIN_REGEX`, `USER_REGEX`, `primitive_types`: internal regex and type
  constants. Not public; do not depend on them.
- `DefaultFactory`, `VirtualPathComponent`: internal type aliases and helpers. Not
  public.
- `extra`, `cache`, `wraps`, `contextmanager`, `basestring`: internal helpers and
  imported builtins. Not public.
- `er`: an alias of `voluptuous.error`. Use the `error` submodule directly.

None of these are validators or markers. If your code uses one, it is coupled to
a voluptuous implementation detail, and you want to import the real thing
directly.

## Submodule imports

The submodules resolve too, so code that imports voluptuous internals has a
Probatio counterpart.

| voluptuous module | Probatio module |
| --- | --- |
| `voluptuous` | `probatio` |
| `voluptuous.error` | `probatio.error` |
| `voluptuous.validators` | `probatio.validators` |
| `voluptuous.humanize` | `probatio.humanize` |
| `voluptuous.schema_builder` | `probatio.schema` |

For dependencies that import voluptuous internals under the `voluptuous` name
(not Probatio), `probatio.compat.install_as_voluptuous()` aliases Probatio into
`sys.modules` so every later `import voluptuous` resolves to probatio. The
[Compatibility](/getting-started/compatibility/) page covers what it registers
and how and when to call it.
