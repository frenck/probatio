# ADR-015: Structured errors, human-first messages, and localization

**Date**: 2026-07-03
**Status**: Accepted

**Context**: Probatio's error messages are voluptuous heritage, and it shows in
three ways. First, the default rendering is written for parsers, not people:
`expected int for dictionary value @ data['server']['port']` leaks an internal
variable name (`data`) that the user has never seen, in a syntax only a Python
developer parses comfortably. Real-world configurations (Home Assistant is the
canonical consumer) nest four or five levels deep, and the `data[...][...]` chain
gets worse with every level. Second, some default wordings are wrong for what the
engine actually accepts: "expected a dictionary" fires for any non-Mapping input,
including the dataclass and TypedDict schema paths, where "dictionary" is not what
the user wrote. Third, every message is an f-string baked at the raise site. By the
time a consumer catches the error, "length of value must be at least 10" is a
finished string: the `10`, the field, and the reason are no longer addressable. A
consumer that wants to present errors in its own words, its own language, or its
own UI has nothing to work with but string parsing.

Half the structured layer already exists. `Invalid` carries a per-class `code`, a
`context` dict, reserved `translation_key` and `placeholders` slots, and
`as_dict()` for serialization. But the built-ins never populate the translation
slots, so the structured layer is a promise without a payload.

The tension is the drop-in promise (ADR-001): message text is observable behavior,
and downstream test suites assert on `str(err)`.

**Options considered**:

1. Keep voluptuous message text and rendering exactly, expose structure only
   through new attributes. Safest for compatibility, but it freezes bad messages
   forever and the library keeps shipping a rendering nobody would design today.
2. Ship translations as the headline: a locale catalog for every message, bundled
   language packs, a global language switch. Rejected as the *first* step: bundled
   translations are a maintenance treadmill, and the consumers that care most
   (Home Assistant) will never use our strings, they need the data underneath.
3. Structured error data first, human-first English defaults, localization as a
   mechanism rather than bundled content (this ADR).

**Decision**: Option 3, in three parts.

**Part 1: every error carries its data.** Every raise site populates a stable
`translation_key` and `placeholders` alongside the message. `LengthInvalid` carries
`translation_key="length_min"`, `placeholders={"min": 10}`, not just the rendered
sentence. The key is a public, documented, stable identifier: renaming one is a
breaking change. With the keys populated, `as_dict()` becomes a complete wire
format, and a consumer can render errors in any words, any language, any UI,
without touching our strings.

**Part 2: human-first default rendering.** This is a deliberate, documented
deviation from voluptuous (per ADR-001, behavioral divergence is a bug unless
documented; this is the documentation):

- The path suffix `@ data['a'][0]['b']` becomes a dotted path: `at 'a[0].b'`.
  Mapping keys join with dots, sequence indices render as `[n]`, keys that are not
  identifier-like fall back to their `repr`. Deeply nested errors stay readable:
  `expected str at 'automation[0].triggers[2].entity_id'`.
- The `for dictionary value` error-type clause disappears from the default
  rendering. The `error_type` attribute stays for compatibility; it just no longer
  clutters `str(e)`.
- Wordings that misdescribe the accepted input are corrected: "expected a
  dictionary" says what the engine means (a mapping, or the specific dataclass or
  TypedDict being validated) instead of naming one Python type.

The structured attributes (`path`, `code`, `translation_key`, `placeholders`,
`as_dict()`) are the advertised API for programmatic consumers; `str(e)` is for
humans and makes no stability promise beyond "readable".

**Part 3: localization as a mechanism.** Default English messages become a catalog
of templates keyed by `translation_key`, rendered lazily at `str()` time, never at
raise time (the error path is a measured hot path; see the compile-versus-validate
split). A locale hook swaps the catalog: a contextvar with a module-level default,
so a web application can render per-request locales without cross-request bleed.
Probatio ships the mechanism and the English catalog. Bundled translations are
explicitly out of scope for now; community locale packages can provide them.

**Rationale**:

- **The data layer serves everyone; our strings serve only some.** A better English
  sentence helps a CLI user. `translation_key` plus `placeholders` helps the CLI
  user, the Home Assistant frontend, a JSON API, and a future locale catalog, all
  from one change.
- **Error messages are product, not protocol.** Freezing them for compatibility
  (option 1) treats prose as API. The actual API is the structured layer; that is
  where the stability promise belongs.
- **Lazy rendering keeps the hot path honest.** Formatting at `str()` time means a
  caught-and-discarded error (the `Any`/`Or` happy path) never pays for template
  rendering.
- **Not bundling translations keeps the promise keepable.** Shipping two languages
  is easy; keeping twenty correct is a treadmill. A mechanism plus an English
  catalog is a commitment probatio can honor.

**Consequences**:

- **A documented compatibility break in `str(e)`.** Downstream suites that assert
  on exact voluptuous message text will fail on the new rendering. The migration
  story: assert on `code`/`translation_key`/`path` instead of prose. The
  compatibility tests pin the new rendering; divergences from voluptuous message
  text are recorded there as intentional. This applies under the compat shim
  too: `install_as_voluptuous` does not restore the old rendering (one rendering
  everywhere, no mode flag). Measured against the proof harnesses: voluptuous's
  own suite gains 24 rendering xfails (114 passed, 51 xfailed), and Home
  Assistant's `config_validation` suite drops from 142/142 to 136/142, the 6
  failures all being exact-string assertions on the old rendering.
- **Translation keys become public API.** Every key is documented, and renaming or
  removing one is treated like renaming a public function.
- **`humanize_error` follows the same rendering.** The humanize module keeps its
  extras (offending value, YAML file locations) on top of the new path style.
- **Roughly fifty raise sites change.** Mechanical, but every site needs a key and
  placeholders chosen with care; that is where the review effort goes.

**Revisit trigger**: Bundle translations if real demand shows up and a sustainable
source of native-speaker review exists (community locale packages proving
insufficient would be the signal). Revisit the dotted path rendering if consumers
are found parsing `str(e)` for the path despite the structured layer; that would
mean the structured API is not discoverable enough.
