# ADR-006: Python support floor (requires-python >=3.12)

**Date**: 2026-06-28
**Status**: Accepted

**Context**: Probatio is a drop-in for voluptuous (see ADR-001), and voluptuous
supports a long tail of interpreters, down to Python 3.9 at the time of writing.
A drop-in that targets only recent Python is a deliberate tension: a project
already on an older interpreter cannot adopt Probatio by changing one import. We
have to decide how far back to reach, knowing that every supported version is a
version the code must stay correct on and the test matrix must cover.

This ADR originally set the floor at Python 3.13. It is revised here to 3.12:
the codebase only reaches for syntax and typing features that already exist in
3.12 (PEP 695 type aliases and generic classes are the most modern of them), so
supporting 3.12 costs nothing in compatibility shims while widening the reach of
the drop-in to every environment still on a fully supported 3.12.

**Options considered**:

1. Set the floor at Python 3.12.
2. Set the floor at Python 3.13.
3. Match voluptuous and support 3.9 or newer, so any current voluptuous user can
   swap the import regardless of their interpreter.

**Decision**: Option 1. `requires-python = ">=3.12"`. Probatio requires Python
3.12 or newer.

**Rationale**:

- **No compatibility cost**: the code already runs unmodified on 3.12. The newest
  features it uses (PEP 695 `type` aliases and generic classes) landed in 3.12,
  so dropping to that floor needs no version guards and no shims. The
  implementation still reads as modern Python.
- **Wider reach for free**: Python 3.12 is fully supported upstream into 2028 and
  is widely deployed. Supporting it lets more current voluptuous users adopt the
  drop-in without first upgrading their interpreter, at no maintenance cost.
- **Maintained, not legacy**: the point of Probatio is a maintained library for
  today, not one that carries the weight of interpreters near or past end of
  life. 3.12 is current; 3.9 through 3.11 are not worth the permanent tax.
- **Where it is used**: the primary target, Home Assistant, already runs on
  recent Python, so the floor is not chosen to satisfy it; it is chosen because
  3.12 is the oldest version the code runs on cleanly.

**Consequences**:

- We exclude 3.11 and older. A project still on Python 3.9 through 3.11 cannot
  adopt Probatio without first upgrading Python, so the drop-in promise is scoped
  to 3.12 and newer. This is an intentional deviation from voluptuous and is
  documented as such (see ADR-001).
- We can write modern Python throughout, with no version-conditional code paths
  to maintain or test, as long as it stays within what 3.12 provides.
- The test matrix covers 3.12 alongside the newer versions, and the lint and type
  targets are pinned to 3.12 so a 3.13-only feature cannot slip in unnoticed.

**Support policy**: New Python versions are added to the supported set as they
are tested, so the matrix tracks current Python over time. The floor moves
forward deliberately, not automatically: raising it is a decision in its own
right, made when keeping an older version costs more than it is worth.
