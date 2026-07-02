# ADR-013: A field-metadata spec for Annotated dataclass and TypedDict fields

**Date**: 2026-07-02
**Status**: Accepted

**Context**: The annotation-driven builders (`create_dataclass_schema`,
`create_typeddict_schema`) generate the mapping _key_ themselves: a field becomes
`Required(name)` or `Optional(name, default=...)`, inferred from the field's
default (or, for a TypedDict, from `Required`/`NotRequired`/`total`). Everything a
field annotation carries is _value_-level; there is no way to give a field a key
facet the plain type cannot express: redact it (`Secret`), accept it under other
names (`Alias`), forbid it, group it, or override its presence.

The obvious move, put the markers straight into `Annotated[..., Secret()]`, does
not work. Markers are mapping keys: they hash and compare by their key so they
share a dict slot (`Required("x") == "x"`, needed for `extend`). Reused as field
metadata, a marker's key slot holds the field name (unknown until the builder
runs), so it is either unset or, worse, holds config (`Alias`'s first alias). Two
such markers then compare equal and collapse in typing's `Annotated` cache, so
`Annotated[str, Secret()]` and `Annotated[str, Optional()]`, or two aliases that
share a leading name, silently become one. Working around it meant either changing
marker equality (breaking the dict-key semantics `extend` relies on) or a keyless
construction form for every arg-carrying marker. Both fight the marker system.

The precedent settles it. Pydantic uses a `Field(...)` object assigned as a
default (`x: str = Field(...)`), which a TypedDict key cannot take. Mashumaro uses
a dedicated `Annotated[int, Alias("id")]` type that is _not_ a mapping key, which
is why it never hits the cache problem. Multiple aliases go in a container
(pydantic's `AliasChoices`).

**Decision**: A small `Key` spec placed in a field's `Annotated` metadata. It is
plain data, never a mapping key, so it cannot collide in the `Annotated` cache and
needs no changes to marker equality. The builder reads it and generates the real
marker chain (`Secret`, `Alias`, ...) with the field name as the key.

```python
class Login(TypedDict):
    user_name: Annotated[str, Key(alias=["user-name", "userName"])]
    password:  Annotated[str, Key(secret=True)]
    token:     Annotated[str, Key(exclusive="auth")]
```

The same spelling works on a dataclass. Plain dict schemas keep using the markers
directly and are untouched, including `Alias`'s multi-alias form
(`{Alias("user_name", "user-name", "userName"): str}`).

`Key` carries the role-defining facets (`alias`, `forbidden`, `remove`,
`inclusive`, `exclusive`, mutually exclusive), the `secret` modifier that layers on
any of them, a `required` override, and `accept_canonical`/`description`/`msg`. It
carries no `default`: a field's default has one source (the dataclass field, or a
TypedDict's absence), so validation and `construct()` never diverge on it.

**Rationale**:

- It works for TypedDict, which is the whole point and where pydantic's
  default-value `Field` cannot reach. `Annotated` metadata is legal in a TypedDict
  body; a default value is not.
- It cannot hit the marker-identity / `Annotated`-cache trap, because a `Key` is
  never a mapping key. That failure class is removed by construction rather than
  defended against, and marker equality stays exactly as it was.
- One vocabulary per surface: dict schemas keep markers, annotated fields get a
  spec, mirroring how pydantic (`Field`/`AliasChoices`) and mashumaro (`Alias`)
  keep field metadata separate from any key object.

**Consequences**:

- **Normalization is one step.** The builder turns `(inferred presence, Key)` into
  a single keyed marker chain, then reuses the ordinary compile path. `secret`
  wraps the base; the role facets pick the base; `required` overrides the inferred
  presence.
- **One default source, so validate and construct agree.** Because a `Key` carries no
  default, a field's default has a single source (the dataclass field, or a TypedDict's
  absence). There are no marker-only defaults for the validating call and `construct()`
  to diverge on.
- **Construction constraints are explicit on a dataclass.** A dataclass constructor
  needs a value for every field, so a field that can be absent needs a default: a
  `forbidden`/`remove` field always (it is never taken from the input), and an
  `optional`/`alias`/group field unless it is required. Without one it is a
  contradiction and raises `SchemaError`. A TypedDict constructs nothing, so none of
  this applies there.
- **A field absent from the validated mapping keeps the dataclass's own default,
  untouched.** `optional`/`alias`/`inclusive`/`exclusive`-when-the-group-is-empty carry
  their default into the validated mapping, so the value schema validates and coerces
  it. But a `forbidden` field (always absent), a `remove` field (always dropped), and an
  unselected `exclusive` member (absent because a sibling won) leave no entry, so
  construction falls back to the raw dataclass default, which the schema never validates
  or coerces. This is a boundary, not a bug: a dataclass's construction defaults are
  Python-level, outside the schema, which validates _input_, and a value the schema
  keeps out of the input is not input. Write an already-typed default for such a field;
  a wrong-typed one is a dataclass-level type error a type-checker flags. A build-time
  check cannot close this soundly (a default factory or a subtype coercion produces the
  real value only at construction), so it is left to the type-checker and this note.
- **Two spellings, one meaning.** The dict-schema `{Secret("password"): str}` and
  the field `Annotated[str, Key(secret=True)]` produce the same key. This is a small
  duplication of surface, accepted so each context keeps the idiom that fits it and
  neither has to distort for the other.
