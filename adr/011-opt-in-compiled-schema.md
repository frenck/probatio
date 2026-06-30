# ADR-011: An adaptive compiled schema variant (codegen, revisited)

**Date**: 2026-06-29
**Status**: Accepted

**Context**: ADR-004 removed a codegen engine. Not declined, removed: an earlier
iteration shipped an interpreted engine plus a codegen engine that generated and
`exec`'d Python source for a mapping, with a plain `Schema` adaptively upgrading
itself after a warmup threshold, and an explicit `Schema.compile`. ADR-004 deleted
all three, for four reasons that still deserve answering: the target workload
(Home Assistant config validation) validates at config load, not in a hot loop, so
the ~1.8x was close to invisible; two mapping engines are a permanent equivalence
tax that rots; a library that rewrites itself into `exec`'d source is a surprise
every reader must vet; and leanness means not adding machinery for a win nobody
feels.

This ADR revisits that decision with a materially different design, not the same
one. Three things changed since ADR-004:

- **Bail-safe, so it is not a second set of semantics.** The generated function is
  a fast _success path only_. On the first sign of any failure (a missing required
  key, a type mismatch, a validator raising, an unexpected key, a declining
  default) it bails to the one interpreted engine, which produces every error,
  path, code, and ordering. Any schema shape it does not handle is left
  interpreted. So the compiled path does not reimplement the validation semantics;
  it reimplements only the _happy path_, and even that is checked against the
  interpreted engine. The equivalence surface ADR-004 feared (marker precedence,
  error tagging, corner cases) lives in one engine still. A `--compiled` CI lane
  runs the whole deterministic behavioral suite through the generated code, so the
  happy-path equivalence is enforced, not just asserted. That lane has already
  earned its keep three times over: it caught a combinator capturing a stale
  bootstrap, a `StrEnum` key whose `repr` is not valid source to emit, and a
  recursive `$ref` mapping that, once compiled, turned a deep-data failure into an
  exponential bail-to-interpreted cascade. The curated differential tests missed all
  three; the whole-suite lane did not.
- **Adaptive by default (`AUTO`), bounded so nothing surprises the caller.** The
  default policy is `AUTO`: a schema validates interpreted and counts its calls,
  and generates only once it crosses a fixed threshold (50), so a cold or one-shot
  schema is never compiled and never pays code generation, and only a genuinely hot
  schema does. The result is identical either way; the counter is the only cost a
  cold schema pays. A caller keeps full control: `Schema(..., compile=True)` or
  `schema.compile()` (spelled to mirror `re.compile`) compiles eagerly, `compile=False`
  opts a schema out, and `set_compile_policy(OFF)` turns the whole thing off. Keeping
  that off switch is the deliberate difference from a library like mashumaro, which
  is always-on with no way out.
- **Lazy, so construction stays cheap.** Generation is deferred to a schema's first
  validation, not its construction. This directly preserves ADR-004's cold-start
  point: building thousands of schemas at import does not pay code generation
  (eager `.compile()` costs ~16x a normal build; the lazy flag costs almost
  nothing extra at build time).

Measured on a Home-Assistant-representative workload, validation only:

|                          | interpreted | compiled | gain  |
| ------------------------ | ----------- | -------- | ----- |
| config (Coerce/Range/In) | 1.6 µs      | 0.7 µs   | ~2.3x |
| dataclass (5 fields)     | 2.4 µs      | 1.0 µs   | ~2.4x |
| TypedDict                | 0.9 µs      | 0.5 µs   | ~1.7x |

Dataclasses are the clearest case: they went from _not compiled at all_ to ~2.4x,
because the generator fuses field validation and object construction into one
function with no intermediate dict. The mapping cases match the ~1.8x ADR-004
measured, plus the inlining of the common validators.

**Options considered**:

1. Hold ADR-004: one interpreted engine, no codegen. The lead over voluptuous is
   already comfortable, and the workload validates at config load.
2. An adaptive, bail-safe compiled variant, default `AUTO`, with the interpreted
   engine as the always-present semantics and fallback (this ADR).
3. mypyc (ADR-010) or a native core: accelerate the existing engine instead of
   generating code. Higher ceilings or a recompile, but neither helps the
   construction step and mypyc is only ~1.3x.

**Decision**: Option 2, with `AUTO` as the default. ADR-004's substance, that there
is one set of validation semantics, stands unchanged: the interpreted engine remains
the only semantics and the always-present fallback, and `AUTO` only swaps a generated
fast path in for a schema that has proven hot, never for a cold or one-shot one. So
the default a consumer gets is the interpreted engine for everything that is not hot,
with the hot schemas accelerating themselves, and an off switch for anyone who wants
none of it. This is a stronger position than the off-by-default opt-in first drafted
here: `AUTO` bounds the memory cost (the reason to be cautious) by construction,
while the bail-safety bounds the correctness risk, so the win is available without
asking every consumer to opt in by hand.

**Rationale**:

- **The equivalence tax is much smaller than the engine ADR-004 removed.** Bailing
  to the interpreted engine for all errors and all unsupported shapes means there
  is one set of validation semantics, not two. The compiled code can only be wrong
  by being _slower_ (an unnecessary bail) or by computing a wrong _success_ value,
  the latter caught by the differential tests and the `--compiled` lane.
- **No observable surprise.** The surprise ADR-004 feared was behavioral: a second
  engine with its own corner cases. Bail-safety removes that. `AUTO` does generate
  code behind the caller's back for a hot schema, but the result, errors, paths, and
  ordering are the interpreted engine's, because anything that is not the plain happy
  path bails to it. The one seam is side effects on the failure path: the fast path
  runs fields optimistically, so a validator or `default` factory that already ran
  before a later field bails runs again in the interpreted re-run. The value and the
  error are still identical; only the count of side effects differs, and only when
  validation fails. Probatio's own validators are pure, so this is invisible for them,
  and a user validator that mutates state should be pure too, the same expectation the
  interpreted engine already leans on. A reader who wants to vet the `exec` finds it in
  one bounded module, not woven through the codebase, and a consumer who wants none of
  it has `set_compile_policy(OFF)`.
- **Construction stays cheap.** Laziness keeps ADR-004's cold-start property: the
  default pays nothing, and even `compile=True` defers generation to first use.

**Consequences**:

- **The `exec`/codegen subsystem exists and must be vetted.** It is ~330 lines,
  opt-in, and bounded to simple mappings and dataclasses (everything else bails),
  but it is real surface, and ADR-004's "every reader must vet `exec`" caution is
  answered by _opt-in_, not eliminated.
- **There is a per-compiled-schema memory cost.** Each compiled schema holds an
  `exec`'d code object plus a namespace capturing its validators. For a _bounded_
  schema set (Home Assistant builds many schemas, but a fixed set, once) this is
  bounded. For a workload that churns _unbounded unique_ schemas it grows without
  bound; forcing compilation across the property-based test suite exhausted memory
  and is why the `--compiled` lane excludes it. This is exactly why the default is
  `AUTO` and not `ON`: a schema validates interpreted and counts its calls, then
  compiles once past a fixed threshold (50), so a one-shot or cold schema is never
  compiled and only the genuinely hot ones pay the memory. `AUTO` is the safe
  default for a mixed workload; a blanket `ON` is not, and an unbounded-unique
  workload should run with `set_compile_policy(OFF)`. The `--compiled` test lane
  runs `ON` on purpose, to compile as much as possible for parity, which is why it
  skips only the property-based, fuzz, and compile-specific suites (each of which
  churns unbounded-unique schemas or drives both modes itself). The deliberately
  pathological security suite stays in the lane, now that the recursion cascade it
  exposed is fixed: it is exactly the kind of input the compiled path must survive.
- **A second test lane.** `--compiled` (via `just test-compiled`) runs the
  behavioral suite through the generated code. It is a maintenance item, and it
  deliberately skips the property-based, fuzz, and compile-specific suites.
- **ADR-004's core caution still partly holds.** At config load, not a hot loop,
  the win is muted, exactly as ADR-004 said. The value is clearest for revalidation
  and dataclasses. `AUTO` answers the caution rather than fighting it: a schema that
  is only ever validated a handful of times at config load never crosses the
  threshold, so it stays interpreted and the machinery costs it nothing but a
  counter. The consumer that does feel the win (revalidation, dataclasses) gets it
  without lifting a finger.

**Revisit trigger**: revisit the default if a real consumer shows the cold-phase
counter is a measurable drag, or if a workload that churns unbounded-unique schemas
turns up in practice and trips the per-schema memory cost (the answer there is
`set_compile_policy(OFF)`, not a redesign). Tuning the threshold (50) is the cheap
knob before any larger change. The off switch stays, on purpose, so a consumer who
wants none of this always has a clean way out.
