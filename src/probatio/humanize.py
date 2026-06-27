"""Human-readable rendering of validation errors.

``humanize_error`` turns an ``Invalid`` (or a ``MultipleInvalid``) into a string
that names what went wrong, where in the data it happened, and the offending
value. The output shape and the ``MAX_VALIDATION_ERROR_ITEM_LENGTH`` constant
match voluptuous, because downstream code imports and relies on both.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from probatio.error import Error, Invalid, MultipleInvalid

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from probatio.error import Location
    from probatio.schema import Schema

MAX_VALIDATION_ERROR_ITEM_LENGTH = 500


def _nested_getitem(data: Any, path: list[Any]) -> Any:
    """Follow ``path`` into ``data``, returning None if it cannot be reached."""
    for item in path:
        try:
            data = data[item]
        except (KeyError, IndexError, TypeError):
            return None
    return data


def humanize_error(
    data: Any,
    validation_error: Invalid,
    max_sub_error_length: int = MAX_VALIDATION_ERROR_ITEM_LENGTH,
    *,
    locator: Callable[[Sequence[Any]], Location | None] | None = None,
) -> str:
    """Render a validation error against ``data`` as a human-readable string.

    ``locator`` is an optional callable that maps an error's ``path`` to a
    ``Location`` (or ``None``); when given, each error line gains the source
    location it points at. Pair it with ``load_yaml_with_locations`` to turn a
    validation failure into a ``file:line:column`` a user can jump to.
    """
    if isinstance(validation_error, MultipleInvalid):
        return "\n".join(
            sorted(
                humanize_error(data, sub_error, max_sub_error_length, locator=locator)
                for sub_error in validation_error.errors
            ),
        )
    offending = repr(_nested_getitem(data, validation_error.path))
    if len(offending) > max_sub_error_length:
        offending = offending[: max_sub_error_length - 3] + "..."
    message = f"{validation_error}. Got {offending}"
    if locator is not None:
        location = locator(validation_error.path)
        if location is not None:
            message = f"{message} (at {location})"
    return message


def validate_with_humanized_errors(
    data: Any,
    schema: Schema,
    max_sub_error_length: int = MAX_VALIDATION_ERROR_ITEM_LENGTH,
) -> Any:
    """Validate ``data``, raising ``Error`` with a humanized message on failure."""
    try:
        return schema(data)
    except (Invalid, MultipleInvalid) as exc:
        raise Error(humanize_error(data, exc, max_sub_error_length)) from exc
