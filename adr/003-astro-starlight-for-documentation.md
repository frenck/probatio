# ADR-003: Astro Starlight for documentation

**Date**: 2026-06-24
**Status**: Accepted

**Context**: Documentation is a first-class concern. We need a modern,
beginner-friendly docs site.

**Options considered**:

1. Astro Starlight, a documentation framework built on Astro.
2. MkDocs Material, a Python-native static site generator.
3. Sphinx, the long-standing Python documentation toolchain.
4. Plain Markdown rendered on GitHub, no site build at all.

**Decision**: Use Astro Starlight.

**Rationale**:

- Modern defaults and fast builds, with no theme to assemble first.
- Built-in search, navigation, and dark mode.
- MDX support for interactive examples.
- Easy to maintain alongside the code.
- Used by many popular open source projects.
- MkDocs Material and Sphinx are both capable and Python-native, which would
  have kept the toolchain in one language. We chose Starlight for the
  out-of-the-box result and the MDX authoring experience over staying in the
  Python ecosystem for docs.
- Plain Markdown on GitHub needs no build at all, but gives up search,
  navigation, versioning, and a real landing page. For a library whose adoption
  leans on a clear getting-started path and a migration guide, that is too thin.

**Consequences**:

- The docs site uses Node tooling, which lives under `docs/` (its own
  `package.json`, lockfile, and Node version pin) and stays out of the Python
  package. The two toolchains are kept separate on purpose.
- The site has a build step. It is not the plain-Markdown "just read the files
  on GitHub" path, so publishing the docs means building and deploying the
  Astro site, not only committing Markdown.
