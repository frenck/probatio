---
title: Loading and dumping
description: Parse JSON, YAML, and TOML into Python, validate it, and write it back out.
---

Validation works on Python values, but data arrives as text: a JSON request
body, a YAML config file, a TOML manifest. Probatio reads and writes all three
through one set of functions. JSON read and write and TOML read work on the
standard library; YAML (read and write) and TOML write need an optional extra,
covered under [Backends](#backends) below. Every function here is exported from
the top level.

## Loading

The loaders parse text into Python values. There is one per format, plus a
unified entry point:

- `load_json(source)`, `load_yaml(source)`, `load_toml(source)`: parse a known
  format.
- `load(source, format=None)`: dispatch on `format`, or auto-detect it from a
  path extension when `format` is omitted.

A `source` is the content itself (a string or bytes), a `pathlib.Path` read from
disk, or a file-like object.

```python
from probatio import load_json

load_json('{"port": 8080}')  # {'port': 8080}
```

Parsing alone does not validate. A parsed value is whatever the text said, so
run it through a schema:

```python
from probatio import Schema, Required, load_json

schema = Schema({Required("port"): int})
schema(load_json('{"port": 8080}'))  # {'port': 8080}
```

That two-step is common enough that `Schema` has convenience methods to parse and
validate in one call: `schema.load_json(source)`, `schema.load_yaml(source)`,
`schema.load_toml(source)`, and `schema.load(source, format=None)`. Same result,
one step:

```python
from probatio import Schema, Required

schema = Schema({Required("port"): int})
schema.load_json('{"port": 8080}')  # {'port': 8080}
```

`load` infers the format from a path extension. Write a file, then read it back
without naming the format:

```python
from pathlib import Path
from probatio import load

Path("config.json").write_text('{"port": 8080}')
load(Path("config.json"))  # {'port': 8080}
```

:::caution[YAML is parsed safely]
`load_yaml` never uses an unsafe YAML loader. The input is untrusted by default,
so it sticks to a safe load that builds plain Python values, not arbitrary
objects. If you were relying on YAML constructing custom types for you, it will
not.
:::

:::caution[Use the fast backend for untrusted YAML]
A safe load still expands YAML aliases, so a small document full of anchors that
reference each other (the billion-laughs pattern) can blow up to gigabytes of
logical nodes. The backend decides whether that is contained. YAMLRocks (the
`probatio[fast]` backend) counts the expanded nodes and refuses a document that
blows up, so it is bomb-resistant. The PyYAML fallback is not: it shares the alias
references, so the document parses cheaply and the cost lands later, when the
structure is walked during validation. Prefer the fast backend for genuinely
untrusted YAML, and bound the input size when you are on the PyYAML fallback.
:::

## Dumping

The dumpers go the other way, serializing a value to text. The same shape: one
per format, plus a unified entry point.

- `dump_json(value)`, `dump_yaml(value)`, `dump_toml(value)`: serialize to a
  known format.
- `dump(value, format)`: dispatch on `format` (`"json"`, `"yaml"`, or `"toml"`).

```python
from probatio import dump_json, load_json

text = dump_json({"port": 8080})
load_json(text)  # {'port': 8080}
```

Before handing a value to the backend, the dumpers normalize the few non-native
types a validated value commonly carries: `Decimal` becomes a float, and `set`,
`frozenset`, and `tuple` become a list. The temporal types are format-aware. TOML
has native `datetime`, `date`, and `time`, so those pass through and round-trip as
the same type; JSON and YAML have no temporal types, so they become ISO 8601
strings. JSON also has no `nan` or `inf`, so a non-finite float is refused with a
clear error rather than silently corrupted (the fast backend would turn it into
`null`, the standard library into an invalid token). YAML and TOML keep non-finite
floats, since both can represent them. The normalization is one-way: a `set`,
`frozenset`, or `tuple` dumps as a list and loads back as a list, not as the
original type. This is a convenience for round-tripping validated data, not a
general serialization framework. Reach for a `default` hook or a dedicated
serializer when you need more.

:::note
The output does not depend on which backend is installed. The JSON text is the
same with or without orjson (the standard-library path uses the same compact
separators), and a value orjson cannot handle, like an integer beyond 64 bits or a
non-string key, falls back to the standard library rather than failing. The
examples here still round-trip through `load_json` rather than pinning the string,
since that is what you actually care about.
:::

## Backends

Probatio uses a fast backend when one is installed and falls back to the standard
library otherwise. The backends are detected once at import time:

- JSON: [orjson](https://github.com/ijl/orjson) when present, otherwise the
  standard library's `json`.
- YAML: [YAMLRocks](https://pypi.org/project/yamlrocks/) when present, then
  PyYAML's safe loader and dumper. YAML is not a hard dependency. Install the
  `probatio[yaml]` or `probatio[fast]` extra to get a parser.
- TOML: reading uses the standard library's `tomllib`, always available on the
  supported Python versions. Writing needs `tomli-w` (the `probatio[toml]`
  extra), since the standard library does not write TOML.

On a parse error, each loader raises the backend's own exception, not a single
probatio type: orjson raises `orjson.JSONDecodeError` (a subclass of the standard
library's `json.JSONDecodeError`), the standard library raises
`json.JSONDecodeError`, YAMLRocks and PyYAML raise their own parse errors, and
`load_toml` raises `tomllib.TOMLDecodeError`. Catch `ValueError` to cover the JSON
and TOML cases across backends; for YAML, catch the parser's error type.

:::caution[YAML backends follow different spec versions]
YAMLRocks implements YAML 1.2; PyYAML implements YAML 1.1. They parse a few inputs
differently. Under 1.1, the bare words `yes`, `no`, `on`, and `off` are booleans,
a leading-zero number like `0755` is octal, and `12:30` is a sexagesimal number;
under 1.2 all of these are plain strings or decimals. So the parsed type of such a
value can depend on which backend is installed. Quote these values in your YAML
(`"yes"`, `"0755"`) when the distinction matters, and validate with an explicit
type so the schema, not the parser, decides.
:::

You do not select a backend. The fast one is used automatically when installed,
and the result is the same value either way:

```python
from probatio import dump, load_json

text = dump({"port": 8080}, "json")
load_json(text)  # {'port': 8080}
```

:::tip
Install the `probatio[fast]` extra in production for the orjson and YAMLRocks
speedups, and leave it out where a pure standard-library footprint matters. Your
code does not change; only the backend does.
:::

## Backend options

Every loader and dumper takes an optional `options` mapping that is forwarded to
the active backend. Without it, the backend stays invisible (consistent output
either way). With it, you tune the backend directly, so the call becomes specific
to whichever backend is installed.

The clearest case is the YAML spec version. YAMLRocks parses YAML 1.2 by default,
where `yes` is a plain string; switch it to 1.1 and `yes` becomes a boolean:

```python
import yamlrocks
from probatio import load_yaml

load_yaml("flag: yes")["flag"]  # 'yes'
load_yaml("flag: yes", options={"option": yamlrocks.OPT_YAML_1_1})["flag"]  # True
```

The same `options` reaches `dump_*` (for example `orjson.OPT_INDENT_2` to
pretty-print JSON) and the other formats (`parse_float` for TOML, `sort_keys` for
PyYAML). Since options are backend-specific, passing them couples the call to the
backend you have, which is the trade for the extra control.

### Setting defaults

Passing the same options on every call gets old. Two layers sit beneath a call's
own `options`. A process-wide default, set once (at your application's entry
point), applies to every later call for that format:

```python
import yamlrocks
from probatio import load_yaml, set_default_options, clear_default_options

set_default_options("yaml", load={"option": yamlrocks.OPT_YAML_1_1})
load_yaml("flag: yes")["flag"]  # True
clear_default_options()         # reset (so the rest of this page is unaffected)
```

A scoped override applies only inside a `with` block and never leaks to other code
(it is async- and thread-safe), so reusable libraries should prefer it over
mutating the global:

```python
import yamlrocks
from probatio import load_yaml, default_options

with default_options("yaml", load={"option": yamlrocks.OPT_YAML_1_1}):
    inside = load_yaml("flag: yes")["flag"]
inside  # True
```

A call's own `options` win over a scoped default, which wins over the process-wide
one. Set the global only where you own the whole process (an application, not a
library that others import).

## Source locations

When a config fails validation, the useful question is _where in the file_.
`load_yaml_with_locations` answers it: it returns `(data, locator)`, where the
locator maps a validation error's `path` back to the source position. Hand the
locator to `humanize_error` and each failure gains the place it points at.

```python
from probatio import Schema, Required, Range, MultipleInvalid, load_yaml_with_locations
from probatio.humanize import humanize_error

data, locator = load_yaml_with_locations("server:\n  port: 70000\n")
schema = Schema({Required("server"): {Required("port"): Range(min=1, max=65535)}})

try:
    schema(data)
except MultipleInvalid as err:
    print(humanize_error(data, err, locator=locator))
# value must be at most 65535 for dictionary value @ data['server']['port']. Got 70000 (at 2:9)
```

The locator returns a `Location` (with `line`, `column`, and `file`) that programs
can read directly, or that renders as `file:line:column`. It points at the exact
value, scalar leaves included. A `Path` source fills in the `file`, following
nested `!include` layers to the source that holds the value. A path that is not in
the document yields `None`.

:::note
Source locations need the YAMLRocks backend, version 0.5.0 or newer, which carries
the positions (install `probatio[fast]`). The plain `load_yaml` works on any
backend; only the located variant needs it.
:::
