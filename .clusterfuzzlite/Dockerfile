# Build environment for ClusterFuzzLite. base-builder-python provides atheris,
# the libFuzzer engine, and compile_python_fuzzer. Pinned by digest for a
# reproducible, supply-chain-safe build; Renovate keeps it current.
FROM gcr.io/oss-fuzz-base/base-builder-python:latest@sha256:171eebccc7906dc0b1d944aa716587f45db79cdb2d75d6287947860ba16b66b7

# Probatio is pure Python with no native extension, so nothing is compiled here;
# build.sh installs the package and compiles each atheris harness.
COPY . $SRC/probatio
WORKDIR $SRC/probatio
COPY .clusterfuzzlite/build.sh $SRC/build.sh
