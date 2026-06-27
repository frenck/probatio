---
title: Performance
description: How Probatio compiles a schema once, how it compares to voluptuous, and how to measure it yourself.
---

Probatio is pure Python with no native extension. That is a deliberate choice
(see [ADR-001](https://github.com/frenck/probatio/blob/main/adr/001-clean-room-reimplementation-of-voluptuous.md)
and [ADR-004](https://github.com/frenck/probatio/blob/main/adr/004-single-validation-engine.md)):
the drop-in promise and easy installation matter more
than squeezing out the last cycle. This page explains the cost model and how to
measure it yourself, with honest numbers.

## The cost model: build once, call cheap

A `Schema` compiles its definition once, when you construct it. After that, calling
it is the cheap part. So the rule is simple: build the schema once, then reuse it.

```python
from probatio import Schema, All, Coerce, Range

# Built once. Reused for every value.
PORT = Schema(All(Coerce(int), Range(min=1, max=65535)))

PORT("443")  # 443
PORT(8080)   # 8080
```

The expensive work (walking the definition, resolving markers, wiring up the
validators) happens in the constructor. If you rebuild the schema on every call,
you pay that cost every time for nothing.

:::tip
Build schemas at module scope, as module-level constants. Import and call them.
Do not construct a `Schema` inside a function that runs in a hot loop.
:::

## How it compares to voluptuous

On the bundled benchmark scenarios, warm validation in Probatio runs roughly twice
as fast as the same schema in voluptuous. Roughly. The exact ratio moves with the
machine, the Python version, and the shape of the schema, so treat "about 2x" as a
ballpark, not a promise.

:::caution[Read the benchmark honestly]
`bench/bench.py` is a rough, single-machine comparison. It builds two equivalent
schemas, validates a fixed payload many times in a plain loop, and prints the
ratio. It is useful for a sanity check and for catching a large regression. It is
not a rigorous benchmark, and the numbers it prints are machine-dependent. Do not
quote them as guarantees.
:::

The tracked benchmarks are the CodSpeed ones in `bench/test_benchmarks.py`. Those
run per pull request, so a performance regression shows up in review.

## Measuring it yourself

The rough comparison against voluptuous:

```bash
just bench
```

That prints a small table of total time and the Probatio/voluptuous ratio per
scenario. Run it a few times; the absolute numbers wander.

The tracked CodSpeed benchmarks (walltime locally, tracked in CI):

```bash
just codspeed
```

These are not part of the normal test run. They exercise the hot paths:
validating a config-style mapping, compiling a schema from scratch, validating a
list of coerced numbers, the deepest-error path through a failing `Any`, and an
exclusive-group post-pass.

## Practical tips

- Build each schema once, at module scope, and reuse it. This is the single
  biggest win.
- Never rebuild a schema inside a hot loop. Compilation is the expensive part.
- Reuse nested schemas too. A `Schema` you reference from another schema is
  compiled once and shared.
- Remember it is pure Python by design. There is no native extension to build or
  install, and no compiled fast path to fall back to. If you need raw throughput
  beyond what this gives you, that is a trade-off you are choosing knowingly.

## Reuse and concurrency

A compiled `Schema` is meant to be built once and called many times, and that is
also what makes it safe to share. Validation does not mutate the schema: it reads
the compiled checks and returns a new value, so the same `Schema` instance can be
called from multiple threads at once. Build it once at import time and let every
worker use it.

The one caveat is your own code. If you write a custom validator that keeps
mutable state, or pass a `default` factory that is not safe to call concurrently,
that state is yours to make thread-safe. Probatio's own validators hold no
per-call state.
