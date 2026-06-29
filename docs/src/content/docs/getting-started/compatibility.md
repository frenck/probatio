---
title: Compatibility
description: How Probatio stays compatible with voluptuous, the compatibility shim, and where it deviates on purpose.
---

Probatio targets behavioral compatibility with voluptuous 0.16.0. The public
surface mirrors it: the same names, the same signatures, the same semantics. See
the [API reference](/reference/) for the full surface. For most code, the only
change is the import line.

## The compatibility shim

Most code uses voluptuous through its public API. There, swapping
`import voluptuous` for `import probatio` is enough, and your schemas keep
working.

Some dependencies are harder. They import voluptuous *internals*, not just the
public names. A real example is `annotatedyaml`, which imports
`voluptuous.schema_builder._compile_scalar`. You cannot edit that code, and a
plain import swap does not reach it.

For that case, Probatio ships `install_as_voluptuous` in `probatio.compat`. Call
it once, very early in process startup, before anything imports voluptuous. It
registers Probatio (and a small set of voluptuous-shaped submodules, including
`schema_builder` with the `_compile_scalar` internal) into `sys.modules` under
the `voluptuous` name. Every later `import voluptuous`, including the ones inside
your dependencies, then resolves to Probatio for the rest of the process.

<!-- verify: skip -->
```python
from probatio.compat import install_as_voluptuous

install_as_voluptuous()
```

The call is idempotent but has no teardown. It shadows a real voluptuous that
was already imported, and it aliases process-wide, so it is meant for an
application or a test harness that owns the process. Do not call it from library
code that others import.

:::caution[Process-wide]
`install_as_voluptuous` mutates `sys.modules` for the whole process. Call it from
your application entry point, not from a library, and call it before the first
`import voluptuous` anywhere in the process.
:::

## Intentional deviations

Compatibility is the target. A few behaviors still differ on purpose, and each
is a deliberate improvement over a sharp edge:

- Recursive `Self` on cyclic or very deep data raises a clean `Invalid` instead
  of letting Python crash with a `RecursionError`. You get a validation error
  with a path, not a stack overflow.
- `from_json_schema` treats its input as untrusted. It refuses a catastrophically
  backtracking `pattern` and a pathologically deep document rather than hanging or
  overflowing the stack.
- A missing complex required key (`Required(Any("a", "b"))`, "at least one of
  these keys") raises one clear error. voluptuous 0.16.0 additionally emits a
  redundant `required key not provided` for the same key; Probatio reports it
  once. The first, meaningful error is identical.
- Any `Mapping` is accepted, not only `dict`. A `MappingProxyType`, a multidict,
  or any custom mapping validates and returns a plain `dict`, where voluptuous
  rejects it. A genuine `dict` subclass is preserved as its own class, matching
  voluptuous, so a Home Assistant `NodeDictClass` keeps its type (and the source
  line it carries) across validation. A strict superset, so dict code is
  unaffected.
- A callable validator that raises `ValueError("reason")` keeps the reason in
  the error ("not a valid value: reason"), where voluptuous drops it. A
  `ValueError` with no message still reads "not a valid value".
- An `enum` member works as a scalar schema and as a mapping key (matched by
  equality), where voluptuous 0.16.0 rejects it with `SchemaError`. Upstream adds
  this in [PR #537](https://github.com/alecthomas/voluptuous/pull/537); Probatio already has it, which Home Assistant relies on for
  its `StrEnum`/`IntEnum` service and attribute names.
- Built-in validators never leak a raw exception on a wrong-typed value:
  `Replace("a", "b")(42)` raises `MatchInvalid` rather than the `TypeError` from
  `re.sub`, and `Number()` on `None`/`dict`/`set`/`bytes`/an empty sequence
  raises `Invalid`. voluptuous fixes the same edges upstream in [PR #540](https://github.com/alecthomas/voluptuous/pull/540) and #539.
- `extend` accepts another `Schema`, merging its keys and preserving its
  `required` intent (its `extra` must match the result's). voluptuous 0.16.0
  raises an `AssertionError`; it is added upstream in [PR #538](https://github.com/alecthomas/voluptuous/pull/538).
- Validating a list reports every failing item, each with its index, where
  voluptuous 0.16.0 stops at the first failing nested item (open request, issue
  #171). The diagnostics are more complete; error-iterating code is unaffected.
- A set schema (`{Coerce(int)}`) transforms its elements like a list schema does,
  so a `Coerce` coerces. voluptuous returns the set untransformed (bug, issue
  #400).
- A failing `Any` with concrete branches lists them ("expected int or str or
  None") as `AnyInvalid`, where voluptuous reports only the first branch or "not
  a valid value" ([issue #412](https://github.com/alecthomas/voluptuous/issues/412)). A validator branch keeps surfacing its own error.

Where Probatio diverges, it tells you with a normal error, not a crash.

## How compatibility is checked

Two things keep Probatio honest, and neither is a claim you have to take on
faith.

First, differential tests. Probatio and voluptuous run the same schemas against
the same inputs, and their results are compared. Voluptuous is the oracle: a
divergence is treated as a Probatio bug unless it is one of the documented
deviations above. The comparison is driven by generated schemas and data, so it
covers more than a hand-written suite would.

Second, a real-world proof. Home Assistant's own `config_validation` test suite
runs against Probatio through the compatibility shim, and it passes. That suite
exercises voluptuous hard across a large, real configuration surface, so it is a
strong signal that the drop-in promise holds in practice.

## Where to next

- [Migrating from voluptuous](/getting-started/migrating-from-voluptuous/): the
  step-by-step swap.
- [API reference](/reference/): the full public surface.
