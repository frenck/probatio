---
title: Validating API requests
description: Validate a request body with a schema and turn failures into a JSON 400 with per-field errors.
---

A request body is untrusted input. Validate it at the boundary, and when it
fails, answer with a 400 that names every offending field, not just the first
one. Probatio collects all failures in one pass and exposes them as structured
data, so the error response is a small dict comprehension away. This recipe
builds that flow with plain Python first, then shows where it plugs into a
framework.

## The request schema

A realistic signup payload: a username with length bounds, an email, a minimum
age, an optional newsletter flag with a default, a nested address, and a list
of tags:

```python
from probatio import Schema, Required, Optional, All, Length, Range, Email

signup = Schema(
    {
        Required("username"): All(str, Length(min=3, max=30)),
        Required("email"): Email(),
        Required("age"): All(int, Range(min=13)),
        Optional("newsletter", default=False): bool,
        Required("address"): {
            Required("city"): str,
            Required("postal_code"): str,
        },
        Optional("tags", default=list): [str],
    }
)
```

A valid body comes back normalized, with the defaults filled in:

```python
body = {
    "username": "ada",
    "email": "ada@example.com",
    "age": 37,
    "address": {"city": "Delft", "postal_code": "2611"},
}
signup(body)
# {'username': 'ada', 'email': 'ada@example.com', 'age': 37, 'address': {'city': 'Delft', 'postal_code': '2611'}, 'newsletter': False, 'tags': []}
```

## Validate or 400

An invalid body raises `MultipleInvalid`, whose `errors` list holds one
`Invalid` per problem. Each carries `path` (the keys to the offending value)
and `error_message` (the bare message, no path). That is everything a JSON
error response needs:

```python
from probatio import MultipleInvalid


def error_response(err):
    """Build the JSON body of a 400 from a MultipleInvalid."""
    return {
        "error": "validation_failed",
        "details": [
            {"field": ".".join(str(seg) for seg in e.path), "message": e.error_message}
            for e in err.errors
        ],
    }


bad = {
    "username": "ab",
    "email": "not-an-email",
    "age": 37,
    "address": {"city": "Delft"},
}

try:
    signup(bad)
except MultipleInvalid as err:
    print(error_response(err))
    # {'error': 'validation_failed', 'details': [{'field': 'username', 'message': 'length of value must be at least 3'}, {'field': 'email', 'message': 'expected an email address'}, {'field': 'address.postal_code', 'message': 'required key not provided'}]}
```

Three problems, three entries, and the nested one reads as
`address.postal_code`. The client can highlight each field.

For a machine-readable contract, each error also offers `as_dict()`, the whole
structured layer in one serializable dict: a stable `code`, the `path` as a
list, and localization slots:

```python
try:
    signup(bad)
except MultipleInvalid as err:
    print(err.errors[0].as_dict())
    # {'code': 'length', 'message': 'length of value must be at least 3', 'path': ['username'], 'secret': False, 'context': {}, 'translation_key': 'length_min', 'placeholders': {'min': 3}}
```

Prefer `as_dict()` when clients branch on the failure kind or translate
messages; the hand-built shape above is fine when they only display them.

## Plugging into a framework

The flow is the same everywhere: parse JSON, call the schema, catch
`MultipleInvalid`, return 400. In Flask:

<!-- verify: skip -->

```python
from flask import Flask, jsonify, request
from probatio import MultipleInvalid

app = Flask(__name__)


@app.post("/signup")
def create_signup():
    try:
        data = signup(request.get_json())
    except MultipleInvalid as err:
        return jsonify(error_response(err)), 400
    user = create_user(data)  # your application logic, on clean data
    return jsonify(user), 201
```

FastAPI users can do the same inside a route taking a `dict` body, or raise
`HTTPException(status_code=400, detail=error_response(err))`.

## Where to next

- [Error handling](/guides/error-handling/): paths, `MultipleInvalid`, and the
  structured layer behind `as_dict()`.
- [JSON Schema](/guides/json-schema/): publish the same schema to clients as
  JSON Schema with `to_json_schema`.
- [Dict schemas and markers](/guides/dict-schemas-and-markers/): required and
  optional keys, defaults, and the extra-key policy.
