---
title: Credits
description: The work Probatio is built on top of, and who maintains it.
---

## Standing on voluptuous

Probatio is a clean-room reimplementation of
[voluptuous](https://github.com/alecthomas/voluptuous). The API and the
behavior it mirrors are the work of voluptuous and its author, Alec Thomas, and
that credit is owed plainly. The pleasant idea that a schema is just data
describing data comes straight from there.

What Probatio does not do is copy code. It is written fresh and matches
voluptuous by behavior, validated against how voluptuous behaves, not by lifting
its source. That is what makes the clean MIT license possible.
[ADR-001](https://github.com/frenck/probatio/blob/main/adr/001-clean-room-reimplementation-of-voluptuous.md)
and [ADR-002](https://github.com/frenck/probatio/blob/main/adr/002-mit-license.md)
cover the reasoning.

The [license](/project/license/) page covers the MIT terms and third-party
notices in full.

## Ideas borrowed with credit

Clean-room does not mean invented in a vacuum. Several ideas in Probatio are
borrowed from [mashumaro](https://github.com/Fatal1ty/mashumaro), and the debt
is recorded where each decision was made:
[ADR-008](https://github.com/frenck/probatio/blob/main/adr/008-type-to-validator-registry.md)
(the type-to-validator registry),
[ADR-009](https://github.com/frenck/probatio/blob/main/adr/009-call-time-validation-context.md)
(the call-time validation context),
[ADR-012](https://github.com/frenck/probatio/blob/main/adr/012-trusted-construction-without-validation.md)
(trusted construction without validation), and
[ADR-013](https://github.com/frenck/probatio/blob/main/adr/013-markers-on-annotated-fields.md)
(field metadata on `Annotated` types) all cite its prior art.
[pydantic](https://docs.pydantic.dev) earns the same credit in ADR-013: its
`Annotated` field spec is the precedent that settled how Probatio's field
metadata works.

## Author

Created and written by **Franck Nijhof**, better known as **Frenck**, a
[GitHub Star](https://stars.github.com/profiles/frenck/) and the Home Assistant
lead. Find more of his work at [frenck.dev](https://frenck.dev) and on GitHub at
[@frenck](https://github.com/frenck).
