# ADR-018: Carry a container subclass's instance state across a rebuild

**Date**: 2026-09-16
**Status**: Accepted

**Context**: Validating a mapping or a sequence builds a new container and fills it
with the validated values. The engine already rebuilds it as the input's own class,
so a `dict` or `list` subclass survives validation as that subclass, matching
voluptuous. What did not survive was the instance state: the rebuilt container is a
fresh, empty instance, so everything the original held in its `__dict__` or its
`__slots__` was silently dropped.

That is not a theoretical loss. Home Assistant loads YAML through `annotatedyaml`,
whose `NodeDictClass(dict)`, `NodeListClass(list)`, and `NodeStrClass(str)` declare
`__slots__ = ("__config_file__", "__line__")` and record where in the configuration
each node was written. Every schema rebuild wiped them, and error messages that
depend on them degraded. The verified case: `cv.deprecated()` prints "The 'old'
option near configuration.yaml:12 is deprecated" before validation, and loses the
"near ..." part after a single schema rebuild. A user gets told something is wrong
with no way to find it.

A `str` subclass was never affected, because a scalar is passed through rather than
rebuilt, so `NodeStrClass` already kept its annotation. The gap was containers only.

**Decision**: Copy the source container's own instance state onto the rebuilt
container, reading it through `object.__getstate__()`.

`object.__getstate__` is the standard state protocol that `pickle` and `copy`
already use, and it has been available on every object since CPython 3.11 (Probatio
requires 3.12, ADR-006), so it is always there. It returns `None` when there is
nothing to carry, a plain dict for an instance `__dict__`, and a
`(dict_or_None, slots_dict)` pair when `__slots__` are involved, with an unset slot
simply absent. One private helper, `_carry_subclass_state`, applies it at every
place the engine rebuilds a container as the input's own type:

- `_MappingValidator.__call__`, right after constructing the subclass instance and
  before the fill, so a subclass `__setitem__` runs with the state already in place.
  The carry reads the original input, not the plain dict that alias resolution
  produces.
- `_SequenceValidator.__call__`, after a successful `out_type(result)` or
  `out_type(*result)` rebuild.
- `ExactSequence.__call__`, which repeats the same rebuild.

Using a standard accessor, rather than a probatio-specific opt-in dunder, is the
point of the decision. Nobody has to learn about, or import, a Probatio hook to
keep state they already model in the normal way. It also keeps the library honest
about the drop-in promise: Probatio holds no knowledge of `annotatedyaml` or of
Home Assistant, and any annotating loader gets the same behavior.

`object.__getstate__` is read **unbound**, so a subclass that overrides
`__getstate__` does not redirect the read. The scope is therefore the default
instance state and nothing else. That bound is deliberate, not an oversight:

- The shape of the value is then guaranteed by the interpreter. Read through the
  instance, an override may return any object at all, and probatio would have to
  either guess at it (a custom two-tuple of non-dicts would be _misread_ as a
  dict/slots pair) or discard it.
- Honoring an override properly means calling `__setstate__` on the destination,
  which runs user code against a container that already holds the _validated_
  items. A `__setstate__` that also restores contents, which is a normal thing for
  one to do, would put the unvalidated items back and silently undo the
  validation. That is the same hazard that keeps `_ObjectValidator` out of this
  ADR, and it gets the same answer.
- Bypassing the override narrows _what_ runs, not whether anything runs. No
  subclass gets to decide what its state _is_, so the value probatio destructures
  is the interpreter's and the shape is fixed. Collecting a slot value is still an
  ordinary attribute access on the source, and that is the limit of the claim.

How much user code the copy runs depends on where the state lives, and the two
halves are not alike. `__dict__` entries are written straight into the
destination's instance dict, so `__setattr__` is never consulted and a class that
refuses assignments still receives all of them. A slot runs user code at both
ends: reading it off the source goes through its `__getattribute__` and may
resolve through a descriptor, and writing it onto the destination goes through its
`__setattr__`. That code failing is not a validation failure, so any error in the
carry is swallowed. A failed read carries nothing at all; a failed write leaves
whatever was applied before it. Either way the worst case is the behavior before
this ADR, so the degradation is to the old, safe result rather than to a crash.
`BaseException` still propagates.

This is a deliberate, documented deviation from voluptuous (ADR-001). voluptuous
builds `data.__class__()` and drops the state too. No schema starts accepting or
rejecting different data, and no validated _value_ changes, with one narrow
exception: in the mapping engine the state is applied before the items, so a
subclass whose own `__setitem__` reads that state now reads it. Such a subclass
previously raised `AttributeError` out of the engine, or read a fallback; it now
sees the real state. Turning that crash into a success is the point, and the
ordering is what makes a state-dependent subclass usable at all.

**Alternatives considered**:

- **A probatio-specific dunder (`__probatio_carry_state__`, or a marker base
  class).** Explicit, and it would let a class opt out. But it makes every
  annotating loader depend on Probatio to keep working, which is the opposite of a
  drop-in library, and it would leave `annotatedyaml` (and every other loader)
  broken until it adopted the hook. Rejected.
- **Copying `__dict__` and walking `__slots__` by hand.** It is what
  `object.__getstate__` does, minus the edge cases: an inherited `__slots__` across
  a class hierarchy, a class that models `__slots__` as a bare string, a class that
  wants to control what it exposes. Reimplementing a protocol that already exists
  buys nothing. Rejected.
- **Reading `__getstate__` through the instance and restoring through
  `__setstate__`.** The full pickle round trip, which would make "anything that
  pickles, carries" literally true. Rejected: `__setstate__` runs user code
  against a container that already holds the validated items, so a `__setstate__`
  that restores contents would undo the validation, and it doubles the amount of
  user code the engine executes per container node for a case no annotating
  loader has. Reading the override _without_ honoring `__setstate__`, which is
  what the first draft of this change did, is worse than either end: it can
  misread a custom two-tuple as a dict/slots pair.
- **Carrying nothing and documenting the loss.** The status quo. It leaves Home
  Assistant with worse error messages than it had on voluptuous plus
  `annotatedyaml`, for no gain. Rejected.
- **Carrying onto `Object(...)`'s rebuilt instance.** `_ObjectValidator` calls
  `type(data)(**validated)`, so the constructor runs with the validated attributes.
  Copying the source's raw state over that would overwrite validated values with
  the unvalidated originals, undoing the validation. Deliberately not done; that
  site is object construction, not container rebuilding.

**Consequences**:

- A `dict` or `list` subclass now comes back with its instance state intact, so an
  annotated node keeps its source file and line through any number of nested schema
  rebuilds. Home Assistant's `cv.deprecated()` message reads the same before and
  after validation.
- Nothing opts in and there is no opt-out. A class cannot suppress the carry by
  overriding `__getstate__`, because the override is never read. A class that
  must not have an attribute copied should not hold it on the instance.
- Custom pickle state is not carried. A class with a `__getstate__`/`__setstate__`
  pair still gets its plain attributes copied like any other class; only the
  private representation those two exchange is out of scope, and it is documented
  as such rather than being silently attempted.
- The plain `dict` and plain `list` paths pay nothing: the mapping engine only
  reaches the carry when it has constructed a real subclass instance, and the
  helper returns immediately for an exact built-in container. A subclass pays one
  `object.__getstate__` call, which returns `None` when there is no state and
  otherwise costs one attribute access per set slot. Measured on a 10 500-line
  Home Assistant configuration (about 4500 container nodes) the whole carry costs
  roughly 0.3 ms, about 66 ns per container node.
- The compiled engine (ADR-011) is unaffected, and needs no generated code for
  this. Its mapping prologue guards `type(data) is not dict` and its inlined
  sequence guards `type(_v) is not list`, so any subclass input bails to the
  interpreted engine before the generated rebuild is reached. The generated code
  only ever builds plain containers, which have nothing to carry.
- A rebuild that degrades to a plain container is unchanged and carries nothing: a
  `Mapping` that is not a `dict` subclass, a `Coerce(dict)`, and the sequence
  engine's `except TypeError` fallback for a subclass whose constructor does not
  take the validated items as one iterable. Those results were never the input's
  own type, so there is no state that belongs on them.
- That `TypeError` fallback is the sequence engine's alone. The mapping engine
  rebuilds with a bare `data_type()` and catches nothing, so a `dict` subclass
  whose constructor requires an argument raises `TypeError` out of validation
  instead of degrading. That is unchanged here, and it is what voluptuous does
  too, but the asymmetry is real and this ADR should not be read as promising a
  graceful degrade for every container.
