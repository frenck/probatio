"""Schema codecs: translate a schema to and from external schema formats.

Each external format is a codec with an encode direction (schema to format) and,
where the format supports it, a decode direction (format to schema):

- JSON Schema: ``to_json_schema`` / ``from_json_schema``
- OpenAPI: ``to_openapi`` / ``from_openapi`` (the decoder lives with the JSON
  Schema decoder it reuses, in ``jsonschema``)
- voluptuous-serialize field list: ``serialize`` (output only; the format has no
  inverse)

``UNSUPPORTED`` is the sentinel a ``custom_serializer`` returns to defer to the
default handling (used by ``serialize`` and ``to_openapi``).
"""

from __future__ import annotations

from probatio.codecs._shared import UNSUPPORTED
from probatio.codecs.fields import serialize
from probatio.codecs.jsonschema import (
    from_json_schema,
    from_openapi,
    to_json_schema,
)
from probatio.codecs.openapi import to_openapi

__all__ = [
    "UNSUPPORTED",
    "from_json_schema",
    "from_openapi",
    "serialize",
    "to_json_schema",
    "to_openapi",
]
