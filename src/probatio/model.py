"""A mixin that gives a dataclass a validating ``from_dict`` classmethod.

Parsing an external payload into a dataclass tree is the common shape: a
``DataclassSchema(T, extra=...)`` built once, then called. ``SchemaMixin`` bundles
that, so a dataclass gets a cached, validating ``from_dict`` by inheriting it,
without a separate module-level schema or a hand-written classmethod. The class
stays an ordinary dataclass; the mixin adds one classmethod and records the
extra-key policy, nothing else. A TypedDict cannot carry methods (PEP 589), so it
keeps using ``TypedDictSchema`` directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, cast

from probatio.dataclass_schema import DataclassSchema

# ``Schema`` is imported at runtime, not under ``TYPE_CHECKING``: the
# ``_probatio_schema`` annotation below rides in the class, so ``get_type_hints``
# on a subclass (which the dataclass builder calls) must resolve it without a
# ``NameError``.
from probatio.schema import PREVENT_EXTRA, Schema

if TYPE_CHECKING:
    from typing import Self


class SchemaMixin:
    """Add a cached, validating ``from_dict`` to a dataclass.

    Inherit it and pass ``extra`` (the schema's extra-key policy) as a class
    argument::

        @dataclass
        class Config(SchemaMixin, extra=REMOVE_EXTRA):
            name: str

        Config.from_dict({"name": "app", "unknown": 1})  # Config(name='app')

    The ``DataclassSchema`` is built on the first ``from_dict`` and cached on the
    class, so it is collected when the class is. ``extra`` is inherited: a subclass
    that does not set its own keeps the parent's policy. The class is a plain
    dataclass otherwise; the mixin adds ``from_dict`` and records ``extra``, and
    does not touch the fields.
    """

    _probatio_extra: ClassVar[int] = PREVENT_EXTRA
    _probatio_schema: ClassVar[Schema | None] = None

    def __init_subclass__(cls, *, extra: int | None = None, **kwargs: Any) -> None:
        """Record the subclass's extra-key policy, or inherit the parent's.

        ``extra`` defaults to ``None`` (not passed), which leaves ``_probatio_extra``
        resolving to the enclosing class's value through the MRO, so a subclass
        inherits it. A value passed here pins it on this class.
        """
        super().__init_subclass__(**kwargs)
        if extra is not None:
            cls._probatio_extra = extra

    @classmethod
    def from_dict(cls, data: Any) -> Self:
        """Validate ``data`` against this dataclass and return the built instance."""
        # Read this class's own cache, not an inherited one: a subclass has different
        # fields and needs its own schema. Store it on the class so it is collected
        # with the class rather than pinned alive by a module-level table.
        schema = cls.__dict__.get("_probatio_schema")
        if schema is None:
            schema = DataclassSchema(cls, extra=cls._probatio_extra)
            cls._probatio_schema = schema
        # ``Schema.__call__`` is typed ``Any``; the mapping came from ``cls``, so the
        # result is a ``cls`` instance.
        return cast("Self", schema(data))
