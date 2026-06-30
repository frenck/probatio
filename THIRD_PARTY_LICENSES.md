# Third-party licenses

Probatio has no third-party runtime dependencies. It is pure Python and uses
only the standard library at runtime, so no third-party code is bundled in the
wheel and there are no third-party licenses to reproduce here. The release
workflow also generates a CycloneDX SBOM and attaches it to each build, so this
claim is verifiable from the published artifact, not just asserted.

Optional integrations are used only when you install them yourself, and they
ship under their own licenses, not with probatio:

- [orjson](https://github.com/ijl/orjson) for fast JSON loading.
  License: `MPL-2.0 AND (Apache-2.0 OR MIT)`.
- [YAMLRocks](https://github.com/frenck/yamlrocks) (MIT) or
  [PyYAML](https://pyyaml.org) (MIT) for YAML loading.
- [tomli-w](https://github.com/hukkin/tomli-w) for writing TOML. License: MIT.

Development and test tooling (pytest, ruff, mypy, ty, and voluptuous as a
test-only conformance oracle) is not distributed with the package.
