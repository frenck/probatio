"""Markers: dictionary keys that carry validation intent and metadata.

A marker is used as a key in a mapping schema to say something about that key:
that it is ``Required`` or ``Optional``, that it has a default, a custom message,
or a description, or that it should be ``Remove``d from the validated output.

A marker compares and hashes by its underlying key (``schema``), so it can be
used interchangeably with the bare key in a dictionary. This is the behavior
voluptuous defined and that downstream code (Home Assistant in particular)
relies on, reading ``.schema``, ``.description``, and ``.default`` off markers
and even copying and mutating them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

from probatio.error import SchemaError

if TYPE_CHECKING:
    from collections.abc import Callable


class Undefined:
    """Type of the ``UNDEFINED`` sentinel, meaning 'no default was given'."""

    def __repr__(self) -> str:
        """Render clearly so it is recognizable in debug output."""
        return "<undefined>"


UNDEFINED = Undefined()


class VirtualPathComponent(str):
    """A path segment for a group, rendered as ``<group>`` instead of a key.

    Inclusive and Exclusive group failures do not belong to any single key, so
    voluptuous points the error at a virtual path component named after the
    group. It compares equal to the bare group name but renders in angle
    brackets, so ``str(error)`` reads ``... @ data[<group>]``.
    """

    __slots__ = ()

    def __str__(self) -> str:
        """Render the group name wrapped in angle brackets."""
        return f"<{super().__str__()}>"

    def __repr__(self) -> str:
        """Render the same as ``str`` (the error path uses ``repr``)."""
        return self.__str__()


class _Self:
    """Sentinel that refers to the enclosing schema, for recursive schemas.

    Recursion follows the data: a ``Self`` schema validates a self-referential
    *structure* fine. Self-referential or pathologically deep *data* is caught by
    a depth guard and reported as a clean ``Invalid`` (unlike voluptuous, which
    overflows the stack with ``RecursionError``), so untrusted data cannot crash
    validation. The depth limit scales with the interpreter's recursion limit.
    """

    def __repr__(self) -> str:
        """Render as ``Self``."""
        return "Self"


# Used inside a schema to mean "validate against the whole enclosing schema",
# which is how recursive structures (a tree, a nested condition) are expressed.
Self = _Self()


class _Extra:
    """Sentinel mapping key that matches every otherwise-unmatched key.

    Used as a key, ``{Extra: validator}`` allows keys not named in the schema and
    validates each against ``validator`` (``{Extra: object}`` allows anything).
    This is voluptuous's ``Extra``: a callable sentinel, so introspection that
    treats a callable key as "additional properties" handles it unchanged.
    """

    def __call__(self, value: Any) -> Any:
        """Never invoked: the engine matches ``Extra`` by identity, not by call."""
        return value  # pragma: no cover

    def __repr__(self) -> str:
        """Render as ``Extra``."""
        return "Extra"


Extra = _Extra()


class Object(dict[Any, Any]):
    """A schema that validates an object's attributes instead of dict keys.

    Built like a mapping schema (``Object({"name": str})``), but matched against
    attributes rather than items. With ``cls`` set, the value must be an instance
    of that class; the validated attributes are used to rebuild an object of the
    value's own type.
    """

    def __init__(self, schema: Any, cls: Any = UNDEFINED) -> None:
        """Wrap a mapping schema, optionally pinning the expected class."""
        self.cls = cls
        super().__init__(schema)


def default_factory(value: Any) -> Callable[[], Any] | Undefined:
    """Normalize a default into a zero-argument factory.

    ``UNDEFINED`` passes through unchanged, a callable is used as-is, and a plain
    value is wrapped so calling the result returns that value.
    """
    if value is UNDEFINED or callable(value):
        normalized: Callable[[], Any] | Undefined = value
        return normalized
    return lambda: value


class Marker:
    """A dictionary key annotated with validation intent and metadata."""

    def __init__(
        self,
        schema: Any,
        msg: str | None = None,
        description: Any | None = None,
    ) -> None:
        """Wrap ``schema`` (the key), with an optional message and description."""
        self.schema = schema
        self.msg = msg
        self.description = description

    def __str__(self) -> str:
        """Render as the underlying key."""
        return str(self.schema)

    def __repr__(self) -> str:
        """Render as the underlying key's repr."""
        return repr(self.schema)

    def __hash__(self) -> int:
        """Hash by the underlying key, so it shares the key's dict slot."""
        return hash(self.schema)

    def __eq__(self, other: object) -> bool:
        """Compare equal to the underlying key (and to a marker of that key)."""
        return bool(self.schema == other)

    def __lt__(self, other: object) -> bool:
        """Order by the underlying key, against another marker or a bare key.

        So a list of markers sorts (alphabetically for string keys), matching
        voluptuous, and a marker compares against a plain value by its key.
        """
        if isinstance(other, Marker):
            return bool(self.schema < other.schema)
        return bool(self.schema < other)


class Required(Marker):
    """A key that must be present in the data."""

    def __init__(
        self,
        schema: Any,
        msg: str | None = None,
        default: Any = UNDEFINED,
        description: Any | None = None,
    ) -> None:
        """Mark ``schema`` required, with an optional default and metadata."""
        super().__init__(schema, msg, description)
        self.default = default_factory(default)


class Optional(Marker):
    """A key that may be absent, in which case its default applies."""

    def __init__(
        self,
        schema: Any,
        msg: str | None = None,
        default: Any = UNDEFINED,
        description: Any | None = None,
    ) -> None:
        """Mark ``schema`` optional, with an optional default and metadata."""
        super().__init__(schema, msg, description)
        self.default = default_factory(default)


class Alias(Marker):
    """A key accepted under one or more alias names, emitted under its canonical name.

    ``Alias("name", "user-name", "userName")`` accepts the value under any of the
    listed names and stores it under ``"name"`` in the validated output. The
    aliases are tried in the order given, and the first one present in the input
    wins, so a source that spells a key several ways resolves to one canonical
    name. By default the canonical name is accepted as an input name too (and leads
    the search, so it wins when both it and an alias appear); pass
    ``accept_canonical=False`` for a strict rename that accepts only the aliases.

    Like ``Optional``, an aliased key may be absent, in which case its ``default``
    applies. Pass ``required=True`` to demand that one of its names is present.
    """

    def __init__(  # noqa: PLR0913
        self,
        schema: Any,
        *aliases: Any,
        accept_canonical: bool = True,
        required: bool = False,
        default: Any = UNDEFINED,
        msg: str | None = None,
        description: Any | None = None,
    ) -> None:
        """Wrap ``schema`` (the canonical name) with extra accepted ``aliases``."""
        if not aliases:
            message = "Alias needs at least one alias name besides the canonical key"
            raise SchemaError(message)

        super().__init__(schema, msg, description)
        self.aliases = tuple(aliases)
        self.accept_canonical = accept_canonical
        self.required = required
        self.default = default_factory(default)

        # The input names searched, in declaration order. The canonical name leads
        # when it is accepted, so the real name wins over an alias when both appear.
        self.input_names: tuple[Any, ...] = (
            (schema, *aliases) if accept_canonical else tuple(aliases)
        )


class Inclusive(Optional):
    """An optional key that is co-dependent with others in its group.

    If any key in the group is present, every key in the group must be present.
    """

    def __init__(
        self,
        schema: Any,
        group_of_inclusion: str,
        msg: str | None = None,
        default: Any = UNDEFINED,
        description: Any | None = None,
    ) -> None:
        """Mark ``schema`` co-dependent on the other keys in its group."""
        super().__init__(schema, msg, default, description)
        self.group_of_inclusion = group_of_inclusion


class Exclusive(Optional):
    """An optional key that is mutually exclusive with others in its group.

    At most one key from the group may be present. ``required`` and ``default``
    control what happens when the group is empty (none of its keys present):
    ``required=True`` makes the group demand exactly one key, and a ``default``
    fills that member in when the group is empty. Both are group-level: setting
    either on any member governs the whole group. A ``default`` satisfies the
    group, so it wins over ``required``.
    """

    def __init__(  # noqa: PLR0913
        self,
        schema: Any,
        group_of_exclusion: str,
        msg: str | None = None,
        description: Any | None = None,
        *,
        required: bool = False,
        default: Any = UNDEFINED,
    ) -> None:
        """Mark ``schema`` mutually exclusive with the other keys in its group."""
        super().__init__(schema, msg, default, description)
        self.group_of_exclusion = group_of_exclusion
        self.group_required = required


class Forbidden(Marker):
    """A key that must not be present in the data.

    If the key appears, validation fails with "key not allowed" (or the marker's
    own ``msg``). The mapped value is never validated, since the key should not
    be there at all, so the idiom is ``{Forbidden("password"): object}``. It
    hashes and compares by its key, so extending a schema with a ``Forbidden``
    marker replaces an existing ``Optional``/``Required`` for the same key.
    """


class Remove(Marker):
    """A key to drop from the validated output.

    Remove markers compare and hash by identity, so several can live in one
    schema (for example ``Remove(str)`` alongside ``Remove(int)``).
    """

    def __hash__(self) -> int:
        """Hash by identity, so distinct Remove markers stay distinct keys."""
        return object.__hash__(self)

    def __eq__(self, other: object) -> bool:
        """Compare by identity."""
        return self is other

    def __repr__(self) -> str:
        """Show that this is a Remove marker around its key."""
        return f"Remove({self.schema!r})"


class Secret(Marker):
    """A key whose value is kept out of validation error output.

    Wrap a key in ``Secret`` to redact its value when validation fails: the error
    still reports the path and the reason, but shows ``<redacted>`` instead of the
    offending value (in ``Invalid`` rendering and ``humanize_error``). The value
    itself passes through validation unchanged; ``Secret`` marks the key, it does
    not transform the value.

    It composes with the presence markers by nesting, so
    ``Optional(Secret("password"))`` (equivalently ``Secret(Optional("password"))``)
    is an optional, redacted key. Order does not matter: presence and redaction are
    independent facets of the same key.

    Redaction covers validation errors only, not values you log yourself elsewhere.
    """

    def __repr__(self) -> str:
        """Show that this is a Secret marker around its key."""
        return f"Secret({self.schema!r})"


class _KeyFacets(NamedTuple):
    """The facets of a mapping key, resolved from its (possibly nested) markers."""

    key: Any
    """The bare key underneath every marker."""
    marker: Marker | None
    """The presence or removal marker governing the key, or None for a bare key."""
    secret: bool
    """Whether any layer marks the key ``Secret`` (redact its value on failure)."""
    msg: str | None
    """The first custom message found walking the chain, or None."""
    description: Any | None
    """The first description found walking the chain, or None."""


def resolve_key(key: Any) -> _KeyFacets:
    """Walk a (possibly nested) marker chain into its facets.

    A mapping key may be a bare value, a single marker, or markers nested to
    compose facets (``Optional(Secret("password"))``). Walk the chain down to the
    bare key, collecting the presence/removal marker (``Required``, ``Optional``,
    ``Alias``, ``Inclusive``, ``Exclusive``, ``Forbidden``, ``Remove``), whether
    any layer marks the key ``Secret``, and the first message and description seen.

    A chain carrying two presence markers (``Required(Optional(...))``) is a
    contradiction and raises ``SchemaError``.
    """
    secret = False
    presence: Marker | None = None
    msg: str | None = None
    description: Any | None = None
    node: Any = key
    while isinstance(node, Marker):
        if msg is None and node.msg is not None:
            msg = node.msg
        if description is None and node.description is not None:
            description = node.description
        if isinstance(node, Secret):
            secret = True
        elif presence is None:
            presence = node
        else:
            message = (
                "a mapping key carries two presence markers: "
                f"{type(presence).__name__} and {type(node).__name__}"
            )
            raise SchemaError(message)
        node = node.schema
    return _KeyFacets(node, presence, secret, msg, description)
