# ADR-016: Remove the serde loaders and dumpers

**Date**: 2026-07-04
**Status**: Accepted

**Context**: Probatio shipped a serde layer (`load_json`/`load_yaml`/`load_toml`,
`dump_json`/`dump_yaml`/`dump_toml`, the `Schema.load*` convenience methods, and
the `FromYAMLString`/`YAMLString` validators). It parsed and serialized JSON, YAML,
and TOML, auto-selecting the fastest installed backend per format (orjson over the
standard library for JSON, YAMLRocks over PyYAML for YAML, `tomllib`/`tomli-w` for
TOML), and documented the backend as an "invisible implementation detail" whose
output "does not depend on which backend is installed."

A review of the subsystem found two problems, and they compound.

The sameness promise is false. orjson coerces an integer of `2**64` or more to a
float where the standard library keeps it exact. A `datetime` dumped by YAMLRocks
as a bare ISO string is re-read by PyYAML (YAML 1.1) as a native `date`, and a
`time` as a base-60 integer (`12:00:00` becomes `43200`). The two YAML backends
also differ on unknown-tag handling and on alias-bomb resistance. Because the pick
depends on what is installed, a transitive dependency that pulls in a faster
backend silently changes how the application parses its data. That is the same
footgun as the reversed type-to-validator registry
([ADR-008](008-type-to-validator-registry.md)): behavior that shifts under you
because of distant, unrelated install state. Reconciling the backends so the
promise holds is whack-a-mole, and some divergences (the YAML 1.1/1.2 temporal
reinterpretation) cannot be cheaply closed.

Dumping is a deeper problem than a backend pick. voluptuous, and Probatio with it,
is a one-way pipeline: validators and transformers take data in, and there is no
defined way back out. Dumping a validated value is not serialization, it is the
_inverse transform_. `AsDate` is `str -> date` on the way in, so a faithful way out
is `date -> str`, and the correct string depends on the schema (`AsDate(format=...)`
must dump back to that format, not ISO). A real "way back" needs bidirectional
transformers, as marshmallow (`_serialize`/`_deserialize`), cattrs (structure and
unstructure), and pydantic (`@field_serializer`) all have. Many Probatio transforms
do not invert at all: `Clamp`, `Lower`, `Coerce`, and `Boolean` are lossy or
many-to-one. A schema-blind `dump` is barely more than `json.dumps` with a few
special cases; the honest version is a different, much larger product.

**Options considered**:

1. Remove the serde layer entirely. Probatio validates parsed Python objects; the
   caller owns parsing and serialization.
2. Keep serde but make the backend an explicit, documented per-call choice with a
   fixed default, dropping the sameness promise (a `backend="orjson"` argument, and
   perhaps a configured `Serde` instance).
3. Redesign around named-backend schema subclasses (`YAMLRocksSchema`), a
   mashumaro-style thin wrapper that parses then validates.
4. Build the real bidirectional-transformer feature so dumping is faithful.

**Decision**: Option 1. Remove the serde subsystem. Probatio is a validation
library in the voluptuous scope: it validates parsed Python objects, and the
caller parses and serializes with whatever library they already trust.

Gone: `src/probatio/serde/`, the `load_*`/`dump_*` top-level functions, the
`Schema.load*` methods, `set_default_options`/`default_options`/`clear_default_options`,
the `FromYAMLString`/`YAMLString` validators and the `YamlInvalid` error, the
`fast`/`yaml`/`toml` extras, and the `_overlay` module. The `FromJSONString` and
`JSONString` validators stay: they use the standard library's `json` directly and
carry no backend machinery.

**Rationale**:

- It removes the invisible-backend footgun at the root, the same way the ADR-008
  reversal did. Behavior no longer shifts under a distant `pip install`.
- Options 2 and 3 keep the loading half but not the dumping half. They still owe a
  "way back" that the one-way engine cannot honestly provide, so they postpone the
  real question rather than answer it.
- Option 4 is a genuinely different, much larger product (bidirectional
  transformers). It may be worth building one day, but as its own thing, not
  bolted onto a validator, and not now.
- It matches the ecosystem. voluptuous has no loaders. pydantic parses JSON with
  its own `model_validate_json` but tells you to parse YAML and TOML yourself and
  call `model_validate`. marshmallow, cerberus, jsonschema, and cattrs all validate
  parsed objects. Validation and parsing are separate concerns, and every neighbor
  draws the line where we now do.

**Consequences**:

- Breaking change for any caller using `load_*`, `dump_*`, `Schema.load*`, the YAML
  string validators, or the extras. The migration is a one-liner:
  `schema(json.loads(source))` in place of `schema.load_json(source)`, and the same
  shape for YAML (`schema(yaml.safe_load(source))`) and TOML.
- The [loading and dumping guide](../docs/src/content/docs/guides/loading-and-dumping.md)
  is kept, rewritten as the bring-your-own-loader pattern with orjson and YAMLRocks
  as concrete examples, so the recipe callers relied on is still documented.
- The source-location feature (a locator handed to `humanize_error`) survives as a
  generic hook: `humanize_error` still takes a `locator`, and `Location` is still
  exported, but building one is now the caller's job on top of a position-tracking
  parser, rather than a bundled `load_yaml_with_locations`.
- Probatio never bundles or auto-picks a parser again. If a "way back" is revisited,
  it is the bidirectional-transformer feature, not a serializer bolt-on.
