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

The ``--lazy-auto`` option runs the same suite the way a large application runs
probatio: schemas build on first use (``BuildPolicy.LAZY``) and compile once they
prove hot (``CompilePolicy.AUTO``). The call threshold is lowered so a schema that
is validated twice crosses it, which makes the suite exercise all three states of
an ``AUTO`` schema: unbuilt, counting, and compiled. Run it with
``just test-lazy-auto``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from hypothesis import settings

import probatio.schema
from probatio import (
    BuildPolicy,
    CompilePolicy,
    get_build_policy,
    get_compile_policy,
    set_build_policy,
    set_compile_policy,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


# Hypothesis fails an example that takes longer than 200 ms, and a property test
# that builds two libraries' schemas per example crosses that now and then on a
# loaded machine. The examples are derandomized, so a slow one is no finding.
settings.register_profile("probatio", deadline=None)
settings.load_profile("probatio")


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
    parser.addoption(
        "--lazy-auto",
        action="store_true",
        default=False,
        help="Build schemas lazily and compile them once hot, at a low threshold.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register the marker that keeps a test out of the ``--lazy-auto`` lane."""
    if config.getoption("--compiled") and config.getoption("--lazy-auto"):
        message = "--compiled and --lazy-auto are separate lanes; pass one of them."
        raise pytest.UsageError(message)

    config.addinivalue_line(
        "markers",
        "eager_interpreted(reason): the test asserts on a schema that is built at "
        "construction and validated interpreted, so --lazy-auto skips it.",
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


# Two calls are the fewest that take a schema through every state: the first one
# builds it and counts, the second one compiles it and runs the generated code.
_LAZY_AUTO_THRESHOLD = 2


def _skip_in_lazy_auto_lane(item: pytest.Item) -> str | None:
    """Why ``--lazy-auto`` skips a test, or ``None`` when it runs it."""
    # The lane compiles what it validates twice, so everything that keeps the
    # compiled lane away from a file applies here too. The lazy-build suite sets
    # the build policy itself.
    if _excluded_from_compiled_lane(item) or item.path.name == "test_lazy_build.py":
        return "not run under --lazy-auto (property/fuzz/compile/build policy)"

    marker = item.get_closest_marker("eager_interpreted")
    if marker is None:
        return None

    return f"not run under --lazy-auto: {marker.kwargs['reason']}"


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip the tests a lane cannot run: see the exclusions above."""
    if config.getoption("--compiled"):
        skip = pytest.mark.skip(
            reason="not run under --compiled (property/fuzz/compile)"
        )
        for item in items:
            if _excluded_from_compiled_lane(item):
                item.add_marker(skip)

    if config.getoption("--lazy-auto"):
        for item in items:
            reason = _skip_in_lazy_auto_lane(item)
            if reason is not None:
                item.add_marker(pytest.mark.skip(reason=reason))


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

    The ``--lazy-auto`` lane is the one place that does want ``AUTO``: it skips the
    suites that generate schemas in bulk, so the timing is two calls for every
    schema and nothing grows.
    """
    if request.config.getoption("--compiled"):
        pinned = CompilePolicy.ON
    elif request.config.getoption("--lazy-auto"):
        pinned = CompilePolicy.AUTO
    else:
        pinned = CompilePolicy.OFF

    original = get_compile_policy()
    set_compile_policy(pinned)
    try:
        yield
    finally:
        set_compile_policy(original)


@pytest.fixture(autouse=True, scope="session")
def _pin_lazy_auto_lane(request: pytest.FixtureRequest) -> Iterator[None]:
    """Under ``--lazy-auto``, build lazily and lower the ``AUTO`` call threshold."""
    if not request.config.getoption("--lazy-auto"):
        yield
        return

    build_policy = get_build_policy()
    threshold = probatio.schema._AUTO_COMPILE_THRESHOLD
    set_build_policy(BuildPolicy.LAZY)
    probatio.schema._AUTO_COMPILE_THRESHOLD = _LAZY_AUTO_THRESHOLD
    try:
        yield
    finally:
        set_build_policy(build_policy)
        probatio.schema._AUTO_COMPILE_THRESHOLD = threshold
