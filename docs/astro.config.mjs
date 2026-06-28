// @ts-check
import { defineConfig } from "astro/config";
import { unified } from "@astrojs/markdown-remark";
import starlight from "@astrojs/starlight";

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
            { label: "Combinators", slug: "guides/combinators" },
            { label: "Built-in validators", slug: "guides/validators" },
            { label: "Error handling", slug: "guides/error-handling" },
            { label: "Loading and dumping", slug: "guides/loading-and-dumping" },
            { label: "Custom validators", slug: "guides/custom-validators" },
            { label: "Recursive schemas", slug: "guides/recursive-schemas" },
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
            { label: "Cookbook", slug: "recipes/cookbook" },
          ],
        },
        {
          label: "Reference",
          items: [
            { label: "API reference", slug: "reference" },
            { label: "Errors", slug: "reference/errors" },
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
