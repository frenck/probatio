# voluptuous drop-in proof

Probatio promises to be a drop-in for voluptuous. The most direct evidence is
voluptuous's *own* test suite, run against Probatio: its test authors' notion of
the contract, at the exact version Probatio targets (0.16.0). This directory
holds a small harness that does that.

It is not part of Probatio's CI (it needs a voluptuous checkout), but it is kept
here so the proof is reproducible.

## How it works

`conftest.py` calls `probatio.compat.install_as_voluptuous()` before collection,
so voluptuous's upstream `tests.py` imports Probatio instead. The same conftest
marks the known divergences `xfail` (with a reason each), so a clean run is "all
green": everything passes or is an expected, documented `xfail`, and any *new*
break, a regression, or a divergence that unexpectedly starts passing, shows up
loudly.

The upstream `tests.py` cannot be imported in place (Probatio is aliased as the
`voluptuous` package, so a file under `voluptuous/tests/` fails to import as
`voluptuous.tests.tests`). So you copy it next to the conftest, where it imports
as a plain top-level module. That copy is voluptuous's BSD-licensed file; it is
git-ignored, not vendored.

## Running it

From a Probatio checkout whose venv has Probatio installed, with a voluptuous
0.16.0 source checkout available:

```bash
cp /path/to/voluptuous/voluptuous/tests/tests.py compat/voluptuous/tests.py
uv run --no-sync python -m pytest compat/voluptuous/tests.py -o addopts="" -q
```

(`-o addopts=""` drops Probatio's own coverage/strict options, which do not apply
to a foreign test file.)

## Result

140 passed, 27 xfailed, 0 unexpected failures.

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

The 27 xfails are all documented divergences, grouped in `conftest.py`:

- **Deliberate improvements** (see the compatibility matrix): the "did you mean
  ...?" unknown-key error, lower-cased `Number` messages, the richer error wording
  for `Contains`, `In`, `NotIn`, `Maybe`, `Coerce`, and `FqdnUrl`, set and
  empty-container element errors that carry an index path, a non-dict `Mapping`
  returning a plain dict, `SomeOf`'s bounds-assertion message, and `Maybe`'s own
  `repr` (probatio's `Maybe` is a real validator, not an alias of `Any`).
- **Out of scope**: one test of the voluptuous internal
  `_iterate_mapping_candidates`, not part of the public contract.
