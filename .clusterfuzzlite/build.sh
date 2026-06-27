#!/bin/bash -eu
# Install probatio and compile every atheris harness to a libFuzzer binary in
# $OUT, as ClusterFuzzLite/OSS-Fuzz expect. base-builder-python supplies atheris
# and compile_python_fuzzer.
cd "$SRC/probatio"

# Install the optional I/O backends too, so the serde loaders fuzz against the
# real orjson/YAMLRocks/PyYAML/tomli-w parsers rather than the bare fallbacks.
pip3 install ".[fast,yaml,toml]"

for harness in fuzz/fuzz_*.py; do
  compile_python_fuzzer "$harness"
done
