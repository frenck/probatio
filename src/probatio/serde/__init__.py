"""Serialize and deserialize data: load and dump JSON, YAML, and TOML.

``loaders`` parses text into Python values (and ``Schema.load*`` validates in one
step); ``dumpers`` serializes a validated value back out. Both pick the fastest
installed backend, detected once in ``_optional``. The public functions are also
re-exported from the top-level ``probatio`` namespace.
"""

from probatio.serde._config import (
    clear_default_options,
    default_options,
    set_default_options,
)
from probatio.serde.dumpers import dump, dump_json, dump_toml, dump_yaml
from probatio.serde.loaders import (
    load,
    load_json,
    load_toml,
    load_yaml,
    load_yaml_with_locations,
)

__all__ = [
    "clear_default_options",
    "default_options",
    "dump",
    "dump_json",
    "dump_toml",
    "dump_yaml",
    "load",
    "load_json",
    "load_toml",
    "load_yaml",
    "load_yaml_with_locations",
    "set_default_options",
]
