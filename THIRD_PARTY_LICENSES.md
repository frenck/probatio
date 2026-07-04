# Third-party licenses

Probatio has no third-party runtime dependencies. It is pure Python and uses
only the standard library at runtime, so no third-party code is bundled in the
wheel and there are no third-party licenses to reproduce here. The release
workflow also generates a CycloneDX SBOM and attaches it to each build, so this
claim is verifiable from the published artifact, not just asserted.

Probatio validates parsed Python objects; parsing and serialization stay with
the caller. Any JSON, YAML, or TOML library you pair with it is installed by you
and ships under its own license, not with Probatio.

Development and test tooling (pytest, ruff, mypy, ty, and voluptuous as a
test-only conformance oracle) is not distributed with the package.
