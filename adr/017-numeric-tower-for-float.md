# ADR-017: Honor the numeric tower for a bare `float`

**Date**: 2026-07-07
**Status**: Accepted

**Context**: A bare `float` schema validated by `isinstance`, so `Schema(float)(5)`
raised "expected float" and only a `float` was accepted. That matches voluptuous,
which is the behavior probatio deliberately mirrors (ADR-001). It is also wrong on
its own terms.

`5` is not dirty data in a `float` field: it genuinely is a valid float value. PEP
484 states that when an argument is annotated `float`, an argument of type `int` is
acceptable, and PEP 3141 grounds this at runtime (an `int` is a `numbers.Real`).
Rejecting it rejects correct input on a representational technicality, and the only
workaround was a `Coerce(float)` that normalizes nothing meaningful. In the
python-fumis migration that was five fields wearing `Coerce(float)` plus three more
`Maybe(Coerce(float))` for the optional ones, annotation noise standing in for a
rule the type system already implies.

The old rule was also inconsistent with the rest of probatio:

- `to_json_schema(Schema(float))` already emits `{"type": "number"}`, and in JSON
  Schema `number` accepts integers. So the schema probatio _published_ said `5` is
  valid while the validator probatio _ran_ rejected it.
- The `isinstance` rule already leaks the numeric tower in the worse direction:
  `Schema(int)(True)` returns `True`, because `bool` is a subclass of `int`. So
  probatio was never principled about the numeric hierarchy; it accepted
  `bool`-as-`int` (the footgun) while rejecting `int`-as-`float` (the harmless one).

This is a different case from a `str` in an `int` field. That one is dirty: reject
it, or coerce it deliberately. The tower is exactly the place where strictness buys
nothing.

**Decision**: A bare `float` honors the numeric tower on every path a bare type
reaches (`Schema(float)`, a mapping value, a sequence element, a dataclass or
TypedDict field, a union or `Maybe` base):

- a `float` passes through unchanged (a `float` subclass included),
- an `int` is accepted and returned as `float(value)`,
- `bool` is excluded (an `int` subclass, but not a number a `float` field should
  hold),
- everything else (a `str`, `None`, a `complex`) is rejected as before.

It accepts _and coerces_ rather than passing the `int` through, so a `float` field
never ends up holding an `int` and the "the type is true" invariant holds. The rule
lives in one place (`_FloatCheck`) and applies to the bare `Schema(float)` validator
as well as the annotation path, so there is no seam between the two.

This is a deliberate, documented deviation from voluptuous (ADR-001), the first on
the scalar type path. It only ever turns a rejection into an acceptance, so it
cannot change the result of a validation that passes today.

Bounded on purpose:

- **`complex`.** The tower also makes a `float` (and `int`) acceptable where
  `complex` is annotated. Rare, and deferred: `Schema(complex)(5.0)` still rejects.
  Recorded here so the omission is a decision, not a gap.
- **`bool`-as-`int`.** A bare `int` still accepts `True` today. Tightening that
  (rejecting `bool` for `int`) is a separate, _stricter_ change with real
  backward-compatibility weight, so it stays out of this decision.

**Consequences**:

- `Schema(float)` now coerces: `Schema(float)(5)` returns `5.0`. A validator that
  used to only ever return its input now normalizes an `int`. This is the intended
  divergence, not a regression.
- The runtime agrees with the JSON Schema probatio emits: an integer that
  `{"type": "number"}` accepts now validates.
- A `float` used as a matcher matches integers too, because an `int` is now a valid
  `float`. `Remove(float)` in a list drops ints as well, and a `{float: ...}` type
  key matches an int key. This follows from the rule and is not special-cased.
- Migrating off voluptuous, a schema that relied on an `int` being _rejected_ for a
  `float` field as a strictness signal now accepts it. That reliance is exactly the
  behavior this ADR argues is wrong, and it is safe by construction otherwise: no
  passing validation changes its result.
- `float` loses the inlined `isinstance` fast path the other builtin types keep:
  `_FloatCheck` exposes no `checked_type`, so the mapping and sequence engines call
  it instead of inlining, paying one call per float value to get the coercion. The
  compiled engine inlines the same tower rule in `_codegen`, bailing a `float`
  subclass or a `bool` to the interpreted `_FloatCheck`, so the two engines agree.
