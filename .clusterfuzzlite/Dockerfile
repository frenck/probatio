# Build environment for ClusterFuzzLite. base-builder-python provides atheris,
# the libFuzzer engine, and compile_python_fuzzer. Pinned by digest for a
# reproducible, supply-chain-safe build; Renovate keeps it current.
FROM gcr.io/oss-fuzz-base/base-builder-python:latest@sha256:3b846e1f290ce8c05608f497ec14ffce8f5f84972fd5ad026fd8bff76df17d56

# Probatio is pure Python with no native extension, so nothing is compiled here;
# build.sh installs the package and compiles each atheris harness.
COPY . $SRC/probatio
WORKDIR $SRC/probatio
COPY .clusterfuzzlite/build.sh $SRC/build.sh
