"""Process-wide policy for whether schemas compile to a specialized validator.

A schema's own ``compile`` flag always wins. When it is unset (``None``), the
schema falls back to this policy. The policy is set deliberately in code, there is
no environment variable on purpose: it is an architectural decision, not a
deployment toggle that flips behavior invisibly.

The default is ``AUTO``: schemas validate interpreted and compile themselves only
once they prove hot, so a cold or one-shot schema stays interpreted (and never
pays code generation), while a repeatedly-validated one gets fast on its own, no
configuration. ``OFF`` opts out of compilation entirely (interpreted always);
``ON`` compiles every eligible schema on first use.

The policy is read lazily, when a schema first decides whether to compile, not at
construction. Schemas are often built at import time, before a consumer's startup
code runs, so reading it at construction would miss a policy set afterwards.
"""

from __future__ import annotations

from enum import Enum


class CompilePolicy(Enum):
    """The house policy for schemas that do not set their own ``compile`` flag."""

    # Never compile unless a schema opts in with ``compile=True``.
    OFF = "off"
    # Compile every schema that does not opt out with ``compile=False``.
    ON = "on"
    # Compile a schema once it has proven hot: it validates interpreted and counts
    # its calls, then generates after a fixed threshold. A one-shot schema never
    # crosses it. The default, so compilation is automatic where it pays and absent
    # where it does not, with no configuration.
    AUTO = "auto"


# The default the process starts with. AUTO so compilation is automatic where it
# pays. Named so the test suite can pin a deterministic policy yet still assert the
# real default.
_DEFAULT_POLICY = CompilePolicy.AUTO
_policy = _DEFAULT_POLICY


def set_compile_policy(policy: CompilePolicy) -> None:
    """Set the process-wide compile policy.

    Call it once, early, from deliberate startup code. A per-schema ``compile``
    flag still overrides it in either direction. Raises ``TypeError`` for anything
    that is not a ``CompilePolicy``, so a stray string like ``"off"`` fails loudly
    rather than being stored and silently breaking every later compile decision.
    """
    if not isinstance(policy, CompilePolicy):
        message = f"compile policy must be a CompilePolicy, got {type(policy).__name__}"
        raise TypeError(message)
    global _policy  # noqa: PLW0603 - a single deliberate process-wide setting
    _policy = policy


def get_compile_policy() -> CompilePolicy:
    """Return the process-wide compile policy currently in effect."""
    return _policy
