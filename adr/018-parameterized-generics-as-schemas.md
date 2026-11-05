# ADR-018: A parameterized generic as a schema validates its type arguments

**Date**: 2026-10-16
**Status**: Accepted

**Context**: A parameterized generic used as a schema (`dict[str, str]`,
`list[int]`) is a `types.GenericAlias`, not a `type`, so the compile walk never
reached the `isinstance` path. It is callable, though, so it compiled as an
arbitrary callable and ran as a constructor. The type arguments were never looked
at, and the constructor coerced whatever it was handed:

- `Schema(dict[str, str])({"a": 1})` returned `{"a": 1}`.
- `Schema(list[int])("abc")` returned `["a", "b", "c"]`.
- `Schema(dict[str, str])([("a", "b")])` returned `{"a": "b"}`.
- `Schema(int | None)` is not callable, so it compiled as an equality literal and
  rejected every value, `None` and `3` included.
- `Schema(typing.List[int])` raised a raw `TypeError` from `typing` on every call.

voluptuous 0.15.2 behaves the same way (ADR-001 is why probatio did too). The
schema reads as if it validates its keys and values, so people write it and trust
it. Issue #469 found four Home Assistant service schemas relying on it by mistake,
one of them (`list[str]` for a device ID) silently exploding a bare string into
characters.

probatio already knows how to read these annotations. The dataclass, TypedDict, and
decorator builders translate a field annotation into the structural schema it
spells (`list[X]` to `[X]`, `dict[K, V]` to `{K: V}`, a union to `Maybe`/`Any`,
`Literal` to `In`, `Annotated` metadata to extra validators). A generic used
directly as a schema was the one place that translation did not reach.

**Decision**: The compile walk translates any node with a `typing.get_origin`
(a builtin or `typing` generic alias, a `|` union, `Literal`, `Annotated`) through
that same annotation translator, then compiles the result. `dict[str, str]`
validates exactly like `{str: str}`, and a generic and its dataclass field twin
can never disagree.

The translator lives in `dataclass_schema`, which imports `_compile`, so it is
registered with `_compile` at import (the same pattern `Schema` uses) instead of
imported, keeping the two free of a cycle. The compiled variant needs no change:
its code generator does not inline a generic, so it calls the interpreted closure
the walk produced, and the two engines agree by construction.

Rejecting a generic with `SchemaError` was considered and turned down. It is
louder, but it turns every schema written this way into an import-time crash on
upgrade, which is a hard way to deliver a drop-in library when the intent of the
schema is unambiguous.

**Consequences**:

- A deliberate, documented deviation from voluptuous (ADR-001). Unlike ADR-017 it
  is not a strict widening: a value that does not match the type arguments was
  accepted and is now rejected. That is the point. A schema that passed because its
  arguments were ignored was not validating what it said.
- The constructor coercion is gone. A string is no longer exploded into a list, and
  a list of pairs no longer becomes a dict. A schema that wanted the conversion has
  to say so (`Coerce(list)`).
- The translation carries the annotation semantics along: `list[SomeEnum]` returns
  members, not raw values, and `list[SomeDataclass]` builds instances.
- `int | None` and `Literal[...]` work as schemas, where they used to reject
  everything.
- The codecs (`to_json_schema`, `to_field_list`) still read the raw schema and do
  not understand a generic. That is a pre-existing gap, left for a follow-up.
