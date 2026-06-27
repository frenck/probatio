# ⚖️ Probatio

[![GitHub Release][releases-shield]][releases]
[![Python Versions][python-versions-shield]][pypi]
![Project Stage][project-stage-shield]
![Project Maintenance][maintenance-shield]
[![License][license-shield]](https://github.com/frenck/probatio/blob/main/LICENSE)

[![Build Status][build-shield]][build]

Put your data to the proof.

## About

Probatio is a modern, maintained data validation library for Python. The model
is simple: a schema is data, and data describes data. You compose schemas from
plain Python types, dicts, lists, and a handful of small helpers, then call the
schema with a value to validate it.

It is a drop-in for [voluptuous][voluptuous]: the same public API, so you can
swap the import and keep your existing schemas. Probatio is a clean-room
reimplementation (the same API written fresh, not a fork), which means it can be
actively maintained, ships under a clean MIT license, and is free to fix bugs
and improve its internals without inheriting old decisions. See
[ADR-001](https://github.com/frenck/probatio/blob/main/adr/001-clean-room-reimplementation-of-voluptuous.md) for the full
reasoning, and [Credits and inspiration](#credits-and-inspiration) for the
lineage.

It does not stop at parity. Probatio clears voluptuous's own backlog (cross-field
rules, dataclass and TypedDict schemas, network and format validators, errors
that carry a path and suggest the key you meant), and it is held to the bar you
would want from a library that loads untrusted config. See
[Why trust it](#why-trust-it).

Probatio is pure Python: no compiler, no build step, no native extension.
Install it and import it. Requires Python 3.13 or newer.

## Installation

```bash
pip install probatio
```

Or with [uv][uv]:

```bash
uv add probatio
```

## Usage

Define a schema, then call it with a value to validate it. A valid value comes
back (possibly normalized); an invalid one raises `Invalid`.

```python
from probatio import Schema, Required, Optional

schema = Schema(
    {
        Required("name"): str,
        Optional("port", default=8080): int,
    }
)

schema({"name": "app"})
# {'name': 'app', 'port': 8080}
```

When a value does not match, the error carries a path to the offending value:

```python
from probatio import Schema, Invalid

schema = Schema({"port": int})

try:
    schema({"port": "nope"})
except Invalid as err:
    print(err)
    # expected int for dictionary value @ data['port']
```

## Why trust it

It is a config-loading library, so the real question is whether you would feed it
untrusted input. The evidence, not the adjectives:

- **voluptuous 0.16.0 test suite:** 140 pass, 27 deliberate and documented
  deviations. voluptuous's own authors' notion of the contract, run against
  Probatio.
- **Home Assistant `config_validation`:** 142 of 142 pass, with voluptuous
  swapped out for Probatio.
- **100% line and branch coverage**, type-checked under both mypy and ty, in CI.
- **Fuzzed on every untrusted-input surface.** The first fuzzing pass found
  hundreds of exception leaks on hostile input. All fixed; none since.
- **Safer than the original:** a built-in validator only ever raises `Invalid`,
  never a raw exception, and that is enforced, not hoped for.

## Migrating from voluptuous

Probatio aims to be a drop-in replacement. In most cases the migration is a
single import change:

```python
# Before
from voluptuous import Schema, Required, Optional, All, Any, Coerce, Invalid

# After
from probatio import Schema, Required, Optional, All, Any, Coerce, Invalid
```

The markers (`Required`, `Optional`, `Remove`, `Extra`), combinators (`All`,
`Any`), helpers (`Coerce`, `Range`, `In`, `Length`, `Match`, and friends), and
errors (`Invalid`, `MultipleInvalid`) all behave the way they do in voluptuous.
See the [migration guide][docs-migrating] for the current compatibility status.

## Documentation

Full documentation lives at **[probatio.frenck.dev][docs]**: getting started, the
migration guide, and the API reference.

## Changelog & Releases

This repository keeps a change log using [GitHub's releases][releases]
functionality. The format of the log is based on
[Keep a Changelog][keepchangelog]. There is intentionally no `CHANGELOG.md` file:
the GitHub Releases are the changelog.

Releases are based on [Semantic Versioning][semver], and use the format
of `MAJOR.MINOR.PATCH`. In a nutshell, the version will be incremented
based on the following:

- `MAJOR`: Incompatible or major changes.
- `MINOR`: Backwards-compatible new features and enhancements.
- `PATCH`: Backwards-compatible bugfixes and package updates.

## Contributing

This is an active open-source project. We are always open to people who want to
use the code or contribute to it.

Using AI tools to help is fine, but you must review and understand everything you
submit. Please read our [AI Policy](https://github.com/frenck/probatio/blob/main/AI_POLICY.md)
first; autonomous agents are not allowed, and unreviewed AI output will be closed.

Before you start, read the [contributing guide][contributing], the
[code of conduct][code-of-conduct], and the [security policy][security]. Bugs and
feature requests go to the [issue tracker][issues].

Thank you for being involved! :heart_eyes:

## Credits and inspiration

Probatio owes its design to [voluptuous][voluptuous] by Alec Thomas. The API and
the "schema is data" validation model are its inspiration. Probatio reimplements
them fresh, no code copied, so the result can be maintained and MIT licensed,
but the original idea is theirs and the credit belongs to them.

voluptuous itself drew on earlier work, and it is only fair to pass that on:
Validino as its major influence, with lighter nods to jsonvalidator and
json_schema. Probatio stands on that same lineage.

## Authors & contributors

The original setup of this repository is by [Franck Nijhof][frenck].

For a full list of all authors and contributors,
check [the contributor's page][contributors].

## License

MIT License

Copyright (c) 2026 Franck Nijhof

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

[build-shield]: https://github.com/frenck/probatio/actions/workflows/tests.yaml/badge.svg
[build]: https://github.com/frenck/probatio/actions/workflows/tests.yaml
[code-of-conduct]: https://github.com/frenck/probatio/blob/main/.github/CODE_OF_CONDUCT.md
[contributing]: https://github.com/frenck/probatio/blob/main/.github/CONTRIBUTING.md
[contributors]: https://github.com/frenck/probatio/graphs/contributors
[issues]: https://github.com/frenck/probatio/issues
[security]: https://github.com/frenck/probatio/blob/main/.github/SECURITY.md
[docs-migrating]: https://probatio.frenck.dev/getting-started/migrating-from-voluptuous/
[docs]: https://probatio.frenck.dev
[frenck]: https://github.com/frenck
[keepchangelog]: http://keepachangelog.com/en/1.0.0/
[license-shield]: https://img.shields.io/github/license/frenck/probatio.svg
[maintenance-shield]: https://img.shields.io/maintenance/yes/2026.svg
[project-stage-shield]: https://img.shields.io/badge/project%20stage-experimental-yellow.svg
[pypi]: https://pypi.org/project/probatio/
[python-versions-shield]: https://img.shields.io/badge/python-3.13_%7C_3.14-blue?logo=python&logoColor=white
[releases-shield]: https://img.shields.io/github/release/frenck/probatio.svg
[releases]: https://github.com/frenck/probatio/releases
[semver]: http://semver.org/spec/v2.0.0.html
[uv]: https://docs.astral.sh/uv/
[voluptuous]: https://github.com/alecthomas/voluptuous
