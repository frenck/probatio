---
title: Projects using Probatio
description: Where Probatio fits, and who is using it.
---

Probatio is young. This page tracks projects that use it and, just as usefully,
the ecosystems it is built to serve. If you adopt Probatio, please
[edit this page on GitHub](https://github.com/frenck/probatio/edit/main/docs/src/content/docs/project/projects.md)
and open a pull request to add yourself here.

## Home Assistant

<img
  src="/logos/home-assistant-light.svg"
  alt="Home Assistant"
  class="adopter-logo adopter-logo--light"
/>
<img
  src="/logos/home-assistant-dark.svg"
  alt="Home Assistant"
  class="adopter-logo adopter-logo--dark"
/>

[Home Assistant](https://www.home-assistant.io) has validated every
integration's configuration with Probatio since Core 2026.9, on a hot path hit
by millions of installations at startup and on every reload. voluptuous is no
longer installed at all: the `voluptuous` name is aliased to Probatio in
`sys.modules` at startup, so custom integrations keep working unchanged while
the core itself imports Probatio directly.

Probatio tracks voluptuous behavior closely, with documented deviations; how
that compatibility is measured, including against Home Assistant's own test
suite, is on the [about page](/project/about/). See the
[Home Assistant recipe](/recipes/home-assistant/).

## Libraries

A library that Home Assistant installs and that declares voluptuous pulls in a
package Home Assistant then shadows, since the name is aliased to Probatio at
startup. Depending on Probatio directly drops the redundant install.

- [ramses-rf](https://github.com/ramses-rf/ramses_rf), an interface for the
  RAMSES-II RF protocol used by Honeywell-compatible HVAC and CH/DHW systems.
  It backs [ramses_cc](https://github.com/ramses-rf/ramses_cc).
- [evohome-async](https://github.com/zxdavb/evohome-async), an async client for
  the Resideo TCC web API, behind Home Assistant's evohome integration.
  Switched on `main`, not yet released.

## Where Probatio fits

Probatio was designed as a drop-in successor to voluptuous, so it fits anywhere
voluptuous is used today: a maintained library, the same schema-is-data API, and
fixes for the rough edges. Home Assistant, above, is the first of those. The
following are the other ecosystems that motivated its design.

### ESPHome

ESPHome validates device configurations with voluptuous, and (at the time of
writing) reaches into its internals for friendly errors and speed. Probatio offers
those as first-class features (close-match key suggestions, an engine that matches
per key in linear time), so a consumer does not have to fork the validator to get
them. See [migrating from voluptuous](/getting-started/migrating-from-voluptuous/)
for what that move looks like.

### Anywhere voluptuous is used

Beyond Home Assistant and ESPHome, voluptuous validates configuration and
request data across a long tail of libraries, CLIs, and services. For any of
them the move is the same: change the import, keep the schemas, and gain a
maintained library with a richer error model and codecs for JSON Schema,
OpenAPI, dataclasses, and field lists.
Start with [migrating from voluptuous](/getting-started/migrating-from-voluptuous/).
