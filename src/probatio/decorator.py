"""The ``probatio`` decorator: validate a callable's arguments from its annotations.

Where the voluptuous-compatible ``validate`` wants a schema named per argument,
``probatio`` reads the signature and infers a validator for each annotated
parameter, the same way ``DataclassSchema`` reads a dataclass. An unannotated
parameter (``self``, ``cls``, a bare ``*args``) is left alone, so it drops onto a
method without ceremony. It works on a coroutine function too, awaiting the call
before validating the result.
"""

from __future__ import annotations

import inspect
import typing
from functools import wraps

from probatio.dataclass_schema import _annotation_to_schema
from probatio.error import SchemaError
from probatio.schema import ALLOW_EXTRA, Schema
from probatio.validators import All

# ``probatio`` preserves the decorated callable's signature for callers: the
# wrapper forwards ``*args, **kwargs`` (so it cannot pass a ParamSpec through
# directly), is typed ``Any`` internally, and is cast back to the callable's own
# ``(**P) -> R``. For a coroutine function ``R`` is the awaitable it returns, so
# one cast covers both the sync and the async wrapper.

# Only these parameter kinds map to a named schema. ``*args``/``**kwargs`` carry
# no single value to validate, so they are skipped, and a constraint cannot target
# them.
_VALIDATED_KINDS = (
    inspect.Parameter.POSITIONAL_ONLY,
    inspect.Parameter.POSITIONAL_OR_KEYWORD,
    inspect.Parameter.KEYWORD_ONLY,
)

_RETURN = "return"

# Distinguishes "no schema for this parameter" from a schema of ``None`` (which
# means the value must be ``None``): ``_annotation_to_schema(None)`` returns
# ``None``, and a constraint value may legitimately be ``None`` too.
_UNSET: typing.Any = object()


def _identity(value: typing.Any) -> typing.Any:
    """Return the value unchanged (the no-op schema when there is nothing to run)."""
    return value


def _name(func: typing.Callable[..., typing.Any]) -> str:
    """Name ``func`` for an error message, falling back to its repr."""
    return getattr(func, "__name__", repr(func))


def _check_constraints(
    func: typing.Callable[..., typing.Any],
    constraints: dict[str, typing.Any],
    signature: inspect.Signature,
) -> None:
    """Reject a constraint that names no parameter, or a variadic one."""
    unknown = sorted(
        repr(name) for name in constraints if name not in signature.parameters
    )
    if unknown:
        message = f"probatio: constraint names no such parameter: {', '.join(unknown)}"
        raise SchemaError(message)
    variadic = sorted(
        repr(name)
        for name in constraints
        if signature.parameters[name].kind not in _VALIDATED_KINDS
    )
    if variadic:
        message = (
            f"probatio: cannot constrain the variadic parameter {', '.join(variadic)} "
            f"of {_name(func)!r}"
        )
        raise SchemaError(message)


def _resolve_hints(
    func: typing.Callable[..., typing.Any],
    needed: set[str],
) -> dict[str, typing.Any]:
    """Resolve only the annotations that are validated.

    An unrelated annotation (a skipped ``*args``, or the return when return
    validation is off) is never resolved, so a forward reference there cannot break
    decoration. Only ``needed`` names are resolved, by narrowing the callable's
    ``__annotations__`` around a single ``get_type_hints`` call and restoring it.
    """
    annotations = getattr(func, "__annotations__", None) or {}
    wanted = {name: value for name, value in annotations.items() if name in needed}
    if not wanted:
        return {}
    try:
        func.__annotations__ = wanted
        return typing.get_type_hints(func, include_extras=True)
    except Exception as exc:
        message = f"probatio cannot resolve the annotations of {_name(func)!r}: {exc}"
        raise SchemaError(message) from exc
    finally:
        func.__annotations__ = annotations


def _parameter_schema(
    signature: inspect.Signature,
    constraints: dict[str, typing.Any],
    hints: dict[str, typing.Any],
) -> dict[str, typing.Any]:
    """Map each annotated (or constrained) parameter to the validator it runs.

    A parameter's annotation becomes its validator; a matching entry in
    ``constraints`` runs after it with ``All``, exactly as a dataclass's
    ``additional_constraints`` layer on the field's type.
    """
    mapping: dict[str, typing.Any] = {}
    for name, parameter in signature.parameters.items():
        if parameter.kind not in _VALIDATED_KINDS:
            continue
        inferred = _annotation_to_schema(hints[name], {}) if name in hints else _UNSET
        extra = constraints.get(name, _UNSET)
        if inferred is not _UNSET and extra is not _UNSET:
            mapping[name] = All(inferred, extra)
        elif inferred is not _UNSET:
            mapping[name] = inferred
        elif extra is not _UNSET:
            mapping[name] = extra
    return mapping


def _return_schema(
    func: typing.Callable[..., typing.Any],
    returns: typing.Any,
    hints: dict[str, typing.Any],
) -> typing.Callable[[typing.Any], typing.Any]:
    """Resolve the ``returns`` argument to the validator run on the result.

    ``None`` (the default) skips return validation, ``True`` validates against the
    ``-> R`` annotation, and any other value is used as the schema directly.
    """
    if returns is None or returns is False:
        return _identity
    if returns is True:
        if _RETURN not in hints:
            message = (
                f"probatio: returns=True needs a return annotation on {_name(func)!r}"
            )
            raise SchemaError(message)
        return Schema(_annotation_to_schema(hints[_RETURN], {}))
    return Schema(returns)


@typing.overload
def probatio[**P, R](
    constraints: typing.Callable[P, R], /
) -> typing.Callable[P, R]: ...


@typing.overload
def probatio[**P, R](
    constraints: dict[str, typing.Any] | None = ...,
    returns: typing.Any = ...,
) -> typing.Callable[[typing.Callable[P, R]], typing.Callable[P, R]]: ...


def probatio(
    constraints: typing.Any = None,
    returns: typing.Any = None,
) -> typing.Any:
    """Validate a callable's arguments (and optionally its result) from annotations.

    Each annotated parameter is validated against its type, coercing where the
    annotation says so, so the body receives the validated value::

        @probatio
        def area(width: int, height: int) -> int:
            return width * height

    ``constraints`` is an optional ``{parameter: validator}`` map that layers an
    extra rule after the inferred type check, the same shape as a dataclass's
    ``additional_constraints``. ``returns`` opts into result validation: ``True``
    validates against the ``-> R`` annotation, or pass a schema to validate against
    it directly::

        @probatio({"name": Length(min=2)}, returns=User)
        def make(name: str, age: int) -> User: ...

    A coroutine function is validated the same way, awaiting the call before the
    result schema runs. Unannotated parameters (``self``, ``cls``, a bare
    ``*args``) are left alone. The undecorated callable stays reachable through the
    standard ``__wrapped__`` attribute for a trusted, unvalidated call.
    """
    # Bare ``@probatio``: the decorated callable arrives as the first argument.
    if callable(constraints) and not isinstance(constraints, dict):
        return _decorate(constraints, {}, None)

    def decorate[**P, R](func: typing.Callable[P, R]) -> typing.Callable[P, R]:
        """Wrap ``func`` so its arguments and result are validated."""
        return _decorate(func, constraints or {}, returns)

    return decorate


def _decorate[**P, R](
    func: typing.Callable[P, R],
    constraints: dict[str, typing.Any],
    returns: typing.Any,
) -> typing.Callable[P, R]:
    """Build the validating wrapper (sync or async) around ``func``."""
    signature = inspect.signature(func)
    _check_constraints(func, constraints, signature)

    needed = {
        name
        for name, parameter in signature.parameters.items()
        if parameter.kind in _VALIDATED_KINDS
    }
    if returns is True:
        needed.add(_RETURN)
    hints = _resolve_hints(func, needed)

    parameter_schema = _parameter_schema(signature, constraints, hints)
    input_schema: typing.Callable[[typing.Any], typing.Any] = (
        Schema(parameter_schema, extra=ALLOW_EXTRA) if parameter_schema else _identity
    )
    output_schema = _return_schema(func, returns, hints)

    def bind(
        args: tuple[typing.Any, ...], kwargs: dict[str, typing.Any]
    ) -> inspect.BoundArguments:
        """Bind the call, validate the named arguments, and write them back."""
        bound = signature.bind(*args, **kwargs)
        named = {
            name: value
            for name, value in bound.arguments.items()
            if signature.parameters[name].kind in _VALIDATED_KINDS
        }
        bound.arguments.update(input_schema(named))
        return bound

    if inspect.iscoroutinefunction(func):

        @wraps(func)
        async def async_wrapper(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:
            """Validate the arguments, await ``func``, then validate the result."""
            bound = bind(args, kwargs)
            result = await func(*bound.args, **bound.kwargs)
            return output_schema(result)

        return typing.cast("typing.Callable[P, R]", async_wrapper)

    @wraps(func)
    def wrapper(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:
        """Validate the arguments, call ``func``, then validate the result."""
        bound = bind(args, kwargs)
        return output_schema(func(*bound.args, **bound.kwargs))

    return typing.cast("typing.Callable[P, R]", wrapper)
