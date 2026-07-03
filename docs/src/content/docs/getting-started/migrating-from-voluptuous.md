---
title: Migrating from voluptuous
description: Probatio aims to be a drop-in replacement for voluptuous. Here is what that means and how to switch.
---

Probatio is a clean-room reimplementation of
[voluptuous](https://github.com/alecthomas/voluptuous) with the same public API.
The goal is simple: you should be able to switch with a one-line import change
and keep your existing schemas.

Behavioral compatibility with voluptuous is the correctness target, checked
against voluptuous itself. If you hit a difference that is not listed below as
intentional, treat it as a bug and
[open an issue](https://github.com/frenck/probatio/issues).

## The short version

Replace the import:

```python
# Before
from voluptuous import Schema, Required, Optional, All, Any, Coerce, Invalid

# After
from probatio import Schema, Required, Optional, All, Any, Coerce, Invalid
```

Your schemas stay the same:

```python
from probatio import Schema, Required, Optional, All, Range

schema = Schema(
    {
        Required("name"): str,
        Optional("port"): All(int, Range(min=1, max=65535)),
    }
)
```

## What carries over

The names you reach for in voluptuous are present in Probatio with the same
behavior and the same signatures (including positional `required`/`extra` on
`Schema`):

- `Schema`, its calling convention, and `extend`.
- Markers: `Required`, `Optional`, `Remove`, `Extra`, `Inclusive`, `Exclusive`.
- Combinators: `All`, `Any`, `Union`, `Switch`, `SomeOf` (and `And`/`Or`).
- Validators: `Coerce`, `Range`, `Clamp`, `Length`, `In`, `NotIn`, `Match`,
  `Contains`, `Equal`, `Literal`, `Set`, `Unordered`, `Object`, `Maybe`,
  `ExactSequence`, `Unique`, the string transforms, `Email`/`Url`/`FqdnUrl`,
  `Datetime`/`Date`, `IsDir`/`IsFile`/`PathExists`, and the rest.
- Helpers: the `validate` decorator and the `raises` guard.
- Errors: `Invalid`, `MultipleInvalid`, and the semantic subclasses, including
  the error path, and `humanize_error` / `validate_with_humanized_errors` in
  `probatio.humanize`.

Probatio ships three submodules you can import from directly: `probatio.error`,
`probatio.validators`, and `probatio.humanize`. Deeper `voluptuous.*` imports,
including `voluptuous.util` and `voluptuous.schema_builder`, are covered by the
[compatibility shim](/getting-started/compatibility/#the-compatibility-shim),
which registers voluptuous-shaped modules under the `voluptuous` name.

## When a dependency imports voluptuous

Your own code migrates with an import swap. A dependency you do not control may
still `import voluptuous`, and editing your imports does not reach it. For that
case, call `install_as_voluptuous()` from `probatio.compat` once, early at
process startup; every later `import voluptuous` then resolves to Probatio,
including the ones inside your dependencies. The
[compatibility shim](/getting-started/compatibility/#the-compatibility-shim)
section has the details and the one sharp edge (it aliases process-wide).

## Known differences

Every intentional deviation is a deliberate improvement, not a regression, and
the [compatibility page](/getting-started/compatibility/#intentional-deviations)
owns the complete list. The ones that bite in practice:

- **The rendered error string differs (ADR-015).** voluptuous renders
  `expected int for dictionary value @ data['server']['port']`; Probatio renders
  the same error as `expected int at 'server.port'`. The attributes (`path`,
  `msg`, `error_message`, `error_type`) keep their voluptuous semantics, so only
  code that string-matches `str(error)` notices; switch that code to `path` and
  `error_message`, or to `as_dict()`.
- **Every failing list item is reported**, not just the first, so
  `MultipleInvalid.errors` can hold more entries than under voluptuous. Code
  that asserts an exact error count on list input notices; code that iterates
  the errors is unaffected.
- **Set schemas transform their elements.** A set schema like `{Coerce(int)}`
  runs the element schema on each item, so a `Coerce` actually coerces, where
  voluptuous returns the set untransformed.

Anything else that differs and is not on the
[deviations list](/getting-started/compatibility/#intentional-deviations) is a
bug; [open an issue](https://github.com/frenck/probatio/issues).

## Where to next

- [Compatibility](/getting-started/compatibility/): the shim in full, the
  complete list of intentional deviations, and how the drop-in claim is tested.
- [Error handling](/guides/error-handling/): paths, multiple errors at once, and
  human-readable messages.
- [Dict schemas and markers](/guides/dict-schemas-and-markers/): required and
  optional keys, defaults, and extra-key policy.
