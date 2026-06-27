# ADR-002: MIT license

**Date**: 2026-06-24
**Status**: Accepted

**Context**: Need to choose a license. Probatio is a clean-room
reimplementation (see ADR-001), so it carries no upstream license obligations
and we are free to pick.

**Decision**: MIT.

**Rationale**:

- Maximum adoption potential.
- Compatible with Home Assistant (Apache 2.0) and the wide range of projects
  that use voluptuous today.
- A clean, permissive license that fits a drop-in replacement: consumers should
  not trade a license headache for a maintenance win.
