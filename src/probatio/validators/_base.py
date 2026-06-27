"""Shared base for probatio's built-in validators."""

from __future__ import annotations


class _SafeValidator:
    """Base for validators that always raise ``Invalid`` on failure.

    The safe-validator contract, the library's #1 invariant: on *any* input, a
    built-in validator may return a value or raise a subclass of ``Invalid``, and
    nothing else. It must never leak a ``ValueError``, ``TypeError``,
    ``AttributeError``, a parser exception, or any other type, no matter how hostile
    the value. The engine calls back into validators with untrusted data, so a leak
    here is a real defect (it escapes the ``MultipleInvalid`` a caller catches), not
    a stylistic one. A validator that calls into code which may raise must catch and
    re-raise as ``Invalid``.

    Carrying ``__probatio_safe__`` lets the compiler call the validator directly and
    skip the generic ``ValueError``-to-``Invalid`` guard it wraps arbitrary
    callables in. Set it only on a validator that genuinely upholds the contract;
    ``tests/validators/test_safe_contract.py`` fuzzes every built-in to enforce it.
    """

    __probatio_safe__: bool = True
