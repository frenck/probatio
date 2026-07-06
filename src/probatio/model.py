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
from weakref import WeakKeyDictionary

from probatio.dataclass_schema import DataclassSchema
from probatio.schema import PREVENT_EXTRA

if TYPE_CHECKING:
    from typing import Self

    from probatio.schema import Schema

# One built schema per subclass, keyed weakly so a throwaway class does not leak.
_SCHEMAS: WeakKeyDictionary[type, Schema] = WeakKeyDictionary()


class SchemaMixin:
    """Add a cached, validating ``from_dict`` to a dataclass.

    Inherit it and pass ``extra`` (the schema's extra-key policy) as a class
    argument::

        @dataclass
        class Config(SchemaMixin, extra=REMOVE_EXTRA):
            name: str

        Config.from_dict({"name": "app", "unknown": 1})  # Config(name='app')

    The ``DataclassSchema`` is built on the first ``from_dict`` and reused after.
    ``extra`` is inherited: a subclass that does not set its own keeps the parent's
    policy. The class is a plain dataclass otherwise; the mixin adds ``from_dict``
    and records ``extra``, and does not touch the fields.
    """

    _probatio_extra: ClassVar[int] = PREVENT_EXTRA

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
        schema = _SCHEMAS.get(cls)
        if schema is None:
            schema = DataclassSchema(cls, extra=cls._probatio_extra)
            _SCHEMAS[cls] = schema
        # ``Schema.__call__`` is typed ``Any``; the mapping came from ``cls``, so the
        # result is a ``cls`` instance.
        return cast("Self", schema(data))
