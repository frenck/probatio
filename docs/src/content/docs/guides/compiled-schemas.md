---
title: Compiled schemas
description: How Probatio compiles a hot schema into a specialized validator, on its own by default, and how to control or turn it off.
---

Probatio validates with one interpreted engine. On top of that, it can compile a
schema into a specialized validator: a flat function generated for that exact
schema, with the common per-key work unrolled and the common validators inlined.
It is faster, and it is the same result: on a representative config schema,
compiling takes a validation from roughly 2 µs to under 1 µs, about seven times
faster than the same schema in voluptuous (see [Numbers](#numbers)). Compiling
only changes speed, never what a schema accepts, rejects, or how it reports an
error.

By default this happens on its own. You do not have to do anything to get it, and in
most cases you should not have to think about it at all. This page explains what it
does, how to steer it when you want to, and the one case where you should turn it
off.

## The default: it compiles itself

The process starts on the `AUTO` policy. Under `AUTO`, a schema validates
interpreted and quietly counts how often it is called. Once it has proven hot (it
has been validated enough times to be worth the cost), it compiles itself and runs
through the generated validator from then on. The line is currently drawn at
roughly 50 validations, an implementation detail that may move. A schema you build
and call once, or a handful of times, never crosses it, so it stays interpreted
and never pays for code generation.

There is no public way to ask whether a schema has compiled; the observable
effect is throughput, so measure that instead. [Performance](/reference/performance/)
shows how to benchmark it yourself.

So the practical rule is the same as it has always been: build a schema once, at
module scope, and reuse it. The hot ones speed themselves up.

```python
from probatio import Schema, All, Coerce, Range

# Built once, reused for every value. After enough calls it compiles itself.
PORT = Schema(All(Coerce(int), Range(min=1, max=65535)))

PORT("443")  # 443
PORT(8080)   # 8080
```

## Asking for it explicitly

When you know a schema is hot and you do not want to wait for the warmup, opt in per
schema. The `compile` flag and `Schema.compile()` both do that; `compile()` is
spelled to mirror `re.compile`, and unlike the flag it generates right away rather
than on first use.

```python
from probatio import Schema, Required, Optional

# Opt in at construction (generated on first validation).
schema = Schema({Required("name"): str, Optional("age"): int}, compile=True)

# Or opt in eagerly, generating now. Returns the same schema.
schema = Schema({Required("name"): str, Optional("age"): int}).compile()
```

`DataclassSchema` and `TypedDictSchema` take the same flag, and they are the
clearest win: compiling fuses field validation and object construction into one
function with no intermediate dict.

```python
from dataclasses import dataclass
from probatio import DataclassSchema

@dataclass
class Point:
    x: int
    y: int

POINT = DataclassSchema(Point).compile()
POINT({"x": 1, "y": 2})  # Point(x=1, y=2)
```

To opt a schema out, pass `compile=False`. It then stays interpreted whatever the
process policy is.

## The process-wide policy

The default for any schema that does not set its own flag is the process policy.
Set it once, early, from deliberate startup code. There is no environment variable
on purpose: this is an architectural choice, not a deployment toggle that flips
behavior invisibly.

```python
from probatio import CompilePolicy, set_compile_policy

set_compile_policy(CompilePolicy.OFF)  # never compile unless a schema opts in
set_compile_policy(CompilePolicy.ON)   # compile every eligible schema on first use
set_compile_policy(CompilePolicy.AUTO) # the default: compile a schema once it is hot
```

A per-schema `compile` flag always wins over the policy, in either direction. The
order of precedence is: `schema.compile()`, then the `compile=True`/`compile=False`
flag, then the process policy.

## What compiles, and what does not

The generator handles the common shapes: dict (mapping) schemas, dataclasses, and
TypedDicts, including nested mappings, and single-element list schemas (`[str]`,
`[All(Coerce(int), Range(...))]`) both inside a mapping and at the top level. It
inlines the validators that show up most: `Coerce` to `int`/`float`, numeric
`Range`, plain `In` membership, type checks, an `Any` of literal choices
(`Any("on", "off")`, validated as a membership test), `Maybe(X)` (an optional
validated value), and `All`/`Any` chains of those.

Anything it does not handle is simply left interpreted. A recursive schema (`Self`
or a recursive JSON Schema `$ref`), an exclusive or inclusive group, a multi-element
list (an "each item matches one of these" union), a list whose element does not
inline, an exotic key: the schema works exactly as before, just without the speedup.
You never lose correctness by compiling; at worst you do not gain speed.

This is the heart of the design. The generated function is a fast **success path
only**. The moment anything is off (a missing required key, a type mismatch, a
validator that raises, an unexpected key) it hands the value back to the interpreted
engine, which produces every error, path, code, and ordering. So there is one set of
validation semantics, not two, and the compiled path differs only by speed (with one
caveat for side-effecting validators on a failing validation, noted below).

:::note
Because failures run through the interpreted engine, an error-heavy workload sees
interpreted speed, not compiled speed. Compilation accelerates the happy path, which
is the one that runs in a steady system.
:::

:::caution[Keep validators pure]
The fast path runs fields optimistically. When a validation fails, a validator or a
`default` factory that already ran before a later field bailed runs a second time in
the interpreted re-run. The returned value and the raised error are always identical;
only the count of side effects differs, and only on a failing validation. So a
validator or default factory that mutates state (a counter, a log line, an external
call) can fire more than once for input that is then rejected. Keep them pure, which
is the right shape for a validator regardless of compilation.
:::

## The one time to turn it off

Each compiled schema holds a generated code object and a small namespace capturing
its validators. For a fixed set of schemas (the normal case, even a large one built
once at import) that is bounded and cheap, and schemas of the same shape share a
single code object behind the scenes.

The exception is a workload that builds an unbounded stream of **unique** schemas,
a new distinct schema per request that is never reused. There, compiling each one
grows memory without bound. `AUTO` already protects you (a one-shot schema never
crosses the warmup threshold, so it is never compiled), but if you run such a
workload under `ON`, turn it off:

```python
from probatio import CompilePolicy, set_compile_policy

set_compile_policy(CompilePolicy.OFF)
```

If your schemas are a fixed set built once, which is almost always the case, you do
not need to think about this.

## Numbers

On the bundled benchmarks, compiled validation runs up to roughly seven times faster
than the same schema in voluptuous, and the interpreted engine already runs about
one and a half to three and a half times faster. The exact ratio moves with the
machine, the Python version, and the schema. See [Performance](/reference/performance/)
for the cost model, the honest caveats, and how to measure it yourself.
