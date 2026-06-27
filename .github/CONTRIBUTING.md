# Contributing

When contributing to this repository, please first discuss the change you wish
to make via issue, email, or any other method with the owners of this repository
before making a change.

Please note we have a [code of conduct][code-of-conduct]; please follow it in all
your interactions with the project.

AI tools are welcome as an aid, but you are responsible for everything you
submit: review and understand it before opening a pull request. Autonomous agents
are not allowed, and unreviewed AI output will be closed. Read the
[AI Policy][ai-policy] before contributing.

## Issues and feature requests

You've found a bug in the source code, a mistake in the documentation or maybe
you'd like a new feature? You can help us by submitting an issue to our
[GitHub Repository][github]. Before you create an issue, make sure you search
the archive, maybe your question was already answered.

Found a security vulnerability? Do not open a public issue; follow the
[security policy][security] instead.

Even better: You could submit a pull request with a fix or new feature!

## Setting up your environment

This is a pure-Python project managed with [uv][uv] and a [just][just] task
runner. To get started:

```shell
uv sync
```

Common tasks are wrapped in `just`. Run `just` to see what is available. Before
opening a pull request, make sure the checks pass:

```shell
uv run --no-sync just test
uv run --no-sync just lint
uv run --no-sync just typecheck
```

Or run the full gate at once:

```shell
uv run --no-sync just check
```

## Pull request process

1. Search our repository for open or closed [pull requests][prs] that relate
   to your submission. You don't want to duplicate effort.

1. Make sure tests cover your change and the full check suite passes locally. A
   pull request cannot be merged unless CI is green.

1. You may merge the pull request once you have the sign-off of another
   developer, or if you do not have permission to do that, you may request the
   reviewer to merge it for you.

[ai-policy]: https://github.com/frenck/probatio/blob/main/AI_POLICY.md
[code-of-conduct]: https://github.com/frenck/probatio/blob/main/.github/CODE_OF_CONDUCT.md
[github]: https://github.com/frenck/probatio/issues
[just]: https://github.com/casey/just
[prs]: https://github.com/frenck/probatio/pulls
[security]: https://github.com/frenck/probatio/blob/main/.github/SECURITY.md
[uv]: https://github.com/astral-sh/uv
