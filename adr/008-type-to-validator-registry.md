# ADR-008: A type-to-validator registry for schema builders

**Date**: 2026-06-27
**Status**: Accepted

**Context**: The structural schema builders turn a type annotation into a
validator: `create_dataclass_schema` reads a dataclass's fields today, and the
planned `Annotated` and `TypedDict` paths will do the same. For a scalar type
that arrives as a string from JSON or YAML (`datetime`, `UUID`, `Path`,
`Decimal`, an `ipaddress` type), the builder emits an `isinstance` check, which
rejects the string the loader produced. mashumaro coerces these transparently.
We deliberately do not: silent, default coercion of arbitrary types breaks the
validate-not-transform identity and would surprise a caller who wanted the string
kept as a string. But the alternative today is to repeat `Coerce(parse_datetime)`
on every `datetime` field, and you cannot reach into a nested dataclass's fields
to do it at all.

The self-validation protocol ([ADR-007](007-self-validation-protocol.md)) solves
this for types you own (add the method). It does nothing for `datetime`, `UUID`,
or any third-party type, because you cannot add a method to a class you do not
control.

**Decision**: A registry mapping a type to a validator, consulted by the
annotation-driven builders. It is empty by default, so nothing changes until you
register. It has the same two layers as the serde options
([the loading-and-dumping defaults](../docs/src/content/docs/guides/loading-and-dumping.md)):
a process-wide setter for an application's entry point, and a scoped context
manager for code that must not mutate global state. When a builder meets an
annotation whose type is registered, it emits the registered validator in place
of the bare type.

**Rationale**:

- It is the opt-in home for scalar coercion, without making coercion the default.
  You ask for `datetime` strings to be parsed by registering it once; a caller who
  did not register keeps strict `isinstance` behavior. The identity is preserved
  and the boilerplate disappears.
- It reaches where a per-field validator cannot. A `Coerce` in
  `additional_constraints` or an `Annotated` hint only covers the field you write
  it on. The registry applies wherever the type appears, including fields of
  nested dataclasses the builder descends into on its own.
- It is the answer for types you do not own, which is exactly the set the
  self-validation protocol cannot reach. The two compose: protocol for your
  types, registry for everyone else's.

**Consequences**: Global mutable state, mitigated the same way serde options are,
by preferring the scoped context manager in library code. Two boundaries must be
stated and held:

- **Scope.** The registry affects only the annotation-driven builders, not the
  engine's `isinstance` path for hand-written schemas. `Schema(datetime)` written
  by hand stays an `isinstance` check regardless of registry state, so a schema's
  explicit meaning never shifts under it because of distant global state.
- **Binding time.** The builder reads the registry when it *builds* the schema and
  bakes the validator in. A schema is stable once constructed; re-registering
  later does not mutate schemas already built. This keeps a compiled schema a
  fixed thing, like every other compiled schema.

Precedence. The registry supplies the *base* validator for a type, replacing the
bare `isinstance` and, since the builder returns it before the engine's
type-dispatch runs, the type's own self-validation protocol
([ADR-007](007-self-validation-protocol.md)) as well. A use-site validator
(`Annotated`, `additional_constraints`) does not override that base; it *composes*
on top through `All`, so `Annotated[datetime, Range(...)]` with `datetime`
registered to a `Coerce` runs the coercion first and the range check on the
result. That is the useful behavior: the registry handles the type, the use site
adds a constraint.
