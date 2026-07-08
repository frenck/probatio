---
title: Lazy building
description: Defer a schema's compilation to first use, so schemas that are built but never validated cost nothing.
---

A `Schema` normally compiles its declaration into a validator the moment you build
it. That is the right default: a malformed schema fails where it is written, the
same as voluptuous. But some programs build far more schemas than they ever
validate against. Home Assistant registers on the order of a thousand service
schemas and a thousand websocket-command schemas at startup, and a given install
exercises a small fraction of them. Every unused one still pays to compile, and
holds its compiled validator tree in memory for the life of the process.

Lazy building defers that work. Under the `LAZY` build policy a schema stores its
declaration and compiles on the first validation instead of at construction, so a
schema that is built but never validated never compiles and never holds a validator
tree. It is opt-in: the default stays eager, so nothing changes unless you ask.

## The default: eager

The process starts on the `EAGER` policy. A schema compiles when you build it, and
a definition error is raised right there, at construction, exactly as voluptuous
does. This is the drop-in behavior, and for most programs it is what you want:
schemas are a fixed set built once at import, and building them is cheap.

```python
from probatio import Schema, Required

schema = Schema({Required("name"): str})  # compiled here, on this line
schema({"name": "app"})  # {'name': 'app'}
```

## Opting into lazy

Set the policy once, early, from deliberate startup code, before the schemas you
want deferred are built. There is no environment variable on purpose: this is an
architectural choice, not a deployment toggle.

<!-- verify: skip -->

```python
from probatio import BuildPolicy, set_build_policy

set_build_policy(BuildPolicy.LAZY)   # defer every eligible schema to first use
set_build_policy(BuildPolicy.EAGER)  # the default: compile at construction
```

:::caution[Applications set this, not libraries]
`set_build_policy` is a single process-wide switch, so only an application (the
process that owns the run) should call it. A library that sets it changes how every
schema in the process builds, the application's own and those of unrelated
dependencies included, which is not a library's call to make. And unlike the compile
policy, the build policy has no per-schema form, so a library cannot scope it to its
own schemas either. Leave it to the application and rely on the `EAGER` default.
:::

After `set_build_policy(BuildPolicy.LAZY)`, a schema you build does not compile
until its first validation. A schema you build and never call never compiles at
all, and never allocates its validator tree.

<!-- verify: skip -->

```python
from probatio import Schema, Required, BuildPolicy, set_build_policy

set_build_policy(BuildPolicy.LAZY)

# Registered at startup; the walk is deferred.
schema = Schema({Required("resource"): str})

# ... much later, only if this command is ever invoked:
schema({"resource": "sensor.sun"})  # compiles now, then validates
```

## What defers, and what does not

Only a plain top-level `Schema` defers. Anything whose compiled form is needed at
construction builds eagerly, even under `LAZY`, so laziness never leaves a
half-built schema anywhere it would be read:

- A **combinator branch** (`Any(...)`, `All(...)`) compiles its branches when the
  combinator is built.
- A **`DataclassSchema` or `TypedDictSchema`** builds at construction, since it
  wires field validation (and, for a dataclass, instance construction) together
  then.
- A nested schema reused as a value builds when its parent is first validated.
- An explicit `compile=` request, or `Schema.compile()`, builds now.

Reading a lazy schema's declaration does not build it: `.schema`, `str()`,
`.extend()`, and the codecs all work on the declaration, so introspection stays
free.

## The one trade: error timing

Deferring the compile walk defers the errors it raises. Under `EAGER`, a malformed
schema (a contradiction like two presence markers on one key, an alias colliding
with another key) raises `SchemaError` at construction. Under `LAZY`, that same
error raises on the **first validation** instead, because that is when the walk
runs. The schema is just as wrong; you learn about it a moment later.

For a program whose schemas are static and covered by tests, this is a non-issue,
the tests validate, so a broken schema still fails in CI. But it is a real
difference from voluptuous, which is why `LAZY` is opt-in and `EAGER` is the
default. If you rely on construction-time schema errors, stay eager.

## When to use it

Reach for `LAZY` when you build many schemas at import but validate against only
some of them in a given run: a large plugin surface, a command or service registry,
per-feature validation that most installs never touch. The win is both time (the
deferred walks never run) and memory (their validator trees never materialize),
which matters most on a small device. If your schemas are a fixed set you validate
against on every run, eager is simpler and there is nothing to gain.
