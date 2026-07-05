"""Process-wide policy for whether a ``Schema`` builds eagerly or on first use.

A ``Schema`` normally compiles its declaration into a validator at construction
(``EAGER``), matching voluptuous: a malformed schema raises ``SchemaError`` right
where it is defined. ``LAZY`` defers that compile walk to the first validation, so
a schema that is built but never validated, an unused service, trigger, condition,
or websocket-command schema registered at startup, never pays to build and never
holds its compiled validator tree in memory.

The trade is error timing: under ``LAZY`` a malformed schema raises at first use,
not at construction. So ``EAGER`` stays the default (the drop-in promise holds),
and an application opts in with ``set_build_policy(LAZY)`` once, early, before it
builds the schemas it wants deferred.

Like the compile policy, this is set deliberately in code; there is no environment
variable, on purpose. It is read at construction (the build decision cannot be
deferred past the point the schema would otherwise build), so set it before the
schemas you want lazy are created.
"""

from __future__ import annotations

from enum import Enum


class BuildPolicy(Enum):
    """The house policy for when a ``Schema`` compiles its declaration."""

    # Build the validator at construction (voluptuous parity; errors at definition).
    EAGER = "eager"
    # Defer the build to first validation, so an unused schema never builds.
    LAZY = "lazy"


# The default the process starts with. EAGER so the drop-in promise holds: a
# malformed schema raises where it is defined, exactly as voluptuous does.
_DEFAULT_POLICY = BuildPolicy.EAGER
_policy = _DEFAULT_POLICY


def set_build_policy(policy: BuildPolicy) -> None:
    """Set the process-wide build policy.

    Call it once, early, from deliberate startup code, before the schemas you want
    deferred are constructed. Raises ``TypeError`` for anything that is not a
    ``BuildPolicy``, so a stray string fails loudly rather than silently disabling
    lazy building.
    """
    if not isinstance(policy, BuildPolicy):
        message = f"build policy must be a BuildPolicy, got {type(policy).__name__}"
        raise TypeError(message)
    global _policy  # noqa: PLW0603 - a single deliberate process-wide setting
    _policy = policy


def get_build_policy() -> BuildPolicy:
    """Return the process-wide build policy currently in effect."""
    return _policy
