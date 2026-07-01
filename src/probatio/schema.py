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
import threading
from contextvars import ContextVar
from enum import Enum
from typing import TYPE_CHECKING, Any, cast

from probatio._codegen import compile_mapping, compile_sequence
from probatio._compile_policy import CompilePolicy, get_compile_policy
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
    resolve_key,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Collection

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


class recursion_guard:  # noqa: N801 - a context manager, named like contextlib's
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

    A plain class rather than ``@contextmanager``: it sits on the per-level
    recursion hot path, and skipping the generator machinery is roughly twice as
    fast per ``with``.
    """

    __slots__ = ("_cost", "_token")

    def __init__(self, cost: int = 1) -> None:
        """Store how much this level costs against the shared depth budget."""
        self._cost = cost

    def __enter__(self) -> None:
        """Charge one level, raising ``Invalid`` if the budget is exceeded."""
        depth = _SELF_DEPTH.get() + self._cost
        if depth > sys.getrecursionlimit() // _SELF_DEPTH_DIVISOR:
            message = "data is nested too deeply for this recursive schema"
            raise Invalid(message)
        self._token = _SELF_DEPTH.set(depth)

    def __exit__(self, *exc: object) -> None:
        """Release this level's charge back to the budget."""
        _SELF_DEPTH.reset(self._token)


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
    # A validator that wraps other schemas (a combinator, a sequence shaper,
    # ``Maybe``/``Msg``) exposes them through ``__probatio_child_schemas__``, so the
    # walk reaches them without guessing which attribute each stored them under.
    child_schemas = getattr(node, "__probatio_child_schemas__", None)
    if child_schemas is not None:
        return any(_schema_uses_self(child) for child in child_schemas())
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


# The extra-key policy rendered as its public name, for ``repr`` (matches
# voluptuous, which shows the policy a Schema was built with).
_EXTRA_TO_NAME = {
    PREVENT_EXTRA: "PREVENT_EXTRA",
    ALLOW_EXTRA: "ALLOW_EXTRA",
    REMOVE_EXTRA: "REMOVE_EXTRA",
}

# Under the AUTO policy, a schema validates interpreted until it has been called
# this many times, then compiles once. Compiling saves roughly 1 us per validation,
# but the cost is sharply asymmetric: the first schema of a shape pays the full code
# generation (~430 us, break-even ~360 calls), while every later schema of the same
# shape reuses the cached code object (see _codegen._compile_source) and pays only
# ~20 us (break-even ~20 calls). So compiling almost never pays for one schema on its
# own; it pays through reuse, the first instance populating the cache for the rest.
# A single conservative "recurring, not a one-shot" threshold captures that: the
# first-of-shape gambles here, and if the shape recurs the others ride the cache.
#
# Making this shape-aware (compile sooner when the shape is already cached) was
# measured and rejected: knowing whether a shape is cached needs its source string,
# the cache key, so the probe has to build the source, which costs about as much as a
# cache-hit compile itself. There is no cheap "should I compile yet" check, so a flat
# threshold beats a probe. It is an internal default, not tunable.
_AUTO_COMPILE_THRESHOLD = 50

# Serializes the one-time bootstrap transition (the pop of ``_interpreted`` and the
# swap of ``_compiled``) so two threads hitting a cold schema at once cannot leave one
# of them re-entering ``_bootstrap`` against a half-swapped ``_compiled``. It is held
# only for that swap, never for validation itself, so the steady state and the AUTO
# counter stay lock-free; a module-level lock keeps armed schemas from each carrying
# their own. Concurrency is documented on the Performance page.
_BOOTSTRAP_LOCK = threading.Lock()


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
        *,
        compile: bool | None = None,  # noqa: A002 - the public, re.compile-style name
    ) -> None:
        """Compile ``schema``; ``required`` and ``extra`` govern mapping keys.

        ``required`` and ``extra`` are positional to match voluptuous, so
        ``Schema({...}, True, ALLOW_EXTRA)`` keeps working.

        ``compile`` opts this schema into a specialized, faster validator: ``True``
        always, ``False`` never, ``None`` (the default) defers to the process-wide
        :func:`set_compile_policy`. Compiled and interpreted schemas validate
        identically; the flag only affects speed. Generation is lazy: a schema builds
        its specialized validator on first use (or eagerly through :meth:`compile`),
        and any shape the generator does not handle stays on the interpreted engine.
        """
        self.schema = schema
        self.required = required
        self.extra = extra
        # ``None`` defers to the policy, resolved lazily in ``_should_compile`` so a
        # policy set after this schema was built (at import time) still applies.
        self._compile_requested = compile
        # Whether ``Self`` appears anywhere in the definition. This is discovered
        # during the compile walk below (set on the first ``Self`` reached, and on
        # a combinator/wrapper branch that holds one), so the tree is walked once,
        # not a second time by a standalone pre-pass. Only a recursive schema then
        # records an active root when validated, a contextvar that is not free, so
        # a non-recursive schema, the common case, skips that cost entirely.
        self._uses_self = False
        # Mark self as the root while compiling, so a ``Self`` inside this schema
        # resolves here. Tokens nest correctly, so a nested Schema restores the
        # outer root on exit.
        token = _COMPILING_ROOT.set(self)
        try:
            self._compiled = self._compile(schema)
        finally:
            _COMPILING_ROOT.reset(token)
        self._arm_compile()

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

    def __str__(self) -> str:
        """Render as the wrapped schema, matching voluptuous.

        Callers ``str()`` a Schema to inspect the shape it wraps. Home Assistant's
        config classifier reads a leading ``{`` or ``[`` to tell dict- from
        list-based config, so this delegates to the inner schema rather than
        returning the default object repr.
        """
        return str(self.schema)

    def __repr__(self) -> str:
        """Render as voluptuous does: the inner schema, extra policy, and required."""
        extra = _EXTRA_TO_NAME.get(self.extra, "??")
        return (
            f"<Schema({self.schema}, extra={extra}, "
            f"required={self.required}) object at 0x{id(self):x}>"
        )

    def _should_compile(self) -> bool:
        """Resolve, lazily, whether this schema should use a compiled validator.

        The per-schema ``compile`` flag wins when set; an unset flag (``None``)
        falls back to the process-wide policy. Read on first use rather than at
        construction, so a policy set after this schema was built still applies.
        """
        if self._compile_requested is not None:
            return self._compile_requested
        # ON compiles on first use; AUTO compiles once the schema proves hot; OFF
        # never. Both ON and AUTO mean "set up to compile", so both arm.
        return get_compile_policy() is not CompilePolicy.OFF

    def compile(self) -> Schema:
        """Eagerly opt this schema into a compiled validator, and return ``self``.

        The explicit twin of ``compile=True``, spelled to mirror ``re.compile``. It
        wins over a ``compile=False`` flag, because calling it is a more explicit
        request than the construction-time default. Unlike the flag, it generates
        now rather than on first use. A schema shape the generator does not handle
        stays interpreted (and identical); only the speedup is lost.
        """
        self._compile_requested = True
        # Resolve now. A schema armed for lazy compilation keeps the interpreted
        # validator in ``_interpreted``; otherwise ``_compiled`` is still it.
        interpreted = self.__dict__.pop("_interpreted", self._compiled)
        self._compiled = self._compile_from(interpreted)
        return self

    def _arm_compile(self) -> None:
        """Set up first-use compilation when this schema is eligible.

        Eligibility is decided now from the flag and the current policy, so the
        common default (policy off, no flag) arms nothing and pays nothing. An
        eligible schema swaps its validator for a one-shot bootstrap that generates
        on the first call, keeping construction cheap: no code generation at import.
        """
        if not self._should_compile() or not self._compilable():
            # ``compile=False`` or the off policy arms nothing (the default pays
            # nothing). A literal, type, or sequence schema never generates, so
            # arming it would only add a bootstrap a combinator could capture.
            return

        self._interpreted: CompiledSchema = self._compiled
        self._compiled = self._bootstrap

    def _compilable(self) -> bool:
        """Report whether this schema is a shape the generator can compile."""
        return not self._uses_self and isinstance(
            self._compiled, (_MappingValidator, _SequenceValidator)
        )

    def _bootstrap(self, data: Any) -> Any:
        """Resolve compilation on the first call, then validate ``data``.

        Reads the policy here (so one set after construction still applies) and
        installs the right validator: the generated one now for the flag or the ON
        policy, an adaptive counter for AUTO, or the interpreted one if the policy
        turned off since arming. A combinator may have captured this bootstrap as a
        branch before the swap; a later call through that stale reference finds
        ``_interpreted`` gone and just delegates to the resolved validator.

        The pop and the swap run under ``_BOOTSTRAP_LOCK`` so two threads racing a
        cold schema resolve it once: the loser finds ``_interpreted`` gone and the
        ``_compiled`` already swapped, so it delegates instead of re-entering this
        bootstrap against a half-installed validator. The lock covers only the swap,
        not the validation call after it.
        """
        with _BOOTSTRAP_LOCK:
            interpreted = self.__dict__.pop("_interpreted", None)
            if interpreted is not None:
                flag = self._compile_requested
                if flag is None and get_compile_policy() is CompilePolicy.AUTO:
                    self._compiled = self._auto_counter(interpreted)
                elif self._should_compile():
                    self._compiled = self._compile_from(interpreted)
                else:
                    self._compiled = interpreted

        return self._compiled(data)

    def _auto_counter(self, interpreted: CompiledSchema) -> CompiledSchema:
        """Return a validator that counts calls and compiles once the schema is hot.

        Below the threshold it validates interpreted, paying only a counter; at the
        threshold it generates once and installs the compiled validator. A one-shot
        schema never reaches the threshold, so it is never compiled. A combinator
        that captured this counter keeps delegating through it to the compiled
        validator after the swap.
        """
        calls = 0

        def validate(data: Any) -> Any:
            nonlocal calls
            calls += 1
            if calls == _AUTO_COMPILE_THRESHOLD:
                self._compiled = self._compile_from(interpreted)
            if calls >= _AUTO_COMPILE_THRESHOLD:
                return self._compiled(data)
            return interpreted(data)

        return validate

    def _compile_from(self, interpreted: CompiledSchema) -> CompiledSchema:
        """Return a generated validator built from ``interpreted``, or it unchanged.

        A non-recursive simple mapping or single-element list schema is generatable
        here; any other shape keeps its interpreted validator. ``DataclassSchema``
        overrides this to fuse the construction step in.
        """
        if self._uses_self:
            return interpreted

        if isinstance(interpreted, _MappingValidator):
            generated = compile_mapping(interpreted)
        elif isinstance(interpreted, _SequenceValidator):
            generated = compile_sequence(self.schema, interpreted)
        else:
            return interpreted

        return generated if generated is not None else interpreted

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
        schema: Schemable,
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
            self._uses_self = True
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
                # Rebinding only matters when a branch holds a nested mapping (the
                # policy changes how a dict compiles); a combinator of types and
                # lists compiles identically, so skip the copy and recompile.
                needs = getattr(schema, "__probatio_needs_extra__", None)
                if rebind is not None and (needs is None or needs()):
                    schema = rebind(self.extra)

            # A combinator or wrapper compiled its own branches at construction, so
            # the compile walk never descends into them; detect a ``Self`` nested in
            # one on the branch node itself. Only a node that holds child schemas
            # (``validators``/``validator``) can carry a nested ``Self``, so a plain
            # leaf validator skips the walk entirely.
            if not self._uses_self and (
                hasattr(schema, "validators") or hasattr(schema, "validator")
            ):
                self._uses_self = _schema_uses_self(schema)

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

        # Walk the marker chain into its facets: the bare key, the presence marker
        # that governs it, and whether it is Secret (redact its value on failure).
        # ``Secret`` composes by nesting (``Optional(Secret("password"))``), so the
        # presence marker may sit above or below it.
        facets = resolve_key(key)
        # Typed ``Any`` so the facet-specific attributes (``group_of_exclusion``,
        # ``input_names``) read cleanly under their ``is_*`` guards, the way the
        # raw key did before markers were resolved into facets.
        marker: Any = facets.marker
        key_schema = facets.key
        is_marker = marker is not None
        if is_marker:
            # Classify the marker's kind once, then reuse the flags below rather
            # than re-running overlapping isinstance checks per attribute. Subtypes
            # are honored (Inclusive and Exclusive are Optional), so the dispatch
            # stays correct for a custom marker subclass too.
            is_required = isinstance(marker, Required)
            is_optional = isinstance(marker, Optional)
            is_alias = isinstance(marker, Alias)
            is_remove = isinstance(marker, Remove)
            is_forbidden = isinstance(marker, Forbidden)
            is_exclusive = isinstance(marker, Exclusive)
            is_inclusive = isinstance(marker, Inclusive)
            default = (
                marker.default
                if (is_required or is_optional or is_alias)
                else UNDEFINED
            )
            # An Alias carries its own required flag and is self-contained, so a
            # schema-wide ``required`` does not force it (like Optional).
            required = (
                is_required
                or (is_alias and marker.required)
                or (
                    self.required
                    and not (is_optional or is_remove or is_forbidden or is_alias)
                )
            )
        else:
            # A bare key (or a key wrapped only in ``Secret``, which carries no
            # presence semantics of its own) is none of the marker kinds.
            is_required = is_optional = is_alias = is_remove = False
            is_forbidden = is_exclusive = is_inclusive = False
            default = UNDEFINED
            required = self.required

        is_literal = not (isinstance(key_schema, type) or callable(key_schema))
        if facets.secret and not is_literal:
            # Redaction names a specific field, so ``Secret`` wraps a concrete key,
            # not a type or callable key schema (``Secret(str)`` would mean "redact
            # every string-keyed value", which is not what the marker is for).
            message = "Secret must wrap a concrete key, not a type or callable"
            raise SchemaError(message)
        check_value = self._compile(value_schema)
        check_key = self._compile(key_schema)

        return _Candidate(
            key_schema=key_schema,
            check_key=check_key,
            check_value=check_value,
            required=required,
            default=default,
            remove=is_remove,
            forbidden=is_forbidden,
            is_literal=is_literal,
            secret=facets.secret,
            exclusive_group=(marker.group_of_exclusion if is_exclusive else None),
            exclusive_required=(marker.group_required if is_exclusive else False),
            inclusive_group=(marker.group_of_inclusion if is_inclusive else None),
            msg=facets.msg,
            value_type=getattr(check_value, "checked_type", None),
            key_type=getattr(check_key, "checked_type", None),
            complex_keys=(
                # Required(Any("a", "b")): the candidate keys, so a "none present"
                # failure can report "at least one of [...] is required". Read by
                # attribute to avoid importing Any (circular with combinators).
                list(key_schema.validators)
                if is_required and getattr(key_schema, "is_complex_key", False)
                else None
            ),
            alias_input_names=marker.input_names if is_alias else (),
            value_schema=value_schema,
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
        # Inside a combinator, Self always defers to the root being validated. A
        # combinator compiles its branches before the enclosing schema exists, so
        # any _COMPILING_ROOT reached here is an intermediate branch schema, not the
        # schema Self refers to. In Any({key: Self}, str) the dict branch compiles
        # as its own Schema and would capture Self; binding to it would trap the
        # recursion in that one branch, so a string leaf never falls through to the
        # sibling str branch. Deferring re-runs the whole combinator instead.
        if _COMPILING_FOR_COMBINATOR.get():
            return _deferred_self

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

        # A bare Schema(Self), or Self wrapped by a validator that compiles it
        # outside a combinator: there is no enclosing schema to resolve against.
        message = (
            "Self must be a mapping value, sequence element, or combinator "
            "branch, not a schema on its own"
        )
        raise SchemaError(message)

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
