"""The Schema: compile a declarative schema once, then validate data with it.

A schema is built from plain Python: a type (``int``), a literal (``"on"``), a
callable validator, a mapping or sequence, or a nested ``Schema``, with markers
(``Required``, ``Optional``, ``Remove``, ``Exclusive``, ``Inclusive``) annotating
mapping keys.

Compilation turns the declarative schema into a single callable that takes a
value and returns the validated (and possibly normalized) result, or raises
``Invalid``. Compiling once keeps validation cheap on the hot paths.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from contextvars import ContextVar
from enum import Enum
from typing import TYPE_CHECKING, Any, cast

from probatio._engine import (
    ALLOW_EXTRA,
    PREVENT_EXTRA,
    REMOVE_EXTRA,
    CompiledSchema,
    _Candidate,
    _MappingValidator,
    _ObjectValidator,
    _SequenceValidator,
)
from probatio.error import (
    EnumInvalid,
    Invalid,
    MultipleInvalid,
    ScalarInvalid,
    SchemaError,
    TypeInvalid,
    ValueInvalid,
)
from probatio.markers import (
    UNDEFINED,
    Alias,
    Exclusive,
    Extra,
    Forbidden,
    Inclusive,
    Marker,
    Object,
    Optional,
    Remove,
    Required,
    Self,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterator

# The schema currently being compiled, so a ``Self`` reference inside it can be
# resolved to the enclosing (root) schema. Only the outermost compile sets it.
_COMPILING_ROOT: ContextVar[Schema | None] = ContextVar(
    "probatio_compiling_root",
    default=None,
)

# True while ``compile_schema`` compiles a combinator's sub-schema. A ``Self``
# there is wrapped in its own ``Schema(Self)`` (so it has no enclosing mapping at
# compile time), and is resolved at validation time instead of being rejected the
# way a bare ``Schema(Self)`` is.
_COMPILING_FOR_COMBINATOR: ContextVar[bool] = ContextVar(
    "probatio_compiling_for_combinator",
    default=False,
)

# The schema currently being validated, so a ``Self`` deferred from inside a
# combinator resolves to the enclosing schema at call time (when its compile-time
# root was only the throwaway ``Schema(Self)`` wrapper).
_ACTIVE_ROOT: ContextVar[Schema | None] = ContextVar(
    "probatio_active_root",
    default=None,
)

# Current ``Self`` recursion depth, so cyclic or pathologically deep data raises a
# clean Invalid instead of crashing the interpreter with a RecursionError. Each
# ``Self`` level costs several stack frames, so the cap is a fraction of the
# interpreter's recursion limit, read live so a caller that raises the limit for
# genuinely deep data scales with it.
_SELF_DEPTH: ContextVar[int] = ContextVar("probatio_self_depth", default=0)
_SELF_DEPTH_DIVISOR = 8

# The context passed to ``schema(data, context=...)``, visible to any validator
# during the call through ``current_context()``. Default None, and only set when a
# call actually passes a context, so the common path pays nothing. A nested call
# that passes its own context overrides it for that subtree; one that passes none
# inherits the enclosing call's.
_VALIDATION_CONTEXT: ContextVar[Any] = ContextVar(
    "probatio_validation_context",
    default=None,
)


class _InheritContext:
    """Sentinel default for ``context``: inherit the enclosing call's context.

    It lets an *omitted* ``context`` (inherit) be told apart from an explicit
    ``context=None`` (set the context to ``None`` for this subtree, clearing any
    inherited one). ``None`` cannot serve as that marker, since it is also a valid
    context value a caller may want to set.
    """

    def __repr__(self) -> str:
        """Render readably in the call signature."""
        return "<inherit>"


_INHERIT_CONTEXT = _InheritContext()


def current_context() -> Any:
    """Return the context of the active ``schema(data, context=...)`` call, or None.

    A validator (a custom callable, or any built-in) can read this to validate
    against per-call state, like a set of allowed values supplied when the schema
    is called rather than when it is built. It is ``None`` when no context was
    passed, so a context-reading validator decides what an absent context means.
    """
    return _VALIDATION_CONTEXT.get()


@contextmanager
def recursion_guard(cost: int = 1) -> Iterator[None]:
    """Bound recursive validation so deep or cyclic data fails cleanly.

    Raises ``Invalid`` once the recursion passes a fraction of the interpreter's
    limit, rather than letting Python crash with ``RecursionError``. Used by
    ``Self``, the JSON Schema decoder's recursive ``$ref`` validators, and the
    recursive-dataclass reference.

    ``cost`` is how much one level counts against the shared budget. It defaults to
    1 (``Self`` and ``$ref``, a couple of stack frames per level); a heavier path
    passes a larger cost so the guard fires before the real stack overflows. The
    budget is shared, so mixed recursion (a ``Self`` schema containing a recursive
    dataclass, say) accounts for both correctly.
    """
    depth = _SELF_DEPTH.get() + cost
    if depth > sys.getrecursionlimit() // _SELF_DEPTH_DIVISOR:
        message = "data is nested too deeply for this recursive schema"
        raise Invalid(message)
    token = _SELF_DEPTH.set(depth)
    try:
        yield
    finally:
        _SELF_DEPTH.reset(token)


def _deferred_self(data: Any) -> Any:
    """Validate ``data`` against the schema being validated (a deferred ``Self``).

    Used when ``Self`` was compiled inside a combinator, so its enclosing schema
    was not known at compile time. The active root is set by ``Schema.__call__``,
    so a ``Self`` reached only by calling a combinator on its own (never through a
    schema) is a definition error rather than a crash.
    """
    root = _ACTIVE_ROOT.get()
    if root is None:
        message = "Self has no enclosing schema to validate against"
        raise SchemaError(message)
    with recursion_guard():
        return root._compiled(data)  # noqa: SLF001


def _schema_uses_self(node: Any) -> bool:
    """Report whether ``Self`` appears anywhere in a schema definition.

    Only such schemas record an active root when validated (the contextvar is not
    free), so every non-recursive schema skips that cost. The walk descends into
    mappings, sequences, and the raw children of combinators and wrappers; it does
    not enter a nested ``Schema``, which resolves its own ``Self``.
    """
    if node is Self:
        return True
    if isinstance(node, dict):
        return any(
            _schema_uses_self(k) or _schema_uses_self(v) for k, v in node.items()
        )
    if isinstance(node, list | tuple | set | frozenset):
        return any(_schema_uses_self(element) for element in node)
    children = getattr(node, "validators", None)
    if isinstance(children, list):
        return any(_schema_uses_self(child) for child in children)
    wrapped = getattr(node, "validator", None)
    if wrapped is not None:
        return _schema_uses_self(wrapped)
    return False


# Anything usable as a schema (a type, literal, callable, container, or Schema).
# Exposed for type annotations, mirroring voluptuous.
type Schemable = Any

# The extra-key constants, CompiledSchema, and Schema make up this module's
# public surface; the constants and type live in _engine and are re-exported.
__all__ = [
    "ALLOW_EXTRA",
    "PREVENT_EXTRA",
    "REMOVE_EXTRA",
    "CompiledSchema",
    "Schema",
    "Schemable",
    "current_context",
]


def _match_any_key(key: Any) -> Any:
    """Return the key unchanged: an ``Extra`` catch-all matches any key."""
    return key


class _TypeCheck:
    """A compiled ``isinstance`` check the engine can inline via ``checked_type``.

    Behaves like the closure ``_compile_type`` used to return when called, but
    exposes the type so the mapping and sequence loops can do the isinstance
    inline and avoid a call per value on the hot path.
    """

    __slots__ = ("_expected", "checked_type")

    def __init__(self, checked_type: type) -> None:
        """Store the type to check and its name for the error message."""
        self.checked_type = checked_type
        self._expected = checked_type.__name__

    def __call__(self, data: Any) -> Any:
        """Require the value to be an instance of the expected type."""
        if not isinstance(data, self.checked_type):
            message = f"expected {self._expected}"
            raise TypeInvalid(message, context={"expected": self._expected})
        return data


class _EnumCheck:
    """Validate against an ``Enum``, accepting a member or one of its values.

    A bare ``Enum`` used as a schema would otherwise validate by ``isinstance``,
    which rejects the member's value, the string a loader hands you, and accepts
    only an already-built member. This accepts a member instance unchanged, or any
    value that maps to one (returning the member), and reports the valid values
    otherwise. It is the built-in consumer of the self-validation idea for the
    stdlib types that cannot carry the protocol method (ADR-007); ``Flag`` and the
    ``IntEnum``/``StrEnum`` family ride here too, since they all subclass ``Enum``.
    """

    __slots__ = ("_enum", "_expected")

    def __init__(self, enum_cls: type[Enum]) -> None:
        """Store the enum type and its name for the error message."""
        self._enum = enum_cls
        self._expected = enum_cls.__name__

    def __call__(self, data: Any) -> Any:
        """Return the matching member, or raise ``EnumInvalid`` listing the values."""
        if isinstance(data, self._enum):
            return data
        try:
            return self._enum(data)
        except (ValueError, TypeError) as exc:
            # ValueError: no member has this value. TypeError: the value is
            # unhashable, so the value-to-member lookup cannot even be tried.
            values = [member.value for member in self._enum]
            message = f"value must be one of {values}"
            raise EnumInvalid(
                message,
                context={"expected": self._expected, "values": values},
            ) from exc


class Schema:
    """A compiled, callable schema.

    Build it from a type, a literal, a callable, or a nested ``Schema``, then
    call it with a value to validate that value.
    """

    def __init__(
        self,
        schema: Any,
        required: bool = False,  # noqa: FBT001, FBT002
        extra: int = PREVENT_EXTRA,
    ) -> None:
        """Compile ``schema``; ``required`` and ``extra`` govern mapping keys.

        ``required`` and ``extra`` are positional to match voluptuous, so
        ``Schema({...}, True, ALLOW_EXTRA)`` keeps working.
        """
        self.schema = schema
        self.required = required
        self.extra = extra
        # Whether ``Self`` appears anywhere in the definition. Only then does
        # validation record an active root (a contextvar that is not free), so a
        # non-recursive schema, the common case, skips that cost entirely.
        self._uses_self = _schema_uses_self(schema)
        # Mark self as the root while compiling, so a ``Self`` inside this schema
        # resolves here. Tokens nest correctly, so a nested Schema restores the
        # outer root on exit.
        token = _COMPILING_ROOT.set(self)
        try:
            self._compiled = self._compile(schema)
        finally:
            _COMPILING_ROOT.reset(token)

    def __call__(self, data: Any, *, context: Any = _INHERIT_CONTEXT) -> Any:
        """Validate ``data``, returning the result or raising ``MultipleInvalid``.

        ``context`` is made available to validators that read ``current_context()``
        for the duration of the call. Omitting it inherits the enclosing call's
        context (if any); passing one (including an explicit ``None``) sets it for
        this call and any nested schema that does not pass its own. So
        ``schema(data, context=None)`` clears an inherited context, where omitting
        it keeps it.
        """
        if context is not _INHERIT_CONTEXT:
            return self._call_with_context(data, context)
        # The body is inlined here (no helper call) so recursive ``Self`` and
        # ``$ref`` validation keeps the same stack-frame budget the depth guard is
        # tuned against; an extra frame per level would trip RecursionError early.
        if self._uses_self:
            return self._call_recursive(data)
        try:
            return self._compiled(data)
        except MultipleInvalid:
            raise
        except Invalid as exc:
            error = exc
        # Raised outside the except block so the single error is reported on its
        # own, not chained as "during handling of the above exception".
        raise MultipleInvalid([error])

    def _call_with_context(self, data: Any, context: Any) -> Any:
        """Set the call context, then validate through the common path.

        Only the rare context-bearing call enters here, so the extra frame it adds
        never lands on the recursive hot path (where the context is already set and
        the common branch runs).
        """
        token = _VALIDATION_CONTEXT.set(context)
        try:
            return self(data)
        finally:
            _VALIDATION_CONTEXT.reset(token)

    def _call_recursive(self, data: Any) -> Any:
        """Validate while recording ``self`` as the active root.

        A ``Self`` deferred from inside a combinator resolves to this (the
        enclosing) schema, so the root must be live for the duration of the call.
        Only taken by schemas that contain ``Self``.
        """
        token = _ACTIVE_ROOT.set(self)
        try:
            return self._compiled(data)
        except MultipleInvalid:
            raise
        except Invalid as exc:
            error = exc
        finally:
            _ACTIVE_ROOT.reset(token)
        raise MultipleInvalid([error])

    def __eq__(self, other: object) -> bool:
        """Two schemas are equal when their definitions match (voluptuous semantics).

        Only the schema definition is compared, like voluptuous, so dict key order
        does not matter and a marker compares equal to its bare key. Anything that
        is not a ``Schema`` is unequal.
        """
        return isinstance(other, Schema) and other.schema == self.schema

    def __ne__(self, other: object) -> bool:
        """Inverse of equality."""
        return not self.__eq__(other)

    # Defining __eq__ drops the inherited __hash__, matching voluptuous: a Schema
    # is compared by content, not used as a dict key or set member.
    __hash__ = None  # type: ignore[assignment]

    @classmethod
    def infer(cls, data: Any, **kwargs: Any) -> Schema:
        """Build a Schema from concrete example data (an API response, say).

        Each value becomes its type: a scalar maps to ``type(value)``, a non-empty
        dict to a mapping of inferred types, a non-empty list to a list of its
        items' inferred types, and an empty dict or list to the bare ``dict`` or
        ``list``. Only basic inference is supported. Keyword arguments
        (``required``, ``extra``) pass through to ``Schema``.
        """
        return cls(cls._infer_type(data), **kwargs)

    @staticmethod
    def _infer_type(value: Any) -> Any:
        """Map a concrete value to a schema node, recursing into dicts and lists."""
        if isinstance(value, dict):
            if not value:
                return dict
            return {key: Schema._infer_type(item) for key, item in value.items()}
        if isinstance(value, list):
            if not value:
                return list
            return [Schema._infer_type(item) for item in value]
        return type(value)

    def extend(
        self,
        schema: dict[Any, Any] | Schema,
        required: bool | None = None,  # noqa: FBT001
        extra: int | None = None,
    ) -> Schema:
        """Return a new Schema with ``schema``'s keys merged into this mapping.

        Keys in ``schema`` replace equal keys in this schema (marker and value
        both), so a bare key can override a ``Required`` one. ``required`` and
        ``extra`` override this schema's settings, or inherit them when omitted.

        ``schema`` may be a plain mapping or another ``Schema`` (voluptuous PR
        #538). Extending with a ``Schema`` carries its ``required`` intent across
        the merge: a bare key is pinned ``Required`` when the extension was built
        with ``required=True``, or kept ``Optional`` when only the result is
        required, recursively into nested mappings, so the merge does not silently
        change it. The extension's ``extra`` must match the resulting schema's;
        pass its ``.schema`` dict instead for a raw merge that ignores that.
        """
        if not isinstance(self.schema, dict):
            message = "extend is only valid on a mapping schema"
            raise SchemaError(message)
        result_required = self.required if required is None else required
        result_extra = self.extra if extra is None else extra
        if isinstance(schema, Schema):
            if schema.extra != result_extra:
                message = (
                    "extend cannot preserve the extension Schema's extra when it "
                    "differs from the resulting Schema's extra; pass its .schema "
                    "dict explicitly for a raw merge"
                )
                raise SchemaError(message)
            schema = self._normalize_schema_extension(
                schema.schema,
                schema_required=schema.required,
                result_required=result_required,
            )
        if not isinstance(schema, dict):
            message = "extend expects a mapping schema"
            raise SchemaError(message)
        merged = dict(self.schema)
        for key, value in schema.items():
            # ``pop`` finds the existing key by its literal (markers hash by their
            # underlying key), so a bare key overrides a ``Required`` one.
            existing = merged.pop(key, None)
            # When both sides are mappings, merge them recursively rather than
            # replacing wholesale, so an extension touching one nested key keeps
            # the base's other nested keys (voluptuous semantics).
            if isinstance(existing, dict) and isinstance(value, dict):
                merged[key] = Schema(existing).extend(value).schema
            else:
                merged[key] = value
        # Rebuild as the same class, so extending a Schema subclass returns that
        # subclass (voluptuous PR, parity with ``type(self)``).
        return type(self)(merged, required=result_required, extra=result_extra)

    @staticmethod
    def _normalize_schema_extension(
        schema: Any,
        *,
        schema_required: bool,
        result_required: bool,
    ) -> Any:
        """Pin an extension Schema's required intent before its keys are merged.

        A bare key carries the extension Schema's ``required`` setting, which is
        lost once the keys are merged and recompiled under the resulting schema's
        setting. So a bare key becomes ``Required`` when the extension required it,
        or ``Optional`` when only the result is required; nested mappings are
        normalized the same way. Explicit markers and ``Extra`` pass through.
        """
        if not isinstance(schema, dict):
            return schema
        result: dict[Any, Any] = {}
        for key, value in schema.items():
            normalized_key = key
            if key is not Extra and not isinstance(key, Marker):
                if schema_required:
                    normalized_key = Required(key)
                elif result_required:
                    normalized_key = Optional(key)
            result[normalized_key] = Schema._normalize_schema_extension(
                value,
                schema_required=schema_required,
                result_required=result_required,
            )
        return result

    # The serde loaders are imported lazily inside these convenience methods, so
    # the validation engine does not pull in the I/O layer (and its optional-backend
    # probing) just by being imported.

    def load_json(self, source: Any) -> Any:
        """Parse JSON from ``source`` and validate it against this schema."""
        from probatio.serde import load_json  # noqa: PLC0415

        return self(load_json(source))

    def load_yaml(self, source: Any) -> Any:
        """Parse YAML from ``source`` and validate it against this schema."""
        from probatio.serde import load_yaml  # noqa: PLC0415

        return self(load_yaml(source))

    def load_toml(self, source: Any) -> Any:
        """Parse TOML from ``source`` and validate it against this schema."""
        from probatio.serde import load_toml  # noqa: PLC0415

        return self(load_toml(source))

    def load(self, source: Any, format: str | None = None) -> Any:  # noqa: A002
        """Parse ``source`` (format auto-detected from a path) and validate it."""
        from probatio.serde import load  # noqa: PLC0415

        return self(load(source, format))

    def _compile(self, schema: Any) -> CompiledSchema:  # noqa: PLR0911
        """Dispatch a schema node to the right compiler for its kind."""
        if schema is Self:
            return self._compile_self()
        if isinstance(schema, type):
            return self._compile_type(schema)
        # Object subclasses dict, so it has to be matched before the dict branch.
        if isinstance(schema, Object):
            return self._compile_object(schema)
        if isinstance(schema, dict):
            return self._compile_dict(schema)
        if isinstance(schema, list | tuple | set | frozenset):
            return self._compile_sequence(schema)
        if callable(schema):
            # A combinator compiles its branches at construction with the strict
            # default extra. When this schema sets a different policy, rebind the
            # combinator so the policy reaches dict schemas nested inside it
            # (matching voluptuous), on a copy so the shared instance is untouched.
            if self.extra != PREVENT_EXTRA:
                rebind = getattr(schema, "__probatio_with_extra__", None)
                if rebind is not None:
                    schema = rebind(self.extra)
            # probatio's own validators always raise Invalid (never leak a
            # ValueError), so they can be called directly. Arbitrary callables go
            # through the guard that turns a ValueError into an Invalid.
            return (
                cast("CompiledSchema", schema)
                if getattr(schema, "__probatio_safe__", False)
                else self._compile_callable(schema)
            )
        return self._compile_literal(schema)

    def _compile_dict(self, schema: dict[Any, Any]) -> CompiledSchema:
        """Compile a mapping schema into a candidate-matching validator."""
        candidates = [self._make_candidate(k, v) for k, v in schema.items()]
        # An Extra catch-all is tried after every named key, regardless of where
        # it sits in the schema dict (matching voluptuous).
        candidates.sort(key=lambda candidate: candidate.key_schema is Extra)
        return _MappingValidator(candidates, self.extra)

    def _compile_object(self, schema: Object) -> CompiledSchema:
        """Compile an Object schema: validate attributes, then rebuild the object."""
        candidates = [self._make_candidate(k, v) for k, v in schema.items()]
        candidates.sort(key=lambda candidate: candidate.key_schema is Extra)
        mapping = _MappingValidator(candidates, self.extra, invalid_msg="object value")
        return _ObjectValidator(mapping, schema.cls)

    def _compile_sequence(self, schema: Collection[Any]) -> CompiledSchema:
        """Compile a sequence or set; each item must match one element schema.

        A ``Remove`` element matches like its wrapped schema, but a matching item
        is dropped from the result instead of kept (voluptuous semantics), so
        ``[Remove(1), int]`` strips every ``1`` and validates the rest.
        """
        element_checks: list[CompiledSchema] = []
        remove_flags: list[bool] = []
        for element in schema:
            if isinstance(element, Remove):
                element_checks.append(self._compile(element.schema))
                remove_flags.append(True)
            else:
                element_checks.append(self._compile(element))
                remove_flags.append(False)
        # Match on the broad category (list/tuple/set/frozenset), not the schema's
        # exact type, so a schema written as a namedtuple instance still accepts a
        # plain tuple (voluptuous semantics). A namedtuple is a tuple subclass, so
        # it lands on ``tuple``.
        schema_type = type(schema)
        base_type = next(
            base
            for base in (list, tuple, set, frozenset)
            if issubclass(schema_type, base)
        )
        return _SequenceValidator(base_type, element_checks, remove_flags)

    def _make_candidate(self, key: Any, value_schema: Any) -> _Candidate:
        """Turn one ``schema`` item into a compiled candidate."""
        if key is Extra:
            # A catch-all: it matches any key (its check_key returns the key
            # unchanged) and validates the value, so unmatched keys are kept and
            # checked rather than rejected by the extra-key policy.
            return _Candidate(
                key_schema=Extra,
                check_key=_match_any_key,
                check_value=self._compile(value_schema),
                required=False,
                default=UNDEFINED,
                remove=False,
                is_literal=False,
            )
        if isinstance(key, Marker):
            key_schema = key.schema
            default = (
                key.default
                if isinstance(key, Required | Optional | Alias)
                else UNDEFINED
            )
            # An Alias carries its own required flag and is self-contained, so a
            # schema-wide ``required`` does not force it (like Optional).
            required = (
                isinstance(key, Required)
                or (isinstance(key, Alias) and key.required)
                or (
                    self.required
                    and not isinstance(key, Optional | Remove | Forbidden | Alias)
                )
            )
        else:
            key_schema = key
            default = UNDEFINED
            required = self.required
        is_literal = not (isinstance(key_schema, type) or callable(key_schema))
        check_value = self._compile(value_schema)
        check_key = self._compile(key_schema)
        return _Candidate(
            key_schema=key_schema,
            check_key=check_key,
            check_value=check_value,
            required=required,
            default=default,
            remove=isinstance(key, Remove),
            forbidden=isinstance(key, Forbidden),
            is_literal=is_literal,
            exclusive_group=(
                key.group_of_exclusion if isinstance(key, Exclusive) else None
            ),
            exclusive_required=(
                key.group_required if isinstance(key, Exclusive) else False
            ),
            inclusive_group=(
                key.group_of_inclusion if isinstance(key, Inclusive) else None
            ),
            msg=key.msg if isinstance(key, Marker) else None,
            value_type=getattr(check_value, "checked_type", None),
            key_type=getattr(check_key, "checked_type", None),
            complex_keys=(
                # Required(Any("a", "b")): the candidate keys, so a "none present"
                # failure can report "at least one of [...] is required". Read by
                # attribute to avoid importing Any (circular with combinators).
                list(key_schema.validators)
                if isinstance(key, Required)
                and getattr(key_schema, "is_complex_key", False)
                else None
            ),
            alias_input_names=key.input_names if isinstance(key, Alias) else (),
        )

    def _compile_self(self) -> CompiledSchema:
        """Compile a ``Self`` reference to a deferred call to the root schema.

        ``Self`` as a direct mapping value or sequence element is compiled within
        the enclosing schema, and binds to it immediately. Inside a combinator
        (``Any(Self, ...)``) it is compiled eagerly as its own ``Schema(Self)``,
        so it has no enclosing mapping yet; it is deferred and resolved at
        validation time. A bare ``Schema(Self)`` (Self with nothing around it) has
        no enclosing schema at all and is a definition error.
        """
        root = _COMPILING_ROOT.get()
        if root is not None and root.schema is not Self:
            # Direct Self: bind to the enclosing schema now.
            def validate(data: Any) -> Any:
                """Validate recursively against the enclosing schema, depth-guarded."""
                with recursion_guard():
                    # root is the enclosing Schema; reading its compiled engine
                    # here lets recursion follow whatever engine it is now on.
                    return root._compiled(data)  # noqa: SLF001

            return validate

        if not _COMPILING_FOR_COMBINATOR.get():
            # A bare Schema(Self), or Self wrapped by a validator that compiles it
            # outside a combinator: there is no enclosing schema to resolve against.
            message = (
                "Self must be a mapping value, sequence element, or combinator "
                "branch, not a schema on its own"
            )
            raise SchemaError(message)

        return _deferred_self

    @staticmethod
    def _compile_type(schema: type) -> CompiledSchema:
        """Compile a type into an isinstance check, or its self-validation (ADR-007).

        A type that knows how to validate a raw value of itself takes precedence
        over the bare ``isinstance``: a ``__probatio_validate__`` classmethod is
        used as the validator (normalized like any callable), and an ``Enum``
        subclass gets value-or-member coercion. Everything else returns a
        ``_TypeCheck``, whose ``checked_type`` the mapping and sequence engines
        read to inline the ``isinstance`` into their loops and skip a call per
        value. Called directly (when not inlined) it behaves like the closure.
        """
        protocol = getattr(schema, "__probatio_validate__", None)
        if callable(protocol):
            return Schema._compile_callable(protocol)
        if issubclass(schema, Enum):
            return _EnumCheck(schema)
        return _TypeCheck(schema)

    @staticmethod
    def _compile_callable(schema: Callable[[Any], Any]) -> CompiledSchema:
        """Compile a callable validator, normalizing the errors it may raise."""

        def validate(data: Any) -> Any:
            """Run the callable, turning a ValueError into an Invalid.

            A standard-library or user callable raises ``ValueError`` with a
            reason ("invalid isoformat string", say). voluptuous discards that
            reason and reports a bare "not a valid value"; probatio keeps it, so
            the message tells you why. The detail is appended only when the
            exception carries one (carry-forward of voluptuous issue #417).
            """
            try:
                return schema(data)
            except Invalid:
                raise
            except ValueError as exc:
                detail = str(exc)
                message = (
                    f"not a valid value: {detail}" if detail else "not a valid value"
                )
                raise ValueInvalid(message) from exc

        return validate

    @staticmethod
    def _compile_literal(schema: Any) -> CompiledSchema:
        """Compile a literal into an equality check."""

        def validate(data: Any) -> Any:
            """Require the value to equal the literal."""
            if data != schema:
                message = "not a valid value"
                raise ScalarInvalid(message)
            return data

        return validate


def compile_schema(
    schema: Any,
    required: bool = False,  # noqa: FBT001, FBT002
    extra: int = PREVENT_EXTRA,
) -> CompiledSchema:
    """Compile a schemable into its raw validating callable.

    The compiler service the combinators use to compile their sub-schemas without
    reaching into a ``Schema``'s internals. It returns the callable that raises
    ``Invalid`` on failure; it does not wrap a lone error in ``MultipleInvalid``
    (that is ``Schema.__call__``'s job, which the structural validators compose).

    ``required`` propagates into mapping sub-schemas, the way voluptuous applies a
    combinator's ``required`` to the schemas it wraps. ``extra`` is the enclosing
    schema's extra-key policy, propagated into dict schemas nested in the
    combinator (also matching voluptuous); it defaults to ``PREVENT_EXTRA``, so a
    combinator built on its own keeps the strict default.
    """
    # Flag the compile so a ``Self`` wrapped here (``Any(Self, ...)``) is deferred
    # to validation time rather than rejected as a bare ``Schema(Self)`` would be.
    token = _COMPILING_FOR_COMBINATOR.set(True)
    try:
        return Schema(schema, required=required, extra=extra)._compiled  # noqa: SLF001
    finally:
        _COMPILING_FOR_COMBINATOR.reset(token)
