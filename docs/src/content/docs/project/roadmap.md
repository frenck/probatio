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

Two different things, and the distinction matters.

The public API tracks voluptuous and is meant to stay stable. The names and
signatures (`Schema`, `Required`, `All`, `Any`, `Coerce`, `Invalid`, and the
rest) are what your code depends on, so they do not move without a documented
reason.

The internals are not promised. Before 1.0 they may change while the project
gathers production feedback and the implementation settles. If you reach past
the public API into private modules, that is on you.

:::caution[Pre-1.0]
Some internals may still change before 1.0. The public API is the contract; the
internals are not.
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
