---
title: Loading and dumping
description: Parse JSON, YAML, or TOML with your own library, then validate the result with Probatio.
---

Validation works on Python values, but data arrives as text: a JSON request
body, a YAML config file, a TOML manifest. Probatio does not parse any of it.
It validates the parsed object, and parsing (and serializing back out) stays
with you, using whatever library you already trust for the format. That keeps a
whole class of parser bugs and dependencies out of the library, and it means you
are never surprised by which parser happens to be installed.

This is the same split voluptuous, pydantic (`model_validate`), marshmallow, and
cattrs draw: the validator takes an object, you own the bytes. The examples here
use [orjson](https://github.com/ijl/orjson) and
[YAMLRocks](https://pypi.org/project/yamlrocks/) as fast, concrete choices, but
nothing about Probatio ties you to them.

## Loading

Parse the text yourself, then hand the result to a schema. JSON parses with the
standard library, so the two-liner works on a bare install:

```python
import json
from probatio import Schema, Required

schema = Schema({Required("port"): int})
schema(json.loads('{"port": 8080}'))  # {'port': 8080}
```

Swapping in a faster parser is a one-import change; the schema call is identical.
With orjson:

<!-- verify: skip -->

```python
import orjson
from probatio import Schema, Required

schema = Schema({Required("port"): int})
schema(orjson.loads('{"port": 8080}'))  # {'port': 8080}
```

YAML has no standard-library parser. Reach for YAMLRocks (fast, YAML 1.2, and
bomb-resistant) or PyYAML, and always use a safe load for untrusted input:

<!-- verify: skip -->

```python
import yamlrocks
from probatio import Schema, Required

schema = Schema({Required("port"): int})
schema(yamlrocks.loads("port: 8080"))  # {'port': 8080}
```

TOML reads with the standard library's `tomllib` (Python 3.11 and newer):

```python
import tomllib
from probatio import Schema, Required

schema = Schema({Required("port"): int})
schema(tomllib.loads("port = 8080"))  # {'port': 8080}
```

:::caution[Untrusted YAML]
Use a safe loader for YAML you did not write. PyYAML's `yaml.load` builds
arbitrary Python objects from tags in the document; `yaml.safe_load` does not, so
a hostile payload cannot instantiate classes or run constructors. A safe load
still expands aliases, so a small document full of anchors that reference each
other (the billion-laughs pattern) can blow up to gigabytes of logical nodes.
YAMLRocks counts the expanded nodes and refuses a document that blows up; PyYAML
does not, so bound the input size when you rely on it.
:::

:::caution[YAML spec versions differ]
YAMLRocks implements YAML 1.2; PyYAML implements YAML 1.1. They parse a few inputs
differently. Under 1.1, the bare words `yes`, `no`, `on`, and `off` are booleans,
a leading-zero number like `0755` is octal, and `12:30` is a sexagesimal number;
under 1.2 all of these are plain strings or decimals. Quote these values in your
YAML (`"yes"`, `"0755"`) when the distinction matters, and validate with an
explicit type so the schema, not the parser, decides.
:::

## Dumping

Serialization is the mirror image: validate first, then serialize the validated
value with your own library. There is a catch worth stating plainly. A validated
value often carries types the text format has no native form for, like a
`datetime`, a `Decimal`, or a `set`. Turning those back into text is a decision
only you can make (an ISO string? a Unix timestamp? which format?), so it is your
`default` hook, not Probatio's job.

The standard library's `json.dumps` takes a `default` callable for exactly this:

```python
import json
from datetime import date
from decimal import Decimal

def to_jsonable(value):
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(type(value).__name__)

json.dumps({"when": date(2020, 1, 1)}, default=to_jsonable)  # '{"when": "2020-01-01"}'
```

orjson takes the same `default` argument and handles `datetime` natively, so the
hook only covers what it does not know:

<!-- verify: skip -->

```python
import orjson
from decimal import Decimal

def to_jsonable(value):
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(type(value).__name__)

orjson.dumps({"scale": Decimal("1.5")}, default=to_jsonable)  # b'{"scale":1.5}'
```

This is deliberately not a framework. Probatio's transforms run one way: `AsDate`
turns a string into a `date` on the way in, and it does not turn a `date` back
into the string it came from. If you need a faithful round-trip (a value dumped
in the same shape it was loaded), that is a bidirectional serializer's job, like
marshmallow, cattrs, or pydantic. Probatio validates; it does not serialize.

## Source locations

When a config fails validation, the useful question is _where in the file_.
Probatio's `humanize_error` accepts a `locator`: a callable you supply that maps
an error's `path` to a `Location` (`line`, `column`, and `file`), so each failure
line gains the place it points at, like `Got 70000 (at 2:9)`.

Building the locator needs a parser that records source positions. YAMLRocks
(0.5.0 and newer) carries them, so you can walk the located tree it returns and
resolve an error `path` to a position:

<!-- verify: skip -->

```python
from probatio import Schema, Required, Range, MultipleInvalid
from probatio.error import Location
from probatio.humanize import humanize_error

schema = Schema({Required("server"): {Required("port"): Range(min=1, max=65535)}})
data, positions = load_yaml_with_positions("server:\n  port: 70000\n")  # your loader

def locator(path):
    node = positions_at(positions, path)  # your lookup into the located tree
    return Location(node.line, node.column) if node else None

try:
    schema(data)
except MultipleInvalid as err:
    print(humanize_error(data, err, locator=locator))
# value must be at most 65535 at 'server.port'. Got 70000 (at 2:9)
```

`Location` is exported from `probatio` (it lives in `probatio.error`). It renders
as `file:line:column`, or programs can read its fields directly. Return `None`
from the locator for a path you cannot place.
