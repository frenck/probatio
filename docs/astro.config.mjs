// @ts-check
import { defineConfig } from "astro/config";
import { unified } from "@astrojs/markdown-remark";
import starlight from "@astrojs/starlight";
import starlightLlmsTxt from "starlight-llms-txt";

import rehypeProbatio from "./src/plugins/rehype-probatio.mjs";

// https://astro.build/config
export default defineConfig({
  site: "https://probatio.frenck.dev",
  // The combined "JSON Schema and OpenAPI" guide was split into three pages.
  redirects: {
    "/guides/json-schema-and-openapi/": "/guides/json-schema/",
  },
  markdown: {
    processor: unified({ rehypePlugins: [rehypeProbatio] }),
  },
  integrations: [
    starlight({
      title: "Probatio",
      description: "A modern Python data validation library.",
      plugins: [
        // Generate /llms.txt, /llms-full.txt, and /llms-small.txt from the docs,
        // so an LLM implementing against Probatio can read the whole manual in one
        // fetch instead of crawling pages. https://llmstxt.org
        starlightLlmsTxt({
          projectName: "Probatio",
          description:
            "A modern, maintained Python data validation library, and a drop-in " +
            "replacement for voluptuous.",
          details: [
            "Probatio validates arbitrary Python data against a schema that is " +
              "itself data: plain types, dicts, lists, and callables. It is a " +
              "clean-room reimplementation of voluptuous with the same public API, " +
              "so changing `import voluptuous` to `import probatio` keeps existing " +
              "schemas working, and it is pure Python with no native extension.",
            "Beyond voluptuous it adds schemas built from your own dataclasses and " +
              "TypedDicts (with statically typed results), JSON Schema, OpenAPI, and " +
              "field-list codecs, a structured error model with stable translation " +
              "keys, and an opt-in compiled engine.",
            "Everything public is importable straight from the `probatio` package.",
          ].join("\n\n"),
          // Topic-split files, so an LLM can fetch just the part it needs: the
          // how-to guides, the task recipes, or the API reference, instead of the
          // whole manual.
          customSets: [
            {
              label: "Guides",
              description:
                "How-to walkthroughs: the validation model, dict and sequence " +
                "schemas, combinators, the built-in validators, error handling, " +
                "custom validators, the probatio decorator, recursive, compiled, " +
                "and lazy schemas, dataclass and TypedDict schemas, and the JSON " +
                "Schema, OpenAPI, and field-list codecs.",
              paths: ["guides/**"],
            },
            {
              label: "Recipes",
              description:
                "End-to-end task recipes: validating Home Assistant config, a " +
                "config file, and web API requests, LLM tool calling and MCP, and " +
                "a cookbook of smaller patterns.",
              paths: ["recipes/**"],
            },
            {
              label: "API reference",
              description:
                "Reference material: the API surface, built-ins by role, the error " +
                "classes and their translation keys, voluptuous compatibility, " +
                "typing, and performance.",
              paths: ["reference/**"],
            },
            {
              label: "Project",
              description:
                "About the project: why it exists, the architecture, the security " +
                "model, the comparison to alternatives, who uses it, the stability " +
                "and 1.0 policy, credits, and the license.",
              paths: ["project/**"],
            },
          ],
          // The small variant targets tight context windows: drop the project and
          // meta pages that do not help someone write code against the API.
          exclude: [
            "project/about",
            "project/credits",
            "project/license",
            "project/projects",
          ],
        }),
      ],
      head: [
        {
          tag: "meta",
          attrs: {
            property: "og:image",
            content: "https://probatio.frenck.dev/social.png",
          },
        },
        {
          tag: "meta",
          attrs: {
            property: "og:image:width",
            content: "640",
          },
        },
        {
          tag: "meta",
          attrs: {
            property: "og:image:height",
            content: "320",
          },
        },
        {
          tag: "meta",
          attrs: {
            property: "og:image:alt",
            content: "Probatio - A modern Python data validation library.",
          },
        },
        {
          tag: "meta",
          attrs: {
            name: "twitter:image",
            content: "https://probatio.frenck.dev/social.png",
          },
        },
        {
          tag: "meta",
          attrs: {
            name: "twitter:image:alt",
            content: "Probatio - A modern Python data validation library.",
          },
        },
      ],
      customCss: ["@fontsource-variable/inter", "./src/styles/custom.css"],
      editLink: {
        baseUrl: "https://github.com/frenck/probatio/edit/main/docs/",
      },
      components: {
        Footer: "./src/components/Footer.astro",
      },
      social: [
        {
          icon: "github",
          label: "GitHub",
          href: "https://github.com/frenck/probatio",
        },
      ],
      sidebar: [
        {
          label: "Getting started",
          items: [
            { label: "Introduction", slug: "index" },
            { label: "Installation", slug: "getting-started/installation" },
            { label: "Quick start", slug: "getting-started/quick-start" },
            {
              label: "Migrating from voluptuous",
              slug: "getting-started/migrating-from-voluptuous",
            },
            { label: "Compatibility", slug: "getting-started/compatibility" },
          ],
        },
        {
          label: "Guides",
          items: [
            { label: "The validation model", slug: "guides/validation-model" },
            {
              label: "Dict schemas and markers",
              slug: "guides/dict-schemas-and-markers",
            },
            { label: "Sequence schemas", slug: "guides/sequence-schemas" },
            { label: "Combinators", slug: "guides/combinators" },
            { label: "Built-in validators", slug: "guides/validators" },
            { label: "Error handling", slug: "guides/error-handling" },
            {
              label: "Custom error messages",
              slug: "guides/custom-error-messages",
            },
            {
              label: "Loading and dumping",
              slug: "guides/loading-and-dumping",
            },
            { label: "Custom validators", slug: "guides/custom-validators" },
            {
              label: "The probatio decorator",
              slug: "guides/probatio-decorator",
            },
            { label: "Recursive schemas", slug: "guides/recursive-schemas" },
            { label: "Compiled schemas", slug: "guides/compiled-schemas" },
            { label: "Lazy building", slug: "guides/lazy-building" },
            { label: "Schemas from dataclasses", slug: "guides/dataclasses" },
            { label: "Schemas from TypedDicts", slug: "guides/typeddict" },
            { label: "JSON Schema", slug: "guides/json-schema" },
            { label: "OpenAPI", slug: "guides/openapi" },
            { label: "Field lists", slug: "guides/field-lists" },
            {
              label: "Testing with pytest-probatio",
              slug: "guides/testing-with-pytest",
            },
            { label: "Troubleshooting", slug: "guides/troubleshooting" },
          ],
        },
        {
          label: "Recipes",
          items: [
            { label: "Home Assistant", slug: "recipes/home-assistant" },
            { label: "Validating a config file", slug: "recipes/config-file" },
            { label: "Validating API requests", slug: "recipes/web-api" },
            { label: "LLM tool calling and MCP", slug: "recipes/llm-tools" },
            { label: "Cookbook", slug: "recipes/cookbook" },
          ],
        },
        {
          label: "Reference",
          items: [
            { label: "API reference", slug: "reference" },
            { label: "Built-ins by role", slug: "reference/builtins-by-role" },
            { label: "Errors", slug: "reference/errors" },
            {
              label: "Translation keys",
              slug: "reference/translation-keys",
            },
            {
              label: "voluptuous compatibility",
              slug: "reference/compatibility-matrix",
            },
            { label: "Typing", slug: "reference/typing" },
            { label: "Performance", slug: "reference/performance" },
          ],
        },
        {
          label: "Project",
          items: [
            { label: "About", slug: "project/about" },
            { label: "Architecture", slug: "project/architecture" },
            { label: "Security", slug: "project/security" },
            { label: "Comparison to alternatives", slug: "project/comparison" },
            { label: "Projects using Probatio", slug: "project/projects" },
            { label: "Stability and roadmap", slug: "project/roadmap" },
            { label: "Credits", slug: "project/credits" },
            { label: "License", slug: "project/license" },
          ],
        },
      ],
    }),
  ],
});
