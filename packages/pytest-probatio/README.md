# pytest-probatio

Use a [probatio](https://github.com/frenck/probatio) schema as a pytest assertion
matcher. A schema reads as the expected shape, and a mismatch is explained by
probatio's path-precise errors instead of a bare `assert`.

```python
from pytest_probatio import Exact, Partial
from probatio import Port


def test_response(response):
    # Exact: extra keys make it unequal.
    assert response == Exact({"name": str, "port": Port()})

    # Partial: extra keys are allowed.
    assert response == Partial({"name": str})
    assert Exact({"name": str}) <= response
```

When the data does not match, the failure lists each error by its path:

```
data does not match the probatio schema (==):
  port: expected a port number between 1 and 65535
```

Install it alongside pytest; the plugin registers itself:

```bash
pip install pytest-probatio
```

This package lives in the probatio monorepo but ships separately, so the core
`probatio` library stays dependency-free.

The full guide, including schema reuse across tests and the `raises` helper,
lives at
[probatio.frenck.dev](https://probatio.frenck.dev/guides/testing-with-pytest/).
