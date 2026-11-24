"""Value metadata: what a value carries alongside its contents.

Some data arrives with more to say than its contents. A YAML loader knows the file
and line every mapping came from; a request parser knows which part of a multipart
body a field was in; a migration knows a key used to be called something else. That
knowledge belongs to the value, not to the schema, and it is exactly what a good
error message needs.

Validation is hostile to it. A mapping or sequence schema rebuilds its input, so
even when the class survives (probatio preserves ``dict`` and ``list`` subclasses,
matching voluptuous) the rebuilt container is a *fresh, empty* instance: the items
are carried over one by one and everything the original held beside them is gone.

This module is probatio's answer: a small, explicit model of that metadata.

This is metadata on a *value*, not the metadata of an ``Annotated[...]`` type hint,
which probatio reads as validators and markers for a dataclass or ``TypedDict``
field. The two are unrelated.

- ``Metadata`` is the model. An immutable mapping of ``str`` to anything.
- A value carries its metadata in one attribute, ``__probatio_metadata__``
  (also available as ``METADATA_ATTR``). A type opts in by making room for that
  attribute, which for a ``__slots__`` type is one line::

      class Node(dict):
          __slots__ = ("__probatio_metadata__",)

  A type with an ordinary ``__dict__`` needs no declaration at all. A ``tuple`` or
  ``bytes`` subclass cannot take the slot form (CPython refuses a non-empty
  ``__slots__`` on one), so it opts in by declaring no ``__slots__`` and using the
  ``__dict__`` it gets instead.

  A property of that name is *not* a third way. probatio writes the attribute on a
  value it has just validated, so it writes only where the write lands in the
  attribute itself; a setter is a call, it receives the container, and it could add
  a key a mapping schema never saw or replace an item a sequence schema checked.
  ``supports_metadata`` reports which values qualify.
- Wherever probatio rebuilds a value *as its own type*, it carries the metadata
  across: the mapping engine, the sequence engine, ``ExactSequence``, and ``Object``.
  The rebuilt value is the original in contents *and* in the metadata it carries.
  A rebuild that does not keep the type cannot keep the metadata either: a
  ``Mapping`` that is not a ``dict`` subclass validates to a plain ``dict``, and a
  plain ``dict`` has nowhere to hold them.
- A validator adds to it with ``add_metadata``, or moves it onto a value it built
  itself with ``carry_metadata``.

Metadata is deliberately *not* general instance state. probatio copies this one
attribute and nothing else, so a subclass keeping a cache, a lock, or a parent
pointer does not have it silently duplicated onto a new object.

Values that cannot hold an attribute (a plain ``dict``, a ``str``, an ``int``) also
cannot hold metadata. ``add_metadata`` and ``carry_metadata`` return such a value
unchanged rather than raise, so a validator can call them without knowing what it
was handed; ``supports_metadata`` answers the question for a caller that cares.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from types import MappingProxyType, MemberDescriptorType
from typing import Any

# The one attribute a value carries its metadata in. The name is namespaced to
# probatio and has two trailing underscores, so Python's private-name mangling
# leaves it alone inside a class body and it can be written straight into
# ``__slots__``.
METADATA_ATTR = "__probatio_metadata__"

__all__ = [
    "METADATA_ATTR",
    "Metadata",
    "add_metadata",
    "carry_metadata",
    "metadata_of",
    "supports_metadata",
]


class Metadata(Mapping[str, Any]):
    """An immutable mapping of metadata attached to a value.

    Build one from a mapping, from keyword arguments, or from both::

        Metadata(file="app.yaml", line=12)
        Metadata({"file": "app.yaml"}, line=12)

    It is immutable on purpose. probatio hands the *same* ``Metadata`` object to
    a rebuilt container rather than copying it, which is what keeps the carry cheap;
    that is only safe because nothing can change it afterwards through either
    reference. Add to it with ``merge``, which returns a new ``Metadata``.

    The immutability is enforced, not a convention: the keys and values are copied
    into a dict no one else holds, and that dict is reached only through a
    ``MappingProxyType``, so there is no route back to a mutable view of it.
    """

    __slots__ = ("_data",)

    # Annotated, not assigned: the slot is filled once in ``__init__`` through
    # ``object.__setattr__``, since this class refuses ordinary attribute writes.
    _data: Mapping[str, Any]

    def __init__(
        self,
        metadata: Mapping[str, Any] | None = None,
        /,
        **extra: Any,
    ) -> None:
        """Build metadata from a mapping, keyword arguments, or both.

        A keyword argument wins over the same key in ``metadata``. The mapping is
        copied, so a later change to it does not reach into the built object.
        """
        data: dict[str, Any] = dict(metadata) if metadata is not None else {}
        if extra:
            data.update(extra)
        # The proxy wraps a dict that leaves this frame unreferenced, so the only
        # way to the contents is read-only, through the proxy. Set through
        # ``object.__setattr__`` because this class refuses attribute writes; this is
        # the one write, and it happens before anything else can see the object.
        object.__setattr__(self, "_data", MappingProxyType(data))

    def __setattr__(self, name: str, value: Any) -> None:
        """Refuse every attribute write: a ``Metadata`` is built once.

        Without this the storage could be rebound (``metadata._data = {...}``),
        which matters more than it looks: probatio hands the *same* object to every
        value it carries onto, and code attaching metadata in bulk may share one
        across every value from the same place, so a single rebinding would change
        what all of them report.
        """
        message = f"{type(self).__name__} is immutable"
        raise AttributeError(message)

    def __delattr__(self, name: str) -> None:
        """Refuse attribute deletion, for the same reason as ``__setattr__``."""
        message = f"{type(self).__name__} is immutable"
        raise AttributeError(message)

    def __reduce__(self) -> tuple[Any, ...]:
        """Rebuild through the constructor, since a ``MappingProxyType`` cannot pickle.

        The default slot-based reduction would try to pickle the proxy itself and
        fail. Handing the constructor a plain dict of the contents round-trips to an
        equal ``Metadata``, and makes ``copy`` and ``deepcopy`` work too.
        """
        return (type(self), (dict(self._data),))

    def __getitem__(self, key: str) -> Any:
        """Return the value stored under ``key``."""
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        """Iterate the metadata keys."""
        return iter(self._data)

    def __len__(self) -> int:
        """Return how many keys the metadata holds."""
        return len(self._data)

    def __repr__(self) -> str:
        """Render as ``Metadata({...})``, showing the metadata itself."""
        # ``dict(...)``, not the proxy's own repr, which would spell the storage
        # (``mappingproxy({...})``) rather than the metadata.
        return f"{type(self).__name__}({dict(self._data)!r})"

    def merge(
        self,
        metadata: Mapping[str, Any] | None = None,
        /,
        **extra: Any,
    ) -> Metadata:
        """Return a new ``Metadata`` with these updated by the given ones.

        The incoming values win on a shared key. This object is left untouched.
        """
        if not metadata and not extra:
            return self
        merged = dict(self._data)
        if metadata is not None:
            merged.update(metadata)
        if extra:
            merged.update(extra)
        return Metadata(merged)


# Whether the metadata attribute on a given class is a plain data attribute, cached
# per type because the answer depends only on the class and this sits on the carry
# path. Bounded, and cleared wholesale when it fills, so a program minting classes
# cannot grow it without limit or pin them alive forever.
_PLAIN_ATTRIBUTE: dict[Any, bool] = {}
_PLAIN_ATTRIBUTE_LIMIT = 512


def _writes_a_plain_attribute(cls: Any) -> bool:
    """Report whether the metadata attribute on ``cls`` is a plain data attribute.

    True for a name in ``__slots__`` and for an ordinary instance ``__dict__``: the
    attribute is somewhere an instance simply holds it. False for a property or any
    other data descriptor the class defines, which would take the write as a call
    rather than a write, and for a class overriding ``__setattr__``, which means to
    intercept its own writes (a frozen dataclass, say).

    This is the protocol, not a defence. A carrier class is first-party code, trusted
    exactly as much as the validator callables probatio already runs; see ADR-018 on
    where that boundary sits. What the check buys is that "a property is not a
    carrier" is true rather than aspirational, which matters because a property over
    fixed fields quietly drops the keys it does not know, and because ``Object``
    validates the very attributes such a property tends to be built over.

    The class is inspected by reading namespaces along ``__mro__`` rather than calling
    ``getattr`` on it, which would run a descriptor's ``__get__`` and report on
    whatever that returned instead of on the descriptor itself.
    """
    cached = _PLAIN_ATTRIBUTE.get(cls)
    if cached is not None:
        return cached
    if len(_PLAIN_ATTRIBUTE) >= _PLAIN_ATTRIBUTE_LIMIT:
        _PLAIN_ATTRIBUTE.clear()
    answer = _compute_plain_attribute(cls)
    _PLAIN_ATTRIBUTE[cls] = answer
    return answer


def _compute_plain_attribute(cls: Any) -> bool:
    """Work out the uncached answer for ``_writes_a_plain_attribute``."""
    if any("__setattr__" in vars(base) for base in cls.__mro__[:-1]):
        return False
    for base in cls.__mro__:
        namespace = vars(base)
        if METADATA_ATTR in namespace:
            found = namespace[METADATA_ATTR]
            if isinstance(found, MemberDescriptorType):
                return True
            if hasattr(type(found), "__set__") or hasattr(type(found), "__delete__"):
                # A data descriptor the class wrote; it also shadows an instance entry.
                return False
            # An ordinary class attribute, a default of some kind. An instance entry
            # simply shadows it, so the instance dictionary is still the place.
            break
    return any("__dict__" in vars(base) for base in cls.__mro__[:-1])


def supports_metadata(value: Any) -> bool:
    """Report whether probatio can attach metadata to ``value`` and carry it.

    True when the metadata attribute is somewhere the value simply holds it: a name
    in its type's ``__slots__``, or an ordinary instance ``__dict__``. Those are the
    two opt-in forms, and they are the only ones.

    False for everything else, including some that can technically be written to. A
    property of that name reports False whether or not it has a setter, and so does
    any other descriptor the type defines, because probatio will not run a carrier's
    code over a value it has just validated. A type overriding ``__setattr__`` reports
    False because it means to intercept its own writes, and probatio will not route
    around that; a frozen dataclass is the case worth naming. A plain ``dict``,
    ``list``, ``str`` or ``int`` has nowhere to put the attribute at all, and a class
    object's ``__dict__`` is a read-only proxy, so those report False too.

    What it cannot tell you is whether a write that does land will be *kept*. A
    carrier is free to store less than it was given, and only reading it back with
    ``metadata_of`` shows that.
    """
    return _writes_a_plain_attribute(type(value))


def metadata_of(value: Any) -> Metadata | None:
    """Return the metadata attached to ``value``, or None if it has none.

    The result is always a ``Metadata``, even when the value stores a plain
    mapping in the attribute, so a caller gets one shape to work with. A value
    holding something that is not a mapping is a broken carrier, and raises
    ``TypeError`` rather than being silently read as empty.
    """
    raw = getattr(value, METADATA_ATTR, None)
    if raw is None:
        return None
    if type(raw) is Metadata:
        return raw
    if not isinstance(raw, Mapping):
        message = (
            f"{METADATA_ATTR} on {type(value).__name__} holds "
            f"{type(raw).__name__}, which is not a mapping"
        )
        raise TypeError(message)
    return Metadata(raw)


def add_metadata[T](
    value: T,
    metadata: Mapping[str, Any] | None = None,
    /,
    **extra: Any,
) -> T:
    """Merge metadata into the value's own and return the value.

    This is how a validator adds to what a value carries::

        def normalize_port(value):
            return add_metadata(int(value), normalized=True)

    Existing keys are kept; the incoming values win on a shared key. Adding
    nothing (no mapping and no keywords, or an empty mapping) changes nothing, so a
    validator can pass a mapping it assembled without checking whether it came out
    empty. The value is returned either way, so this reads well as the last line of
    a validator. A
    value that cannot hold metadata is returned unchanged, because a validator
    should not fail over metadata it could not attach, and that covers a carrier
    whose setter raises something of its own.

    Reading is not swallowed the way ``carry_metadata`` swallows it. A value
    already carrying something that is not a mapping raises ``TypeError`` the same
    way ``metadata_of`` does, and a carrier whose getter raises surfaces that.
    This is an explicit call by the code that wants the metadata, so a broken
    carrier is worth hearing about, and proceeding would mean silently discarding
    whatever the value already had. The engine's own carry has neither luxury: it
    runs behind every rebuild and must never turn a carrier's fault into a
    validation failure.
    """
    if not metadata and not extra:
        return value
    # The same rule the engine's carry follows, so one protocol governs both: a value
    # probatio would not carry onto is not one it adds metadata to either.
    if not _writes_a_plain_attribute(type(value)):
        return value
    # Read through ``metadata_of`` so a value carrying something that is not a
    # mapping reports that plainly rather than failing inside a dict copy.
    current = metadata_of(value)
    merged = (
        Metadata(metadata, **extra)
        if current is None
        else current.merge(metadata, **extra)
    )
    try:
        setattr(value, METADATA_ATTR, merged)
    except Exception:  # noqa: BLE001 - a carrier refusing the write is not an error
        # The slot or instance dict would not take it. A no-op, not an error, the
        # same way ``carry_metadata`` treats it.
        return value
    return value


def carry_metadata[T](source: Any, target: T) -> T:
    """Copy ``source``'s metadata onto ``target`` and return ``target``.

    Use it in a validator that builds a new value from an old one, so the old one's
    metadata is not lost in the transformation::

        def drop_empty(value):
            kept = type(value)((k, v) for k, v in value.items() if v)
            return carry_metadata(value, kept)

    This replaces whatever ``target`` carried rather than merging into it: it moves
    a value's metadata onto its replacement. Both the no-metadata case and the
    cannot-hold-metadata case leave ``target`` alone.

    The metadata object itself is shared, not copied. That is safe for the
    ``Metadata`` this module defines, which cannot change. A carrier that chooses
    to store some other, mutable mapping shares that mapping between the two values.

    Unlike ``metadata_of`` and ``add_metadata``, this moves whatever it finds without
    checking that it is a mapping at all. It is the one line here that runs per
    rebuilt container, and a type check on every one of them would cost more than it
    is worth. A source carrying something that is not a mapping therefore spreads it
    rather than being reported, until something reads it through ``metadata_of``.

    It never raises for a carrier's own reasons. Both ends are ordinary attribute
    access, so both can run code the carrier wrote: a property getter on ``source``,
    a property setter or a ``__setattr__`` on ``target``. Whatever that code raises
    is swallowed and the carry is abandoned. This is not politeness, it is the
    safe-validator contract (see ``validators/_base.py``): ``ExactSequence`` and the
    mapping and sequence engines all call this, and a built-in validator that leaked
    a carrier's ``RuntimeError`` would escape the ``MultipleInvalid`` a caller
    catches. Failing to move metadata is not a statement about the data, so it is
    never a validation failure. ``BaseException`` still propagates.
    """
    # The whole read-and-write is guarded, not just the write: a property getter on
    # ``source`` can raise too. A ``try`` that does not raise is free, so this costs
    # the hot path nothing; ``contextlib.suppress`` would build an object and call
    # into it every time, measured at 91 ns against 18 ns.
    try:
        # Inside the guard: working out how to write the attribute reads the target's
        # class, and a hostile metaclass can raise from that alone.
        if not _writes_a_plain_attribute(type(target)):
            return target
        metadata = getattr(source, METADATA_ATTR, None)
        if metadata is not None:
            setattr(target, METADATA_ATTR, metadata)
    except Exception:  # noqa: BLE001 - a carrier's own code must not fail validation
        return target
    return target
