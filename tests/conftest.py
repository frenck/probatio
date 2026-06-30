"""Shared pytest configuration for the probatio test suite.

The ``--compiled`` option runs the whole behavioral suite with schema compilation
forced on, so every schema that can be generated is, and validation goes through
the generated code. Because a compiled schema must behave identically to its
interpreted twin, the entire suite is the parity check: if it passes interpreted
and passes compiled, the two engines agree across the whole behavioral surface,
not just the curated cases in ``test_codegen.py``.

Run it with ``just test-compiled``. The compile-specific suites (``test_codegen``
and ``test_compile_policy``) drive both modes themselves, so the recipe excludes
them from this lane.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from probatio import CompilePolicy, get_compile_policy, set_compile_policy

if TYPE_CHECKING:
    from collections.abc import Iterator


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add ``--compiled`` to run the suite with schema compilation forced on.

    Run it through ``just test-compiled``, which selects only the deterministic
    behavioral tests. Do not point it at the property-based or fuzz suites: they
    generate thousands of distinct schemas, and compiling each one ``exec``s a
    fresh code object that is never reused, so the memory grows without bound.
    """
    parser.addoption(
        "--compiled",
        action="store_true",
        default=False,
        help="Force schema compilation on, to prove the compiled engine's parity.",
    )


# Test files excluded from the --compiled lane. The property-based and fuzz suites
# generate thousands of distinct schemas, and compiling each execs a code object
# that is never reused, so forcing compilation there grows memory without bound.
# The compile-specific suites drive both modes themselves, so forcing one mode on
# them is meaningless. Matched against the test file name only (not the full node
# id), so a parametrized id or a directory that happens to contain one of these
# words is never skipped by accident.
_COMPILED_LANE_EXCLUDE_FILES = frozenset(
    {
        "test_codegen.py",
        "test_compile_policy.py",
        "test_safe_contract.py",
    },
)


def _excluded_from_compiled_lane(item: pytest.Item) -> bool:
    """Whether a test's file is excluded from the ``--compiled`` lane."""
    name = item.path.name
    # The fuzz suites are a family (``test_fuzz_*`` across packages), matched by
    # name; the others are named in full above.
    return name in _COMPILED_LANE_EXCLUDE_FILES or "fuzz" in name


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip the property-based, fuzz, and compile-specific tests under ``--compiled``."""
    if not config.getoption("--compiled"):
        return
    skip = pytest.mark.skip(reason="not run under --compiled (property/fuzz/compile)")
    for item in items:
        if _excluded_from_compiled_lane(item):
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _reset_compile_policy() -> Iterator[None]:
    """Restore the process-wide compile policy after each test, so it cannot leak."""
    original = get_compile_policy()
    try:
        yield
    finally:
        set_compile_policy(original)


@pytest.fixture(autouse=True, scope="session")
def _pin_compile_policy(request: pytest.FixtureRequest) -> Iterator[None]:
    """Pin the compile policy for the whole session, so the suite is deterministic.

    The library default is ``AUTO``, which compiles a schema once it proves hot.
    That timing is exactly what a test suite must not depend on: the property-based
    and fuzz suites revalidate enough to cross the threshold and compile thousands
    of throwaway schemas, which is both slow and a memory risk. So the bulk of the
    suite runs pinned to ``OFF`` (fast, interpreted, deterministic), and the
    ``--compiled`` lane runs pinned to ``ON`` to prove the generated code's parity.
    Tests that care about a specific policy set it themselves.
    """
    pinned = (
        CompilePolicy.ON
        if request.config.getoption("--compiled")
        else CompilePolicy.OFF
    )
    original = get_compile_policy()
    set_compile_policy(pinned)
    try:
        yield
    finally:
        set_compile_policy(original)
