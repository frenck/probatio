"""Build a ``Schema`` from a dataclass or a TypedDict, driven by its annotations.

``create_dataclass_schema`` (and the ``DataclassSchema`` class around it) reads a
dataclass's fields and turns each annotation into a validator: a field validates
a plain dict, and a passing dict is turned into a dataclass instance. Fields with
a ``default`` or ``default_factory`` become ``Optional`` keys; the rest are
``Required``. ``additional_constraints`` layer extra validators onto chosen
fields with ``All``.

``create_typeddict_schema`` (and ``TypedDictSchema``) does the same for a
TypedDict, sharing the annotation mapping below. The difference is the output: a
TypedDict is a plain dict at runtime, so the validated mapping is returned as-is
(typed as the TypedDict), with nothing constructed.

This is a carry-forward of voluptuous PR #533 (issue #409), with a deliberately
richer type mapping: a parameterized generic keeps its element types
(``list[str]`` becomes ``[str]``, ``dict[str, int]`` becomes ``{str: int}``), a
nested dataclass recurses into its own schema, and ``X | None`` becomes
``Maybe(X)``. voluptuous's draft collapses a generic to its bare origin; probatio
validates all the way down. The names match the upstream draft so code written
against it keeps working if it lands.

A field annotation may also carry its own validators inline with
``Annotated[X, validator, ...]``: ``X`` is validated first, then each callable in
the metadata is applied through ``All`` (non-callable metadata is left for other
tools). A ``NewType`` is followed to the type it wraps. Both are an alternative to
the ``additional_constraints`` side mapping, with the constraint living next to
the field it guards.
"""

from __future__ import annotations

import dataclasses
import types
from collections.abc import (
    Mapping,
    MutableMapping,
    MutableSequence,
    MutableSet,
    Sequence,
)
from collections.abc import Set as AbstractSet
from typing import (
    Annotated,
    Literal,
    NotRequired,
    cast,
    get_args,
    get_origin,
    get_type_hints,
    is_typeddict,
)
from typing import Any as TypingAny
from typing import Required as RequiredHint
from typing import Union as TypingUnion

from probatio._type_registry import resolve_type_validator
from probatio.error import SchemaError
from probatio.markers import Optional, Required
from probatio.schema import (
    _INHERIT_CONTEXT,
    PREVENT_EXTRA,
    CompiledSchema,
    Schema,
    recursion_guard,
)
from probatio.validators import All, Any, ExactSequence, In, Maybe, Union

__all__ = [
    "DataclassSchema",
    "TypedDictSchema",
    "create_dataclass_schema",
    "create_typeddict_schema",
    "is_dataclass",
]

# One recursive-dataclass level runs the full validate-and-construct machinery
# (roughly four times the stack frames of a bare ``Self``), so each level counts
# more against the shared recursion budget, letting the guard fire before the real
# stack overflows.
_RECURSION_COST = 4


class _RecursiveSchemaRef:
    """A deferred reference to a dataclass schema still under construction.

    A self-referential (or mutually recursive) dataclass field cannot name its own
    schema while that schema is being built, so the field validates through this
    placeholder, bound to the finished schema once it exists. Each call is
    depth-guarded, so cyclic or pathologically deep data fails with a clean
    ``Invalid`` rather than overflowing the stack, exactly like ``Self``.
    """

    __slots__ = ("_validate",)

    def __init__(self) -> None:
        """Start unbound; ``bind`` fills in the compiled schema before any call."""
        self._validate: CompiledSchema | None = None

    def bind(self, schema: Schema) -> None:
        """Point the reference at the finished schema's compiled engine."""
        self._validate = schema._compiled  # noqa: SLF001

    def __call__(self, data: TypingAny) -> TypingAny:
        """Validate ``data`` against the bound schema, depth-guarded."""
        validate = self._validate
        if validate is None:  # pragma: no cover - bound before any validation runs
            message = "recursive dataclass reference used before it was bound"
            raise SchemaError(message)
        with recursion_guard(cost=_RECURSION_COST):
            return validate(data)


def is_dataclass(obj: TypingAny) -> bool:
    """Return whether ``obj`` is a dataclass type or instance.

    Thin wrapper over ``dataclasses.is_dataclass``, exposed under the probatio
    namespace so callers do not have to reach for the standard library too.
    """
    return dataclasses.is_dataclass(obj)


def _is_dataclass_type(annotation: TypingAny) -> bool:
    """Return whether an annotation is a dataclass *type* (not an instance)."""
    return isinstance(annotation, type) and dataclasses.is_dataclass(annotation)


def _annotation_to_schema(  # noqa: PLR0911, PLR0912
    annotation: TypingAny,
    self_refs: dict[type, _RecursiveSchemaRef],
) -> TypingAny:
    """Map a single type annotation to a probatio schema fragment.

    ``self_refs`` maps each dataclass type on the current build stack to its
    deferred reference. A field whose type is one of them (a self-referential or
    mutually recursive dataclass) becomes that reference instead of recursing
    forever, and the reference resolves once its schema is built.
    """
    if annotation is TypingAny:
        return object
    if annotation is None or annotation is type(None):
        return None
    if hasattr(annotation, "__supertype__"):
        # A ``NewType`` is a thin alias; validate against the type it wraps.
        return _annotation_to_schema(annotation.__supertype__, self_refs)
    if get_origin(annotation) is Annotated:
        # ``Annotated[X, *meta]``: validate ``X``, then apply any callable items
        # from the metadata as extra validators (in order, through ``All``).
        # Non-callable metadata belongs to other tools, so it is ignored.
        base, *meta = get_args(annotation)
        base_schema = _annotation_to_schema(base, self_refs)
        extras = [item for item in meta if callable(item)]
        return All(base_schema, *extras) if extras else base_schema
    if _is_dataclass_type(annotation):
        if annotation in self_refs:
            # A back-reference to a type still being built: use its deferred
            # reference, bound to the finished schema when that build returns.
            return self_refs[annotation]
        return create_dataclass_schema(annotation, _self_refs=self_refs)
    if is_typeddict(annotation):
        # A nested TypedDict validates as its own mapping schema (it cannot be an
        # ``isinstance`` check, since a TypedDict has no runtime type).
        if annotation in self_refs:
            return self_refs[annotation]
        return create_typeddict_schema(annotation, _self_refs=self_refs)
    origin = get_origin(annotation)
    if origin is None:
        # A plain type validates by isinstance, unless a validator is registered
        # for it (ADR-008), in which case that is used (read at build time and
        # baked in). Anything that is not a type accepts any value.
        if isinstance(annotation, type):
            registered = resolve_type_validator(annotation)
            return registered if registered is not None else annotation
        return object
    args = get_args(annotation)
    if origin in (TypingUnion, types.UnionType):
        return _union_to_schema(args, self_refs)
    if origin is Literal:
        return In(list(args))
    if not args:
        # A bare generic alias (``typing.List``, ``typing.Dict``): no element type
        # to descend into, so validate the container type itself.
        return origin
    if origin is list:
        return [_annotation_to_schema(args[0], self_refs)]
    if origin is set:
        return {_annotation_to_schema(args[0], self_refs)}
    if origin is frozenset:
        return frozenset([_annotation_to_schema(args[0], self_refs)])
    if origin is dict:
        return {
            _annotation_to_schema(args[0], self_refs): _annotation_to_schema(
                args[1],
                self_refs,
            ),
        }
    if origin is tuple:
        return _tuple_to_schema(args, self_refs)
    if origin in (Sequence, MutableSequence):
        # An abstract sequence validates element-wise like a list; config data
        # arrives as a list, and a str (also a Sequence) is correctly not one.
        return [_annotation_to_schema(args[0], self_refs)]
    if origin in (AbstractSet, MutableSet):
        return {_annotation_to_schema(args[0], self_refs)}
    if origin in (Mapping, MutableMapping):
        return {
            _annotation_to_schema(args[0], self_refs): _annotation_to_schema(
                args[1], self_refs
            ),
        }
    # Any other parameterized generic (``Iterable[int]``, a user generic): validate
    # the container type itself rather than silently accept any value, the same as a
    # bare generic alias. ``object`` only for the rare non-type origin.
    return origin if isinstance(origin, type) else object


def _union_to_schema(
    args: tuple[TypingAny, ...], self_refs: dict[type, _RecursiveSchemaRef]
) -> TypingAny:
    """Map a union: ``X | None`` becomes ``Maybe(X)``, a wider union becomes ``Any``.

    A union of dataclasses that share a literal tag field (a ``kind: Literal[...]``
    that is distinct per member) becomes a discriminated ``Union``: the tag picks
    the one branch to validate, instead of trying every member in order. Without
    such a tag it stays an ``Any``.
    """
    has_none = type(None) in args
    member_types = [a for a in args if a is not type(None)]
    members = [_annotation_to_schema(a, self_refs) for a in member_types]
    if len(members) == 1:
        inner: TypingAny = members[0]
    else:
        discriminant = _build_discriminant(member_types, members)
        inner = (
            Union(*members, discriminant=discriminant)
            if discriminant is not None
            else Any(*members)
        )
    return Maybe(inner) if has_none else inner


def _literal_tags(dataclass_type: type) -> dict[str, TypingAny]:
    """Return the fields of a dataclass typed as a single-value ``Literal``.

    These are the candidate tag fields for a discriminated union: a field annotated
    ``Literal["circle"]`` carries one fixed value that names the variant. The hints
    resolve cleanly here, since every member's schema was built (and its hints
    resolved) before this runs.
    """
    tags: dict[str, TypingAny] = {}
    for name, annotation in get_type_hints(dataclass_type).items():
        if get_origin(annotation) is Literal:
            values = get_args(annotation)
            if len(values) == 1:
                tags[name] = values[0]
    return tags


def _build_discriminant(
    member_types: list[TypingAny], members: list[TypingAny]
) -> TypingAny:
    """Build a discriminant for a union of tagged dataclasses, or None.

    Every member must be a dataclass, and they must share a tag field whose
    single-value ``Literal`` differs across members. The returned discriminant
    reads that field from the input and selects the one matching member.
    """
    if not all(_is_dataclass_type(member_type) for member_type in member_types):
        return None
    tag_maps = [_literal_tags(member_type) for member_type in member_types]
    common = set(tag_maps[0])
    for tags in tag_maps[1:]:
        common &= set(tags)
    for field_name in sorted(common):
        values = [tags[field_name] for tags in tag_maps]
        if len(set(values)) == len(values):
            # Distinct tag values: a clean discriminator. Map each to its member.
            by_value = dict(zip(values, members, strict=True))
            return _make_discriminant(field_name, by_value)
    return None


def _make_discriminant(
    field_name: str, by_value: dict[TypingAny, TypingAny]
) -> TypingAny:
    """Return a ``Union`` discriminant selecting a member by its tag field value."""

    def discriminant(value: TypingAny, validators: list[TypingAny]) -> list[TypingAny]:
        """Pick the member whose tag matches; fall back to all on a miss."""
        if isinstance(value, Mapping):
            try:
                match = by_value.get(value.get(field_name))
            except TypeError:
                # An unhashable tag value cannot index the map; treat as no match.
                match = None
            if match is not None:
                return [match]
        return validators

    return discriminant


def _tuple_to_schema(
    args: tuple[TypingAny, ...], self_refs: dict[type, _RecursiveSchemaRef]
) -> TypingAny:
    """Map a tuple: ``tuple[X, ...]`` is homogeneous, ``tuple[X, Y]`` is positional.

    Both accept a list or a tuple, since a sequence arrives as a list from JSON,
    and preserve whichever was given (the value is not coerced between them).
    """
    if len(args) == 2 and args[1] is Ellipsis:
        element = _annotation_to_schema(args[0], self_refs)
        return Any([element], (element,))
    return ExactSequence([_annotation_to_schema(a, self_refs) for a in args])


def _constant(value: TypingAny) -> TypingAny:
    """Return a zero-argument factory that yields ``value`` unchanged.

    A dataclass default is a literal, even when it happens to be a callable, so it
    is wrapped here: the marker calls a callable default to produce the value, and
    ``print`` as a field default must come back as ``print``, not its return value.
    """
    return lambda: value


def _iter_init_fields(dataclass_type: type) -> list[TypingAny]:
    """Return every constructor field of a dataclass, regular and ``InitVar``.

    ``dataclasses.fields`` drops ``InitVar`` pseudo-fields, but they are real
    constructor parameters (passed on to ``__post_init__``), so a schema that omits
    them cannot build the instance and leaks a ``TypeError``. The private
    ``_FIELD_INITVAR`` sentinel is the only reliable way to find them, since under
    ``from __future__ import annotations`` the field type is a bare string. An
    ``init=False`` field is not a constructor argument, so it is skipped. The
    private names are read through ``getattr`` so the types stay clean.
    """
    fields_map = getattr(dataclass_type, "__dataclass_fields__", {})
    regular = getattr(dataclasses, "_FIELD", object())
    initvar = getattr(dataclasses, "_FIELD_INITVAR", object())
    return [
        field
        for field in fields_map.values()
        if field.init and field._field_type in (regular, initvar)  # noqa: SLF001
    ]


def _field_annotation(hint: TypingAny) -> TypingAny:
    """Unwrap an ``InitVar[X]`` annotation to ``X``, leaving other hints untouched."""
    return hint.type if isinstance(hint, dataclasses.InitVar) else hint


def _field_mapping(
    dataclass_type: type,
    constraints: dict[str, TypingAny],
    self_refs: dict[type, _RecursiveSchemaRef],
) -> dict[TypingAny, TypingAny]:
    """Build the mapping schema for a dataclass's constructor fields."""
    try:
        hints = get_type_hints(dataclass_type, include_extras=True)
    except Exception as exc:
        # An unresolvable forward reference (or any annotation error) is a schema
        # definition problem, reported as SchemaError rather than a leaked NameError.
        message = f"cannot resolve type hints for {dataclass_type.__name__!r}: {exc}"
        raise SchemaError(message) from exc
    mapping: dict[TypingAny, TypingAny] = {}
    for field in _iter_init_fields(dataclass_type):
        annotation = _field_annotation(hints.get(field.name, TypingAny))
        value_schema = _annotation_to_schema(annotation, self_refs)
        if field.name in constraints:
            value_schema = All(value_schema, constraints[field.name])
        if field.default is not dataclasses.MISSING:
            key: TypingAny = Optional(field.name, default=_constant(field.default))
        elif field.default_factory is not dataclasses.MISSING:
            key = Optional(field.name, default=field.default_factory)
        else:
            key = Required(field.name)
        mapping[key] = value_schema
    return mapping


class _Constructor:
    """Turn a validated dict into a dataclass instance (the final ``All`` step)."""

    __slots__ = ("_init_fields", "dataclass_type")

    def __init__(self, dataclass_type: type) -> None:
        """Remember the type and which of its fields the constructor accepts."""
        self.dataclass_type = dataclass_type
        self._init_fields = frozenset(
            field.name for field in _iter_init_fields(dataclass_type)
        )

    def __call__(self, data: dict[TypingAny, TypingAny]) -> TypingAny:
        """Construct the dataclass, passing only the keys it accepts.

        Extra keys (kept by ``ALLOW_EXTRA``) are dropped here, since a dataclass
        cannot take an unexpected keyword argument.
        """
        kwargs = {key: value for key, value in data.items() if key in self._init_fields}
        return self.dataclass_type(**kwargs)

    def __repr__(self) -> str:
        """Render with the target type, so it reads well in an ``All`` repr."""
        return f"<construct {self.dataclass_type.__name__}>"


def create_dataclass_schema(
    dataclass_type: type,
    additional_constraints: dict[str, TypingAny] | None = None,
    *,
    required: bool = False,
    extra: int = PREVENT_EXTRA,
    _self_refs: dict[type, _RecursiveSchemaRef] | None = None,
) -> Schema:
    """Build a ``Schema`` that validates a dict and constructs a dataclass.

    Each field's annotation becomes a validator (``list[str]`` to ``[str]``, a
    nested dataclass to its own schema, ``X | None`` to ``Maybe(X)``, and so on).
    Fields with a ``default`` or ``default_factory`` are ``Optional`` (the default
    fills in when the key is absent); fields without one are ``Required``.
    ``additional_constraints`` maps a field name to an extra validator, run after
    the type check with ``All``. The resulting schema validates a plain mapping
    and returns an instance of ``dataclass_type``. A self-referential or mutually
    recursive dataclass is supported: such a field validates against the same
    schema, depth-guarded.
    """
    if not _is_dataclass_type(dataclass_type):
        message = (
            f"create_dataclass_schema expects a dataclass type, got {dataclass_type!r}"
        )
        raise SchemaError(message)
    # Register this type's deferred reference before building its fields, so a
    # field that refers back to it (directly or through another recursive type)
    # resolves to the reference. It is bound to the finished schema below.
    self_refs = dict(_self_refs or {})
    ref = _RecursiveSchemaRef()
    self_refs[dataclass_type] = ref
    mapping = _field_mapping(dataclass_type, additional_constraints or {}, self_refs)
    inner = Schema(mapping, required=required, extra=extra)
    schema = Schema(All(inner, _Constructor(dataclass_type)))
    ref.bind(schema)
    return schema


class DataclassSchema[DataclassT](Schema):
    """A ``Schema`` generated from a dataclass type.

    Calling it validates a mapping against the dataclass's fields and returns a
    constructed instance. ``additional_constraints`` adds per-field validators.
    Thin wrapper over ``create_dataclass_schema``; see it for the full mapping.

    It is generic in the dataclass type, so ``DataclassSchema(User)`` is a
    ``DataclassSchema[User]`` and calling it is typed as returning a ``User``,
    unlike a plain ``Schema`` whose result is ``Any``.
    """

    def __init__(
        self,
        dataclass_type: type[DataclassT],
        additional_constraints: dict[str, TypingAny] | None = None,
        *,
        required: bool = False,
        extra: int = PREVENT_EXTRA,
    ) -> None:
        """Build and compile the schema for ``dataclass_type``."""
        self.dataclass_type = dataclass_type
        built = create_dataclass_schema(
            dataclass_type,
            additional_constraints,
            required=required,
            extra=extra,
        )
        super().__init__(built.schema)

    def __call__(
        self, data: TypingAny, *, context: TypingAny = _INHERIT_CONTEXT
    ) -> DataclassT:
        """Validate ``data`` and return the constructed dataclass instance."""
        return cast("DataclassT", super().__call__(data, context=context))


def _typeddict_mapping(
    typeddict_type: TypingAny,
    constraints: dict[str, TypingAny],
    self_refs: dict[type, _RecursiveSchemaRef],
) -> dict[TypingAny, TypingAny]:
    """Build the mapping schema for a TypedDict's fields."""
    try:
        hints = get_type_hints(typeddict_type, include_extras=True)
    except Exception as exc:
        # An unresolvable forward reference (or any annotation error) is a schema
        # definition problem, reported as SchemaError rather than a leaked NameError.
        message = f"cannot resolve type hints for {typeddict_type.__name__!r}: {exc}"
        raise SchemaError(message) from exc
    # Required-ness is read from each resolved annotation, not from
    # ``__required_keys__``: under ``from __future__ import annotations`` the
    # annotations are strings at class-creation time, so ``__required_keys__``
    # cannot see a ``Required``/``NotRequired`` wrapper and comes out wrong. A
    # field with an explicit wrapper takes it; otherwise the TypedDict's ``total``
    # decides.
    total = typeddict_type.__total__
    mapping: dict[TypingAny, TypingAny] = {}
    for name, annotation in hints.items():
        origin = get_origin(annotation)
        if origin is RequiredHint:
            required, field_type = True, get_args(annotation)[0]
        elif origin is NotRequired:
            required, field_type = False, get_args(annotation)[0]
        else:
            required, field_type = total, annotation
        value_schema = _annotation_to_schema(field_type, self_refs)
        if name in constraints:
            value_schema = All(value_schema, constraints[name])
        key = Required(name) if required else Optional(name)
        mapping[key] = value_schema
    return mapping


def create_typeddict_schema(
    typeddict_type: TypingAny,
    additional_constraints: dict[str, TypingAny] | None = None,
    *,
    extra: int = PREVENT_EXTRA,
    _self_refs: dict[type, _RecursiveSchemaRef] | None = None,
) -> Schema:
    """Build a ``Schema`` that validates a mapping against a TypedDict.

    Each field's annotation becomes a validator, the same mapping a dataclass uses
    (a parameterized generic keeps its element types, a nested dataclass or
    TypedDict recurses, ``X | None`` becomes ``Maybe(X)``). A field in the
    TypedDict's required keys is ``Required``, the rest ``Optional``;
    ``total=False`` and ``Required``/``NotRequired`` are honored.
    ``additional_constraints`` maps a field name to an extra validator, run after
    the type check with ``All``. The validated mapping is returned unchanged: a
    TypedDict is a plain dict at runtime, so nothing is constructed. A
    self-referential or mutually recursive TypedDict is supported.
    """
    if not is_typeddict(typeddict_type):
        message = (
            f"create_typeddict_schema expects a TypedDict type, got {typeddict_type!r}"
        )
        raise SchemaError(message)
    # Register this type's deferred reference before building its fields, so a
    # field that refers back to it resolves to the reference (bound below).
    self_refs = dict(_self_refs or {})
    ref = _RecursiveSchemaRef()
    self_refs[typeddict_type] = ref
    mapping = _typeddict_mapping(
        typeddict_type, additional_constraints or {}, self_refs
    )
    inner = Schema(mapping, extra=extra)
    ref.bind(inner)
    return inner


class TypedDictSchema[TypedDictT](Schema):
    """A ``Schema`` generated from a TypedDict type.

    Calling it validates a mapping against the TypedDict's fields and returns the
    validated mapping, typed as the TypedDict. Unlike a dataclass, nothing is
    constructed: a TypedDict is a plain dict at runtime, so the validated dict is
    the result (dict in, dict out, at no construction cost). ``additional_constraints``
    adds per-field validators. Thin wrapper over ``create_typeddict_schema``.

    It is generic in the TypedDict type, so ``TypedDictSchema(Config)`` is a
    ``TypedDictSchema[Config]`` and calling it is typed as returning a ``Config``,
    unlike a plain ``Schema`` whose result is ``Any``.
    """

    def __init__(
        self,
        typeddict_type: type[TypedDictT],
        additional_constraints: dict[str, TypingAny] | None = None,
        *,
        extra: int = PREVENT_EXTRA,
    ) -> None:
        """Build and compile the schema for ``typeddict_type``."""
        self.typeddict_type = typeddict_type
        built = create_typeddict_schema(
            typeddict_type,
            additional_constraints,
            extra=extra,
        )
        # ``built.schema`` is the raw mapping, so ``extra`` has to be passed again
        # when re-wrapping; the dataclass path gets away without it because there
        # the ``extra`` is baked into an inner Schema wrapped in ``All``.
        super().__init__(built.schema, extra=extra)

    def __call__(
        self, data: TypingAny, *, context: TypingAny = _INHERIT_CONTEXT
    ) -> TypedDictT:
        """Validate ``data`` and return it typed as the TypedDict."""
        return cast("TypedDictT", super().__call__(data, context=context))
