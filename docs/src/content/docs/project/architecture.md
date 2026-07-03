---
title: Architecture
description: How Probatio is put together, from errors and markers up to the voluptuous compatibility shim.
---

This page is a map, not an essay. It walks the design in layers, bottom to top,
so you know where a given piece of behavior lives. For the reasoning behind the
big choices, read the architecture decision records in
[`adr/`](https://github.com/frenck/probatio/tree/main/adr), starting at
[`adr/README.md`](https://github.com/frenck/probatio/blob/main/adr/README.md).

Probatio is pure Python. No native extension, nothing to build at install
time. That is a deliberate choice, not a limitation I have not gotten around to
yet. The target workload (config validation, such as Home Assistant) runs at
load time, not in a hot inner loop, and the interpreted engine already beats
voluptuous there. On top of that engine sits an optional compiled fast path: a
hot schema generates specialized Python for itself, purely as an accelerator.
[ADR-004](https://github.com/frenck/probatio/blob/main/adr/004-single-validation-engine.md)
and [ADR-011](https://github.com/frenck/probatio/blob/main/adr/011-opt-in-compiled-schema.md)
together tell that story: one set of validation semantics, with speed layered
on top of it.

## The layers

### Errors and markers

At the bottom sit the things everything else speaks in.

Errors live in `error.py`. `Invalid` is a single validation failure that carries
a `path` to the offending value. `MultipleInvalid` collects several. The
semantic subclasses (`TypeInvalid`, `RangeInvalid`, `RequiredFieldInvalid`, and
the rest) let callers catch by kind. Keeping the path precise is the whole game:
the engine calls back into arbitrary user code constantly, so every layer is
careful to report where a value went wrong, not just that it did.

Markers live in `markers.py`. These are dictionary keys that carry intent:
`Required`, `Optional`, `Remove`, `Inclusive`, `Exclusive`, and the `Extra`
catch-all. Each compares and hashes by its underlying key, so a marker can stand
in for the bare key it wraps.

### Errors for humans

On top of the raw errors sits the rendering layer. Every built-in error carries
a stable `translation_key` and `placeholders`, drawn from the message catalog in
`_messages.py`, so a consumer can present a failure in its own words or its own
language instead of parsing a finished string. `humanize.py` renders the
default human-facing output: dotted paths, "did you mean ...?" suggestions, and
`Secret` redaction. [ADR-015](https://github.com/frenck/probatio/blob/main/adr/015-structured-errors-and-localization.md)
covers why the structured data is the API and the English text is just one
rendering of it.

### The engine

`_engine.py` is the interpreted core. A schema is compiled once into a
callable, then run per validation. Think of it like `re.compile`: you pay the
build cost once, then validate many values cheaply.

The engine owns the mapping and sequence validators, where the awkward
voluptuous semantics live: marker precedence, literal keys before type keys,
the extra-key policy, and the exact error paths. There is one set of validation
semantics, and this engine is it.
[ADR-004](https://github.com/frenck/probatio/blob/main/adr/004-single-validation-engine.md)
explains why an earlier second engine was removed: two full implementations
must stay behaviorally identical on every corner case, and that equivalence tax
rots.

[ADR-011](https://github.com/frenck/probatio/blob/main/adr/011-opt-in-compiled-schema.md)
revisits that decision with a design that avoids the tax. `_codegen.py`
generates a flat, success-path-only function for a schema's exact shape, and
`_compile_policy.py` decides when: under the default `AUTO` policy a schema
compiles itself only once it has proven hot. The generated code handles only
the happy path. On any failure (a missing key, a type mismatch, a validator
raising) it bails to the interpreted engine, which produces every error, path,
and ordering. So compiling changes speed, never behavior, and the semantics
still live in one place. The knobs are in the
[compiled schemas guide](/guides/compiled-schemas/).

One small optimization stays: validators can declare `__probatio_safe__` to
promise they only raise `Invalid`, and the engine then calls them without the
extra guard that wraps stray `ValueError`. It is a contract, not a second
engine.

### The Schema compiler

`schema.py` is the front door. `Schema(...)` takes a declarative definition (a
type, a literal, a callable, a dict, a list, a nested schema, or any validator)
and compiles it into the engine callable. Calling the schema validates a value
and returns the normalized result, or raises.

This is the compile-once-then-validate model in one object. Build the schema
when your program starts, call it on every value after that.

### Dataclass and TypedDict schemas

`dataclass_schema.py` builds schemas from type annotations instead of dict
literals. `create_dataclass_schema` and `create_typeddict_schema` read a class's
fields, infer `Required` and `Optional` from defaults, and turn each annotation
(including `Annotated[int, Range(...)]`) into a schema fragment through a shared
annotation engine. `DataclassSchema` validates a dict and constructs the
instance in one step.
[ADR-013](https://github.com/frenck/probatio/blob/main/adr/013-markers-on-annotated-fields.md)
covers the field-metadata spec that lets an `Annotated` field carry marker
facets like `Secret` and `Alias`.

### The probatio decorator

`decorator.py` is the same annotation engine pointed at a function signature.
`@probatio` reads each parameter's annotation, validates the arguments before
the body runs, and works on coroutine functions too
([ADR-014](https://github.com/frenck/probatio/blob/main/adr/014-annotation-driven-argument-decorator.md)).
The older `validate` decorator (schemas named by hand, sync-only) stays for the
voluptuous drop-in.

### The validators

`validators/` holds the building blocks you compose schemas from, one module
per group: combinators (`All`, `Any`, `Union`, `SomeOf`), comparison and
membership (`Range`, `In`, `Length`, `Equal`), coercion (`Coerce`, `Boolean`),
conditional presence (`RequiredWith`, `ExactlyOne`), encodings (`Base64`,
`JSONString`), checksummed formats (`CreditCard`, `IBAN`), identifiers (`UUID`,
`ULID`, `MacAddress`), network (`IPAddress`, `Hostname`, `Port`), strings
(`Email`, `Url`, the case transforms), structural (`ExactSequence`, `Unique`,
`Maybe`), temporal (`Datetime`, `Date`, `Duration`), transitions between an old
and a new payload (`Immutable`, `WriteOnce`), predicates, and the `validate`
decorator. They share a small base in `validators/_base.py`.

### The codecs

`codecs/` converts schemas to and from other schema languages, for the
constructs that map cleanly: JSON Schema (`jsonschema.py`), OpenAPI
(`openapi.py`), and a plain field-list serialization (`fields.py`). A custom
serializer returns the `UNSUPPORTED` sentinel to defer a construct it does not
handle to the built-in logic.

`from_json_schema` treats its input as untrusted. It refuses a catastrophically
backtracking `pattern` and a pathologically deep document, so a hostile schema
cannot hang the process or overflow the stack. That guard lives in
`codecs/_regex_safety.py`.

### The serde loaders and dumpers

`serde/` reads and writes JSON, YAML, and TOML. It uses a fast backend when one
is installed (such as orjson) and falls back to the standard library where the
standard library can do the job: JSON read and write and TOML read work bare,
while YAML and TOML write need an optional backend. The `Schema.load_*`
convenience methods parse and validate in one step on top of
this layer.

### The voluptuous compatibility shim

`compat/` is the thin top layer that backs the drop-in promise. It exposes the
voluptuous names and signatures so changing the import from `voluptuous` to
`probatio` keeps existing schemas working. The plumbing behind it lives in
`_vol_shim/`: the voluptuous-shaped modules (`error`, `validators`,
`schema_builder`, `util`) that `compat.install_as_voluptuous` registers under
the `voluptuous` name, so even a dependency that imports voluptuous internals
resolves to Probatio. Behavior, not source, is what is matched here. No code
was copied ([ADR-001](https://github.com/frenck/probatio/blob/main/adr/001-clean-room-reimplementation-of-voluptuous.md)).

## Where to read next

- [`adr/README.md`](https://github.com/frenck/probatio/blob/main/adr/README.md):
  the index of architecture decision records, with the why behind each major
  decision.
- The [API reference](/reference/): the public surface, grouped by what each
  name does.
