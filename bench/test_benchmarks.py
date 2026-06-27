"""CodSpeed benchmarks for probatio's validation hot paths.

Run with: ``uv run --no-sync pytest bench --codspeed``. These are tracked per-PR
by CodSpeed so a performance regression shows up in review. They are not part of
the normal test run (testpaths is ``tests``).
"""

from __future__ import annotations

from typing import Any

import probatio


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


CONFIG = probatio.Schema(_config_schema())
CONFIG_PAYLOAD = {
    "name": "service",
    "port": "443",
    "host": "example.com",
    "tags": ["a", "b", "c"],
    "mode": "auto",
}


def test_validate_config(benchmark: Any) -> None:
    """Validate a configuration-style payload."""
    result = benchmark(CONFIG, CONFIG_PAYLOAD)
    # Assert the work actually happened (port coerced to int), so a benchmark
    # cannot look faster by quietly skipping validation.
    assert result["port"] == 443


def test_compile_config(benchmark: Any) -> None:
    """Compile the full configuration schema from scratch."""
    result = benchmark(lambda: probatio.Schema(_config_schema()))
    assert isinstance(result, probatio.Schema)


def test_validate_list(benchmark: Any) -> None:
    """Validate a list of coerced, range-checked numbers (single-element schema)."""
    schema = probatio.Schema(
        [probatio.All(probatio.Coerce(int), probatio.Range(min=0))]
    )
    payload = [str(value) for value in range(50)]
    result = benchmark(schema, payload)
    assert result == list(range(50))


def test_validate_any_miss(benchmark: Any) -> None:
    """Reject a value against an Any whose branches all fail (the deepest-error path)."""
    schema = probatio.Schema(probatio.Any(int, float, str))

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


LEAF_HEAVY = probatio.Schema(
    {
        probatio.Required("email"): probatio.Email(),
        probatio.Required("ip"): probatio.IPv4Address(),
        probatio.Required("host"): probatio.Hostname(),
        probatio.Required("code"): probatio.Match(r"^[A-Z]{3}$"),
        probatio.Required("slug"): probatio.Slug(),
    },
)
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


NESTED = probatio.Schema(
    {
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
    },
)
NESTED_PAYLOAD = {
    "entity_id": "light.kitchen",
    "data": {"brightness": "200", "rgb": [255, 0, 0]},
}


def test_validate_nested(benchmark: Any) -> None:
    """Validate a nested mapping (recursing into a sub-mapping and a list)."""
    result = benchmark(NESTED, NESTED_PAYLOAD)
    assert result["data"]["brightness"] == 200
