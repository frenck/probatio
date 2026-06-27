---
title: Architecture
description: How Probatio is put together, from errors and markers up to the voluptuous compatibility shim.
---

This page is a map, not an essay. It walks the design in layers, bottom to top,
so you know where a given piece of behavior lives. For the reasoning behind the
big choices, read the architecture decision records in
[`adr/`](https://github.com/frenck/probatio/tree/main/adr), starting at
[`adr/README.md`](https://github.com/frenck/probatio/blob/main/adr/README.md).

Probatio is pure Python. No native extension, no build step, no compiler. That
is a deliberate choice, not a limitation we have not gotten around to yet. The
target workload (config validation, such as Home Assistant) runs at load time,
not in a hot inner loop, and the pure-Python engine already beats voluptuous
there. See [ADR-004](https://github.com/frenck/probatio/blob/main/adr/004-single-validation-engine.md)
for the measurements and the call to keep a single engine.

## The layers

### Errors and markers

At the bottom sit the things everything else speaks in.

Errors live in `error.py`. `Invalid` is a single validation failure that carries
a `path` to the offending value. `MultipleInvalid` collects several. The
semantic subclasses (`TypeInvalid`, `RangeInvalid`, `RequiredFieldInvalid`, and
the rest) let callers catch by kind. Keeping the path precise is the whole game:
the engine calls back into arbitrary user code constantly, so every layer is
careful to report where a value went wrong, not just that it did.

Markers live in `markers.py`. These are dictionary keys that carry intent:
`Required`, `Optional`, `Remove`, `Inclusive`, `Exclusive`, and the `Extra`
catch-all. Each compares and hashes by its underlying key, so a marker can stand
in for the bare key it wraps.

### The engine

`_engine.py` is the compiled core. A schema is compiled once into a callable,
then run per validation. Think of it like `re.compile`: you pay the build cost
once, then validate many values cheaply.

The engine owns the mapping and sequence validators, where the awkward
voluptuous semantics live: marker precedence, literal keys before type keys,
the extra-key policy, and the exact error paths. There is one engine and one set
of mapping semantics. ADR-004 explains why a second implementation (the removed
codegen path) was not worth the permanent tax of keeping two engines
behaviorally identical.

One small optimization stays: validators can declare `__probatio_safe__` to
promise they only raise `Invalid`, and the engine then calls them without the
extra guard that wraps stray `ValueError`. It is a contract, not a second
engine.

### The Schema compiler

`schema.py` is the front door. `Schema(...)` takes a declarative definition (a
type, a literal, a callable, a dict, a list, a nested schema, or any validator)
and compiles it into the engine callable. Calling the schema validates a value
and returns the normalized result, or raises.

This is the compile-once-then-validate model in one object. Build the schema
when your program starts, call it on every value after that.

### The validators

`validators/` holds the building blocks you compose schemas from, grouped by
what they do: combinators (`All`, `Any`, `Union`, `SomeOf`), comparison and
membership (`Range`, `In`, `Equal`), coercion (`Coerce`, `Boolean`), strings
(`Email`, `Url`, the case transforms), structural (`Length`, `ExactSequence`,
`Object`), temporal (`Datetime`, `Date`), predicates, and the `validate`
decorator. They share a small base in `validators/_base.py`.

### The codecs

`codecs/` converts schemas to and from other schema languages, for the
constructs that map cleanly: JSON Schema (`jsonschema.py`), OpenAPI
(`openapi.py`), and a plain field-list serialization (`fields.py`). A custom
serializer returns the `UNSUPPORTED` sentinel to defer a construct it does not
handle to the built-in logic.

`from_json_schema` treats its input as untrusted. It refuses a catastrophically
backtracking `pattern` and a pathologically deep document, so a hostile schema
cannot hang the process or overflow the stack. That guard lives in
`codecs/_regex_safety.py`.

### The serde loaders and dumpers

`serde/` reads and writes JSON, YAML, and TOML. It uses a fast backend when one
is installed (such as orjson) and falls back to the standard library where the
standard library can do the job: JSON read and write and TOML read work bare,
while YAML and TOML write need an optional backend. The `Schema.load_*`
convenience methods parse and validate in one step on top of
this layer.

### The voluptuous compatibility shim

`compat/` is the thin top layer that backs the drop-in promise. It exposes the
voluptuous names and signatures so changing the import from `voluptuous` to
`probatio` keeps existing schemas working. Behavior, not source, is what is
matched here. No code was copied ([ADR-001](https://github.com/frenck/probatio/blob/main/adr/001-clean-room-reimplementation-of-voluptuous.md)).

## Where to read next

- [`adr/README.md`](https://github.com/frenck/probatio/blob/main/adr/README.md):
  the index of architecture decision records, with the why behind each major
  decision.
- The [API reference](/reference/): the public surface, grouped by what each
  name does.
