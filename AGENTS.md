# AGENTS.md

Guidance for AI coding agents (and humans) working in this repository. This file
follows the [agents.md](https://agents.md) convention. `CLAUDE.md` is a symlink to
this file, so Claude-compatible tooling reads the same guidance.

## What this project is

Probatio is a modern, maintained data validation library for Python. It is a
clean-room reimplementation of [voluptuous](https://github.com/alecthomas/voluptuous):
the same public API, written fresh (no copied code), so it can be MIT licensed
and actively maintained. It is pure Python, no native extension. The package
lives in `src/probatio/`.

The drop-in promise is the whole point: changing the import from `voluptuous` to
`probatio` should keep existing schemas working. Behavioral compatibility with
voluptuous is the primary correctness target (see ADR-001).

## Project layout

| Path            | Purpose                                                       |
| --------------- | ------------------------------------------------------------- |
| `src/probatio/` | The Python package                                            |
| `tests/`        | pytest suite; each test has a one-line docstring              |
| `docs/`         | Astro Starlight documentation site                            |
| `adr/`          | Architecture decision records (the why behind major choices)  |

## Commands: `just` is the interface

This project uses [uv](https://docs.astral.sh/uv/) for Python and
[just](https://github.com/casey/just) as the task runner. `just` is the primary
interface: every common workflow (setup, test, lint, type-check, spellcheck,
docs, the full gate) is a recipe that wraps the exact `uv` command CI runs, so
the two cannot drift. **Run `just --list` (or `just`) to discover the recipes;
that list is the source of truth, not this file.**

Run a recipe with the venv activated (`uv sync && source .venv/bin/activate`,
then `just <recipe>`), or without activating by prefixing `uv run --no-sync`:

```bash
uv run --no-sync just check         # the full local gate: hooks, suite, types
uv run --no-sync just test -k foo   # the suite; extra args pass through to pytest
```

`just check` is the gate to pass before calling anything done. There is nothing
to compile (Probatio is pure Python); `just setup` (`uv sync`) creates the venv
and installs the dev dependencies. During iteration, running a single tool
directly (`uv run --no-sync pytest -k ...`, `ruff check`, `mypy src/probatio`) is
fine and faster than the whole gate; the recipes wrap those same tools.

The compatibility tests pin Probatio behavior to voluptuous. When you change the
validation engine, run them and treat any divergence from voluptuous as a bug,
unless it is documented as an intentional deviation.

## Conventions

- The public API mirrors voluptuous. Do not rename or re-signature public names
  without a documented reason; the drop-in promise depends on it.
- Every public function and class carries a docstring.
- Every test has a one-line docstring describing what it verifies.
- No copied code from voluptuous. Probatio is a clean-room implementation
  (ADR-001); match behavior, not source.
- Match the surrounding code style; prefer small, well-named functions.

## Writing and voice

This project is public and read closely. Code and prose are held to a high bar:
clear, idiomatic, honest, no filler. English for all public artifacts (commits,
PRs, issues, docs). When writing any of those, avoid:

- AI cheerleading and marketing speak (leverage, synergize, delight).
- Em-dashes and en-dashes anywhere. Use a period, colon, comma, or parentheses;
  hyphen only for compound words. Restructure a sentence rather than reach for one.
- "e.g.", "i.e.", "etc."; write "like", "for example", "such as".
- CAPS for emphasis (use italics); "click" as a verb (use "select").
- "HA"/"HASS"; write "Home Assistant" in full, and never frame it as fragile or
  easy to break.
- "master/slave"; use "client/server", "leader/follower", "main/replica".

## Gotchas

- Schemas are built from arbitrary Python callables and types. The engine calls
  back into user code constantly, so keep error paths and value paths precise:
  `Invalid` must report the right path to the offending value.
- Validation order matters for `All`/`Any` and for marker defaults. Match
  voluptuous semantics exactly.

## Where to read next

- `adr/` (start at `adr/README.md`): architecture decision records.
- `docs/`: the full user-facing documentation (Astro Starlight).
