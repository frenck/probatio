---
title: Performance
description: How Probatio validates fast, how it compiles a hot schema, how it compares to voluptuous and mashumaro, and how to measure it yourself.
---

Probatio is pure Python with no native extension. That is a deliberate choice
(see [ADR-001](https://github.com/frenck/probatio/blob/main/adr/001-clean-room-reimplementation-of-voluptuous.md)
and [ADR-011](https://github.com/frenck/probatio/blob/main/adr/011-opt-in-compiled-schema.md)):
the drop-in promise and easy installation matter more than a native core. Even so,
the interpreted engine is well ahead of voluptuous, and a hot schema compiles itself
into a specialized validator for more speed. This page explains the cost model and
how to measure it, with honest numbers.

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

## Two engines: interpreted and compiled

Validation runs on one interpreted engine. On top of that, a schema can compile
itself into a flat function generated for its exact shape, with the per-key work
unrolled and the common validators inlined. By default this is automatic: a hot
schema compiles itself once it has been called enough to be worth it, and a one-shot
schema stays interpreted. Compiling only changes speed; the result is identical,
because anything off the happy path bails to the interpreted engine.

You do not have to do anything to get this. To opt a specific schema in eagerly, or
to turn the behavior off for an unusual workload, see
[Compiled schemas](/guides/compiled-schemas/).

## How it compares to voluptuous

On the bundled benchmark scenarios, the interpreted engine runs roughly one and a
half to three and a half times faster than the same schema in voluptuous, and the
compiled path reaches up to about seven times faster on real config and dataclass
shapes. The exact ratio moves with the machine, the Python version, and the shape of
the schema, so treat these as ballparks, not promises.

| Scenario                         | voluptuous | Probatio | Probatio compiled |
| -------------------------------- | ---------- | -------- | ----------------- |
| Flat types (`{str, int, ...}`)   | 3.7 µs     | 1.1 µs   | 0.5 µs            |
| Config (coerce, range, in, list) | 6.0 µs     | 2.2 µs   | 0.9 µs            |
| Nested mapping                   | 7.0 µs     | 3.0 µs   | 1.0 µs            |

Microseconds per validation, lower is faster, on one machine with Python 3.13.

![Validation throughput vs voluptuous: probatio is 1.7 to 3.4 times faster interpreted, and 4.7 to 7.2 times faster compiled, across the benchmark scenarios.](/benchmarks/vs-voluptuous.svg)

:::caution[Read the benchmark honestly]
`bench/bench.py` is a rough, single-machine comparison. It builds equivalent
schemas, validates a fixed payload many times in a plain loop, and prints the
ratio. It is useful for a sanity check and for catching a large regression. It is
not a rigorous benchmark, and the numbers are machine-dependent. Do not quote them
as guarantees.
:::

The tracked benchmarks are the CodSpeed ones in `bench/test_benchmarks.py`. Those
run per pull request, so a performance regression shows up in review. They pin each
case to a known engine (interpreted or compiled) so the two are tracked separately.

## How a dataclass compares to mashumaro

For the dataclass path there is also a comparison against
[mashumaro](https://github.com/Fatal1ty/mashumaro), which generates a `from_dict`
per class. It is not a like-for-like comparison, and that is the point: mashumaro
deserializes and largely trusts the declared types, while Probatio _validates_ every
field against its type and then constructs. mashumaro does strictly less work, so it
is faster on already-correct input. The compiled Probatio path lands within roughly
1.3x of it on a small dataclass while still validating, and the gap all but closes
as the field count grows (about 1.1x on a wide one).

| Dataclass        | mashumaro | Probatio | Probatio compiled |
| ---------------- | --------- | -------- | ----------------- |
| Small (4 fields) | 0.5 µs    | 1.5 µs   | 0.7 µs            |
| Wide (12 fields) | 1.2 µs    | 2.8 µs   | 1.3 µs            |

![Dataclass construction vs mashumaro: compiled probatio is within about 1.3 times of mashumaro on a small dataclass and essentially even on a wide one, while validating every field.](/benchmarks/dataclass-vs-mashumaro.svg)

The two libraries pair well: validate untrusted input with Probatio, then hand
trusted dataclasses to mashumaro to serialize. See
[Comparison to alternatives](/project/comparison/) for where each one fits.

## How it compares across libraries

There is also a cross-library comparison on the dict-to-object path, in the spirit
of mashumaro's benchmark suite: one representative nested record, handed to each
library as the same dict, timed turning it into a validated or constructed object.

Be honest about what is being compared, because these libraries do different amounts
of work. _Validators_ (Probatio, pydantic, marshmallow) check every field against
its type and would reject a mismatch; voluptuous validates but returns a dict rather
than constructing an object. _Deserializers_ (mashumaro, cattrs, dacite,
dataclasses-json) build the object and largely trust the declared types. Probatio
appears in both groups: its normal call validates, and its opt-in
[`construct`](/guides/dataclasses/#trusted-construction-without-validation) builds
from trusted input without validating, the same job the deserializers do.

![dict to object across libraries, log scale: probatio construct is the fastest of all, then mashumaro, pydantic v2, and cattrs; compiled probatio sits next, ahead of voluptuous, pydantic v1, dacite, marshmallow, and dataclasses-json.](/benchmarks/vs-world.svg)

Two honest readings. On the **validate** path, compiled Probatio lands in the
leading group, ahead of voluptuous, pydantic v1, dacite, marshmallow, and
dataclasses-json, and within about 1.7x of the Rust-cored pydantic v2, while staying
pure Python and validating every field. On the **trust the types** path,
`construct` is the fastest in the whole field, ahead of mashumaro and cattrs,
because it is a purpose-built constructor generated for that one dataclass. Run it
yourself with `just bench-world`.

Narrowing to the like-for-like group, only the libraries that actually validate,
makes the placement clearer:

![Validators only, log scale: pydantic v2 (native Rust core) is fastest, then compiled probatio, then interpreted probatio, then voluptuous, pydantic v1, and marshmallow, all pure Python.](/benchmarks/validators.svg)

Among validators, the only thing faster than compiled Probatio is pydantic v2, and
it gets there with a native core (the Rust `pydantic-core`). Probatio is right behind
it and ahead of every other validator, while being pure Python, no extension to
build, nothing to compile at install. That is the trade Probatio is built around:
the speed is close to the native option, the install is a plain `pip install`.

:::note[Where the native core actually wins]
pydantic v2's lead here comes from the workload: this record is parsing-heavy (ISO
datetime strings, enums, decoded out of JSON), which is exactly what a Rust core is
good at. The advantage is not uniform. It shrinks on a schema dominated by your own
custom validators, because a native core cannot run a Python validator natively, it
has to call it across the Rust boundary (efficiently, but it is still a Python call),
so the speedup is muted right where the work is your code. The Rust win is real in
the parsing-heavy regime, not everywhere.
:::

## Measuring it yourself

The rough comparison against voluptuous:

```bash
just bench
```

The dataclass comparison against mashumaro:

```bash
just bench-dataclass
```

The cross-library comparison (syncs the extra libraries on first run):

```bash
just bench-world
```

These print a small table of per-validation times and ratios. Run them a few times;
the absolute numbers wander. The charts on this page are regenerated from the same
data with `just charts`.

The tracked CodSpeed benchmarks (walltime locally, tracked in CI):

```bash
just codspeed
```

These are not part of the normal test run. They exercise the hot paths interpreted
and compiled: validating a config-style mapping, a dataclass, a nested mapping, a
composed schema, and a combinator under the automatic compile policy; calling a
`@probatio`-decorated function; compiling a schema from scratch; and the
generation step itself.

To dig into a hot spot, the profiler wraps cProfile (and py-spy) over the generator
and the validators it produces:

```bash
just profile run-config   # see bench/profiling.py for the targets
```

## Practical tips

- Build each schema once, at module scope, and reuse it. This is the single
  biggest win, and it is also what lets a hot schema compile itself.
- Never rebuild a schema inside a hot loop. Compilation is the expensive part.
- Reuse nested schemas too. A `Schema` you reference from another schema is
  built once and shared.
- Let `AUTO` do its job. You rarely need to reach for the `compile` flag by hand;
  the hot schemas speed themselves up. See
  [Compiled schemas](/guides/compiled-schemas/) for when you do.

## Reuse and concurrency

A compiled `Schema` is meant to be built once and called many times, and that is
also what makes it safe to share. Validating reads the compiled checks and returns
a new value without changing what the schema accepts, so the same `Schema` instance
can be called from multiple threads at once. The one thing a call can change is the
engine under the hood: a hot schema compiles itself on first use (see
[Compiled schemas](/guides/compiled-schemas/)), and that one-time swap is
synchronized, so two threads racing a cold schema resolve it once and both get the
right result. Build it once at import time and let every worker use it.

The one caveat is your own code. If you write a custom validator that keeps
mutable state, or pass a `default` factory that is not safe to call concurrently,
that state is yours to make thread-safe. Probatio's own validators hold no
per-call state.
