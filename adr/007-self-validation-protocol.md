# ADR-007: A self-validation protocol for types

**Date**: 2026-06-27
**Status**: Accepted

**Context**: A bare type used as a schema validates by `isinstance`. That is
right for `str`, `int`, and most plain types, but wrong for a type whose runtime
value is a different thing from its validated form. The clearest case is `Enum`:
`Schema(Color)("red")` raises `Invalid: expected Color`, because only an actual
`Color` member passes the `isinstance` check. But `"red"` is exactly what a JSON
or YAML loader hands you. Even `StrEnum` rejects its own value. So the one type
that is a closed set of named values, the textbook thing to validate config
against, rejects the data you would feed it. Today the workaround is to wrap
every such use in `Coerce(Color)` (which works, but reports a bare `expected
Color` with no member list) or a hand-written validator, repeated at every use
site and inside every nested structure.

More generally, probatio has no way for a type to declare _how it validates a raw
value of itself_. A domain value object that knows how to parse its own string
form cannot be a first-class schema citizen; it has to be wrapped externally.

**Decision**: Recognize types that know how to validate themselves, through two
mechanisms that share one dispatch path in the engine:

- A protocol method on user-defined types. A class implements
  `__probatio_validate__(value)`, a classmethod that returns the validated value
  or raises `Invalid`. When the engine encounters a type-as-schema that defines
  it, it dispatches there instead of to `isinstance`.
- Built-in recognition of stdlib closed-set types that cannot carry the method.
  `Enum` and `Flag` are handled by the engine recognizing the subclass and
  applying value-or-member coercion (accept a member or a member value, return
  the member, raise `Invalid` listing the valid values otherwise). We do not
  monkeypatch the standard library; the protocol is the general form and these
  are the built-in consumers of the same idea.

**Rationale**:

- The Enum behavior today is close to a bug: the type rejects precisely the data
  it exists to describe. Fixing it as a one-off would leave the next
  self-describing type (a value object, a parsed identifier) in the same hole.
  A protocol fixes the class of problem, not the instance.
- The type is the right owner of "how do I validate a raw value of myself."
  Pushing that knowledge to every use site (a `Coerce` wrapper everywhere) is the
  boilerplate the dataclass and `Annotated` builders would otherwise inherit and
  multiply across nested fields.
- It is additive and drop-in safe. A type without the method keeps `isinstance`
  semantics exactly, so no existing schema changes meaning. voluptuous has no
  such protocol, so there is nothing to diverge from.

**Consequences**: A new public protocol (`__probatio_validate__`) is a stable
surface we commit to. The safe-validator contract still binds: an implementation
must only ever raise `Invalid` on bad input, never leak another exception. The
boundary to police in docs is that this is _self_-validation (an Enum value to its
member, a value object to itself), not a license for arbitrary transformation
that would break the validate-not-transform identity. A type's own protocol beats
a bare `isinstance` check. (The type-to-validator registry once proposed in
[ADR-008](008-type-to-validator-registry.md) would have overridden this protocol,
but it was reversed before shipping.) Enum fields in dataclass and `Annotated`
schemas stop rejecting their own values for free, since they ride this dispatch.
