"""CodSpeed benchmarks for probatio's validation hot paths.

Run with: ``uv run --no-sync pytest bench --codspeed``. These are tracked per-PR
by CodSpeed so a performance regression shows up in review. They are not part of
the normal test run (testpaths is ``tests``).

Every benchmark pins its compile policy explicitly; none rides the process default.
That matters because the default is ``AUTO``, which compiles a schema once it has
been validated enough times, and a benchmark loops far past that threshold. Left to
the default, the interpreted benchmarks would silently start measuring generated
code mid-run, so the numbers would mix two engines and break the CodSpeed history.
Instead:

- The interpreted benchmarks build their schema with ``compile=False``. They are the
  engine baseline, continuous with every prior CodSpeed run.
- The ``*_compiled`` benchmarks call ``.compile()`` eagerly, so the generated
  validator is in place before the first measured call, with no warmup to mix in.
  A guard test asserts each one really swapped in generated code, so a future
  generator change cannot quietly turn a compiled benchmark back into an interpreted
  one without anyone noticing.
- ``test_generate_*`` measures the code generation itself (the cost being monitored),
  not validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import probatio
from probatio._codegen import compile_mapping


def _is_compiled(schema: probatio.Schema) -> bool:
    """Report whether the schema swapped in a generated validator."""
    return getattr(schema._compiled, "__name__", "") == "_validate"


def _config_schema() -> dict[Any, Any]:
    """The declarative config schema, fresh each call (for the compile benchmark)."""
    return {
        probatio.Required("name"): str,
        probatio.Optional("port", default=8080): probatio.All(
            probatio.Coerce(int),
            probatio.Range(min=1, max=65535),
        ),
        probatio.Optional("host", default="localhost"): str,
        probatio.Optional("tags", default=list): [str],
        probatio.Optional("mode"): probatio.In(["auto", "manual", "off"]),
    }


CONFIG = probatio.Schema(_config_schema(), compile=False)
CONFIG_COMPILED = probatio.Schema(_config_schema()).compile()
CONFIG_PAYLOAD = {
    "name": "service",
    "port": "443",
    "host": "example.com",
    "tags": ["a", "b", "c"],
    "mode": "auto",
}


def test_validate_config(benchmark: Any) -> None:
    """Validate a configuration-style payload (interpreted)."""
    result = benchmark(CONFIG, CONFIG_PAYLOAD)
    # Assert the work actually happened (port coerced to int), so a benchmark
    # cannot look faster by quietly skipping validation.
    assert result["port"] == 443


def test_validate_config_compiled(benchmark: Any) -> None:
    """Validate the same config payload through the generated validator."""
    result = benchmark(CONFIG_COMPILED, CONFIG_PAYLOAD)
    assert result["port"] == 443


def test_compile_config(benchmark: Any) -> None:
    """Build the full configuration schema from scratch (no code generation)."""
    result = benchmark(lambda: probatio.Schema(_config_schema(), compile=False))
    assert isinstance(result, probatio.Schema)


def test_generate_config(benchmark: Any) -> None:
    """Generate a validator for the config mapping: the codegen plus exec cost."""
    validator = probatio.Schema(_config_schema(), compile=False)._compiled
    result = benchmark(compile_mapping, validator)
    # Assert the generator accepted the mapping, so the benchmark cannot look faster
    # by bailing to None on a shape it no longer handles.
    assert result is not None


def _list_schema(**kwargs: Any) -> probatio.Schema:
    """A single-element list schema (coerced, range-checked numbers)."""
    return probatio.Schema(
        [probatio.All(probatio.Coerce(int), probatio.Range(min=0))], **kwargs
    )


LIST = _list_schema(compile=False)
LIST_COMPILED = _list_schema().compile()
LIST_PAYLOAD = [str(value) for value in range(50)]


def test_validate_list(benchmark: Any) -> None:
    """Validate a list of coerced, range-checked numbers (interpreted)."""
    result = benchmark(LIST, LIST_PAYLOAD)
    assert result == list(range(50))


def test_validate_list_compiled(benchmark: Any) -> None:
    """Validate the same list through the generated per-item loop."""
    result = benchmark(LIST_COMPILED, LIST_PAYLOAD)
    assert result == list(range(50))


def test_validate_any_miss(benchmark: Any) -> None:
    """Reject a value against an Any whose branches all fail (the deepest-error path)."""
    schema = probatio.Schema(probatio.Any(int, float, str), compile=False)

    def run() -> bool:
        try:
            schema(None)
        except probatio.MultipleInvalid:
            return True
        return False

    # Assert the value was actually rejected, so the benchmark cannot look faster
    # by quietly accepting it.
    assert benchmark(run) is True


def test_validate_exclusive_group(benchmark: Any) -> None:
    """Validate a mapping carrying an exclusive group (the group post-pass)."""
    schema = probatio.Schema(
        {
            probatio.Exclusive("a", "g"): int,
            probatio.Exclusive("b", "g"): int,
            probatio.Optional("c"): int,
        },
        compile=False,
    )
    result = benchmark(schema, {"a": 1, "c": 3})
    assert result == {"a": 1, "c": 3}


# A payload that fails the config schema two ways at once: a value that cannot
# coerce (a dictionary-value error with a path) and an unknown key (the extra-key
# "did you mean ...?" suggestion). This drives the error-construction path:
# building the path, aggregating into MultipleInvalid, and the suggestion lookup.
CONFIG_BAD_PAYLOAD = {
    "name": "service",
    "port": "not-a-number",
    "surplus": 1,
}


def test_validate_config_reject(benchmark: Any) -> None:
    """Reject a config payload with a bad value and an unknown key (the error path)."""

    def run() -> int:
        try:
            CONFIG(CONFIG_BAD_PAYLOAD)
        except probatio.MultipleInvalid as err:
            return len(err.errors)
        return 0

    # Assert both failures were reported, so the benchmark cannot look faster by
    # short-circuiting the error collection.
    assert benchmark(run) == 2


def _leaf_heavy_schema() -> dict[Any, Any]:
    """A wide mapping of built-in leaf validators, fresh each call."""
    return {
        probatio.Required("email"): probatio.Email(),
        probatio.Required("ip"): probatio.IPv4Address(),
        probatio.Required("host"): probatio.Hostname(),
        probatio.Required("code"): probatio.Match(r"^[A-Z]{3}$"),
        probatio.Required("slug"): probatio.Slug(),
    }


LEAF_HEAVY = probatio.Schema(_leaf_heavy_schema(), compile=False)
LEAF_HEAVY_COMPILED = probatio.Schema(_leaf_heavy_schema()).compile()
LEAF_HEAVY_PAYLOAD = {
    "email": "user@example.com",
    "ip": "192.168.1.1",
    "host": "example.com",
    "code": "ABC",
    "slug": "my-slug",
}


def test_validate_leaf_heavy(benchmark: Any) -> None:
    """Validate a mapping of built-in leaf validators (Email, IP, Match, ...)."""
    result = benchmark(LEAF_HEAVY, LEAF_HEAVY_PAYLOAD)
    assert result["email"] == "user@example.com"


def test_validate_leaf_heavy_compiled(benchmark: Any) -> None:
    """Validate the leaf-heavy mapping through the generated validator."""
    result = benchmark(LEAF_HEAVY_COMPILED, LEAF_HEAVY_PAYLOAD)
    assert result["email"] == "user@example.com"


def _nested_schema() -> dict[Any, Any]:
    """A nested mapping (sub-mapping and a list), fresh each call."""
    return {
        probatio.Required("entity_id"): str,
        probatio.Optional("data", default=dict): {
            probatio.Optional("brightness"): probatio.All(
                probatio.Coerce(int),
                probatio.Range(min=0, max=255),
            ),
            probatio.Optional("rgb"): [
                probatio.All(probatio.Coerce(int), probatio.Range(min=0, max=255)),
            ],
        },
    }


NESTED = probatio.Schema(_nested_schema(), compile=False)
NESTED_COMPILED = probatio.Schema(_nested_schema()).compile()
NESTED_PAYLOAD = {
    "entity_id": "light.kitchen",
    "data": {"brightness": "200", "rgb": [255, 0, 0]},
}


def test_validate_nested(benchmark: Any) -> None:
    """Validate a nested mapping (recursing into a sub-mapping and a list)."""
    result = benchmark(NESTED, NESTED_PAYLOAD)
    assert result["data"]["brightness"] == 200


def test_validate_nested_compiled(benchmark: Any) -> None:
    """Validate the nested mapping through the generated top-level validator."""
    result = benchmark(NESTED_COMPILED, NESTED_PAYLOAD)
    assert result["data"]["brightness"] == 200


# A composed schema: a pre-built Schema instance reused as a mapping value, the
# way large applications (Home Assistant among them) assemble config schemas from
# shared pieces. The nested Schema goes through the callable-wrapping path rather
# than compiling inline like a plain dict value does, so this tracks the cost of
# composition itself.
_COMPOSED_DATA = probatio.Schema(
    {
        probatio.Optional("brightness"): probatio.All(
            probatio.Coerce(int),
            probatio.Range(min=0, max=255),
        ),
    },
    compile=False,
)
COMPOSED = probatio.Schema(
    {
        probatio.Required("entity_id"): str,
        probatio.Optional("data", default=dict): _COMPOSED_DATA,
    },
    compile=False,
)
COMPOSED_PAYLOAD = {"entity_id": "light.kitchen", "data": {"brightness": "200"}}


def test_validate_composed(benchmark: Any) -> None:
    """Validate a mapping whose value is a nested, pre-built Schema instance."""
    result = benchmark(COMPOSED, COMPOSED_PAYLOAD)
    assert result["data"]["brightness"] == 200


def _combinator_auto_schema() -> probatio.Schema:
    """A combinator with a mapping branch, built and warmed under ``AUTO``.

    Under the default ``AUTO`` policy the mapping branch arms for lazy
    compilation, and the combinator captures the armed bootstrap at construction.
    Warming past the compile threshold resolves the schema onto the generated
    validator, but the combinator keeps calling through its captured (now stale)
    reference; that steady-state delegation is exactly what real applications run
    with, and what this benchmark tracks.
    """
    previous = probatio.get_compile_policy()
    probatio.set_compile_policy(probatio.CompilePolicy.AUTO)
    try:
        schema = probatio.Schema(
            probatio.Any({probatio.Required("value"): int}, str),
        )
        for _ in range(200):  # past the AUTO threshold, so the engine is steady
            schema(COMBINATOR_AUTO_PAYLOAD)
    finally:
        probatio.set_compile_policy(previous)
    return schema


COMBINATOR_AUTO_PAYLOAD = {"value": 1}
COMBINATOR_AUTO = _combinator_auto_schema()


def test_validate_combinator_auto(benchmark: Any) -> None:
    """Validate through a combinator's mapping branch under the AUTO policy."""
    result = benchmark(COMBINATOR_AUTO, COMBINATOR_AUTO_PAYLOAD)
    assert result == {"value": 1}


@probatio.probatio
def _decorated_scale(value: int, factor: int = 1, *, label: str = "x") -> int:
    """A decorated function with typed annotations (the argument hot path)."""
    del label
    return value * factor


@probatio.probatio
def _decorated_forward(a, b, c=None):  # type: ignore[no-untyped-def]
    """A decorated function with no annotations: nothing validates, only binding."""
    return (a, b, c)


def test_validate_decorated_call(benchmark: Any) -> None:
    """Call a decorated function with typed, validated arguments."""
    result = benchmark(_decorated_scale, 21, factor=2, label="y")
    assert result == 42


def test_validate_decorated_passthrough(benchmark: Any) -> None:
    """Call a decorated function with nothing to validate (pure binding cost)."""
    result = benchmark(_decorated_forward, 1, b=2)
    assert result == (1, 2, None)


def test_combinator_auto_measures_the_stale_bootstrap() -> None:
    """Guard: the AUTO benchmark really runs the captured-bootstrap delegation.

    The branch must still be the bound bootstrap (the capture is permanent) and
    its schema must have resolved onto the generated validator, so the benchmark
    measures steady-state delegation, not warmup or the interpreted engine.
    """
    branch = COMBINATOR_AUTO.schema._compiled[0]
    assert getattr(branch, "__func__", None) is probatio.Schema._bootstrap
    assert _is_compiled(branch.__self__)


@dataclass
class _Service:
    """A small dataclass, the clearest compiled win (validate and construct fused)."""

    name: str
    port: int
    enabled: bool
    weight: float


SERVICE = probatio.DataclassSchema(_Service, compile=False)
SERVICE_COMPILED = probatio.DataclassSchema(_Service).compile()
SERVICE_PAYLOAD = {"name": "service", "port": 443, "enabled": True, "weight": 1.5}


def test_validate_dataclass(benchmark: Any) -> None:
    """Validate and construct a dataclass (interpreted)."""
    result = benchmark(SERVICE, SERVICE_PAYLOAD)
    assert result.port == 443


def test_validate_dataclass_compiled(benchmark: Any) -> None:
    """Validate and construct a dataclass through the fused generated validator."""
    result = benchmark(SERVICE_COMPILED, SERVICE_PAYLOAD)
    assert result.port == 443


def test_compiled_benchmarks_use_the_generated_validator() -> None:
    """Guard: every ``*_compiled`` benchmark really measures generated code."""
    assert _is_compiled(CONFIG_COMPILED)
    assert _is_compiled(LEAF_HEAVY_COMPILED)
    assert _is_compiled(NESTED_COMPILED)
    assert _is_compiled(SERVICE_COMPILED)
    assert _is_compiled(LIST_COMPILED)


def _combinator_schema() -> dict[Any, Any]:
    """A combinator-heavy mapping (All/Any/Union nesting), fresh each call."""
    return {
        probatio.Required("mode"): probatio.Any("auto", "manual", "off"),
        probatio.Required("level"): probatio.All(
            probatio.Coerce(int), probatio.Range(min=0, max=10)
        ),
        probatio.Optional("value"): probatio.Any(
            probatio.All(str, probatio.Length(min=1)),
            probatio.All(probatio.Coerce(int), probatio.Range(min=0)),
            None,
        ),
        probatio.Optional("kind"): probatio.Union(int, str, float),
    }


def _deep_schema(depth: int) -> dict[Any, Any]:
    """A mapping nested ``depth`` levels deep, fresh each call.

    Construction cost grows with depth and tree size, so a deep schema is where
    the compile walk actually shows up; a flat schema barely exercises it.
    """
    node: dict[Any, Any] = {probatio.Required("leaf"): int}
    for _ in range(depth):
        node = {probatio.Required("value"): int, probatio.Optional("child"): node}
    return node


def test_compile_nested(benchmark: Any) -> None:
    """Build a nested schema from scratch (recursive compile over a sub-mapping)."""
    result = benchmark(lambda: probatio.Schema(_nested_schema(), compile=False))
    assert isinstance(result, probatio.Schema)


def test_compile_leaf_heavy(benchmark: Any) -> None:
    """Build a wide, many-key mapping from scratch."""
    result = benchmark(lambda: probatio.Schema(_leaf_heavy_schema(), compile=False))
    assert isinstance(result, probatio.Schema)


def test_compile_combinators(benchmark: Any) -> None:
    """Build a combinator-heavy schema (All/Any/Union nesting) from scratch."""
    result = benchmark(lambda: probatio.Schema(_combinator_schema(), compile=False))
    assert isinstance(result, probatio.Schema)


def test_compile_deep(benchmark: Any) -> None:
    """Build a deeply nested schema, where construction cost actually lives."""
    result = benchmark(lambda: probatio.Schema(_deep_schema(16), compile=False))
    assert isinstance(result, probatio.Schema)
