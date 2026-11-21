# ADR-018: An annotation model for validated values

**Date**: 2026-09-16
**Status**: Accepted

**Context**: Some data arrives knowing more about itself than its contents say. A
YAML loader knows the file and the line every mapping came from. A request parser
knows which part of a multipart body a field was in. A migration knows a key used
to be spelled differently. That knowledge is what turns "expected a string" into
"expected a string, near configuration.yaml:12", so it is worth keeping.

Validation loses it. A mapping or sequence schema rebuilds its input, and while
probatio preserves `dict` and `list` subclasses (matching voluptuous, see
`_engine.py`), the rebuilt container is a fresh, empty instance of that class: the
items are copied over one at a time and everything the original held beside them is
gone. Home Assistant hit this concretely. `annotatedyaml` records the source file
and line in `__slots__` on its node classes, and every schema that rebuilds a
mapping drops them, which is why `cv.deprecated` stopped being able to say where
the deprecated option was. The loss is not confined to the top level: it happens at
every nesting depth, for every schema shape that rebuilds, so no amount of care at
the call site reaches it.

Three ways to close it were considered.

1. **Carry the whole instance state.** Read the source's default state through
   `object.__getstate__` (which reports `__dict__` and set `__slots__`) and write it
   onto the rebuilt container. It needs no cooperation from the data's author, and
   heals Home Assistant with no change in `annotatedyaml` at all.
2. **Let the type supply a copier.** An opt-in dunder on the input's class that
   probatio calls with the source and the destination.
3. **Define what the metadata _is_.** Give probatio a model of the thing being
   preserved, a single documented place values carry it, and an API validators use
   to read and add to it.

**Decision**: Take the third. `probatio.annotations` defines the model:

- `Annotations`, an immutable mapping of `str` to anything, is what a value carries.
- A value carries it in one attribute, `__probatio_annotations__`, also exported as
  `ANNOTATIONS_ATTR`. A `__slots__` type opts in with one line, and a type with an
  ordinary `__dict__` needs no declaration. Those are the only two forms: the
  attribute has to be somewhere the value simply holds it, not a property or any
  other descriptor, for the reason in the rationale.
- Every site where probatio rebuilds a value carries the annotations across: the
  mapping engine, the sequence engine, `ExactSequence`, and `Object`. Each does so
  only when writing the attribute runs none of the carrier's own code.
- Validators read with `annotations_of`, add with `annotate`, and move annotations
  onto a value they built themselves with `carry_annotations`.

**Rationale**:

- **Carrying arbitrary state is a promise probatio cannot keep.** Option 1 copies
  whatever the instance happened to hold: a cached hash, a lock, a parent pointer, a
  memoized render. Duplicating those onto a second object is not obviously correct,
  and probatio has no way to tell the ones that should be shared from the ones that
  should not. A defined, narrow concept can be reasoned about; "the instance's
  state" cannot. It is also why option 1 has to stop at `Object`, where reapplying
  raw state would put the _unvalidated_ attributes back over the validated ones.
  Annotations avoid that hazard, but only because probatio never lets a carrier's
  own code run over freshly validated output. An earlier draft of this record argued
  that a container was safe because its items are not attributes. That was wrong: a
  property setter receives the container itself, so it can add a key a mapping schema
  never saw or replace an item a sequence schema just checked, and both
  `PREVENT_EXTRA` and the element checks are bypassed. The same setter on an object
  built by `Object` can restore the unvalidated attributes over the validated ones.

  So the condition is on the write, and it is the same at every site: probatio
  carries when setting the attribute lands in the attribute itself (a `__slots__`
  member descriptor, a plain instance `__dict__`) and declines when it would run a
  property, another descriptor the carrier defined, or an overridden `__setattr__`.
  One rule, no per-site exceptions, and `supports_annotations` reports it. The answer
  depends only on the type, so it is computed once and cached; the lookup reads class
  namespaces directly rather than calling `getattr` on the class, which would run a
  custom descriptor's `__get__`.

- **A model lets validators participate.** This is what neither of the other options
  offers. Options 1 and 2 preserve what was already there; they give a validator no
  way to say anything. With a model there is an obvious answer: `annotate` merges
  into what a value carries, and because the engine propagates whatever it finds,
  an annotation a validator adds survives every container rebuild above it. A
  validator that
  transforms a container calls `carry_annotations` and the metadata follows the
  transformation. Composition falls out: `All(schema, annotator)` and
  `All(annotator, schema)` both end with the loader's annotations and the
  validator's own.
- **It is the cheapest of the three.** One attribute read and one attribute write,
  behind one cached lookup of how to perform the write. Measured on CPython 3.14,
  `carry_annotations` costs 66 ns per rebuilt value for a slot carrier with its
  annotations set, 35 ns for a subclass that never opted in, 125 ns for a slot
  declared but left unset on that value (the descriptor exists and raises on the
  read), and 34 ns for a value it declines to carry onto. Reading the full default
  state through `object.__getstate__` is several times a plain write, and allocates a
  state tuple and a dict to report it. On a 1500-entry nested config (1502 rebuilt
  containers) the carry itself costs roughly 55 ns per container, about 0.08 ms for
  the document; a plain `dict` or `list` input is unchanged, because the generated
  validators take it and never reach the carry at all.

- **The attribute is the whole protocol.** No registration, no dunder method, no
  base class to inherit. That matters because a slotted mixin is impossible here:
  `class Node(dict, Mixin)` with a non-empty `__slots__` on the mixin is a layout
  conflict, so anything probatio shipped as a base class would not work for the
  `dict` and `list` subclasses this exists to serve.
- **Immutability makes sharing safe.** The rebuilt value gets the _same_
  `Annotations` object rather than a copy, which is what keeps the carry to two
  attribute operations. That is only sound because nothing can change it through
  either reference, so the guarantee is enforced rather than left to convention:
  the contents are copied into a dict no one else holds and reached only through a
  `MappingProxyType`. The one cost is that the proxy cannot be pickled, so
  `Annotations` reduces through its own constructor.

**Consequences**: Six additive public names (`ANNOTATIONS_ATTR`, `Annotations`,
`annotate`, `annotations_of`, `carry_annotations`, `supports_annotations`) and no
change to any existing signature. Points to fix in the design and the docs:

- **Opt-in.** A type that makes no room for the attribute carries nothing, and the
  common case (a plain `dict` in, a plain `dict` out) is untouched. Home Assistant
  gets the fix when `annotatedyaml` adds the slot and its loader writes the file and
  line _into_ the annotations. Adding the slot alone is not enough: `__config_file__`
  and `__line__` are separate slots that probatio does not know about and does not
  carry. The four places in Home Assistant that read those two slots move to
  `annotations_of` with it.
- **Values that cannot hold an attribute.** A plain `dict`, a `str`, an `int` cannot
  be annotated. `annotate` and `carry_annotations` return such a value unchanged
  rather than raise, so a validator can call them without knowing what it was handed;
  the cost is that a genuine mistake is quiet, which `supports_annotations` exists to
  let a caller check for.
- **Replace, not merge, on a rebuild.** The engine moves the source's annotations
  onto the rebuilt value, overwriting any the fresh instance gave itself in its own
  constructor. The rebuilt value stands in for the original, so the original's
  annotations are the right ones. A source carrying none leaves the new instance's
  own alone.
- **`Object` does not see the attribute.** `_iterate_object` skips it, so an
  annotated object's metadata is never offered to the attribute schema as a field
  (where `PREVENT_EXTRA` would reject it) and an unset slot is never read. It is
  carried onto the constructed object like any other rebuild, under the same rule.
- **A carrier class is first-party code, and is trusted like one.** probatio writes
  the annotation attribute with `setattr`, so a class that defines a property of that
  name would have its setter run on a value validation has just produced, and that
  setter could add a key a mapping schema never saw. The rule below rejects such a
  class, which closes that door, but it is worth being clear about why the door is
  worth closing: not because a carrier is untrusted. It is not. A plain validator
  callable can already do exactly the same thing, and more, with nothing in its way:

  ```python
  Schema(All({"a": str}, inject), extra=PREVENT_EXTRA)({"a": "x"})
  # {'a': 'x', 'injected': 'not validated'}
  ```

  probatio does not sandbox validators and does not sandbox carriers. A schema's
  output is what its validators leave behind, and a carrier's author is the schema's
  author. Hardening the carry against a class written to sabotage its own validation
  would buy nothing that the front door does not already give away, and the checks
  needed to do it properly have no natural end (a property, then `__setattr__`, then
  `__getattribute__`, then a metaclass). The boundary is stated here so it does not
  have to be rediscovered one review at a time.

  It earns its keep immediately. The per-type cache is keyed by the class, so a
  metaclass defining `__eq__` and `__hash__` can make two classes collide and hand a
  property carrier the answer computed for a slot carrier, and a metaclass that defines
  `__eq__` without `__hash__` leaves a class that cannot be a cache key at all. Both are
  declined. The first needs a metaclass written to confuse probatio about its own
  author's classes. The second looks at first like the ordinary `__eq__`-without-
  `__hash__` slip, but that intuition is about instances and does not transfer: a class
  left unhashable cannot be deep-copied or pickled _as an instance_, and breaks
  `lru_cache`, `singledispatch`, and any set or dict holding the class. Such a class is
  unusable as a data carrier long before probatio looks at it, so raising there is the
  same answer the standard library already gives.

- **A property is not a carrier.** An earlier revision let a type expose a property
  of that name over fields it already had, as a way to opt in without touching the
  loader. It is rejected now, and the reasons are ordinary ones rather than
  adversarial: such a property silently drops any key the fields behind it cannot
  hold, it costs several times a slot read on every rebuilt value, and `Object`
  validates the very attributes such a property tends to be built over, so a setter
  writing them back undoes the coercion that just ran. That last one was a real
  accident waiting to happen, not a contrived one, because the Home Assistant recipe
  recommended exactly that shape. The protocol is a plain data attribute, the check
  is what makes that true rather than aspirational, and `supports_annotations`
  reports it. It is computed once per type and cached; recomputing per carry costs
  264 ns against a 10 ns lookup.
- **`Annotations` is not optimized for the small case, yet.** One holding two keys
  costs about 264 bytes: the object, its `MappingProxyType`, and the backing dict.
  A consumer allocating one per config node would feel that, and a packed
  representation for a handful of keys would cut it by roughly half. It is not done
  here, because immutability already buys the larger win: the same `Annotations` can
  be shared by every value from the same place, which makes the cost one object per
  distinct location rather than one per value, and brings a loader's per-node write
  to 36 ns against 26 ns for two plain slot stores. The representation stays private
  to `annotations.py`, so packing it later changes nothing outside.
- **A carrier that keeps less than it is given is not detected.** The write lands in
  a plain attribute, so probatio knows it succeeded; whether the value holds what it
  was handed is only visible by reading it back, and `annotations_of` is how a caller
  checks. Verifying inside `annotate` was considered and rejected: `annotate` is what
  a loader calls once per value, and a read-back there taxes the common case to
  diagnose a rare one.
- **`supports_annotations` asks the question probatio asks itself.** It reports
  whether the attribute is a plain data attribute, which is the same test the carry
  performs, so the public helper and the engine cannot disagree. Earlier drafts asked
  whether the attribute was merely reachable, and then whether a write would land at
  all; both reported True for values probatio would not in fact carry. Recorded
  because the readings are easy to confuse.
- **Type destruction is still out of reach.** A validator that returns
  `dict(value)`, a comprehension, or an accumulator produces a plain `dict` or
  `list`, and no engine change can heal that. `carry_annotations` is the fix, applied
  by the validator's author.
- **Errors do not read annotations yet.** Attaching the annotations of the offending
  value to the `Invalid` it raises is the obvious next step and is deliberately not
  in this change; the model is the prerequisite for it.
