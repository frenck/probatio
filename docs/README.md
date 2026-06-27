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
│       ├── getting-started.md    # install + quick example
│       ├── guides/               # migrating from voluptuous, …
│       └── reference/            # API reference
```

The site is served at `https://probatio.frenck.dev` (set in `astro.config.mjs`).
