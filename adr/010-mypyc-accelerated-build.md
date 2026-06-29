# ADR-010: mypyc as an optional accelerated build

**Date**: 2026-06-29
**Status**: Proposed

**Context**: ADR-005 chose pure Python with no required runtime dependencies, and
recorded that "if a future, measured workload genuinely needs more speed, a native
core is the path to revisit." ADR-004 says the same: the door to a native core
stays open, the default stays interpreted.

We have now reached the interpreted floor. A long pass of profile-driven work
(cProfile and py-spy on Home-Assistant-representative schemas) flipped construction
from ~1.47x slower than voluptuous to ~1.64x faster, and holds a ~2.3x validation
lead. After that work, the profiles show the hot paths are doing irreducible work:
validation spends ~47% of its time in one Python `for` loop over a mapping's keys,
the rest in core dispatch. You cannot make that loop meaningfully faster _in
CPython_; the cost is the interpreter executing bytecode, not the logic. The next
significant speedup is architectural, not algorithmic: change what runs the code.

mypyc is the lowest-effort native path. It compiles type-annotated Python straight
to a C extension. Probatio is unusually ready for it: the package is mypy-strict
clean already, which is mypyc's input contract.

**What an actual build showed**: a first spike compiled the four core modules
(`error`, `markers`, `_engine`, `schema`) plus the rest of the package and reported
1.30x construction and 1.38x validation. That spike benchmarked the happy path but
never ran the test suite against the compiled build. Building it for real and
running the full suite tells a narrower story. "Compiles without error" is not
"behaves correctly", and three of the four core modules fail the suite once
compiled:

- **`error.py`** breaks the error model. The `Invalid` hierarchy reads its
  per-subclass `default_code` off the type object (`type(self).default_code`).
  mypyc stores it as an instance slot, not a class attribute, so reading `.code`
  raises and the failure path segfaults. It is pure failure-path code (it runs
  only when validation fails), so compiling it buys nothing on the hot path.
- **`schema.py`** cannot be compiled. `Schema` must stay a non-native class because
  `DataclassSchema`/`TypedDictSchema` and user code subclass it, and mypyc forbids
  an interpreted class inheriting a compiled one. A non-native `Schema` then trips
  an internal mypyc assertion on `_compile_self`'s nested closure. This is the
  module that holds construction, the headline the first spike claimed.
- **`markers.py`** compiles but silently breaks `isinstance(x, Marker)` on the
  non-native marker subclasses, so marker ordering and equality go wrong. The suite
  catches it.

Only **`_engine.py`**, the validation hot loop, compiles cleanly: zero source
changes, full behavioral parity (the whole suite passes against it). On the
Home-Assistant-representative workload:

|              | pure Python | mypyc (engine only) | gain  |
| ------------ | ----------- | ------------------- | ----- |
| construction | 0.87s       | 0.81s               | 1.08x |
| validation   | 0.80s       | 0.61s               | 1.29x |

The validation gain is real and lands with no caveats. Construction barely moves,
because construction lives in `schema.py`, which does not compile. So the honest
payoff today is a validation accelerator, not the construction win the first spike
advertised. The construction story would need real work on `schema.py` (refactoring
to dodge the mypyc closure limitation, and re-checking the non-native subclass
contract), not the "cosmetic adjustments" that spike assumed.

**Options considered**:

1. Stay pure Python only. Accept the interpreter floor; the lead over voluptuous
   is already comfortable.
2. mypyc as an optional accelerated build of the engine, with pure Python as the
   always-present fallback. Compile what compiles cleanly (`_engine.py`), leave the
   rest interpreted.
3. A native core (Rust or C, pydantic-core style). The highest ceiling (5x to
   50x), but a rewrite into effectively a different project, with an FFI boundary
   and a Rust toolchain to maintain.
4. Per-schema code generation (drop ADR-004). Generate and `exec` a specialized
   validator per schema. It speeds validation but makes construction slower, which
   is the wrong trade for Home Assistant, whose cold start is construction-bound
   (thousands of schemas built at import, each config validated roughly once).

**Decision**: Option 2, deferred. Pure Python stays the canonical build and the
guaranteed fallback (ADR-005 holds in spirit: install it and import it, on any
platform, with no compiler). The opt-in accelerated build compiles `_engine.py`
only, the one module that stays correct under mypyc. It is recorded here as a
validated, ready option to adopt when we choose to, not now. The build is wired up
behind `just build-fast` (it runs `scripts/build_accelerated.py`, which drops the
compiled `.so` next to the source; `just clean` removes it), so the path is real
and runnable, not just described.

**Rationale**:

- **Measured, not assumed, and corrected**: the numbers and the blockers above are
  from a working build run against the full suite, not an estimate. The first
  spike's wider claim did not survive contact with the tests; this records what
  actually holds.
- **Keeps the architecture**: same engine, same ADR-004 single-engine design, same
  drop-in semantics. mypyc accelerates the existing code; it does not replace it.
- **Right tool, narrower scope**: a native rewrite (option 3) abandons the
  clean-room readable-Python identity for a payoff we do not need yet; codegen
  (option 4) optimizes the wrong axis for the primary consumer. mypyc on the engine
  is a real validation win with no source contortion.
- **Fallback preserves the promise**: shipping a compiled wheel with a pure-Python
  fallback keeps ADR-005's portability for platforms without a prebuilt wheel.

**Consequences**:

- **The payoff today is validation, not construction.** Adopting this accelerates
  validation ~1.29x and leaves construction essentially unchanged, because
  `schema.py` does not compile. If construction is the goal (it dominates Home
  Assistant's cold start), this is not yet the answer; it would need the `schema.py`
  work above first.
- **Packaging is the real ongoing cost.** Adopting this means building and shipping
  per-platform wheels (cibuildwheel in CI) alongside a pure-Python sdist, and a
  runtime that prefers the compiled module when present and falls back otherwise.
  This is the part that amends ADR-005: the default install would carry a native
  extension on supported platforms, with pure Python as the fallback rather than
  the only artifact.
- **A second test lane, without coverage.** CI would run the suite against both the
  pure and the compiled build, since mypyc can change behavior in edge cases (it
  did, in three modules). The compiled lane runs with coverage off: mypyc code is
  not traced, and the tracer can crash native code. The pure lane keeps the 100%
  coverage gate.
- **The other core modules stay interpreted until reworked.** Compiling `error.py`,
  `markers.py`, or `schema.py` needs real changes (a class-attribute model that
  survives mypyc; a non-native `Schema` that mypyc will actually compile; an
  `isinstance` path that holds for non-native subclasses), not decorators. The
  `scripts/build_accelerated.py` header documents each blocker at the point it
  matters.
- **The door stays open wider, not the default changed**: until this is adopted,
  ADR-005 and ADR-004 stand unchanged. Adoption is a follow-up decision; this ADR
  records that the engine path is validated and what it costs.

**Revisit trigger**: adopt when the validation gain is worth the packaging and CI
cost, for example if a consumer with a tight validation loop needs it. Revisit the
wider compile (construction) only with budget to do the `schema.py` work, not as a
drop-in. The build script and numbers here are the starting point for that work.
