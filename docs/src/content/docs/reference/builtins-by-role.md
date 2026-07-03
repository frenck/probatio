---
title: Built-ins by role
description: Every built-in grouped by the job it does, split by the axis that matters most, whether it checks a value and hands it back or returns a changed one.
---

The [API reference](/reference/) lists every name with its signature, and the
[voluptuous compatibility](/reference/compatibility-matrix/) page maps each name
to its status against voluptuous. This page is the third lens: what _role_ each
built-in plays, so you can find the right tool by the job you need done rather
than by remembering its name.

Everything here splits into four roles:

- **Markers** are dictionary keys that carry intent (required, optional, secret).
- **Combinators** compose or wrap other validators (`All`, `Any`, `Maybe`).
- **Validators** check a value and return it unchanged.
- **Transformers** return a changed value.

The line that matters most runs between the last two. A validator is a gate: the
value passes through untouched or it raises. A transformer rewrites the value, so
the thing that comes out is not the thing that went in. Transformers split again
by whether the _type_ changes:

- A **converter** changes the type (`"5"` to `5`, `"192.0.2.1"` to an
  `IPv4Address`). Its name says so: `As<Type>` converts to a named type,
  `From<Source>` decodes a source, `Coerce` is the generic one.
- A **normalizer** keeps the type and cleans the value (`"ABC"` to `"abc"`, a
  number clamped into a range). Its name reads as an action on the value
  (`Lower`, `Strip`, `Clamp`).

Knowing the role tells you where a name belongs in a chain. Validators and
transformers run left to right inside `All`, so a converter early in the chain
decides the type every later step sees.

## Markers

Dictionary keys that carry intent. Each compares and hashes by its underlying
key, so a marker stands in for the bare key.

| Name        | Note                                           |
| ----------- | ---------------------------------------------- |
| `Required`  | The key must be present.                       |
| `Optional`  | The key may be present; a `default` fills in.  |
| `Remove`    | Drop matching keys from the output.            |
| `Extra`     | Catch-all key for the rest of a mapping.       |
| `Inclusive` | Group of keys that must appear together.       |
| `Exclusive` | Group of keys of which at most one may appear. |
| `Self`      | A recursive reference to the schema.           |
| `Forbidden` | The key must be absent.                        |
| `Alias`     | Accept the key under alternate input names.    |
| `Secret`    | Redact the key's value in error output.        |

## Combinators and wrappers

Compose or wrap other validators.

| Name     | Note                                                |
| -------- | --------------------------------------------------- |
| `All`    | Run each in turn; the output of one feeds the next. |
| `Any`    | The first that accepts wins.                        |
| `And`    | Alias of `All`.                                     |
| `Or`     | Alias of `Any`.                                     |
| `Union`  | `Any` with an optional discriminant.                |
| `Switch` | Alias of `Union`.                                   |
| `SomeOf` | Between `min_valid` and `max_valid` must pass.      |
| `Maybe`  | Accept `None`, otherwise the wrapped validator.     |
| `Msg`    | Override a validator's error message.               |

## Validators

Check a value and return it unchanged.

### Value and type

| Name            | Note                                 |
| --------------- | ------------------------------------ |
| `Literal`       | Equal to a literal value.            |
| `Equal`         | Equal to a target.                   |
| `In`            | A member of a container.             |
| `NotIn`         | Not a member of a container.         |
| `Contains`      | Contains a target value.             |
| `Match`         | Matches a regular expression.        |
| `IsRegex`       | A compilable regular expression.     |
| `Object`        | Attributes validated like a mapping. |
| `ExactSequence` | A sequence matching a fixed shape.   |
| `Unordered`     | A sequence in any order.             |
| `Unique`        | No duplicate elements.               |
| `Sorted`        | Already in ascending order.          |
| `Length`        | Length within bounds.                |
| `NonEmpty`      | Not empty.                           |

### Numbers

| Name          | Note                                                |
| ------------- | --------------------------------------------------- |
| `Range`       | Within a numeric range.                             |
| `Number`      | A number; `yield_decimal=True` returns a `Decimal`. |
| `Positive`    | Greater than zero.                                  |
| `Negative`    | Less than zero.                                     |
| `NonNegative` | Zero or greater.                                    |
| `MultipleOf`  | An exact multiple of a base.                        |
| `Byte`        | An integer from 0 to 255.                           |
| `SmallFloat`  | A float from 0 to 1.                                |
| `Latitude`    | A valid latitude.                                   |
| `Longitude`   | A valid longitude.                                  |
| `Percentage`  | A number or `"NN%"` string in 0 to 100.             |

### Strings and formats

| Name             | Note                                           |
| ---------------- | ---------------------------------------------- |
| `Email`          | An email address.                              |
| `Url`            | A URL.                                         |
| `FqdnUrl`        | A URL with a fully qualified domain.           |
| `Slug`           | A URL slug.                                    |
| `Alpha`          | Letters only.                                  |
| `Alphanumeric`   | Letters and digits only.                       |
| `ASCII`          | ASCII characters only.                         |
| `PrintableASCII` | Printable ASCII only.                          |
| `NoWhitespace`   | No whitespace characters.                      |
| `StartsWith`     | Begins with a prefix.                          |
| `EndsWith`       | Ends with a suffix.                            |
| `ByteLength`     | UTF-8 byte length within bounds.               |
| `HexColor`       | A hex color; compose `Lower`/`Upper` for case. |
| `Hex`            | Hexadecimal; checks, does not decode.          |
| `Base64`         | Base64; checks, does not decode.               |
| `JSONString`     | A JSON string; value via `FromJSONString`.     |
| `YAMLString`     | A YAML string; value via `FromYAMLString`.     |
| `ULID`           | A ULID; compose `Upper` for canonical case.    |
| `CreditCard`     | A card number (Luhn).                          |
| `IBAN`           | An IBAN (mod-97).                              |
| `DataURI`        | A `data:` URI.                                 |
| `E164`           | An E.164 phone number.                         |
| `Datetime`       | A datetime string; string in, string out.      |
| `Date`           | A date string; string in, string out.          |
| `Time`           | A time string; string in, string out.          |
| `Duration`       | A duration string; object via `AsTimedelta`.   |
| `TimeZone`       | A UTC offset; object via `AsTimezone`.         |
| `TimeZoneInfo`   | An IANA name; object via `Coerce(ZoneInfo)`.   |

### Network and identifier

Check the format and return the string unchanged. The parsed object is opt-in
through `Coerce`, since each of these types constructs from its string.

| Name          | Note                                                     |
| ------------- | -------------------------------------------------------- |
| `Hostname`    | A hostname.                                              |
| `Fqdn`        | A fully qualified domain name.                           |
| `Port`        | A TCP/UDP port number.                                   |
| `MacAddress`  | A MAC address; canonical form via `NormalizeMacAddress`. |
| `UUID`        | A UUID; object via `Coerce(uuid.UUID)`.                  |
| `IPv4Address` | Object via `Coerce(ipaddress.IPv4Address)`.              |
| `IPv6Address` | Object via `Coerce(ipaddress.IPv6Address)`.              |
| `IPAddress`   | Object via `Coerce(ipaddress.ip_address)`.               |
| `IPNetwork`   | Object via `Coerce(ipaddress.ip_network)`.               |

### Filesystem

| Name            | Note                   |
| --------------- | ---------------------- |
| `IsDir`         | An existing directory. |
| `IsFile`        | An existing file.      |
| `PathExists`    | An existing path.      |
| `IsSymlink`     | A symbolic link.       |
| `IsSocket`      | A socket.              |
| `IsFifo`        | A FIFO.                |
| `IsBlockDevice` | A block device.        |

### Truthiness

| Name      | Note            |
| --------- | --------------- |
| `IsTrue`  | A truthy value. |
| `IsFalse` | A falsy value.  |

### Cross-field and mapping rules

Run over a whole mapping, usually after a dict schema with `All`.

| Name              | Note                                      |
| ----------------- | ----------------------------------------- |
| `RequiredWith`    | Required when another key is present.     |
| `RequiredWithout` | Required when another key is absent.      |
| `RequiredIf`      | Required when a condition holds.          |
| `Check`           | An arbitrary predicate over the mapping.  |
| `AtLeastOne`      | At least one of a set of keys is present. |
| `AtMostOne`       | At most one of a set of keys is present.  |
| `ExactlyOne`      | Exactly one of a set of keys is present.  |
| `AllOrNone`       | All of a set of keys, or none.            |
| `Immutable`       | Rejects a change against the prior value. |
| `WriteOnce`       | Rejects a second write.                   |

## Transformers

Return a changed value.

### Converters

The type changes.

| Name             | Result                                    |
| ---------------- | ----------------------------------------- |
| `Coerce`         | `type(value)`, the generic convert.       |
| `Boolean`        | A string to a `bool`.                     |
| `Set`            | An iterable to a `set`.                   |
| `EnsureList`     | A scalar to a one-element `list`.         |
| `AsDatetime`     | A string to a `datetime`.                 |
| `AsDate`         | A string to a `date`.                     |
| `AsTime`         | A string to a `time`.                     |
| `AsTimedelta`    | A duration to a `timedelta`.              |
| `AsTimezone`     | An offset to a `datetime.timezone`.       |
| `FromEpoch`      | A timestamp to a `datetime`.              |
| `FromPercentage` | `"80%"` to a `float`.                     |
| `HexInt`         | A hex string to an `int`.                 |
| `FromJSONString` | A JSON string to the decoded value.       |
| `FromYAMLString` | A YAML string to the decoded value.       |
| `DefaultTo`      | `None` to a default (substitution).       |
| `SetTo`          | Anything to a fixed value (substitution). |

### Normalizers

The type stays; the value is cleaned.

| Name                  | Result                           |
| --------------------- | -------------------------------- |
| `Lower`               | Lowercase.                       |
| `Upper`               | Uppercase.                       |
| `Capitalize`          | Capitalized.                     |
| `Title`               | Title-cased.                     |
| `Strip`               | Whitespace trimmed.              |
| `Replace`             | Regular-expression replace.      |
| `Clamp`               | A number pinned into a range.    |
| `NormalizeMacAddress` | A MAC address in canonical form. |
