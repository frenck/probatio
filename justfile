# probatio task runner. See every recipe with `just --list`.
#
# First time:   uv sync && source .venv/bin/activate   (then `just <recipe>`)
# Or without activating, prefix any recipe: `uv run --no-sync just <recipe>`.
#
# Recipes use the uv-managed environment and assume `just setup` has run once.
# Versions live only in pyproject.toml / uv.lock.

# Show the list of recipes.
default:
    @just --list

# Install all development dependencies into the uv-managed environment, including
# every workspace package under packages/.
setup:
    uv sync --all-packages

# Run the test suite. Extra args pass through, e.g. `just test -k schema`.
test *args:
    uv run --no-sync pytest {{args}}

# Run the workspace packages' own suites (the core coverage gate does not apply).
test-packages:
    uv run --no-sync pytest packages/pytest-probatio/tests -o addopts=""

# Lint and format-check Python (read-only; use `just fmt` to fix).
lint:
    uv run --no-sync ruff check .
    uv run --no-sync ruff format --check .

# Auto-format Python in place.
fmt:
    uv run --no-sync ruff check --fix .
    uv run --no-sync ruff format .

# Type-check with both mypy and ty.
typecheck:
    uv run --no-sync mypy src/probatio
    uv run --no-sync ty check src/probatio
    uv run --no-sync mypy packages/pytest-probatio/src

# Spell-check the codebase (codespell; config in pyproject.toml).
spellcheck:
    uv run --no-sync codespell

# Audit the GitHub Actions workflows for security issues (zizmor, pedantic).
zizmor:
    uv run --no-sync zizmor .github/workflows/ --persona=pedantic

# Run every pre-commit hook via prek (the exact set CI runs): ruff, mypy, ty,
# codespell, zizmor, actionlint, prettier, file hygiene. Pass a hook id to run
# just one, e.g. `just precommit actionlint`.
precommit *args:
    uvx prek run {{args}} --all-files

# Measure test coverage and report missing lines.
coverage:
    uv run --no-sync pytest --cov --cov-report=term-missing --cov-report=xml

# Print a rough probatio vs voluptuous throughput comparison.
bench:
    uv run --no-sync python bench/bench.py

# Run the CodSpeed benchmarks (walltime locally; tracked in CI).
codspeed:
    uv sync --group codspeed
    uv run --no-sync pytest bench --codspeed --no-cov -o addopts=""

# Run every documented Python example and verify its output comments.
examples:
    uv run --no-sync python docs/verify_examples.py

# Fuzz the atheris harnesses (each for `seconds`, default 30). Runs on an isolated
# Python 3.13 env: atheris has no 3.14 wheel, and the oss-fuzz CI image is 3.11, so
# this is the path that actually exercises the harnesses. A crash fails the recipe
# and leaves a gitignored crash-* file to reproduce.
fuzz seconds='30':
    #!/usr/bin/env bash
    set -euo pipefail
    for harness in fuzz/fuzz_*.py; do
      echo "=== ${harness} ({{seconds}}s) ==="
      uv run --no-project --isolated --python 3.13 \
        --with 'atheris==3.1.0' --with-editable '.[fast,yaml,toml]' \
        python "${harness}" -max_total_time={{seconds}} -artifact_prefix=./
    done

# Run Home Assistant's config_validation suite against probatio (set HOME_ASSISTANT_CORE to a core checkout).
ha-proof:
    #!/usr/bin/env bash
    set -euo pipefail
    core="${HOME_ASSISTANT_CORE:-}"
    if [ -z "${core}" ]; then
      echo "Set HOME_ASSISTANT_CORE to a Home Assistant 'core' checkout." >&2
      exit 1
    fi
    uv pip install --python "${core}/.venv" -e .
    cd "${core}"
    PYTHONPATH="{{justfile_directory()}}/compat/home_assistant" \
      .venv/bin/python -m pytest tests/helpers/test_config_validation.py \
      -p probatio_vol_swap -q

# Build the documentation site.
docs:
    cd docs && npm ci && npm run build

# Serve the docs with live reload.
docs-dev:
    cd docs && npm ci && npm run dev

# Run the full local gate (CI parity): all pre-commit hooks, the suite, the
# workspace packages, and docs.
check: precommit
    uv run --no-sync pytest -q
    uv run --no-sync pytest packages/pytest-probatio/tests -o addopts=""
    uv run --no-sync python docs/verify_examples.py

# Remove build and tooling artifacts.
clean:
    rm -rf dist build .pytest_cache .ruff_cache .mypy_cache .ty htmlcov .coverage coverage.xml
    find . -type d -name __pycache__ -exec rm -rf {} +
