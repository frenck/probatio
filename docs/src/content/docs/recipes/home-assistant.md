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

## Keeping the source file and line

Home Assistant loads YAML through `annotatedyaml`, which records the file and
the line every mapping, list, and string came from on its own node classes.
Validation does not keep them: a schema that rebuilds a mapping produces a fresh
instance of the node class, holding the validated items and nothing else. A rule
like `cv.deprecated` then has no way to say where in the configuration the
deprecated option was written.

Probatio's [value metadata](/guides/metadata/) closes that, and it does so
without the YAML loader and Probatio knowing about each other. Each party owns
one piece:

- the loader lets its container nodes hold one more attribute, which is a
  general capability and names nothing from Probatio;
- Probatio carries a value's metadata across every rebuild, at every nesting
  depth;
- Home Assistant, the one place that uses both, turns the loader's location into
  metadata right after loading, and reads it back where it reports an error.

### The loader: room for one more attribute

`annotatedyaml` declares `__slots__` on its node classes, so an instance holds
`__config_file__` and `__line__` and nothing else. Adding `__dict__` to the slots
of the two container classes lets a consumer attach attributes of its own:

```python
class NodeListClass(list):
    """Wrapper class to be able to add attributes on a list."""

    __slots__ = ("__config_file__", "__line__", "__dict__")


class NodeDictClass(dict):
    """Wrapper class to be able to add attributes on a dict."""

    __slots__ = ("__config_file__", "__line__", "__dict__")
```

That is the whole change on the loader side. The loader keeps recording the
location in its own two slots, exactly as it does today, and nothing in it
mentions Probatio. An instance `__dict__` is one of the two places Probatio
writes metadata to, because writing to it runs none of the class's own code (see
[Opting a type in](/guides/metadata/#opting-a-type-in)).

The string node needs no change. A string is never rebuilt, so it keeps the
loader's own slots through validation.

### Home Assistant: attach the location after loading

Metadata has to be on a value before the first schema rebuilds it, so the place
to attach it is where Home Assistant loads YAML. The metadata is a small
read-only mapping of Home Assistant's own, holding the file and the line:

```python
from collections.abc import Mapping


class Location(Mapping):
    """Where a loaded value came from, as read-only value metadata."""

    __slots__ = ("_file", "_line")

    def __init__(self, file, line):
        object.__setattr__(self, "_file", file)
        object.__setattr__(self, "_line", line)

    def __setattr__(self, name, value):
        raise AttributeError("a Location cannot change")

    def __delattr__(self, name):
        raise AttributeError("a Location cannot change")

    def __reduce__(self):
        # Rebuild through the constructor, since attribute writes are refused.
        return (type(self), (self._file, self._line))

    def __getitem__(self, key):
        if key == "file":
            return self._file
        if key == "line":
            return self._line
        raise KeyError(key)

    def __iter__(self):
        return iter(("file", "line"))

    def __len__(self):
        return 2
```

Probatio accepts any mapping as a value's metadata. `metadata_of` returns it as
a `Metadata`, and a validator that adds to it with `add_metadata` replaces it
with a merged `Metadata` on that one value. It has to be immutable, because
Probatio hands the same object to every rebuild of a value rather than copying
it. A `Location` is used rather than a `Metadata` because the pass below creates
one for every container: it takes about a fifth of the memory and is cheaper to
build.

One pass over the loaded tree then gives every mapping and list its location:

```python
def attach_locations(tree):
    """Give every loaded mapping and list its file and line as value metadata."""
    seen = set()
    stack = [tree]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            children = node.values()
        elif isinstance(node, list):
            children = node
        else:
            continue
        if id(node) in seen:
            continue  # the same node reached twice, through a YAML alias
        seen.add(id(node))
        try:
            node.__probatio_metadata__ = Location(node.__config_file__, node.__line__)
        except AttributeError:
            pass  # not a loaded node, or one with no recorded location
        stack.extend(children)
    return tree
```

In Home Assistant this belongs in the `homeassistant/util/yaml` load functions,
which every configuration load goes through. Files pulled in with `!include` and
the `!include_dir_*` tags are part of the tree those functions return, so one
pass covers them, each node with the file it came from.

The pass touches each container once. Measured on CPython 3.14 with a
configuration of about 4,200 mappings and lists, it adds about 7% to the time
loading the YAML takes. Together with the `__dict__` slot itself, the memory the
loaded tree holds grows by about 14%. Validation then carries the metadata at the
cost of the carry itself, a few tens of nanoseconds per rebuilt container.

### Reading it back

After validation, a rebuilt mapping or list holds the metadata and no longer has
`__config_file__` or `__line__`. Keys and strings are not rebuilt, so they keep
the loader's own slots. One helper reads both:

```python
from probatio import Schema, metadata_of


def config_location(value):
    """Return the file and line a loaded value came from, or None."""
    where = metadata_of(value)
    if where is not None and "file" in where:
        return where["file"], where.get("line", "?")
    if hasattr(value, "__config_file__"):
        # Keys and strings are never rebuilt, so they hold the loader's own.
        return value.__config_file__, getattr(value, "__line__", "?")
    return None


class NodeStrClass(str):
    __slots__ = ("__config_file__", "__line__")


# What the loader produces for "name: kitchen" on line 12.
key = NodeStrClass("name")
key.__config_file__, key.__line__ = "configuration.yaml", 12
node = NodeDictClass({key: "kitchen"})
node.__config_file__, node.__line__ = "configuration.yaml", 12

validated = Schema({"name": str})(attach_locations(node))

type(validated) is NodeDictClass  # True
hasattr(validated, "__line__")  # False
config_location(validated)  # ('configuration.yaml', 12)
[config_location(name) for name in validated]  # [('configuration.yaml', 12)]
```

Home Assistant reports a configuration location in four places, and each one
calls this helper instead of reading `__config_file__` and `__line__` itself:

- `homeassistant/config.py`, `find_annotation`
- `homeassistant/scripts/check_config.py`, `line_info`
- `homeassistant/helpers/config_validation.py`, `cv.deprecated`
- `homeassistant/components/mqtt/entity.py`

Two of them read the configuration as it was loaded and would keep working
as they are. The other two can see values a schema has already rebuilt:
`cv.deprecated` runs inside validation, and the configuration check runs a
platform's own schema on the output of the base platform schema; `check_config`
then prints the validated configuration. Those need the metadata. Routing all
four through one helper keeps them consistent, and leaves one place that knows
the loader's attribute names.

### Adding to it from a validator

The metadata on these nodes is ordinary value metadata, so a validator can add
to it with `add_metadata`, and what it adds survives every rebuild above it:

```python
from probatio import All, Optional, add_metadata, carry_metadata


def rename_old_name(value):
    if "old_name" not in value:
        return value
    renamed = type(value)(value)
    renamed["name"] = renamed.pop("old_name")
    return add_metadata(carry_metadata(value, renamed), renamed_from="old_name")


loaded = NodeDictClass({"old_name": "kitchen"})
loaded.__config_file__, loaded.__line__ = "configuration.yaml", 7

schema = Schema(All(rename_old_name, {Optional("name"): str}))
result = schema(attach_locations(loaded))

dict(result)  # {'name': 'kitchen'}
dict(
    metadata_of(result)
)  # {'file': 'configuration.yaml', 'line': 7, 'renamed_from': 'old_name'}
```

### Why the loader does not write the metadata itself

The loader could add a `__probatio_metadata__` slot and fill it as it builds
each node. That makes a YAML library depend on the name and the shape of one
validation library's protocol, which is the wrong way round: the loader records
where a value came from, and what a consumer does with that is the consumer's
business. It is also the more expensive placement. A loader writes metadata for
every node, strings included, whether or not anything validates it, and on the
configuration measured above that more than doubles the memory the loaded tree
holds.

Exposing a property of that name over the existing `__config_file__` and
`__line__` fields does not work either: Probatio carries onto a value it has
just validated only when the write lands in the attribute itself, never through
a setter, which receives the container and could rewrite what validation just
approved. The [metadata guide](/guides/metadata/) has the reasoning.

The opt-in lives in the node classes and in one function at load time, not in
the schemas. Nothing in `config_validation` changes to make the carry happen,
and a schema that never sees a value carrying metadata behaves exactly as it did
before.

### Validators that build their own container

This covers the metadata half of the problem, and only that half. A validator
that returns `dict(value)`, a comprehension, or an accumulator hands back a
plain `dict`, which is no longer a node class and can hold no attributes at all.
No engine change reaches that, and neither does `carry_metadata` on its own:
carrying onto a plain `dict` is a silent no-op, because the target still cannot
hold the attribute. Such a validator needs both halves, rebuilding as the input's
own type and then carrying:

```python
from probatio import carry_metadata


# Before: the type is destroyed, so the metadata goes with it.
def strip_empty(value):
    return {key: item for key, item in value.items() if item}


# After: rebuild as the input's own class, then move the metadata across.
def strip_empty_keeping_source(value):
    kept = type(value)((key, item) for key, item in value.items() if item)
    return carry_metadata(value, kept)
```

The [metadata guide](/guides/metadata/) has the same pattern in full.

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
- [Value metadata](/guides/metadata/): the file and line a value carries, and
  how a type opts in.
- [Validating a config file](/recipes/config-file/): a worked end-to-end example.
- [Error handling](/guides/error-handling/): paths, multiple errors, and readable
  messages.
