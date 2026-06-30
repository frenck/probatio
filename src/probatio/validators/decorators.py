"""Function-level helpers: the ``validate`` decorator and the ``raises`` guard."""

from __future__ import annotations

import inspect
import re
import typing
from contextlib import contextmanager
from functools import wraps

from probatio.error import Invalid, SchemaError, ValueInvalid
from probatio.schema import ALLOW_EXTRA, Schema

_RETURNS_KEY = "__return__"

# ``validate`` preserves the decorated function's signature for callers: the
# wrapper transforms the arguments internally (so it cannot forward a ParamSpec
# directly), so it is typed ``Any`` and cast to the function's own ``(**P) -> R``.
_P = typing.ParamSpec("_P")
_R = typing.TypeVar("_R")


def message(
    default: str | None = None,
    cls: type[Invalid] | None = None,
) -> typing.Callable[..., typing.Any]:
    """Turn a function that raises ``ValueError`` into a configurable validator.

    The decorated function becomes a factory. Calling it returns a validator that
    runs the original function and, when it raises ``ValueError``, raises an
    ``Invalid`` carrying ``default`` instead. Both the message and the error class
    can be overridden per use::

        @message("not an integer", cls=IntegerInvalid)
        def isint(value):
            return int(value)

        Schema(isint())            # raises IntegerInvalid("not an integer")
        Schema(isint("bad value")) # raises IntegerInvalid("bad value")

    Matches voluptuous, so ``Boolean`` and friends are factories here too.
    """
    if cls is not None and not issubclass(cls, Invalid):
        problem = "message can only use subclasses of Invalid as a custom class"
        raise SchemaError(problem)

    def decorator(
        func: typing.Callable[..., typing.Any],
    ) -> typing.Callable[..., typing.Any]:
        """Wrap ``func`` as a factory producing message-carrying validators."""

        @wraps(func)
        def check(
            msg: str | None = None,
            clsoverride: type[Invalid] | None = None,
        ) -> typing.Callable[..., typing.Any]:
            """Return a validator that runs ``func`` with a fixed failure message."""

            @wraps(func)
            def wrapper(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:
                """Run ``func``, turning its ``ValueError`` into an ``Invalid``."""
                try:
                    return func(*args, **kwargs)
                except ValueError:
                    raise (clsoverride or cls or ValueInvalid)(
                        msg or default or "invalid value"
                    ) from None

            return wrapper

        return check

    return decorator


def truth(func: typing.Callable[..., typing.Any]) -> typing.Callable[..., typing.Any]:
    """Turn a predicate into a validator that returns the value when it is truthy.

    The predicate is called with the value; a falsy result raises ``ValueError``,
    which the engine reports as ``Invalid``. A truthy result returns the value
    unchanged::

        @truth
        def isdir(value):
            return os.path.isdir(value)

        Schema(isdir)("/")  # "/"
    """

    @wraps(func)
    def check(value: typing.Any) -> typing.Any:
        """Return ``value`` when ``func(value)`` is truthy, else raise."""
        if not func(value):
            raise ValueError
        return value

    return check


def _identity(value: typing.Any) -> typing.Any:
    """Return the value unchanged (the no-op schema when none is given)."""
    return value


_POSITIONAL = (
    inspect.Parameter.POSITIONAL_ONLY,
    inspect.Parameter.POSITIONAL_OR_KEYWORD,
)


def _args_to_dict(
    func: typing.Callable[..., typing.Any],
    args: tuple[typing.Any, ...],
) -> dict[str, typing.Any]:
    """Pair positional arguments with their parameter names."""
    names = [
        name
        for name, parameter in inspect.signature(func).parameters.items()
        if parameter.kind in _POSITIONAL
    ]
    return {name: args[index] for index, name in enumerate(names) if index < len(args)}


def validate(
    *args: typing.Any, **kwargs: typing.Any
) -> typing.Callable[[typing.Callable[_P, _R]], typing.Callable[_P, _R]]:
    """Decorate a function to validate its arguments (and return) against schemas.

    Name a schema per argument, positionally or by keyword, and optionally a
    ``__return__`` schema for the return value::

        @validate(arg1=int, arg2=str, __return__=int)
        def f(arg1, arg2): ...
    """
    returns_defined = False
    returns = None
    schema_arguments = dict(kwargs)

    if _RETURNS_KEY in schema_arguments:
        returns_defined = True
        returns = schema_arguments.pop(_RETURNS_KEY)

    def decorate(
        func: typing.Callable[_P, _R],
    ) -> typing.Callable[_P, _R]:
        """Wrap ``func`` so its arguments and return value are validated."""
        positional = _args_to_dict(func, args)
        arguments = {**positional, **schema_arguments}
        input_schema: typing.Callable[[typing.Any], typing.Any] = (
            Schema(arguments, extra=ALLOW_EXTRA) if arguments else _identity
        )
        output_schema: typing.Callable[[typing.Any], typing.Any] = (
            Schema(returns) if returns_defined else _identity
        )

        # A parameter declared before the ``/`` cannot be passed by keyword, so it
        # has to go back to ``func`` positionally; everything else goes as keywords.
        positional_only = [
            name
            for name, parameter in inspect.signature(func).parameters.items()
            if parameter.kind is inspect.Parameter.POSITIONAL_ONLY
        ]

        @wraps(func)
        def wrapper(*call_args: typing.Any, **call_kwargs: typing.Any) -> typing.Any:
            """Validate the bound arguments, call ``func``, validate the result."""
            bound = {**_args_to_dict(func, call_args), **call_kwargs}
            validated = input_schema(bound)
            leading = [
                validated.pop(name) for name in positional_only if name in validated
            ]
            return output_schema(func(*leading, **validated))

        return typing.cast("typing.Callable[_P, _R]", wrapper)

    return decorate


@contextmanager
def raises(
    exc: type[BaseException],
    msg: str | None = None,
    regex: str | re.Pattern[str] | None = None,
) -> typing.Iterator[None]:
    """Assert that the block raises ``exc``, optionally matching ``msg``/``regex``.

    A testing helper kept for drop-in compatibility with voluptuous.
    """
    try:
        yield
    except exc as caught:
        if msg is not None:
            assert str(caught) == msg, f"{str(caught)!r} != {msg!r}"  # noqa: S101, PT017
        if regex is not None:
            assert re.search(regex, str(caught)), (  # noqa: S101, PT017
                f"{str(caught)!r} does not match {regex!r}"
            )
    else:
        message = f"Did not raise exception {exc.__name__}"
        raise AssertionError(message)
