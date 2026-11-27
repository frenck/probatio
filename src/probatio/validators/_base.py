"""Shared base for probatio's built-in validators."""

from __future__ import annotations

from typing import Any


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

    A validator that only inspects its input and hands it back is generic in the
    caller's type (``def __call__[T](self, value: T) -> T``), so a schema built on
    it does not erase what went in. Inside such a body the value is passed on
    through a local annotated ``typing.Any``, because the runtime check *is* the
    type check: ``strptime`` on a non-string, ``len`` on something unsized, and
    ``in`` on a non-container all raise, and the contract above turns that into an
    ``Invalid``. Narrowing the parameter instead would reject statically what the
    validator is there to reject at runtime. ``test_passthrough_typing.py`` finds
    every pass-through and enforces the signature.

    Carrying ``__probatio_safe__`` lets the compiler call the validator directly and
    skip the generic ``ValueError``-to-``Invalid`` guard it wraps arbitrary
    callables in. Set it only on a validator that genuinely upholds the contract;
    ``tests/validators/test_safe_contract.py`` fuzzes every built-in to enforce it.

    The promise covers the ``__call__`` probatio wrote, not a subclass's. A subclass
    that resolves to a ``__call__`` from outside the package, its own or one a mixin
    supplies, has promised nothing, so ``__init_subclass__`` withdraws the flag and
    the compiler wraps it in the generic guard like any other callable. A subclass
    that keeps probatio's ``__call__`` keeps the flag.
    """

    __probatio_safe__: bool = True

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Withdraw the safe flag when the class runs a ``__call__`` probatio did not write."""
        super().__init_subclass__(**kwargs)

        # Walk the MRO by hand: ``getattr(cls, "__call__")`` falls back to
        # ``type.__call__`` on a class without one (the abstract bases), which is not
        # a validator ``__call__`` at all.
        owner = next((base for base in cls.__mro__ if "__call__" in vars(base)), None)
        if owner is None:
            return

        # Judge by the class that defines ``__call__``, not by the function: an
        # override decorated with ``functools.wraps(Range.__call__)`` carries the
        # wrapped function's ``__module__`` and would pass for probatio's own.
        if not owner.__module__.startswith("probatio."):
            cls.__probatio_safe__ = False
