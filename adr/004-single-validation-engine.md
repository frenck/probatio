# ADR-004: A single validation engine (no codegen)

**Date**: 2026-06-25
**Status**: Accepted, revised by [ADR-011](011-opt-in-compiled-schema.md)

**Context**: Probatio compiles a declarative schema once into a callable, then
runs that callable per validation (like `re.compile`). An earlier iteration
shipped two engines: an interpreted closure engine, and a codegen engine that
generated Python source for a mapping schema and `exec`'d it, with a plain
`Schema(...)` adaptively upgrading itself to the codegen engine after a warmup
threshold. Measured on a representative config schema, the interpreted engine is
already about 2x faster than voluptuous; the codegen engine added roughly another
1.8x on top.

**Decision**: Keep only the interpreted engine. Remove the codegen engine, the
adaptive warmup, and the explicit `Schema.compile` constructor.

**Rationale**:

- Validation in the target workloads (Home Assistant config validation) happens
  at config load, not in a hot inner loop. The extra 1.8x is close to invisible
  there, while the interpreted engine already beats voluptuous.
- A second mapping implementation is a permanent tax: the two engines must stay
  behaviorally identical on every voluptuous corner case (marker precedence,
  literal-vs-type key ordering, error paths, error tagging), defended only by
  tests. That equivalence surface is exactly the kind of thing that rots.
- A library that rewrites itself into `exec`'d source behind the caller's back
  is a surprise, and the `exec`/codegen subsystem is something every reader must
  vet before trusting the library. For a library, comprehension and a small
  surface matter more than a microbenchmark win.
- Leanness is a feature here. Declining the clever path keeps the codebase
  honest: measure first, and when you have already won, do not add machinery for
  a win nobody will feel.

**Consequences**: One engine, one set of mapping semantics, no `exec`. The
`__probatio_safe__` fast-path dispatch (built-in validators declare they only
raise `Invalid`, so the engine calls them without the ValueError-wrapping guard)
stays, since it is a small, contract-based optimization, not a second engine. If
a future, measured workload genuinely needs more speed, a native core is the
path to revisit, not regenerated Python source.

**Revisited by ADR-011.** The substance of this decision still stands: the
interpreted engine remains the only validation semantics and the always-present
fallback. ADR-011 reopens the codegen question with a different design, an
adaptive, bail-safe compiled variant whose default policy is `AUTO`: a schema runs
interpreted and compiles itself only once it proves hot, and every error and
unsupported shape falls back to this engine. So a cold or one-shot schema still
uses the interpreted engine, while a hot schema accelerates itself. ADR-011 weighs
that honestly against the four objections above rather than overturning them.
