---
title: Stability and roadmap
description: Where Probatio stands today, and what stable means before 1.0.
---

Probatio is pre-1.0. Honest status: it works, it is tested, and it is young.
The current release line is 0.5, with v0.5.4 the latest at the time of writing;
the [release notes on GitHub](https://github.com/frenck/probatio/releases)
track what each release changed.

## The goal

Be a faithful drop-in for voluptuous. Change the import, keep your schemas. That
is the whole point, and it sets the bar for correctness: behavior is validated
against how voluptuous behaves, and a divergence is treated as a bug unless it is
documented as an intentional deviation ([ADR-001](https://github.com/frenck/probatio/blob/main/adr/001-clean-room-reimplementation-of-voluptuous.md)).

The order of work follows from that. Match voluptuous first, then iterate.

## What stable means here

Three things, and the distinction matters.

**The voluptuous-compatible surface** is the contract, and it tracks voluptuous.
The names and signatures every voluptuous user already depends on (`Schema`,
`Required`, `All`, `Any`, `Coerce`, `Invalid`, and the rest) do not move without a
documented reason, and when they do it is to sit closer to voluptuous, not further
from it.

**The Probatio-only surface** is public too, and there is a lot of it: the parts
voluptuous never had. Schemas built from your own types (`DataclassSchema`,
`TypedDictSchema`), the extra validators and markers (`AsDatetime`, `Slug`,
`Secret`, `Alias`, the cross-field rules, and more), the codecs (`to_json_schema`
and `to_openapi` with their `from_*` inverses, plus the output-only
`to_field_list`), and the build and compile policies. Anything importable straight
from `probatio` and listed in `__all__` is part of this surface. Before 1.0 it may
still shift as it settles under real use; at 1.0 it is frozen under semantic
versioning like the rest, and a public-surface snapshot test in the suite covers
the whole of it, so a change can only be deliberate.

**The error model** gets its own line, because it is the largest thing Probatio
adds over voluptuous. The error classes (`Invalid` and its subclasses) and the
structured data they carry, the `path` to the offending value, the
machine-readable `code`, the `context`, and the `translation_key`, are the
contract: catch them by type, read those fields, and rely on them. The
`translation_key` names the exact sentence of each message, and with its
`placeholders` it is what a translation keys on, so renaming or removing one is a
breaking change ([ADR-015](https://github.com/frenck/probatio/blob/main/adr/015-structured-errors-and-localization.md);
the [translation keys](/reference/translation-keys/) reference lists them all).
The one thing not frozen is the rendered English text: a custom `msg=` overrides
it, and a default may be reworded to read better, but the key stays put, so a
translation follows the key, not the words.

**The internals are not promised.** Before 1.0 they may change while the project
gathers production feedback and the implementation settles. If you reach past the
public API into private modules (anything with a leading underscore), that is on
you.

:::caution[Pre-1.0]
The Probatio-only surface may still shift before 1.0 as production feedback comes
in. The voluptuous-compatible surface is already the contract; the internals never
are.
:::

## Versioning

Probatio follows semantic versioning. While it is pre-1.0 (`0.x`), the practical
reading is: a patch release (`0.x.y`) is for fixes and compatibility
corrections, a minor release (`0.x`) may add to the public surface or change an
internal, and any breaking change to the public API is called out in the
[release notes](https://github.com/frenck/probatio/releases).

Because the public API tracks voluptuous, most changes are really compatibility
fixes: Probatio moving closer to how voluptuous behaves. Those are bug fixes,
even when they change Probatio's old output, and they ship as patch releases. A
deliberate deviation from voluptuous is documented on the
[compatibility page](/getting-started/compatibility/) and is never silent.
Release notes are drafted from the merged pull requests, so every change is
traceable to its reason.

## No promises I cannot keep

There are no dates here, and no feature list of things that do not yet exist.
The roadmap is the goal above: faithful compatibility, then iteration from real
use. When something ships, it ships in the docs and the
[release notes](https://github.com/frenck/probatio/releases), not as a promise
on this page.
