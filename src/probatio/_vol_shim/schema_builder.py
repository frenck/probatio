"""The ``voluptuous.schema_builder`` shim, backed by probatio.

Besides re-exporting the public surface, this carries ``_compile_scalar``: a
voluptuous internal that some dependencies (notably ``annotatedyaml``) import
directly as ``voluptuous.schema_builder._compile_scalar``. It is ported onto
probatio's error types so those imports keep working.
"""

from __future__ import annotations

import inspect
from typing import Any

from probatio import error as _error
from probatio._vol_shim import _surface
from probatio._vol_shim._reexport import reexport


def _compile_scalar(schema: Any) -> Any:
    """Port of ``voluptuous.schema_builder._compile_scalar`` onto probatio errors.

    Returns a ``(path, data)`` validator for a scalar schema (a type, a callable,
    or a plain value), matching the internal voluptuous helper.
    """
    if inspect.isclass(schema):

        def validate_instance(path: Any, data: Any) -> Any:
            """Require the data to be an instance of the schema type."""
            if isinstance(data, schema):
                return data
            message = f"expected {schema.__name__}"
            raise _error.TypeInvalid(message, path)

        return validate_instance

    if callable(schema):

        def validate_callable(path: Any, data: Any) -> Any:
            """Call the schema, trapping ValueError and re-pathing Invalid."""
            try:
                return schema(data)
            except ValueError as exc:
                message = "not a valid value"
                raise _error.ValueInvalid(message, path) from exc
            except _error.Invalid as exc:
                exc.prepend(path)
                raise

        return validate_callable

    def validate_value(path: Any, data: Any) -> Any:
        """Require the data to equal the schema value."""
        if data != schema:
            message = "not a valid value"
            raise _error.ScalarInvalid(message, path)
        return data

    return validate_value


# Re-export voluptuous.schema_builder's surface; ``_compile_scalar`` stays off
# ``__all__`` (it is an internal that dependencies import by name, not via ``*``).
reexport(globals(), _surface.SCHEMA_BUILDER)
