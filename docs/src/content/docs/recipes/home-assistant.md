---
title: Home Assistant
description: Use Probatio where Home Assistant uses voluptuous, with or without touching internals.
---

Home Assistant validates its configuration with voluptuous, and it does so
heavily. The `config_validation` helper is one of the largest voluptuous
consumers there is. Probatio mirrors the voluptuous API, so it can stand in.

## The simple case: change the import

Home Assistant code does not import voluptuous names one by one. The idiom is
`import voluptuous as vol`, with every schema written against the `vol.`
namespace: `vol.Schema`, `vol.Required`, `vol.Optional`, `vol.All`. That idiom
makes the migration a one-line diff, with every `vol.` reference untouched:

```diff
-import voluptuous as vol
+import probatio as vol
```

The rest of the file does not change. This runs on Probatio as-is:

```python
import probatio as vol

CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required("name"): str,
        vol.Optional("port", default=8123): int,
    }
)

CONFIG_SCHEMA({"name": "living-room"})  # {'name': 'living-room', 'port': 8123}
```

The names, signatures, and behavior match. `Required`, `Optional`, `All`, `Any`,
`Coerce`, `Range`, `In`, the markers, the error classes: same surface, fresh
implementation.

## The harder case: code that imports voluptuous internals

Not everything imports the public API. Some dependencies reach into voluptuous
_internals_. Home Assistant's `annotatedyaml`, for example, imports
`voluptuous.schema_builder._compile_scalar` directly. You cannot change the
import in code you do not own.

For that, Probatio ships `install_as_voluptuous`. Call it once at process
startup, before anything imports voluptuous:

<!-- verify: skip -->

```python
from probatio.compat import install_as_voluptuous

install_as_voluptuous()
```

It registers a small voluptuous-shaped shim, backed by Probatio, into
`sys.modules` under the `voluptuous` name, so every later `import voluptuous`
resolves to Probatio for the rest of the process. It is process-wide, so call it
from an application entry point, not from library code, and call it early: if a
real voluptuous was already imported, it is shadowed and a `RuntimeWarning` is
emitted, since references already taken to the real module will not update. The
[Compatibility](/getting-started/compatibility/) page covers exactly what it
registers and when to call it.

## It is tested against the real thing

This is not a paraphrase of compatibility. Probatio is validated against Home
Assistant's own `config_validation` test suite, with voluptuous swapped out for
Probatio through `install_as_voluptuous`. As of July 2026, 136 of the 142 tests
pass; the harness in `compat/home_assistant/` in the repository is the source
of truth for the current count. The 6 that fail all assert the exact
voluptuous-rendered error string, which Probatio deliberately renders
differently (a dotted path instead of `@ data[...]`, see the
[compatibility matrix](/reference/compatibility-matrix/)). The error attributes
those tests could assert on instead (`path`, `error_message`, the error class)
all match.

Getting there surfaced real compatibility gaps that isolated unit tests had
missed, like `Remove(key)` keeping a value that fails its schema, and the
`error_type` tag on a failed mapping value. Those are fixed. The harness
reproduces the run against a Home Assistant checkout.

## Where to next

- [Migrating from voluptuous](/getting-started/migrating-from-voluptuous/): the
  general swap, beyond Home Assistant.
- [Validating a config file](/recipes/config-file/): a worked end-to-end example.
- [Error handling](/guides/error-handling/): paths, multiple errors, and readable
  messages.
