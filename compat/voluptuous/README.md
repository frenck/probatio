# voluptuous drop-in proof

Probatio promises to be a drop-in for voluptuous. The most direct evidence is
voluptuous's _own_ test suite, run against Probatio: its test authors' notion of
the contract, at the exact version Probatio targets (0.16.0). This directory
holds a small harness that does that.

It runs in CI on every pull request, and locally with one command.

## How it works

`conftest.py` calls `probatio.compat.install_as_voluptuous()` before collection,
so voluptuous's upstream `tests.py` imports Probatio instead. The same conftest
marks the known divergences as strict `xfail` (with a reason each), so a clean
run is "all green": everything passes or is an expected, documented `xfail`, and
any _new_ break, a regression, or a divergence that unexpectedly starts passing,
fails the run.

The upstream `tests.py` cannot be imported in place (Probatio is aliased as the
`voluptuous` package, so a file under `voluptuous/tests/` fails to import as
`voluptuous.tests.tests`). So `fetch_upstream.py` downloads it next to the
conftest, where it imports as a plain top-level module. That copy is voluptuous's
BSD-licensed file; it is git-ignored, not vendored. The script pins both the
upstream commit and the SHA-256 of the file, so what a green run means cannot
change unnoticed.

## Running it

From a Probatio checkout whose venv has Probatio installed:

```bash
uv run --no-sync just compat-voluptuous
```

The recipe fetches the pinned file and runs it with `-o addopts=""`, which drops
Probatio's own coverage options: they do not apply to a foreign test file.

## Result

115 passed, 52 xfailed, 0 unexpected failures.

Getting there fixed several real bugs that Probatio's own tests had not surfaced,
each pinned with a Probatio test:

- `Range` admitted `NaN` (every comparison with `NaN` is false, so the old
  "raise if below/above" form let it through). Now rejected, matching voluptuous.
- `Email` waved through trailing junk (`user@host>`): the character sets of the
  local and domain parts are now checked.
- A namedtuple as data crashed the sequence engine (`type(data)(list)` fails for a
  namedtuple); it is now rebuilt with a splat. A schema written as a namedtuple
  also accepts a plain tuple, matching voluptuous.
- `Schema.extend` did not deep-merge nested mappings (it replaced a nested key
  wholesale) and did not preserve a `Schema` subclass. Both fixed.
- Markers were not orderable; `sorted([Required("b"), Required("a")])` and
  `Optional("a") < "b"` now work (compare by the underlying key).

The 52 xfails are all documented divergences, grouped in `conftest.py`:

- **The error rendering deviation (ADR-015)**: `str(error)` renders the path as
  a dotted trail (`at 'a.b'`) instead of `@ data['a']['b']`, drops the
  `for dictionary value` clause, and rejects a non-mapping as "expected a
  mapping". Every test that string-matches the rendered error diverges; the
  `path` segments and the bare message still match voluptuous.
- **Deliberate improvements** (see the compatibility matrix): the "did you mean
  ...?" unknown-key error, lower-cased `Number` messages, the richer error wording
  for `Contains`, `In`, `NotIn`, `Maybe`, `Coerce`, and `FqdnUrl`, the reworded
  `Literal` message, set and empty-container element errors that carry an index
  path, a `float` matcher that matches an `int` too (ADR-017, which is why
  `Remove(float)` in a list drops ints), `SomeOf`'s bounds-assertion message, and `Maybe`'s own `repr` (probatio's
  `Maybe` is a real validator, not an alias of `Any`).
- **Out of scope**: one test of the voluptuous internal
  `_iterate_mapping_candidates`, not part of the public contract.
