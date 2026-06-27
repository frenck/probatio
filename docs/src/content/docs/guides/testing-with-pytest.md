---
title: Testing with pytest-probatio
description: Use a probatio schema as a pytest assertion matcher, with path-precise failures.
---

`pytest-probatio` is a small companion package that lets a probatio schema stand
in as a pytest assertion matcher. A schema reads as the expected shape, and a
mismatch is explained by probatio's path-precise errors instead of a bare
`assert`. It is handy for asserting the shape of API responses and other
structured data in tests.

It ships as a separate distribution, so the core library stays dependency-free,
and it is released lock-step with probatio at the same version.

## Installation

```bash
pip install pytest-probatio
```

The plugin registers itself with pytest; no configuration is needed.

## Matchers

Two matchers are exposed. The schema goes on one side of the comparison and the
data on the other:

<!-- verify: skip -->

```python
from pytest_probatio import Exact, Partial
from probatio import Port


def test_response(response):
    # Exact: an extra key makes it unequal.
    assert response == Exact({"name": str, "port": Port()})

    # Partial: extra keys are allowed under ==.
    assert response == Partial({"name": str})

    # The <= operator relaxes Exact to a partial match too.
    assert Exact({"name": str}) <= response
```

The right-hand schema may be any probatio schema: a type, a validator, a nested
dict, markers, and so on. With `Exact`, `==` requires no extra keys and `<=`
allows them; `Partial` allows extra keys under `==`.

## Readable failures

When the data does not match, pytest's assertion rewriting prints each error by
its path through the data, using probatio's errors:

```text
data does not match the probatio schema (==):
  data['port']: expected int
```

So a failing `assert response == Exact(...)` points at the exact offending value
rather than just reporting that the two are not equal.

## Reuse a schema across tests

A schema is data, so define the expected shape once and reuse it like any other
constant. Keep the plain schema (a dict, a `Schema`, a validator) at module level
and wrap it in `Exact` or `Partial` at each assertion, which also lets the same
shape compose into larger ones:

<!-- verify: skip -->

```python
from pytest_probatio import Exact
from probatio import Email

USER = {"id": int, "name": str, "email": Email()}


def test_create_user():
    assert create_user("ada@example.com") == Exact(USER)


def test_get_user():
    assert get_user(1) == Exact(USER)


def test_list_users():
    # The same shape, composed into a bigger one.
    assert list_users() == Exact({"users": [USER], "total": int})
```

The shape can also be a pre-built `Schema`, so a schema you already use elsewhere
(a production config schema, say) doubles as a test matcher. `Exact` and `Partial`
still control whether extra keys are allowed:

<!-- verify: skip -->

```python
from pytest_probatio import Exact, Partial
from probatio import Schema

USER = Schema({"id": int, "name": str})

assert get_user(1) == Exact(USER)  # no extra keys
assert get_user(1) == Partial(USER)  # extra keys allowed
```

A pytest fixture that returns the schema works too, if you would rather inject it
than import a module-level constant.

## Why a separate package

The core `probatio` library has no required dependencies. A pytest plugin needs
pytest and registers a plugin entry point, which is a test-framework concern, so
it lives in its own distribution. It shares probatio's repository, so the two are
developed and released together.
