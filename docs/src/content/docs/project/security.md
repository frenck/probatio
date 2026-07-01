---
title: Security
description: Probatio's safety model for validating untrusted data and schemas.
---

Probatio sits at the edge of a program: it validates data that came from
somewhere you do not control. That data is often hostile, and through
`from_json_schema` even the _schema_ can be hostile. This page is honest about
what Probatio defends against, how, and where the responsibility stays with you.

## Threat model

The thing Probatio touches most is untrusted data. A developer writes a schema,
Probatio validates incoming values against it. That direction is safe: a schema
is plain Python the developer wrote, and validating data against it does not
expose any code-execution surface. Probatio does not `eval`, `exec`, `pickle`,
or `marshal` the values it validates. There is no path where validating data
runs attacker code.

The harder case is `from_json_schema` (and `from_openapi`). There the schema
itself is decoded from an untrusted document. That widens the attack surface,
because now both the data and the rules describing it are attacker-controlled.

An attacker against this surface is not after code execution; there is none to
get. The realistic goals are denial of service: burn CPU until the process is
useless, or exhaust the stack and crash the interpreter. Probatio's safeguards
target exactly those two outcomes.

:::note
"Untrusted schema" means a JSON Schema or OpenAPI document you decode with
`from_json_schema` or `from_openapi`. A schema you write in Python is trusted
code, the same as the rest of your program.
:::

## Threats and mitigations

| Threat                                    | Vector                                                       | Mitigation                                                                                      |
| ----------------------------------------- | ------------------------------------------------------------ | ----------------------------------------------------------------------------------------------- |
| Catastrophic backtracking (ReDoS)         | A `pattern` in an untrusted JSON Schema, compiled to a regex | `from_json_schema` refuses a nested unbounded quantifier with `SchemaError`, before it compiles |
| Stack exhaustion from a deep document     | A pathologically nested untrusted JSON Schema                | The decoder caps nesting depth and raises `SchemaError` instead of overflowing the stack        |
| Stack exhaustion from deep or cyclic data | Crafted data run through a recursive `Self` schema           | A recursion depth guard raises a clean `Invalid` instead of `RecursionError`                    |
| Arbitrary object construction from YAML   | Tags in an untrusted YAML payload                            | YAML is always parsed with a safe loader; the unsafe loaders are never used                     |

## Regex denial of service

Python's `re` engine backtracks, so a pattern like `(a+)+$` runs in exponential
time on crafted input. There is no safe timeout for `re` in pure Python, so the
only defense is to refuse the dangerous pattern before compiling it.

`from_json_schema` does that. When a `pattern` contains a nested unbounded
quantifier (an unbounded repeat applied to a group that is itself unbounded),
the decoder raises `SchemaError` rather than building a validator that could
hang:

<!-- verify: raises SchemaError -->

```python
from probatio import from_json_schema

from_json_schema({"type": "string", "pattern": "(a+)+$"})
```

A benign pattern compiles as you would expect:

```python
from probatio import from_json_schema

schema = from_json_schema({"type": "string", "pattern": "^[a-z]+$"})
print(schema("hello"))  # hello
```

:::caution[This is a heuristic, not a proof]
The detector targets the dominant catastrophic shape, nested unbounded
quantifiers. It does not prove a pattern is safe against every form of
pathological backtracking. Treat it as a strong guard against the common case,
not a guarantee.
:::

The trust boundary is the `from_json_schema` path, and only that path. A
`Match` pattern you write in Python is _not_ checked. That matches voluptuous:
a developer-written regex is the developer's responsibility. If you compile a
pattern from input you do not trust, screen it yourself before handing it to
`Match`.

## Recursion and stack exhaustion

Two recursive shapes can drive Probatio into the Python stack: a deeply nested
schema document, and deeply nested data validated against a recursive schema.
A naive recursive walk turns either into a `RecursionError`, which is an
unhandled crash. Probatio guards both.

A JSON Schema document nested past a fixed depth is refused while decoding:

<!-- verify: raises SchemaError -->

```python
from probatio import from_json_schema


def nest(levels):
    root = {"type": "object", "properties": {}}
    cursor = root
    for _ in range(levels):
        child = {"type": "object", "properties": {}}
        cursor["properties"]["x"] = child
        cursor = child
    return root


from_json_schema(nest(500))
```

On the data side, `Self` lets a schema validate a recursive structure, like a
tree. Feed it data nested deeper than the recursion guard allows, and it raises
a clean `Invalid` with the path to where it gave up, not a `RecursionError`:

```python
from probatio import Schema, Self, Invalid

schema = Schema({"value": int, "children": [Self]})

# A normal tree validates fine.
ok = {"value": 1, "children": [{"value": 2, "children": []}]}
print(schema(ok))  # {'value': 1, 'children': [{'value': 2, 'children': []}]}


def deep(levels):
    node = {"value": 0, "children": []}
    for _ in range(levels):
        node = {"value": 0, "children": [node]}
    return node


try:
    schema(deep(5000))
except Invalid as err:
    print(err.error_message)  # data is nested too deeply for this recursive schema
```

The result is the same in both directions: a depth that would crash the process
becomes a normal, catchable error instead.

## Safe YAML loading

Probatio reads YAML with a safe loader and nothing else. `load_yaml` uses
YAMLRocks when it is installed, otherwise PyYAML's `safe_load`. Neither can
construct arbitrary Python objects from tags in the document, so a hostile YAML
payload cannot instantiate classes or run constructors. The unsafe loaders that
PyYAML also ships are never reached.

```python
from probatio import load_yaml

print(load_yaml("name: app\nport: 8080"))  # {'name': 'app', 'port': 8080}
```

:::tip
This holds for the bare `load_yaml` and for `Schema.load_yaml`. Both go through
the same safe loader, so validating YAML never opens an object-construction
hole.
:::

## Keeping secrets out of error output

Configuration often carries credentials: a password, an API token, a private key.
Wrap the key in `Secret`, and a validation failure under it is redacted: the error
still reports the path and the reason, but shows `<redacted>` instead of the
offending value, so a rejected credential does not leak into a rendered error, a
log line, or a stack trace.

```python
from probatio import Schema, Required, Secret
from probatio.humanize import humanize_error
from probatio.error import MultipleInvalid

schema = Schema({Required(Secret("api_token")): str, Required("host"): str})
data = {"api_token": 12345, "host": "example.com"}
try:
    schema(data)
except MultipleInvalid as err:
    print(humanize_error(data, err))
    # expected str for dictionary value @ data['api_token']. Got <redacted>
```

The redaction is targeted: only the secret key's value is hidden, a sibling
field's value still renders. Each error also carries a `secret` flag (on the
error and in `as_dict()`), so a consumer building its own output can redact the
same values.

The threat model is deliberately narrow: `Secret` covers validation error output,
the place a schema library controls. It does not reach values you log yourself
elsewhere, and it does not encrypt or mask data at rest. The validated value
passes through unchanged; if you also need to keep it out of your own log lines,
wrap it in your own carrier after validation.

## Reporting a vulnerability

Found something that looks like a security issue? Please report it privately
through the GitHub security advisories on the
[project repository](https://github.com/frenck/probatio), not as a public issue.
That gives a fix time to land before the details are out in the open.
