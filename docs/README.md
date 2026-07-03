# probatio documentation

The probatio documentation site, built with [Astro
Starlight](https://starlight.astro.build/).

## Local development

```bash
cd docs
npm install
npm run dev      # serve at http://localhost:4321
npm run build    # build static site to ./dist
```

## Structure

```
docs/
├── astro.config.mjs              # site + sidebar configuration
├── src/
│   ├── content.config.ts         # Starlight content collection
│   └── content/docs/
│       ├── index.mdx             # landing page
│       ├── getting-started/      # install, quick start, migrating from voluptuous
│       ├── guides/               # dict schemas, combinators, codecs, …
│       ├── recipes/              # Home Assistant, config files, APIs, LLM tools, …
│       ├── reference/            # API reference, errors, typing, performance
│       └── project/              # architecture, roadmap, security, credits
```

The site is served at `https://probatio.frenck.dev` (set in `astro.config.mjs`).

## Verified examples

Every Python block in the pages is executed by `verify_examples.py`, and the
output comments are checked against what the code really produces. Run it from
the repository root when you change a page with code on it:

```bash
uv run --no-sync just examples
```
