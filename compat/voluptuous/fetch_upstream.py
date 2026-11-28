"""Fetch voluptuous's own test suite, at the version Probatio targets.

The file is voluptuous's BSD-licensed ``tests.py``. It is downloaded next to the
conftest and git-ignored, not vendored. Both the commit it comes from and its
SHA-256 are pinned here, so what a green run means cannot change unnoticed:
bumping the version is an edit to this file and a fresh look at the known
divergences in ``conftest.py``.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

# The commit behind the 0.16.0 tag. A tag can be moved, a commit cannot.
_COMMIT = "87825d6dbdab8830fcc6d559ecb3b88bdf68af6d"
_SHA256 = "88972c9324a124159d9f4c8d52674d702cf10be6ebf2580411867145ef68d34c"

_URL = (
    "https://raw.githubusercontent.com/alecthomas/voluptuous/"
    f"{_COMMIT}/voluptuous/tests/tests.py"
)
_TARGET = Path(__file__).parent / "tests.py"


def main() -> str | None:
    """Download the suite, and refuse it when it is not the pinned file.

    Returns the reason for a refusal, which ``sys.exit`` reports as a failure.
    """
    with urllib.request.urlopen(_URL, timeout=30) as response:  # noqa: S310
        content = response.read()

    digest = hashlib.sha256(content).hexdigest()
    if digest != _SHA256:
        return f"{_URL}\nhas SHA-256 {digest}, expected {_SHA256}."

    _TARGET.write_bytes(content)
    return None


if __name__ == "__main__":
    sys.exit(main())
