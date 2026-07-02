# ADR-014: An annotation-driven argument-validation decorator

**Date**: 2026-07-02
**Status**: Accepted

**Context**: Probatio ships `validate`, the voluptuous-compatible decorator: you
name a schema per argument by hand (`@validate(width=int, __return__=int)`), it
validates the bound arguments against a dict schema, and it is sync-only. That
serves the drop-in promise, but it repeats type information a caller has usually
already written as annotations, and it cannot wrap a coroutine function.

The annotation engine that `create_dataclass_schema` and `create_typeddict_schema`
use (`_annotation_to_schema`) already turns a single type annotation into a schema
fragment, including `Annotated[int, Range(...)]`, unions, and nested dataclasses. A
function signature is just another source of annotations, so the same inference
applies: read each parameter's validator from its annotation, coerce as the
annotation says, validate the arguments before the body runs, and do it on a
coroutine function too.

**Decision**: A new decorator, `probatio`, that reads a callable's signature and
validates each annotated parameter through the shared annotation engine, on both
sync and coroutine functions. `validate` stays untouched for the voluptuous
drop-in.

```python
@probatio
async def fetch(user_id: Annotated[int, Range(min=1)], name: str) -> Response:
    ...

@probatio({"name": Length(min=2)}, returns=User)
def make(name: str, age: int) -> User:
    ...
```

- **Inference is the default.** Each annotated parameter becomes its inferred
  validator. An unannotated parameter (`self`, `cls`, a bare `*args`) carries no
  schema and is passed through, so the decorator drops onto a method with no
  ceremony.
- **`constraints` extends, it does not replace.** An optional `{parameter:
validator}` first argument layers an extra rule after the inferred type with
  `All`, the same shape and meaning as a dataclass's `additional_constraints`.
- **`returns` is one opt-in knob.** Off by default; `True` validates the result
  against the `-> R` annotation, any other value is used as the return schema
  directly.
- **The escape hatch is the standard `__wrapped__`.** `functools.wraps` already
  sets it to the undecorated callable, so a trusted, unvalidated call needs no
  bespoke attribute.

**Rationale**:

- One engine, two entry points. A function signature and a dataclass are both
  annotation sources, so `_annotation_to_schema` serves both. The decorator adds a
  signature-to-mapping front end, not a second validation path.
- Distinct from `validate` on purpose. `validate` is the hand-named voluptuous
  drop-in; `probatio` is the annotation-driven, async-aware one. Keeping both means
  neither has to distort: the compatibility surface stays literal, and the new one
  is free to be opinionated.
- Named for what it is. `@probatio` reads as a stamp on a function ("validated by
  probatio"), and stays clear of the `validate` name so the two decorators do not
  blur together.

**Consequences**:

- **Coercion reaches the body.** A parameter is bound, validated, and written back
  before the call, so a coercing annotation (`Annotated[int, Coerce(int)]`, a
  dataclass parameter) hands the body the validated value, consistent with how the
  rest of the library returns a normalized result. Binding goes through
  `inspect.Signature.bind`, so positional-only, keyword-only, and `*args`/`**kwargs`
  reconstruct correctly.
- **Only what is validated is resolved.** Annotations are resolved per call site,
  scoped to the parameters that are actually validated (plus the return, only when
  `returns=True`). An unresolved forward reference on a skipped `*args`, or on the
  return when return validation is off, cannot break decoration. The scoping narrows
  the callable's `__annotations__` around a single `get_type_hints` call and restores
  it, rather than reaching into private typing internals.
- **A constraint on a variadic is a build-time error.** `constraints` may only name
  a parameter that is actually validated; naming a `*args`/`**kwargs` (or a
  nonexistent parameter) raises `SchemaError` when the function is decorated, so a
  typo fails loudly instead of silently validating nothing.
- **Return validation is off unless asked.** Unlike the parameters, a return
  annotation is not enforced by default, so a loose return hint does not silently
  become a runtime contract; opt in with `returns`.
- **The failure surface matches `validate`.** Arguments are validated as a mapping,
  so a bad argument reports as `... for dictionary value @ data['name']`, the same
  phrasing `validate` produces. The path already names the parameter; the shared
  wording keeps the two decorators coherent.
- **First async-aware surface.** The decorator detects a coroutine function and
  awaits the call before the return schema runs. It is the only place in the package
  that branches on async; the validation engine itself stays synchronous.
