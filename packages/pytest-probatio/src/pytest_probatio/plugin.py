"""Use a probatio schema as a pytest assertion matcher.

``assert response == Exact({"name": str, "port": Port()})`` validates ``response``
against the schema. On a mismatch, pytest's assertion rewriting calls the
``pytest_assertrepr_compare`` hook below, which renders each probatio error by its
path, so the failure points at the exact offending value instead of a bare
``assert ... == ...``.

Two matchers are exposed:

- ``Exact(schema)``: extra dict keys make it unequal; ``<=`` relaxes that to a
  partial match (extra keys allowed).
- ``Partial(schema)``: a partial match under ``==`` (extra keys allowed).

This lives outside the ``probatio`` package on purpose: the core library is
dependency-free, and a pytest plugin is a test-framework concern.
"""

from __future__ import annotations

import typing

from probatio import ALLOW_EXTRA, PREVENT_EXTRA, Invalid, MultipleInvalid, Schema


def _compile(schema: typing.Any, extra: int) -> Schema:
    """Return ``schema`` as a ``Schema`` with the given extra-key policy.

    A ready-made ``Schema`` (you can build one once and reuse it across tests) is
    rebuilt with the requested policy, its underlying schema and ``required`` flag
    preserved, so ``Exact`` and ``Partial`` control extra keys the same way whether
    they are given a raw shape or a ``Schema``.
    """
    if isinstance(schema, Schema):
        return Schema(schema.schema, required=schema.required, extra=extra)
    return Schema(schema, extra=extra)


class _Matcher:
    """A schema that compares equal to data validating against it.

    ``__eq__`` runs the schema and records the errors, so the assertion hook can
    show them. It is not hashable (the recorded errors make it mutable), which also
    keeps it out of places that expect a stable hash.
    """

    __slots__ = ("_errors", "_loose", "_strict", "_strict_eq")

    def __init__(self, schema: typing.Any, *, partial: bool) -> None:
        """Build the strict and partial schemas; ``partial`` picks which ``==`` uses."""
        self._strict = _compile(schema, PREVENT_EXTRA)
        self._loose = _compile(schema, ALLOW_EXTRA)
        # ``Partial`` validates loosely under ``==``; ``Exact`` validates strictly.
        self._strict_eq = not partial
        self._errors: list[Invalid] = []

    @property
    def errors(self) -> list[Invalid]:
        """The probatio errors from the most recent comparison (empty if it matched)."""
        return self._errors

    def _run(self, data: typing.Any, schema: Schema) -> bool:
        """Validate ``data``, recording any errors, returning whether it matched."""
        try:
            schema(data)
        except MultipleInvalid as exc:
            self._errors = list(exc.errors)
            return False
        except Invalid as exc:
            self._errors = [exc]
            return False
        self._errors = []
        return True

    def __eq__(self, data: object) -> bool:
        """Whether ``data`` validates (strictly for ``Exact``, loosely for ``Partial``)."""
        return self._run(data, self._strict if self._strict_eq else self._loose)

    def __ne__(self, data: object) -> bool:
        """Return the negation of ``__eq__``."""
        return not self.__eq__(data)

    def __le__(self, data: object) -> bool:
        """Return a partial match: ``data`` validates with extra keys allowed."""
        return self._run(data, self._loose)

    def __ge__(self, data: object) -> bool:
        """Support the reversed ``data <= matcher`` form (also a partial match)."""
        return self._run(data, self._loose)

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        """Render with the underlying schema, so a failing assert reads clearly."""
        return f"{type(self).__name__}({self._strict.schema!r})"


class Exact(_Matcher):
    """A schema matcher: ``==`` requires an exact match, ``<=`` a partial one.

    Exact means an extra dictionary key makes the data unequal; ``<=`` relaxes
    that to allow extra keys, the same as ``Partial`` under ``==``.
    """

    def __init__(self, schema: typing.Any) -> None:
        """Wrap ``schema`` as an exact-by-equality matcher."""
        super().__init__(schema, partial=False)


class Partial(_Matcher):
    """A schema matcher whose ``==`` allows extra keys (a partial match)."""

    def __init__(self, schema: typing.Any) -> None:
        """Wrap ``schema`` as a partial-by-equality matcher."""
        super().__init__(schema, partial=True)


def _format_path(path: list[typing.Any]) -> str:
    """Render an error path as ``data['a'][0]``, or ``<root>`` when empty."""
    if not path:
        return "<root>"
    return "data" + "".join(f"[{segment!r}]" for segment in path)


def pytest_assertrepr_compare(
    op: str,
    left: object,
    right: object,
) -> list[str] | None:
    """Explain a failed schema comparison by listing each error with its path."""
    if op not in ("==", "!=", "<=", ">="):
        return None

    if isinstance(left, _Matcher):
        matcher: _Matcher = left
    elif isinstance(right, _Matcher):
        matcher = right
    else:
        return None

    if not matcher.errors:
        # A negated comparison (``!=``) that failed because the data *did* match.
        return [
            f"data matches the probatio schema, but the assertion ({op}) required it not to"
        ]

    lines = [f"data does not match the probatio schema ({op}):"]
    lines.extend(
        f"  {_format_path(error.path)}: {error.error_message or str(error)}"
        for error in matcher.errors
    )
    return lines
