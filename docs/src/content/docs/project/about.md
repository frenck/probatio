---
title: About Probatio
description: Why Probatio exists, the state of voluptuous, and who builds it.
---

Probatio exists because a huge amount of Python leans on
[voluptuous](https://github.com/alecthomas/voluptuous) for data validation, and
voluptuous has gone quiet. The idea is excellent and the API is loved; what it
needs is a maintained home. Probatio is that home: the same public API, written
fresh, MIT licensed, and actively developed.

## voluptuous runs a lot of Python

Home Assistant validates every integration's configuration with voluptuous. So
does a long tail of libraries and tools across the ecosystem. The premise that
made it popular is genuinely good: a schema is just data describing data, built
from plain Python types, dicts, lists, and small helpers, then called with a
value to validate it. You already know the language; the schema is just more of
it.

That reach is also the problem. When the library underneath millions of
installations stops moving, every consumer inherits the bugs that never get
fixed, the sharp edges that never get filed down, and the Python versions that
never get supported.

## The state of validation in Python

Reaching for validation in Python tends to mean one of a few trades:

- **voluptuous** is the lightweight, schema-is-data choice that Home Assistant
  and many others standardized on. The model is a pleasure to use, but the
  project has seen little movement for years, and several rough edges (a
  `RecursionError` on deep data, a leaked `TypeError` from a built-in validator,
  errors reported twice) sit unfixed.
- **mashumaro** is a fast, dataclass-first take focused on serialization and
  deserialization. It is genuinely first-rate at what it does, and several ideas
  in Probatio are borrowed from it with credit (see the architecture decision
  records). It is a codec library more than a free-form validator, though, so the
  schema-is-data model is not the problem it set out to solve.
- **pydantic** is the heavyweight, class-first choice. It is fast and capable,
  but it asks you to describe data as typed models, which is a different mental
  model and a migration, not a drop-in. It has also broken backward compatibility
  and reshaped its API substantially in the past (the v1 to v2 rewrite), which is
  not a foundation this project wants to stand on.

There simply was not a maintained library that kept voluptuous's
schema-is-data feel while fixing the edges and keeping pace with Python.

## What Probatio is

Probatio is a clean-room reimplementation of voluptuous: the same public API,
matched by behavior rather than by copied source
([ADR-001](https://github.com/frenck/probatio/blob/main/adr/001-clean-room-reimplementation-of-voluptuous.md)),
so changing `import voluptuous` to `import probatio` keeps existing schemas
working. That clean-room rule is what lets it be MIT licensed
([ADR-002](https://github.com/frenck/probatio/blob/main/adr/002-mit-license.md))
and fit anywhere voluptuous did.

On top of the drop-in promise, Probatio fixes the rough edges (clean errors on
deep or cyclic data, no leaked exceptions from built-ins, a richer error model),
adds tooling voluptuous never had (JSON Schema, OpenAPI, dataclass and
field-list codecs), and is pure Python with zero required runtime dependencies.
It is held to a high bar for code and prose, because it is public and read
closely.

The compatibility is measured, not asserted: Home Assistant's own
`config_validation` test suite runs against Probatio (142 of 142 passing), and so
does voluptuous's own 0.16.0 test suite, with every divergence documented. The
[voluptuous compatibility](/reference/compatibility-matrix/) reference lists those
documented deviations name by name.

## Who builds it

Probatio is created and written by **Franck Nijhof**, better known as **Frenck**,
a [GitHub Star](https://stars.github.com/profiles/frenck/) and the Home Assistant
lead, where he has spent years working with voluptuous-validated configuration at
a scale and on a hot path that most projects never see. That experience is where
Probatio comes from.

Find more of his work at [frenck.dev](https://frenck.dev) and on GitHub at
[@frenck](https://github.com/frenck).
