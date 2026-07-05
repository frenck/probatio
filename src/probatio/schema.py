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

import threading
from contextvars import ContextVar
from typing import Any

from probatio import _compile as _compile_module
from probatio._build_policy import BuildPolicy, get_build_policy
from probatio._codegen import compile_mapping, compile_sequence
from probatio._compile import (
    _ACTIVE_ROOT,
    _COMPILING_FOR_COMBINATOR,
    _COMPILING_ROOT,
    CompileCtx,
    compile_node,
)
from probatio._compile_policy import CompilePolicy, get_compile_policy
from probatio._engine import (
    ALLOW_EXTRA,
    PREVENT_EXTRA,
    REMOVE_EXTRA,
    CompiledSchema,
    _MappingValidator,
    _SequenceValidator,
)
from probatio.error import (
    Invalid,
    MultipleInvalid,
    SchemaError,
)
from probatio.markers import (
    Extra,
    Marker,
    Optional,
    Required,
)

# ``_COMPILING_ROOT``/``_COMPILING_FOR_COMBINATOR`` (compile time) and
# ``_ACTIVE_ROOT`` (validation time) live in ``_compile`` alongside the walk that
# reads them; ``Schema`` imports them to set the root it is building or validating.

# The context passed to ``schema(data, context=...)``, visible to any validator
# during the call through ``current_context()``. Default None, and only set when a
# call actually passes a context, so the common path pays nothing. A nested call
# that passes its own context overrides it for that subtree; one that passes none
# inherits the enclosing call's.
_VALIDATION_CONTEXT: ContextVar[Any] = ContextVar(
    "probatio_validation_context",
    default=None,
)

# True while an internal builder (a combinator branch through ``compile_schema``, a
# dataclass/TypedDict inner) constructs a ``Schema`` whose compiled form it reads
# immediately. Such a schema must build eagerly even under the LAZY policy, so the
# deferral applies only to a top-level user schema.
_INTERNAL_BUILD: ContextVar[bool] = ContextVar(
    "probatio_internal_build",
    default=False,
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

# Serializes a lazy schema's first build across threads. Reentrant, because building
# one schema recursively forces any lazily-deferred nested schema to build (a nested
# mapping reused as a value), which re-enters on the same thread; a plain lock would
# deadlock there. Held only for the one-time build, never for validation.
_BUILD_LOCK = threading.RLock()


class Schema:
    """A compiled, callable schema.

    Build it from a type, a literal, a callable, or a nested ``Schema``, then
    call it with a value to validate that value.
    """

    # The active validator: the compiled engine, the compile bootstrap, or, under
    # the LAZY policy before first use, the ``_lazy_build`` stub (all callables of a
    # value). Declared so every assignment site checks against the one type.
    _compiled: CompiledSchema

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
        self._built = False
        # Under the LAZY build policy a top-level user schema defers its compile walk
        # to first validation, so one that is built but never validated (an unused
        # service, trigger, or websocket schema registered at startup) never pays to
        # build and never holds its validator tree. The default stays EAGER, so the
        # drop-in promise holds: a malformed schema still raises where it is defined.
        # Only a plain top-level schema defers; a combinator branch, a dataclass or
        # TypedDict inner (``_INTERNAL_BUILD``), a subclass, or an explicit
        # ``compile=`` request builds now, since their compiled form is read at once.
        if (
            type(self) is Schema
            and compile is None
            and not _INTERNAL_BUILD.get()
            and get_build_policy() is BuildPolicy.LAZY
        ):
            self._compiled = self._lazy_build
        else:
            self._build()

    def _build(self) -> None:
        """Compile the declaration into the validator engine.

        Split from ``__init__`` so the LAZY policy can defer it to first use. Marks
        ``self`` the root while compiling, so a ``Self`` inside resolves here; tokens
        nest, so a nested Schema restores the outer root on exit. The walk lives in
        ``_compile`` as free functions; a small context carries the policies it reads
        and reports back whether a ``Self`` was seen.
        """
        ctx = CompileCtx(self.extra, self.required)
        token = _COMPILING_ROOT.set(self)
        try:
            self._compiled = compile_node(self.schema, ctx)
        finally:
            _COMPILING_ROOT.reset(token)
        self._uses_self = ctx.uses_self
        self._built = True
        self._arm_compile()

    def _ensure_built(self) -> None:
        """Force a lazily-deferred schema to build now; a no-op once built.

        Called wherever the compiled form is needed directly (a nested schema being
        compiled into a parent, ``compile()``), so laziness never leaks a half-built
        schema. The lock serializes concurrent first-touches, like the compile
        bootstrap; the double check keeps the built steady state lock-free.
        """
        if not self._built:
            with _BUILD_LOCK:
                # The re-check's false edge (another thread built it between the
                # lock-free check and the lock) is reachable only under contention.
                if not self._built:  # pragma: no branch
                    self._build()

    def _lazy_build(self, data: Any) -> Any:
        """First-call stub for a lazy schema: build, then validate through the real path.

        Re-enters ``self`` once the real validator is installed and ``_uses_self`` is
        known, so recursion and error wrapping take the correct path; the active
        context, if any, is still set on the enclosing frame and inherited here.
        """
        self._ensure_built()
        return self(data)

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
        # A lazily-deferred schema must build before it can be compiled from.
        self._ensure_built()
        # Resolve now. A schema armed for lazy compilation keeps the interpreted
        # validator in ``_interpreted``; otherwise ``_compiled`` is still it. The
        # swap lands before ``_interpreted`` is dropped: a combinator holding the
        # armed bootstrap reads "``_interpreted`` gone" as "``_compiled`` is
        # final", so the reverse order would hand it the bootstrap itself.
        interpreted = self.__dict__.get("_interpreted", self._compiled)
        self._compiled = self._compile_from(interpreted)
        self.__dict__.pop("_interpreted", None)
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
        branch before the swap; every later call through that stale reference lands
        here forever, so the resolved case must stay cheap: it is a lock-free
        membership test and a delegation, not a lock acquisition per call.

        The lock-free check is sound because of the resolver's write order: the
        final validator is stored in ``_compiled`` *before* ``_interpreted`` is
        deleted (both under ``_BOOTSTRAP_LOCK``), so "``_interpreted`` gone" always
        means "``_compiled`` is final". Two threads racing a cold schema still
        resolve it once: the loser blocks on the lock, finds ``_interpreted``
        gone, and delegates. The lock covers only the swap, not the validation
        call after it.
        """
        if "_interpreted" not in self.__dict__:
            return self._compiled(data)

        with _BOOTSTRAP_LOCK:
            interpreted = self.__dict__.get("_interpreted")
            # ``None`` only when another thread resolved the schema between the
            # lock-free check above and taking the lock, so the false edge is
            # reachable only under contention (the race test hits it by chance).
            if interpreted is not None:  # pragma: no branch
                flag = self._compile_requested
                if flag is None and get_compile_policy() is CompilePolicy.AUTO:
                    self._compiled = self._auto_counter(interpreted)
                elif self._should_compile():
                    self._compiled = self._compile_from(interpreted)
                else:
                    self._compiled = interpreted
                # Deleted only after the swap above, so the lock-free check can
                # never observe the transition half-done.
                del self.__dict__["_interpreted"]

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
    # ``_INTERNAL_BUILD`` forces the branch eager under the LAZY policy: the
    # combinator reads its ``_compiled`` here and now, so it cannot be deferred.
    token = _COMPILING_FOR_COMBINATOR.set(True)
    internal = _INTERNAL_BUILD.set(True)
    try:
        return Schema(schema, required=required, extra=extra)._compiled  # noqa: SLF001
    finally:
        _COMPILING_FOR_COMBINATOR.reset(token)
        _INTERNAL_BUILD.reset(internal)


# Register ``Schema`` with the compile walk, which lives in ``_compile`` and needs
# the class for one ``isinstance`` check (a nested ``Schema`` reused as a value).
# Set here, after the class exists, so ``_compile`` never imports this module and
# the two stay free of an import cycle. Ready before any schema is built.
_compile_module._SCHEMA_CLS = Schema  # noqa: SLF001
