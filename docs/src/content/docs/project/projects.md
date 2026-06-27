---
title: Projects using Probatio
description: Where Probatio fits, and who is using it.
---

Probatio is young. This page tracks projects that use it and, just as usefully,
the ecosystems it is built to serve. If you adopt Probatio, please
[open a pull request](https://github.com/frenck/probatio) to add yourself here.

## Using Probatio

_Be the first._ There are no public adopters yet. If your project validates data
with Probatio, we would love to list it.

## Where Probatio fits

Probatio was designed as a drop-in successor to voluptuous, so it fits anywhere
voluptuous is used today: a maintained library, the same schema-is-data API, and
fixes for the rough edges. The following ecosystems are the primary motivation
for its design.

### Home Assistant

Home Assistant validates every integration's configuration with voluptuous, on a
hot path hit by millions of installations at startup and on every reload.
Probatio matches that behavior exactly, its compatibility is pinned against Home
Assistant's own `config_validation` test suite (142 of 142 passing), and it adds
a cleaner error model with paths, no interpreter-level `RecursionError` on deep
configuration, and "did you mean ...?" suggestions for misspelled keys. See the
[Home Assistant recipe](/recipes/home-assistant/).

### ESPHome

ESPHome validates device configurations with voluptuous, and (at the time of
writing) reaches into its internals for friendly errors and speed. Probatio offers
those as first-class features (close-match key suggestions, an engine that matches
per key in linear time), so a consumer does not have to fork the validator to get
them. See [migrating from voluptuous](/getting-started/migrating-from-voluptuous/)
for what that move looks like.

### Anywhere voluptuous is used

Beyond the big two, voluptuous validates configuration and request data across a
long tail of libraries, CLIs, and services. For any of them the move is the same:
change the import, keep the schemas, and gain a maintained library with a richer
error model and codecs for JSON Schema, OpenAPI, dataclasses, and field lists.
Start with [migrating from voluptuous](/getting-started/migrating-from-voluptuous/).
