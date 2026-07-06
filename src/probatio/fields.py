"""Field metadata for the annotation-driven builders (ADR-013).

``Key`` is a small spec placed in a field's ``Annotated`` metadata to give that
field a key facet the plain type cannot express: redact it, accept it under other
names, forbid it, group it, or override its presence. It works the same on a
dataclass and a TypedDict, because it rides in ``Annotated`` (a TypedDict key
cannot take a default value, so pydantic's ``Field(...)`` default trick does not
apply there).

A ``Key`` is not a mapping-key marker and never appears as a dict key. The builder
reads it and generates the real marker chain (``Secret``, ``Alias``, ...) with the
field name as the key. Plain dict schemas keep using the markers directly.
"""

from __future__ import annotations

# Imported at runtime, not under TYPE_CHECKING: ``Key`` is public, so
# ``get_type_hints(Key)`` must resolve without a NameError on ``Sequence``.
from collections.abc import Sequence  # noqa: TC003
from dataclasses import dataclass
from typing import Any


@dataclass
class Key:
    """Configure the mapping key a builder generates for an ``Annotated`` field.

    ``secret`` redacts the field's value in errors. ``alias`` accepts the field
    under one or more alternate input names (the field name stays canonical);
    ``accept_canonical=False`` makes it a strict rename. ``forbidden`` rejects a
    caller who supplies the field, ``remove`` drops it after validating.
    ``inclusive``/``exclusive`` name a co-dependent or mutually-exclusive group.
    ``required`` overrides the presence a dataclass default (or a TypedDict's
    ``total``) would imply. ``description`` and ``msg`` pass through to the marker.

    ``extra`` pins the extra-key policy for this field's own subtree, overriding
    the one the enclosing schema propagates. Set it (to ``PREVENT_EXTRA``,
    ``ALLOW_EXTRA``, or ``REMOVE_EXTRA``) on a field whose type is a nested
    dataclass, TypedDict, or a container of them, to keep that subtree strict while
    the rest of the schema is loose, or the reverse. On a leaf field (a plain type)
    it has nothing to apply to and is ignored.

    The facets that define the key's role (``alias``, ``forbidden``, ``remove``,
    ``inclusive``, ``exclusive``) are mutually exclusive; ``secret`` layers on top
    of any of them, and ``extra`` is orthogonal to all of them.
    """

    secret: bool = False
    alias: str | Sequence[str] | None = None
    accept_canonical: bool = True
    forbidden: bool = False
    remove: bool = False
    inclusive: str | None = None
    exclusive: str | None = None
    required: bool | None = None
    description: Any = None
    msg: str | None = None
    extra: int | None = None
