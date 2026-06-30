"""Atheris harness: fuzz the ReDoS guard.

``is_catastrophic`` decides whether an untrusted regular-expression ``pattern``
(from a JSON Schema) backtracks catastrophically, so it is itself a piece of
untrusted-input handling. It must always return a ``bool`` without raising, and
it must not hang on a crafted pattern (a self-inflicted denial of service). A
libFuzzer timeout surfaces a hang; this harness surfaces any leaked exception or
a non-boolean result.

Run locally (needs the ``atheris`` package):
    python fuzz/fuzz_is_catastrophic.py
"""

import sys

import atheris

with atheris.instrument_imports():
    from probatio.codecs._regex_safety import is_catastrophic


def TestOneInput(data: bytes) -> None:  # noqa: N802 (atheris entry point)
    """Run the guard over a fuzzed pattern; it must return a bool, fast, no raise."""
    fdp = atheris.FuzzedDataProvider(data)
    pattern = fdp.ConsumeUnicodeNoSurrogates(256)

    result = is_catastrophic(pattern)

    if not isinstance(result, bool):  # pragma: no cover - a contract violation
        msg = f"is_catastrophic returned {type(result).__name__}, not bool"
        raise TypeError(msg)


def main() -> None:
    """Set up and run the fuzzer."""
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
