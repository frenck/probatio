# ADR-001: Clean-room reimplementation of voluptuous

**Date**: 2026-06-24
**Status**: Accepted

**Context**: [voluptuous](https://github.com/alecthomas/voluptuous) is a widely
used Python data validation library with a small, pleasant API. It is also
barely maintained, and its license history makes reuse awkward for some
consumers. We want a library that keeps the voluptuous API but is actively
maintained, cleanly licensed, and free to evolve internally.

**Options considered**:

1. Fork voluptuous and maintain the fork.
2. Vendor voluptuous and patch it as needed.
3. Reimplement the API from scratch (clean room), keeping it compatible.

**Decision**: Option 3, reimplement fresh. No code is copied from voluptuous.
Probatio matches the voluptuous public API by behavior, validated against how
voluptuous behaves, not by lifting its source.

**Rationale**:

- **Maintenance**: A fork inherits the upstream code and its quirks. A fresh
  implementation lets us structure the internals for clarity and long-term
  upkeep.
- **Licensing**: Clean-room code with no copied source can ship under a clear
  MIT license (see ADR-002) without dragging along the upstream license
  history.
- **Compatibility without lock-in**: We owe users the API, not the internals.
  Keeping the API stable while owning the implementation lets us fix bugs and
  improve performance without being constrained by upstream decisions.
- **Drop-in intent**: The whole value proposition is "change the import, keep
  your schemas". That requires matching behavior, which a clean-room
  implementation can target deliberately.

**Consequences**:

- We must build and maintain a compatibility test surface that pins behavior to
  voluptuous, so regressions against the drop-in promise are caught.
- We own every bug; there is no upstream to defer to.
- We are free to improve internals, error messages, and performance as long as
  the documented API behavior holds.
- Any intentional deviation from voluptuous must be documented as such.
