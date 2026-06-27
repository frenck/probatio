# ADR-005: Pure Python, no required runtime dependencies

**Date**: 2026-06-26
**Status**: Accepted

**Context**: Probatio is a drop-in for voluptuous (see ADR-001), and voluptuous
is pure Python with no required runtime dependencies. A validation library sits
low in the dependency tree: Home Assistant and many other projects pull it in
transitively, often onto a wide range of platforms and Python builds. Anything
Probatio requires at runtime, every one of those consumers requires too. A
native extension or a mandatory third-party dependency would push install cost,
wheel-building, and supply-chain surface onto every downstream project, for a
library whose hot path is config load, not a tight inner loop (see ADR-004).

**Options considered**:

1. Pure Python, standard library only at runtime, with optional extras for the
   parts that benefit from faster or extra backends.
2. A native core (Rust or C) for the validation engine.
3. Require third-party runtime dependencies, like orjson for JSON or PyYAML for
   YAML, so the loaders always have a fast or capable backend.

**Decision**: Option 1. Probatio is pure Python and uses only the standard
library at runtime. There are no required runtime dependencies. Faster or extra
backends are opt-in extras: `fast` (orjson for JSON, YAMLRocks for YAML), `yaml`
(PyYAML as the portable YAML fallback), and `toml` (tomli-w for writing TOML,
since the standard library reads TOML but does not write it).

**Rationale**:

- **Portability**: Pure Python runs anywhere CPython runs, including platforms
  and interpreters that have no prebuilt native wheel. No compiler, no build
  step, no native extension. Install it and import it.
- **Easy install and small surface**: No required dependencies means nothing to
  resolve, nothing to pin, and a smaller supply-chain surface for every
  downstream project. The wheel bundles no third-party code, and the release
  workflow ships a CycloneDX SBOM so that claim is verifiable from the artifact.
- **Drop-in parity**: voluptuous is dependency-free pure Python. A drop-in that
  dragged in a native toolchain or mandatory dependencies would be a worse trade
  than the library it replaces.
- **The speed is already there**: the interpreted engine already beats
  voluptuous on representative workloads (see ADR-004), and validation happens
  at config load, not in a hot loop. The raw speed a native core would buy is
  close to invisible where Probatio is actually used.
- **Pay only for what you use**: callers who want faster JSON or YAML, or TOML
  writing, install the matching extra. Everyone else carries nothing extra.

**Consequences**:

- We give up the raw throughput a native core might offer. ADR-004 records that
  if a future, measured workload genuinely needs more speed, a native core is
  the path to revisit, not regenerated Python source. That door stays open, but
  the default stays pure Python and dependency-free.
- The loaders and dumpers must degrade gracefully: use the fast backend when its
  extra is installed, fall back to the standard library otherwise, and raise a
  clear error only when a capability the standard library genuinely lacks (TOML
  writing) is used without its extra.
- Optional backends ship under their own licenses and are installed by the
  caller, never bundled with Probatio (see THIRD_PARTY_LICENSES.md).
- The no-dependency promise is a constraint on every future change: adding a
  required runtime dependency is a decision that would need its own ADR.
