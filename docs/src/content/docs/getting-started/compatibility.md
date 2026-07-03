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

Some dependencies are harder. They import voluptuous _internals_, not just the
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

- `str(error)` renders a dotted path and drops the error-type clause (ADR-015).
  voluptuous's `expected int for dictionary value @ data['server']['port']`
  reads `expected int at 'server.port'` in Probatio, with sequence indices as
  `[n]`. A non-mapping is rejected as "expected a mapping" rather than
  "expected a dictionary". The attributes (`path`, `msg`, `error_message`,
  `error_type`) are unchanged, so only code that string-matches `str(error)`
  notices.
- Recursive `Self` on cyclic or very deep data raises a clean `Invalid` instead
  of letting Python crash with a `RecursionError`. You get a validation error
  with a path, not a stack overflow.
- `from_json_schema` treats its input as untrusted. It refuses a catastrophically
  backtracking `pattern` and a pathologically deep document rather than hanging or
  overflowing the stack.
- A missing complex required key (`Required(Any("a", "b"))`, "at least one of
  these keys") raises one clear error. voluptuous 0.16.0 additionally emits a
  redundant `required key not provided` for the same key; Probatio reports it
  once. The first, meaningful error matches voluptuous.
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
  raises `Invalid`. voluptuous fixes the same edges upstream in [PR #540](https://github.com/alecthomas/voluptuous/pull/540) and
  [PR #539](https://github.com/alecthomas/voluptuous/pull/539).
- `extend` accepts another `Schema`, merging its keys and preserving its
  `required` intent (its `extra` must match the result's). voluptuous 0.16.0
  raises an `AssertionError`; it is added upstream in [PR #538](https://github.com/alecthomas/voluptuous/pull/538).
- Validating a list reports every failing item, each with its index, where
  voluptuous 0.16.0 stops at the first failing nested item (open request,
  [issue #171](https://github.com/alecthomas/voluptuous/issues/171)). The
  diagnostics are more complete; error-iterating code is unaffected.
- A set schema (`{Coerce(int)}`) transforms its elements like a list schema does,
  so a `Coerce` coerces. voluptuous returns the set untransformed (bug,
  [issue #400](https://github.com/alecthomas/voluptuous/issues/400)).
- A failing `Any` with concrete branches lists them ("expected int or str or
  None") as `AnyInvalid`, where voluptuous reports only the first branch or "not
  a valid value" ([issue #412](https://github.com/alecthomas/voluptuous/issues/412)). A validator branch keeps surfacing its own error.

Where Probatio diverges, it tells you with a normal error, not a crash.

## How compatibility is checked

The drop-in claim is tested, not asserted. voluptuous 0.16.0 is pinned as a
dev-only oracle in Probatio's development dependencies (no code is copied from
it), and three layers of evidence back the claim:

- **voluptuous's own test suite runs against Probatio.** Through the shim,
  upstream `tests.py` at 0.16.0 imports Probatio instead of voluptuous. A clean
  run is all green: every divergence is one of the documented deviations above,
  marked as expected with a reason, so any new break shows up loudly. This is
  voluptuous's own authors' notion of the contract, checked.
- **Differential tests in Probatio's suite** (`tests/test_conformance.py`,
  `tests/test_fidelity.py`, `tests/test_v0_16.py`). The same schemas and inputs
  run through both libraries and the results are compared: the same accepted or
  normalized value, the same error paths, and the same bare error messages
  where downstream code string-matches them. A divergence is treated as a
  Probatio bug unless it is one of the documented deviations above.
- **Home Assistant's `config_validation` test suite passes** with voluptuous
  swapped out for Probatio through the shim. That suite exercises voluptuous
  hard across a large, real configuration surface, so it is a strong signal
  that the drop-in promise holds in practice.

## Where to next

- [Migrating from voluptuous](/getting-started/migrating-from-voluptuous/): the
  step-by-step swap.
- [API reference](/reference/): the full public surface.
