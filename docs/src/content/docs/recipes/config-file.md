---
title: Validating a config file
description: Define a schema for an app config, then load and validate a file end to end.
---

A config file is just data on disk. You parse it, then check it against a schema.
Probatio does both in one step: `schema.load(path)` parses the file and validates
the result. This recipe walks the whole path, from schema to a friendly error.

## Define the schema

Start with the shape of a valid config. A required name, an optional log level
limited to a known set, and a nested `server` section with a host and a port. The
port is coerced to an int and range-checked, so `"9000"` from the file becomes
`9000`:

```python
from probatio import Schema, Required, Optional, All, Coerce, Range, In

schema = Schema(
    {
        Required("name"): str,
        Optional("log_level", default="info"): In(
            ["debug", "info", "warning", "error"]
        ),
        Required("server"): {
            Required("host"): str,
            Optional("port", default=8080): All(Coerce(int), Range(min=1, max=65535)),
        },
    }
)
```

`Required` keys must be present. `Optional` keys may be missing, and their
`default` fills in when they are. `In` limits a value to a fixed set of choices.
`All(Coerce(int), Range(...))` runs left to right: it converts the value to an
int, then checks the bounds.

## Write a config file

For a self-contained example, write a small JSON file. JSON parses with the
standard library, so this works on a stdlib-only install. Note the port is a
string here, on purpose, to show the coercion:

```python
import json
from pathlib import Path

config = {
    "name": "my-app",
    "server": {"host": "localhost", "port": "9000"},
}
Path("config.json").write_text(json.dumps(config, indent=2))  # 85
```

## Load and validate

Pass a `Path` to `schema.load`. It reads the file, detects the format from the
`.json` extension, parses it, and validates the result against the schema in one
call:

```python
result = schema.load(Path("config.json"))
print(result)
# {'name': 'my-app', 'server': {'host': 'localhost', 'port': 9000}, 'log_level': 'info'}
```

Two things normalized on the way through. The port string `"9000"` became the int
`9000`, and the missing `log_level` was filled with its default `"info"`. The
result is a fresh dict; your file is untouched.

:::note
`schema.load` auto-detects the format from a path extension. If you already know
it, the explicit loaders are there: `schema.load_json`, `schema.load_yaml`, and
`schema.load_toml`. YAML needs a parser installed (`probatio[yaml]`); JSON and
TOML use the standard library.
:::

A YAML file reads the same way, when a YAML parser is installed:

<!-- verify: skip -->

```python
from pathlib import Path

result = schema.load(Path("config.yaml"))  # auto-detects YAML
result = schema.load_yaml(Path("config.yaml"))  # or be explicit
```

## Handle a bad config

When the file does not match, validation raises. `humanize_error` from
`probatio.humanize` renders the failure against the data, naming the value that
went wrong, which is exactly what you want to print for whoever wrote the config:

```python
import json
from pathlib import Path
from probatio import Invalid
from probatio.humanize import humanize_error

bad = {"name": "my-app", "server": {"host": "localhost", "port": "70000"}}
Path("bad.json").write_text(json.dumps(bad))

try:
    schema.load(Path("bad.json"))
except Invalid as err:
    print(humanize_error(bad, err))
    # value must be at most 65535 at 'server.port'. Got '70000'
```

The message points straight at `server.port` and shows the offending
value. The [error handling guide](/guides/error-handling/) goes deeper into
paths, collecting every error at once, and the structured layer underneath.

## Where to next

- [Quick start](/getting-started/quick-start/): the basics of building a schema.
- [Dict schemas and markers](/guides/dict-schemas-and-markers/): required and
  optional keys, defaults, and the extra-key policy.
- [Home Assistant](/recipes/home-assistant/): using Probatio where voluptuous is
  already in place.
