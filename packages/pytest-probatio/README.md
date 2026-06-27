# pytest-probatio

Use a [probatio](https://github.com/frenck/probatio) schema as a pytest assertion
matcher. A schema reads as the expected shape, and a mismatch is explained by
probatio's path-precise errors instead of a bare `assert`.

```python
from pytest_probatio import S, Partial, Exact
from probatio import Port


def test_response(response):
    # Strict: extra keys make it unequal.
    assert response == S({"name": str, "port": Port()})

    # Partial: extra keys are allowed.
    assert response == Partial({"name": str})
    assert S({"name": str}) <= response
```

When the data does not match, the failure lists each error by its path:

```
data does not match the probatio schema (==):
  data['port']: expected int
```

Install it alongside pytest; the plugin registers itself:

```bash
pip install pytest-probatio
```

This package lives in the probatio monorepo but ships separately, so the core
`probatio` library stays dependency-free.
