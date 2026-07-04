---
title: Validating a config file
description: Define a schema for an app config, then load and validate a file end to end.
---

A config file is just data on disk. You parse it, then check it against a schema.
Probatio validates the parsed result: you own the parsing, with whatever library
fits the format, and hand the object to the schema. This recipe walks the whole
path, from schema to a friendly error.

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
_ = Path("config.json").write_text(json.dumps(config, indent=2))
```

## Load and validate

Read the file, parse it, then validate the parsed object. JSON parses with the
standard library's `json`, so this works on a bare install:

```python
result = schema(json.loads(Path("config.json").read_text()))
print(result)
# {'name': 'my-app', 'server': {'host': 'localhost', 'port': 9000}, 'log_level': 'info'}
```

Two things normalized on the way through. The port string `"9000"` became the int
`9000`, and the missing `log_level` was filled with its default `"info"`. The
result is a fresh dict; your file is untouched.

A YAML file works the same way: parse it with a YAML library (use a safe loader),
then validate the result.

<!-- verify: skip -->

```python
import yaml  # PyYAML

result = schema(yaml.safe_load(Path("config.yaml").read_text()))
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
    schema(json.loads(Path("bad.json").read_text()))
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
