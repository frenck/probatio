# Build environment for ClusterFuzzLite. base-builder-python provides atheris,
# the libFuzzer engine, and compile_python_fuzzer. Pinned by digest for a
# reproducible, supply-chain-safe build; Renovate keeps it current.
FROM gcr.io/oss-fuzz-base/base-builder-python:latest@sha256:6b2b3a7e4a2da50de47f94925cffbe34747e1aae4f33d7f07ba6c681dd648b23

# Probatio is pure Python with no native extension, so nothing is compiled here;
# build.sh installs the package and compiles each atheris harness.
COPY . $SRC/probatio
WORKDIR $SRC/probatio
COPY .clusterfuzzlite/build.sh $SRC/build.sh
