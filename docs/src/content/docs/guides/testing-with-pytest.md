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

A schema is data, so define the expected shape once and assert it across as many
tests as you like. This is where the matcher earns its keep: one schema, many
tests, and each failure still points at the offending field. A `Schema` you
already use elsewhere (a production config or response schema) works as the
matcher just as well as a fresh one.

<!-- verify: skip -->

```python
from pytest_probatio import Exact, Partial
from probatio import Schema, Email, Range

# The shape of a user, defined once and shared by every test below.
USER = Schema(
    {
        "id": Range(min=1),
        "name": str,
        "email": Email(),
    }
)


def test_create_user_returns_the_created_user(api):
    response = api.post("/users", json={"name": "Ada", "email": "ada@example.com"})
    assert response.status_code == 201
    assert response.json() == Exact(USER)


def test_get_user_returns_the_user(api):
    assert api.get("/users/1").json() == Exact(USER)


def test_user_list_wraps_users_in_a_page(api):
    # The same USER schema, composed into a larger shape.
    page = Exact({"users": [USER], "total": Range(min=0)})
    assert api.get("/users").json() == page


def test_user_detail_may_carry_extra_fields(api):
    # Partial: the response must contain a valid user; extra fields are allowed.
    assert api.get("/users/1?expand=true").json() == Partial(USER)
```

Here `api` is your application's test client, an ordinary pytest fixture you
provide (a `fixture` that returns the schema works the same way, if you would
rather inject the schema than import a module-level constant). When a response is
wrong, the failure names the exact field, even inside the composed list:

```text
data does not match the probatio schema (==):
  data['users'][0]['email']: expected an email address
```

## Why a separate package

The core `probatio` library has no required dependencies. A pytest plugin needs
pytest and registers a plugin entry point, which is a test-framework concern, so
it lives in its own distribution. It shares probatio's repository, so the two are
developed and released together.
