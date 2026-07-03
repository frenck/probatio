---
title: Built-in validators
description: A tour of the validators Probatio ships with, grouped by what they check.
---

A validator is a callable that takes a value and returns it (possibly
normalized), or raises `Invalid`. Probatio ships a stack of them so you rarely
have to write your own. This page walks the toolbox by category, with a short
runnable example for nearly all of them.

These are the leaf validators. The combinators that compose them (`All`, `Any`,
`Union`, `SomeOf`) live in the [combinators guide](/guides/combinators/), and the
dictionary markers (`Required`, `Optional`, and friends) in the [dict schemas and
markers guide](/guides/dict-schemas-and-markers/). You will see those names in
passing here; this page is about the leaves. For the whole toolbox at a glance,
including the transformers that change a value rather than check it, see
[Built-ins by role](/reference/builtins-by-role/).

:::note
Every validator is importable straight from `probatio`, for example
`from probatio import Range, Coerce`.
:::

## Type and value

These check what a value is, or what it equals.

`Coerce` converts with `type(value)` and reports a clean `CoerceInvalid` when the
conversion fails. `Boolean()` reads common truthy and falsy strings (`"yes"`,
`"on"`, `"off"`, and such) as a `bool`; it is a factory, so call it. `Literal`
and `Equal` pin a value to a constant. `In` and `NotIn` test membership,
`Contains` tests the other direction, and `Match` runs a regular expression.

```python
from probatio import Schema, Coerce, Boolean, Literal, Equal

Schema(Coerce(int))("42")   # 42
Schema(Boolean())("on")     # True
Schema(Boolean())("off")    # False
Schema(Literal("on"))("on") # 'on'
Schema(Equal(3))(3)         # 3
```

```python
from probatio import Schema, In, NotIn, Contains, Match

Schema(In(["red", "green", "blue"]))("green")  # 'green'
Schema(NotIn(["root", "admin"]))("frenck")     # 'frenck'
Schema(Contains(2))([1, 2, 3])                 # [1, 2, 3]
Schema(Match(r"^[a-z]+$"))("probatio")         # 'probatio'
```

`Coerce` raises when the value cannot be converted:

<!-- verify: raises MultipleInvalid -->

```python
from probatio import Schema, Coerce

Schema(Coerce(int))("not a number")
```

## Numbers

Numeric bounds and conversions.

`Range` checks that a value falls within `min` and `max`. Both endpoints are
inclusive by default; set `min_included=False` or `max_included=False` for an
open bound. `Clamp` pins a value into the range instead of failing. `Number`
validates a numeric string, optionally checking its precision (significant
digits) and scale (decimal places).

```python
from probatio import Schema, Range, Clamp, Number

Schema(Range(min=1, max=10))(5)                  # 5
Schema(Range(min=0, max=1, max_included=False))(0.5)  # 0.5
Schema(Clamp(min=0, max=100))(150)               # 100
Schema(Number(precision=4, scale=2))("12.34")    # '12.34'
```

`Positive`, `Negative`, and `NonNegative` are sign conveniences over `Range`.
`Byte` (0 to 255) and `SmallFloat` (0 to 1) are bounded ranges, and `Latitude`
(-90 to 90) and `Longitude` (-180 to 180) bound geographic coordinates.
`MultipleOf` requires an integer multiple. `Percentage` validates a number, a bare
numeric string, or a `"NN%"` string in 0 to 100 and returns it unchanged;
`FromPercentage` parses it to a float. None of these coerce the type otherwise; wrap
with `Coerce` for that (`All(Coerce(int), NonNegative())`).

```python
from probatio import (
    Schema, Positive, MultipleOf, Percentage, FromPercentage, Latitude, Longitude,
)

Schema(Positive())(5)               # 5
Schema(MultipleOf(15))(45)          # 45
Schema(Percentage())("80%")         # '80%'
Schema(FromPercentage())("80%")     # 80.0
Schema(Latitude())(52.37)           # 52.37
Schema(Longitude())(4.9)            # 4.9
```

## Collections and structure

These shape sequences, sets, and objects.

`Length` bounds the length of a sized value. `Unique` requires distinct items.
`Set` turns an iterable into a `set` (handy because JSON has no set type, so sets
arrive as lists). `ExactSequence` validates a fixed-length sequence position by
position, `Unordered` does the same but lets the items appear in any order.
`Object` validates an object's attributes like a mapping. `Maybe` allows `None`,
otherwise it defers to the wrapped validator. `EnsureList` normalizes the common
"one value or a list of them" shape: a scalar becomes a single-item list, a list
passes through, and `None` becomes an empty list. `NonEmpty` requires a sized
value (string, list, mapping) to not be empty.

```python
from probatio import Schema, Length, Unique, ExactSequence, Unordered, Maybe, EnsureList

Schema(Length(min=1, max=3))([1, 2])      # [1, 2]
Schema(Unique())([1, 2, 3])               # [1, 2, 3]
Schema(ExactSequence([str, int]))(["a", 1])  # ['a', 1]
Schema(Unordered([str, int]))([1, "a"])   # [1, 'a']
Schema(Maybe(int))(None)                  # None
Schema(Maybe(int))(5)                     # 5
Schema(EnsureList())("one")               # ['one']
```

`Sorted` requires a collection to already be in order (it does not reorder):

```python
from probatio import Schema, Sorted

Schema(Sorted())([1, 2, 3])  # [1, 2, 3]
```

`Set` returns a real set, so its repr ordering is not stable:

```python
from probatio import Schema, Set

result = Schema(Set())([1, 2, 2, 3])
sorted(result)  # [1, 2, 3]
```

`Object` rebuilds an object of the same type after validating its attributes:

```python
from probatio import Schema, Object

class Point:
    def __init__(self, x, y):
        self.x, self.y = x, y

result = Schema(Object({"x": int, "y": int}))(Point(1, 2))
result.x  # 1
result.y  # 2
```

## Strings

Two kinds live here: transforms that rewrite the value, and format validators
that check it.

The transforms (`Lower`, `Upper`, `Capitalize`, `Title`, `Strip`) are plain
functions, not classes. Use them bare, `Lower`, not `Lower()`. `Replace`
substitutes a pattern. The format validators (`Email()`, `Url()`, `FqdnUrl()`)
are factories, so you call them to build the validator, matching voluptuous.
They avoid backtracking regular expressions, so a crafted input cannot hang them.

```python
from probatio import Schema, Lower, Upper, Capitalize, Title, Strip, Replace

Schema(Lower)("HELLO")            # 'hello'
Schema(Upper)("hello")            # 'HELLO'
Schema(Capitalize)("hello world") # 'Hello world'
Schema(Title)("hello world")      # 'Hello World'
Schema(Strip)("  hi  ")           # 'hi'
Schema(Replace("-", "_"))("a-b-c")  # 'a_b_c'
```

```python
from probatio import Schema, Email, Url, FqdnUrl

Schema(Email())("me@example.com")          # 'me@example.com'
Schema(Url())("https://example.com/path")  # 'https://example.com/path'
Schema(FqdnUrl())("https://example.com")   # 'https://example.com'
```

`Slug` validates a slug (lowercase alphanumerics with hyphen or underscore
separators), returning it unchanged. It checks the shape; it does not slugify
arbitrary text (transliteration belongs to a dedicated package, reached with
`Coerce`). `IsRegex` checks that the value is itself a compilable regular
expression (it validates the pattern, it does not run it).

```python
from probatio import Schema, Slug

Schema(Slug())("my-config_key-2")  # 'my-config_key-2'
```

More string checks: the character classes `Alpha`, `Alphanumeric`, `ASCII`,
`PrintableASCII`, and `NoWhitespace`; the affix checks `StartsWith` and
`EndsWith`; `ByteLength` (UTF-8 bytes, not code points); and `HexColor`.

```python
from probatio import Schema, Alphanumeric, StartsWith, HexColor

Schema(Alphanumeric())("abc123")     # 'abc123'
Schema(StartsWith("https://"))("https://example.com")  # 'https://example.com'
Schema(HexColor())("#FF8800")        # '#FF8800' (validated, unchanged; use Lower to fold case)
```

:::tip
The transforms coerce to a string first, so `Lower(123)` returns `"123"`. If you
want to reject non-strings, put a `str` check ahead of the transform with `All`.
:::

## Format and checksum

A handful of validators check a structured format or a checksum, all pure (no
network, no extra dependency). Like the network validators below, these are
Probatio additions with no voluptuous equivalent: `CreditCard` (the Luhn
check), `IBAN` (the ISO 13616
mod-97 check), `DataURI` (an RFC 2397 `data:` URI), and `E164` (a phone number in
international format). By default `CreditCard`, `IBAN`, and `E164` canonicalize the
input (strip grouping, upper-case the IBAN); pass `normalize=False` to validate and
return the value unchanged.

```python
from probatio import Schema, CreditCard, IBAN, E164

Schema(CreditCard())("4242 4242 4242 4242")     # '4242424242424242'
Schema(IBAN())("de89 3704 0044 0532 0130 00")   # 'DE89370400440532013000'
Schema(E164())("+1 (415) 555-2671")             # '+14155552671'
Schema(E164(normalize=False))("+14155552671")   # '+14155552671' (unchanged)
```

These check shape, not existence: `CreditCard` confirms the Luhn checksum, not that
the card is real, and `E164` confirms the international format, not that the number
is dialable (which needs a phone-number database).

## Date and time

`Datetime` and `Date` validate a string against a `strptime` format, returning
the string unchanged when it parses. `Datetime` defaults to ISO 8601
(`%Y-%m-%dT%H:%M:%S.%fZ`), `Date` defaults to `%Y-%m-%d`. Pass `format=` for
anything else.

```python
from probatio import Schema, Datetime, Date

Schema(Datetime())("2026-06-25T10:30:00.000000Z")  # '2026-06-25T10:30:00.000000Z'
Schema(Date())("2026-06-25")                        # '2026-06-25'
Schema(Date(format="%d/%m/%Y"))("25/06/2026")       # '25/06/2026'
```

`Time` is the time-of-day sibling, defaulting to `%H:%M:%S`. `Duration` validates a
duration (a `timedelta`, a number of seconds as an `int`/`float`/numeric string, a
`H:MM[:SS]` string, an ISO 8601 duration like `P1DT2H30M`, or a `timedelta` keyword
mapping) and returns the value unchanged; `AsTimedelta` accepts the same forms and
returns the parsed `datetime.timedelta`, the same `Datetime`/`AsDatetime` split. An
ISO 8601 duration is limited to the fields a `timedelta` can represent (weeks, days,
hours, minutes, seconds); a year or a month is rejected, since neither is a fixed
length.

For time zones, `TimeZoneInfo` validates an IANA name (for the `ZoneInfo`
object itself, wrap the type: `Coerce(zoneinfo.ZoneInfo)`; its constructor
takes the name). `TimeZone` validates a fixed UTC offset (`+01:00`, `Z`,
`UTC`), with `AsTimezone` as the object-returning sibling that parses the
offset into a `datetime.timezone`.

```python
import zoneinfo

from probatio import (
    Schema, Time, Duration, AsTimedelta, TimeZone, TimeZoneInfo, AsTimezone, Coerce,
)

Schema(Time())("14:30:00")                  # '14:30:00'
Schema(Duration())("1:30:00")               # '1:30:00'
Schema(AsTimedelta())("1:30:00")            # datetime.timedelta(seconds=5400)
Schema(AsTimedelta())("P1DT2H30M")          # datetime.timedelta(days=1, seconds=9000)
Schema(TimeZoneInfo())("Europe/Amsterdam")  # 'Europe/Amsterdam'
Schema(Coerce(zoneinfo.ZoneInfo))("Europe/Amsterdam")  # zoneinfo.ZoneInfo(key='Europe/Amsterdam')
Schema(TimeZone())("+01:00")                # '+01:00'
Schema(AsTimezone())("+01:00")              # datetime.timezone(datetime.timedelta(seconds=3600))
```

`AsDatetime`, `AsDate`, and `AsTime` are the object-returning siblings of
`Datetime`, `Date`, and `Time`. They return the parsed `datetime`, `date`, or
`time` instead of the original string, and they parse ISO 8601 out of the box, so
no `format=` is needed for the common case. Pass `format=` to parse a specific
`strptime` layout instead. `AsDatetime` takes `require_timezone=True` to reject a
naive result; the ISO default reads the offset, so that needs no extra format. A
native object passes straight through, so a `datetime`, `date`, or `time` that a
YAML or TOML loader already produced validates without a round-trip (and `AsDate`
rejects a `datetime`, since it carries a time a pure date would drop).

```python
from probatio import Schema, AsDatetime, AsDate, AsTime

Schema(AsDate())("2026-06-25")                    # datetime.date(2026, 6, 25)
Schema(AsTime())("14:30:00")                      # datetime.time(14, 30)
Schema(AsDatetime())("2026-06-25T10:30:00+02:00")
# datetime.datetime(2026, 6, 25, 10, 30, tzinfo=datetime.timezone(datetime.timedelta(seconds=7200)))
Schema(AsDatetime(format="%d/%m/%Y %H:%M"))("25/06/2026 10:30")
# datetime.datetime(2026, 6, 25, 10, 30)
```

Reach for these when the next step wants a real object instead of a string;
`Datetime`/`Date`/`Time` stay string-in, string-out for voluptuous compatibility.
Parsing uses the standard library on purpose: a faster backend like ciso8601
accepts a different set of strings and returns a different `tzinfo` type, which
would make validation depend on what happens to be installed.

`FromEpoch` reads a Unix timestamp (an `int` or `float`) into a timezone-aware UTC
`datetime`. It takes `unit="seconds"` by default or `unit="milliseconds"`. The
result is always UTC: a naive, local datetime would depend on the host's time
zone, so the same input would validate to a different moment on a different
machine.

```python
from probatio import Schema, FromEpoch

Schema(FromEpoch())(1719571800)
# datetime.datetime(2024, 6, 28, 10, 50, tzinfo=datetime.timezone.utc)
Schema(FromEpoch(unit="milliseconds"))(1719571800000)
# datetime.datetime(2024, 6, 28, 10, 50, tzinfo=datetime.timezone.utc)
```

## Network and identifiers

These have no voluptuous equivalent; they are Probatio additions. They validate
and return the value unchanged: `IPv4Address`/`IPv6Address`/`IPAddress`/`IPNetwork`
check the address or network, `UUID` checks a UUID, `MacAddress` a MAC address,
`Hostname` and `Fqdn` a name, and `Port` returns an `int`. When you want the parsed
Python object rather than the validated string, wrap the type with `Coerce` (its
constructor takes the string), and use `NormalizeMacAddress` for a canonical MAC.

```python
from probatio import Schema, IPAddress, UUID, MacAddress, Port, ULID

Schema(IPAddress())("192.0.2.1")  # '192.0.2.1'
Schema(UUID())("12345678-1234-5678-1234-567812345678")
# '12345678-1234-5678-1234-567812345678'
Schema(MacAddress())("AA-BB-CC-DD-EE-FF")  # 'AA-BB-CC-DD-EE-FF'
Schema(Port())("8080")  # 8080
Schema(ULID())("01ARZ3NDEKTSV4RRFFQ69G5FAV")  # '01ARZ3NDEKTSV4RRFFQ69G5FAV'
```

Reach for `Coerce` when you want the object instead of the validated string:

```python
import ipaddress
from uuid import UUID as UUIDType

from probatio import Schema, Coerce

Schema(Coerce(ipaddress.IPv4Address))("192.0.2.1")  # IPv4Address('192.0.2.1')
Schema(Coerce(UUIDType))("12345678-1234-5678-1234-567812345678")
# UUID('12345678-1234-5678-1234-567812345678')
```

`NormalizeMacAddress` rewrites a MAC to a canonical form, lowercase and
colon-separated by default. Pass `upper=True` or a different `separator` (`""` for
bare hex); `MacAddress` itself only validates and returns the input unchanged:

```python
from probatio import Schema, NormalizeMacAddress

Schema(NormalizeMacAddress())("AA-BB-CC-DD-EE-FF")  # 'aa:bb:cc:dd:ee:ff'
Schema(NormalizeMacAddress(upper=True))("aa-bb-cc-dd-ee-ff")  # 'AA:BB:CC:DD:EE:FF'
Schema(NormalizeMacAddress(separator="-"))("aabbccddeeff")  # 'aa-bb-cc-dd-ee-ff'
```

`IPNetwork` accepts host bits (it validates, it does not normalize to the network);
`Hostname` takes a bare label, `Fqdn` requires a dotted name:

```python
from probatio import Schema, IPNetwork, Hostname, Fqdn

Schema(IPNetwork())("192.0.2.5/24")  # '192.0.2.5/24'
Schema(Hostname())("localhost")      # 'localhost'
Schema(Fqdn())("host.example.com")   # 'host.example.com'
```

## Encoding

`JSONString` and `YAMLString` validate that a string is valid JSON or YAML (and, with
an inner schema, that the decoded value matches it) and return the string unchanged.
`FromJSONString` and `FromYAMLString` are the decoding siblings: they parse the string
and return the decoded value. YAML is parsed with the safe loader, and the YAML
validators need a YAML backend installed (they raise a clear error at build time
otherwise).

```python
from probatio import Schema, JSONString, FromJSONString

Schema(JSONString())('{"a": 1, "b": [2, 3]}')          # '{"a": 1, "b": [2, 3]}'
Schema(FromJSONString())('{"a": 1, "b": [2, 3]}')      # {'a': 1, 'b': [2, 3]}
Schema(FromJSONString({"port": int}))('{"port": 8080}')  # {'port': 8080}
```

`Base64` and `Hex` validate that a string is a valid encoding (they return it
unchanged; decode it yourself with `Coerce` if you want the bytes).

```python
from probatio import Schema, Base64, Hex

Schema(Base64())("aGVsbG8=")  # 'aGVsbG8='
Schema(Hex())("deadbeef")     # 'deadbeef'
```

`HexInt` is the parsing sibling of `Hex`: it reads a hexadecimal string (a
leading `0x` is optional) and returns the `int`.

```python
from probatio import Schema, HexInt

Schema(HexInt())("ff")    # 255
Schema(HexInt())("0x1A")  # 26
```

## Filesystem

`IsDir`, `IsFile`, and `PathExists` check a path on disk, with `IsSymlink`,
`IsSocket`, `IsFifo`, and `IsBlockDevice` for the special file types. Because they
touch the real filesystem, the example below creates a temporary directory and
file first.

```python
import os
import tempfile
from probatio import Schema, IsDir, IsFile, PathExists

with tempfile.TemporaryDirectory() as path:
    file_path = os.path.join(path, "config.yaml")
    open(file_path, "w").close()

    Schema(IsDir())(path)          # an existing directory
    Schema(IsFile())(file_path)    # an existing file
    Schema(PathExists())(path)     # any existing path
```

## Truthiness

`IsTrue` requires a truthy value, `IsFalse` a falsy one. Both return the value
unchanged.

```python
from probatio import Schema, IsTrue, IsFalse

Schema(IsTrue())(1)   # 1
Schema(IsFalse())(0)  # 0
```

## Cross-field rules

A marker annotates one key. These three look at the whole mapping, so you place
them after a dict schema with `All`: the dict validates first, then the rule sees
the validated mapping.

`RequiredWith` makes keys conditional on a trigger key being present:
`RequiredWith("tls", "cert", "key")` requires `cert` and `key` whenever `tls` is
in the mapping. `RequiredWithout` is the mirror, requiring keys when a trigger is
_absent_: `RequiredWithout("cert", "cert_path")` requires `cert_path` when `cert`
is not given. `RequiredIf` keys on a value: `RequiredIf({"auth": "token"}, "token")`
requires the `token` key only when `auth` equals `"token"`. When the rule does not
fire, nothing is required and the mapping passes through unchanged.

Each takes several triggers (or conditions) with a `mode`. For the presence rules,
pass a list of trigger keys with `mode="any"` (the default, any one fires) or
`mode="all"` (every trigger must hold). For `RequiredIf`, several conditions
combine with `mode="all"` (the default, every condition must match) or
`mode="any"`.

```python
from probatio import Schema, All, Optional, RequiredWith

schema = Schema(
    All(
        {"tls": bool, Optional("cert"): str, Optional("key"): str},
        RequiredWith("tls", "cert", "key"),
    ),
)
schema({"tls": True, "cert": "c", "key": "k"})  # unchanged
schema({})                                      # unchanged, no trigger
```

`Check` runs an arbitrary predicate over the value with a paired message. A falsy
result, or a predicate that raises (a missing key, a wrong type), is reported with
that message, so a cross-field rule never leaks a raw exception.

```python
from probatio import Schema, All, Check

schema = Schema(
    All({"start": int, "end": int}, Check(lambda d: d["start"] < d["end"], "start must be before end")),
)
schema({"start": 1, "end": 2})  # unchanged
```

For a plain predicate on a single value, rather than a whole mapping, the
`truth` decorator (a voluptuous-compat helper) turns it into a validator; the
[custom validators guide](/guides/custom-validators/) covers it.

`AtLeastOne`, `AtMostOne`, `ExactlyOne`, and `AllOrNone` are the key-group
presence rules: how many of a set of keys may or must appear. `AtLeastOne("host",
"url")` requires one of the keys (or both); `AtMostOne("include", "exclude")`
allows one at most; `ExactlyOne("token", "password")` requires one and only one;
`AllOrNone("lat", "lon")` requires either all of the keys or none of them. They are
the dict-level form of `Inclusive`/`Exclusive`, handy when the constraint reads
more naturally as a standalone check than as a marker on each key.

```python
from probatio import Schema, AtLeastOne, AtMostOne, ExactlyOne, AllOrNone

Schema(AtLeastOne("host", "url"))({"host": "nas"})       # unchanged
Schema(AtMostOne("include", "exclude"))({"include": 1})  # unchanged
Schema(ExactlyOne("token", "password"))({"token": "t"})  # unchanged
Schema(AllOrNone("lat", "lon"))({"lat": 1, "lon": 2})    # unchanged
```

A non-mapping is rejected by default, so the rule stands on its own without an
enclosing dict schema. Pass `require_mapping=False` to leave a non-mapping
untouched when the rule sits inside a larger pipeline. When more than one key
conflicts (or, for `AllOrNone`, when a key is missing its partners), each offending
key is reported with its own path.

## Transition validators

When you validate an update, some fields must not change. `Immutable` and
`WriteOnce` compare the new data against its previous value, which you pass as the
call's `context` (see [call-time context](/guides/custom-validators/)). The same
compiled schema then checks every update. `Immutable` rejects any change to a
field; `WriteOnce` lets a field be set once (from absent or `None`) and freezes it
after. With no context (a first validation) they do nothing.

```python
from probatio import Schema, All, Required, Optional, Immutable, MultipleInvalid

schema = Schema(All({Required("id"): int, Optional("name"): str}, Immutable("id")))

old = {"id": 1, "name": "ada"}
schema({"id": 1, "name": "bob"}, context=old)  # name may change, unchanged otherwise

try:
    schema({"id": 2}, context=old)
except MultipleInvalid as err:
    print(err.errors[0].path)  # ['id'], with the message "'id' cannot be changed"
```

## Defaults and messages

These do not reject values; they patch them.

`DefaultTo` replaces `None` with a default and passes everything else through.
`SetTo` ignores the input and always produces a fixed value. `Msg` wraps another
validator and swaps its failure message for one you choose, which is the simplest
way to make an error read in your own words.

```python
from probatio import Schema, DefaultTo, SetTo

Schema(DefaultTo("fallback"))(None)     # 'fallback'
Schema(DefaultTo("fallback"))("value")  # 'value'
Schema(SetTo(42))("anything")           # 42
```

`Msg` rewrites the message on failure:

<!-- verify: raises MultipleInvalid -->

```python
from probatio import Schema, Msg, Range

Schema(Msg(Range(min=10), "too small"))(5)  # raises with: too small
```

## Where to next

- [Combinators](/guides/combinators/): compose these with `All`, `Any`, `Union`,
  and `SomeOf`.
- [Dict schemas and markers](/guides/dict-schemas-and-markers/): `Required`,
  `Optional`, defaults, and extra-key policy.
- [API reference](/reference/): every name and signature in one place.
