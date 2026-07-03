# Home Assistant drop-in proof

The real compatibility target for Probatio is Home Assistant: its
`config_validation` helper is the largest and most demanding voluptuous consumer.
This directory holds a small harness that runs Home Assistant's own
`config_validation` test suite with `voluptuous` swapped out for Probatio, so the
drop-in promise is measured against the actual tests, not a paraphrase of them.

It is not part of Probatio's CI (it needs a Home Assistant checkout), but it is
kept here so the proof is reproducible.

## How it works

`probatio_vol_swap.py` is a tiny pytest plugin that calls
`probatio.compat.install_as_voluptuous()` before collection. That shipped helper
aliases `voluptuous` (and the submodules Home Assistant's dependencies reach into)
to Probatio in `sys.modules`, including a behavior-compatible
`voluptuous.schema_builder._compile_scalar`, because `annotatedyaml` imports that
voluptuous internal directly (a genuine drop-in finding: the public API alone is
not the whole surface). The mechanism lives in the library, so this plugin is
just the seam that activates it for the test run.

## Running it

From a Home Assistant `core` checkout whose virtualenv has Probatio installed
(`uv pip install --python .venv -e /path/to/probatio`):

```bash
PYTHONPATH=/path/to/probatio/compat/home_assistant \
  .venv/bin/python -m pytest tests/helpers/test_config_validation.py \
  -p probatio_vol_swap -q
```

## Result

136 of the 142 tests in `tests/helpers/test_config_validation.py` pass against
Probatio. The 6 that fail all assert the exact voluptuous-rendered error string
(`"... for dictionary value @ data[...]"`), which Probatio deliberately renders
differently since ADR-015 (a dotted path, no error-type clause). The `path`
segments, error classes, and bare messages still match; only the rendering
around them differs.

Getting there surfaced (and fixed) several real compatibility gaps that pure unit
tests had not:

- `Remove(key): value_schema` must still validate the value; only a value that
  validates is dropped, otherwise the key falls through to the extra-key policy.
- `Email`, `Url`, and `FqdnUrl` are factories (`Url()` returns the validator),
  matching voluptuous, not direct validators.
- A failed mapping _value_ error is tagged `error_type = "dictionary value"`
  (the attribute is kept even though `str(error)` no longer renders it).
- `All` and `Any` raise `MultipleInvalid` on failure (a bare `AllInvalid` /
  `AnyInvalid` only when a custom `msg` is given), and `Any` surfaces the branch
  error that reached the deepest path rather than a generic message.
