"""Schema codecs: translate a schema to and from external schema formats.

Each external format is a codec with an encode direction (schema to format) and,
where the format supports it, a decode direction (format to schema):

- JSON Schema: ``to_json_schema`` / ``from_json_schema``
- OpenAPI: ``to_openapi`` / ``from_openapi`` (the decoder lives with the JSON
  Schema decoder it reuses, in ``jsonschema``)
- voluptuous-serialize field list: ``to_field_list`` (output only; the format has
  no inverse)

``UNSUPPORTED`` is the sentinel a ``custom_serializer`` returns to defer to the
default handling (used by ``to_field_list`` and ``to_openapi``).
"""

from __future__ import annotations

from probatio.codecs._shared import UNSUPPORTED
from probatio.codecs.fields import to_field_list
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
    "to_field_list",
    "to_json_schema",
    "to_openapi",
]
