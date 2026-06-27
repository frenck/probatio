"""Atheris harness: fuzz the serde loaders on untrusted bytes.

``load_json``, ``load_yaml``, and ``load_toml`` parse untrusted input. A
malformed document must surface as the backend's own parse error (a ``ValueError``
subclass for JSON and TOML, the parser's error for YAML), or a ``RecursionError``
on pathologically nested input, not an unexpected crash. This harness feeds fuzzed
bytes at each loader and treats any other escaping exception as a bug.

Run locally (needs the ``atheris`` package):
    python fuzz/fuzz_serde.py
"""

import sys

import atheris

with atheris.instrument_imports():
    from probatio import load_json, load_toml, load_yaml

# Parse errors are expected. YAML's parser raises its own exception type, which is
# not always a ValueError, so it is allowed explicitly when a parser is installed.
_ACCEPTABLE: tuple[type[BaseException], ...] = (ValueError, RecursionError)
try:
    import yaml

    _ACCEPTABLE = (*_ACCEPTABLE, yaml.YAMLError)
except ImportError:  # pragma: no cover - PyYAML is a dev dependency
    pass


def TestOneInput(data: bytes) -> None:  # noqa: N802 (atheris entry point)
    """Parse fuzzed bytes through each loader; only a parse error may escape."""
    for loader in (load_json, load_yaml, load_toml):
        try:
            loader(data)
        except _ACCEPTABLE:
            pass


def main() -> None:
    """Set up and run the fuzzer."""
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
