# ADR-006: Python support floor (requires-python >=3.13)

**Date**: 2026-06-26
**Status**: Accepted

**Context**: Probatio is a drop-in for voluptuous (see ADR-001), and voluptuous
supports a long tail of interpreters, down to Python 3.9 at the time of writing.
A drop-in that targets only recent Python is a deliberate tension: a project
already on an older interpreter cannot adopt Probatio by changing one import. We
have to decide how far back to reach, knowing that every supported version is a
version the code must stay correct on and the test matrix must cover.

**Options considered**:

1. Set the floor at Python 3.13.
2. Match voluptuous and support 3.9 or newer, so any current voluptuous user can
   swap the import regardless of their interpreter.

**Decision**: Option 1. `requires-python = ">=3.13"`. Probatio requires Python
3.13 or newer.

**Rationale**:

- **Modern syntax and typing**: targeting recent Python lets the code use
  current syntax and typing features without compatibility shims or version
  guards. The implementation stays clean and reads as modern Python, which fits
  a freshly written clean-room codebase.
- **Maintained, not legacy**: the point of Probatio is a maintained library for
  today, not one that carries the weight of interpreters that are themselves
  near or past end of life. Supporting the long tail is a permanent tax on every
  change.
- **Where it is used**: the primary target, Home Assistant, already runs on
  recent Python, so the practical reach of the drop-in promise is not meaningfully
  narrowed for the consumers that matter most here.

**Consequences**:

- We exclude older interpreters. A project still on Python 3.9 through 3.12
  cannot adopt Probatio without first upgrading Python, so the drop-in promise is
  scoped to 3.13 and newer. This is an intentional deviation from voluptuous and
  is documented as such (see ADR-001).
- We can write modern Python throughout, with no version-conditional code paths
  to maintain or test.

**Support policy**: New Python versions are added to the supported set as they
are tested, so the matrix tracks current Python over time. The floor moves
forward deliberately, not automatically: raising it is a decision in its own
right, made when keeping an older version costs more than it is worth.
