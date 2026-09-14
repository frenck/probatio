"""Enforce that a pass-through validator keeps the caller's type.

A validator that only inspects its input and hands it straight back must not
promise ``Any`` on the way out. Typed ``Any -> Any`` it silently erases the
caller's type, so ``Length(min=1)(names)`` returns ``Any`` instead of the
``list[str]`` that went in, and the erasure spreads from there. The fix is one
type parameter: ``def __call__[T](self, value: T) -> T``.

Returning something narrower than the input is fine and is not what this guards:
``Slug`` and ``Hostname`` hand the value back too, but promise ``str``, which
tells a caller holding an ``Any`` more than ``T`` would.

Rather than list the validators that follow the rule (a list that goes stale the
moment one is added), this reads each ``__call__`` and works out which ones are
pass-throughs: every ``return`` hands back the parameter, and the body never
rebinds it. A validator that transforms its input is none of this test's
business, and neither is one that declares its typing through ``@overload``
(``EnsureList``, ``Unique``), which is checked in that validator's own test.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
import typing

import pytest

import probatio
from probatio.validators._base import _SafeValidator


def _returns_its_input_unchanged(func: typing.Any) -> bool:
    """Report whether every return hands back the untouched first parameter."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    call = tree.body[0]
    assert isinstance(call, ast.FunctionDef)

    parameters = call.args.args[1:]
    if not parameters:
        return False
    name = parameters[0].arg

    returns: list[ast.expr | None] = []
    rebinds = False
    for node in ast.walk(call):
        if isinstance(node, ast.Return):
            returns.append(node.value)
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.For)):
            targets = [node.target]
        rebinds = rebinds or any(
            isinstance(bound, ast.Name) and bound.id == name
            for target in targets
            for bound in ast.walk(target)
        )

    if not returns or rebinds:
        return False

    return all(
        isinstance(returned, ast.Name) and returned.id == name for returned in returns
    )


def _every_validator() -> list[type[_SafeValidator]]:
    """Collect every validator class, subclasses of subclasses included."""
    # Importing the package pulls in every validator module, so the walk below sees
    # all of them and not just the ones another test happened to import first.
    assert probatio.Schema is not None

    found: set[type[_SafeValidator]] = set()
    pending = [_SafeValidator]
    while pending:
        for subclass in pending.pop().__subclasses__():
            if subclass not in found:
                found.add(subclass)
                pending.append(subclass)
    return sorted(found, key=lambda cls: cls.__qualname__)


def _pass_through_validators() -> list[type[_SafeValidator]]:
    """Collect the validators that hand their input straight back."""
    return [
        cls
        for cls in _every_validator()
        # Only where ``__call__`` is defined: an inherited one belongs to the base.
        if "__call__" in cls.__dict__
        and not typing.get_overloads(cls.__dict__["__call__"])
        and _returns_its_input_unchanged(cls.__dict__["__call__"])
    ]


def _resolved_hints(call: typing.Any) -> dict[str, typing.Any]:
    """Resolve a ``__call__``'s annotations, type parameter and all."""
    # A type parameter is scoped to the method, so resolving the annotations needs
    # it in the local namespace.
    return typing.get_type_hints(
        call, localns={param.__name__: param for param in call.__type_params__}
    )


def test_the_sweep_finds_pass_through_validators() -> None:
    """The detector finds the pass-through validators, so the rule has teeth."""
    names = {cls.__name__ for cls in _pass_through_validators()}

    # A spot check across the modules, not the full list: this guards the detector
    # itself, and pinning every name would just be the same list twice.
    assert {"Equal", "Length", "Match", "Datetime", "IsTrue", "Immutable"} <= names
    assert len(names) > 30


@pytest.mark.parametrize(
    "validator", _pass_through_validators(), ids=lambda cls: cls.__name__
)
def test_a_pass_through_validator_promises_more_than_any(
    validator: type[_SafeValidator],
) -> None:
    """A validator returning its input unchanged never hands back a bare Any."""
    call = validator.__dict__["__call__"]
    hints = _resolved_hints(call)
    _self, parameter = inspect.signature(call).parameters
    returned = hints["return"]

    assert returned is not typing.Any, (
        f"{validator.__name__}.__call__ returns its input unchanged but promises "
        f"Any, erasing the caller's type; type it as "
        f"`def __call__[T](self, value: T) -> T`, or annotate the narrower type it "
        f"guarantees"
    )

    if call.__type_params__:
        # The caller's own type, carried through: one parameter, in and out.
        (type_param,) = call.__type_params__
        assert hints[parameter] is type_param
        assert returned is type_param
