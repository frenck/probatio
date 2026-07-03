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

Imports that reach into voluptuous submodules keep working too: `voluptuous`,
`voluptuous.error`, `voluptuous.validators`, `voluptuous.humanize`,
`voluptuous.util`, and `voluptuous.schema_builder` all have Probatio equivalents.

## Known differences

Probatio targets behavioral compatibility, so the list is short and every entry
is a deliberate improvement, not a regression:

- **The rendered error string differs (ADR-015).** voluptuous renders
  `expected int for dictionary value @ data['server']['port']`; Probatio renders
  the same error as `expected int at 'server.port'`. The path is a dotted trail
  (sequence indices as `[n]`), the error-type clause is not rendered, and a
  non-mapping is rejected as "expected a mapping" instead of "expected a
  dictionary". The attributes (`path`, `msg`, `error_message`, `error_type`)
  keep their voluptuous semantics, so only code that string-matches
  `str(error)` notices; switch that code to `path` and `error_message`, or to
  `as_dict()`.
- **Recursive `Self` schemas fail cleanly.** Cyclic or pathologically deep data
  raises a normal `Invalid` (caught with the rest of your validation errors)
  instead of crashing with `RecursionError`, as voluptuous does. The depth limit
  scales with the interpreter's recursion limit, so legitimately deep data is
  unaffected.
- **`from_json_schema` treats its input as untrusted.** A catastrophically
  backtracking `pattern` or a pathologically deep document is refused with
  `SchemaError`, rather than hanging or overflowing the stack. This only matters
  when the schema document itself comes from an untrusted source.
- **A missing complex required key reports once.** For
  `Required(Any("a", "b"))` ("at least one of these keys"), voluptuous 0.16.0
  emits both the "at least one of [...] is required" error and a redundant
  "required key not provided" for the same key. Probatio reports the single,
  meaningful error; the first error matches voluptuous.
- **Any `Mapping` is accepted, not only `dict`.** A `MappingProxyType`, a
  multidict, or any custom type implementing the `Mapping` protocol validates
  and returns a plain `dict`, where voluptuous rejects it with "expected a
  dictionary". A genuine `dict` subclass is preserved as its own class, the same
  as voluptuous, so a subclass that carries metadata (like Home Assistant's
  `NodeDictClass`) survives validation. This is a strict superset, so dict code
  is unaffected.
- **A callable's `ValueError` message is kept.** When a plain callable validator
  raises `ValueError("reason")`, the reason is carried into the error ("not a
  valid value: reason") instead of being dropped. A `ValueError` with no message
  still reads "not a valid value".
- **Enum members work as schemas and keys.** An `enum` member (a `StrEnum` or
  `IntEnum` value) is matched by equality and can be used as a mapping key, with
  `Required`/`Optional`, or as a value. voluptuous 0.16.0 rejects this with
  `SchemaError`; it is being added upstream in [PR #537](https://github.com/alecthomas/voluptuous/pull/537).
- **Built-in validators never leak raw exceptions.** A wrong-typed value raises
  a clean `Invalid` rather than a bare `TypeError`/`ValueError` from the
  underlying call: `Replace("a", "b")(42)` raises `MatchInvalid`, and `Number()`
  on `None`, a `dict`, a `set`, `bytes`, or an empty sequence raises `Invalid`.
  voluptuous fixes the same edges upstream in [PR #540](https://github.com/alecthomas/voluptuous/pull/540) and [PR #539](https://github.com/alecthomas/voluptuous/pull/539).
- **`extend` accepts another `Schema`.** `base.extend(other_schema)` merges the
  extension's keys and preserves its `required` intent across the merge
  (recursively into nested mappings); its `extra` must match the resulting
  schema's. voluptuous 0.16.0 raises an `AssertionError`; it is added upstream in
  [PR #538](https://github.com/alecthomas/voluptuous/pull/538). Pass the extension's `.schema` dict for the old raw-merge behavior.
- **Every failing list item is reported.** Validating a list collects an error
  for each failing item, not just the first. voluptuous 0.16.0 stops at the first
  failing nested item (open request, [issue #171](https://github.com/alecthomas/voluptuous/issues/171)). You get more complete
  diagnostics; code that iterates `MultipleInvalid.errors` is unaffected.
- **Set schemas transform their elements.** A set schema like `{Coerce(int)}`
  runs the element schema on each item, so a `Coerce` actually coerces.
  voluptuous returns the set untransformed (bug, [issue #400](https://github.com/alecthomas/voluptuous/issues/400)).
- **`Any` names its alternatives.** When every branch is concrete (a type,
  `None`, or a literal), a failing `Any` reports "expected int or str or None"
  instead of voluptuous's first-branch-only "expected int" or "not a valid value"
  ([issue #412](https://github.com/alecthomas/voluptuous/issues/412)). A branch that is an arbitrary validator keeps surfacing its own
  error. The error class for the combined message is `AnyInvalid`.

If you depend on any of the old behaviors (you almost certainly do not), that is
the place to know about it.
