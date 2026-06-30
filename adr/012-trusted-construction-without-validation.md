# ADR-012: An opt-in trusted construction path (`construct`, no validation)

**Date**: 2026-06-30
**Status**: Accepted

**Context**: Probatio is a validation library. Its whole value is checking that
arbitrary data matches a schema before you trust it. But a `DataclassSchema` does two
things on every call: it validates each field, and it constructs the instance. There
are real spots where the validation half is wasted work: the input is the
application's own data round-tripping back in (loaded from a store it wrote, or
already validated at the boundary), and the caller knows it is correct. There, a
caller currently either pays for validation it does not need, or reaches for a second
library (mashumaro, cattrs, dacite) to deserialize the trusted data fast, duplicating
the dataclass definition probatio already understands.

Measured, the gap is large: validating-and-constructing the benchmark record costs
about 2.7 µs compiled, where building it from trusted input with a purpose-built
constructor costs about 0.75 µs, faster than mashumaro (1.1 µs) and every other
deserializer in the cross-library benchmark, because it is a flat function generated
for that one dataclass and stays pure Python.

**Options considered**:

1. Do nothing. Probatio validates; for trusted-input speed, reach for a deserializer.
   One less feature, but the schema you already wrote cannot be reused for the fast
   path, and probatio leaves an easy, real win on the table.
2. A construction-time flag that makes a whole schema skip validation. Rejected: a
   schema that silently never validates is a footgun waiting at every call site, and
   it muddies what a `DataclassSchema` _is_.
3. An opt-in, per-call `construct` method, validation untouched as the default (this
   ADR).

**Decision**: Option 3. `DataclassSchema.construct(data)` (and
`TypedDictSchema.construct(data)`) builds the result from trusted data without
validating: it reads each field straight from the dict, recurses into nested
dataclasses, lists of them, `Optional` fields, and a single dataclass among plain
alternatives in a union (told apart at runtime by being a dict), fills defaults, and
constructs. It is a separate, explicitly named method, so it cannot fire by accident;
calling the schema (`schema(data)`) still validates, exactly as before. A shape the
fast path does not handle (a recursive dataclass, a union of two dataclasses, a tuple
or set of dataclasses) falls back to validating, so `construct` always returns a
correct instance for trusted input, just not always at top speed.

Probatio stays a validation library. `construct` is an escape hatch for the spots
where validation is genuinely not needed, not a repositioning as a deserializer.

**Rationale**:

- **It reuses what the schema already knows.** The dataclass structure, defaults, and
  nesting are already modelled. A trusted constructor is a second, cheaper reading of
  the same model, not a parallel definition.
- **The default is unchanged and safe.** Validation is still what a call does. The
  trust is opt-in, per call, and named loudly. The footgun of option 2 (a schema that
  never validates) does not exist here.
- **It is honestly fast.** Because it generates a flat constructor per dataclass, it
  beats the dedicated deserializers on the trust path while remaining pure Python,
  which is the comparison consumers actually want when their input is trusted.
- **The fall-back keeps it correct.** For a shape the generator does not handle,
  `construct` validates rather than guessing, so it never returns a wrong object for
  trusted-correct input.

**Consequences**:

- **A "skip validation" path exists in a validation library, and that must be taught,
  not hidden.** The name and the docs carry the warning: a wrong type lands in the
  instance unchecked. Used outside its contract (untrusted input) it defeats the
  point of the library. The guidance is explicit: `construct` for input you already
  trust, the normal call for everything else.
- **No coercion on the trusted path.** `construct` does not apply `Coerce` or
  registered type conversions; it trusts the values are already in final form. Input
  that needs converting should be validated, not constructed.
- **A small generated-code surface, like the compiled variant.** `construct` builds
  and caches one `exec`'d constructor per dataclass shape. It is bounded (one per
  schema), pure Python, and falls back rather than failing on shapes it does not
  cover.

**Revisit trigger**: `Optional` fields and single-dataclass unions are handled now;
extend the fast path to the shapes that still fall back (tuples and sets of
dataclasses, unions of two dataclasses, which need a discriminator, and a "convert
but do not check" middle setting that applies `Coerce`) if real usage shows those
falling back often enough to matter. Reconsider the feature entirely if it is found
being used on untrusted input in practice, that would be a sign the naming or docs
are not loud enough.
