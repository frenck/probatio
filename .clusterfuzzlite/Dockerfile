# Build environment for ClusterFuzzLite. base-builder-python provides atheris,
# the libFuzzer engine, and compile_python_fuzzer. Pinned by digest for a
# reproducible, supply-chain-safe build; Renovate keeps it current.
FROM gcr.io/oss-fuzz-base/base-builder-python:latest@sha256:66c3a78c912a076695da349f2c0f21538be76bdfcba5d73603be45e39066cd38

# Probatio is pure Python with no native extension, so nothing is compiled here;
# build.sh installs the package and compiles each atheris harness.
COPY . $SRC/probatio
WORKDIR $SRC/probatio
COPY .clusterfuzzlite/build.sh $SRC/build.sh
