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
``Annotated[X, validator, ...]``: each callable in the metadata is applied through
``All`` in order (non-callable metadata is left for other tools). When ``X`` is a plain
type, its ``isinstance`` check runs on the *result*, so the type says what the field is
rather than gating the raw input: ``Annotated[datetime, AsDatetime()]`` parses the
string and confirms the result is a ``datetime``, keeping the field honestly typed. When
``X`` itself coerces (a nested schema), it runs first and the metadata layers on top. A
``NewType`` is followed to the type it wraps. Both are
an alternative to the ``additional_constraints`` side mapping, with the constraint
living next to the field it guards.
"""

from __future__ import annotations

import dataclasses
import enum
import types
from collections.abc import (
    Callable,
    Mapping,
    MutableMapping,
    MutableSequence,
    MutableSet,
    Sequence,
)
from collections.abc import Set as AbstractSet
from typing import (
    TYPE_CHECKING,
    Annotated,
    Literal,
    NotRequired,
    get_args,
    get_origin,
    get_type_hints,
    is_typeddict,
)
from typing import Any as TypingAny
from typing import Required as RequiredHint
from typing import Union as TypingUnion

from probatio._codegen import compile_mapping
from probatio._compile import recursion_guard
from probatio._engine import _MappingValidator
from probatio.error import Invalid, MultipleInvalid, SchemaError, ValueInvalid
from probatio.fields import Key
from probatio.markers import (
    UNDEFINED,
    Alias,
    Exclusive,
    Forbidden,
    Inclusive,
    Optional,
    Remove,
    Required,
    Secret,
    resolve_key,
)
from probatio.schema import (
    _INHERIT_CONTEXT,
    ALLOW_EXTRA,
    PREVENT_EXTRA,
    CompiledSchema,
    Schema,
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


def _base_asserts_the_result(base_schema: TypingAny) -> bool:
    """Whether an ``Annotated`` base only *checks* the value (so it runs last).

    A plain type compiles to an ``isinstance`` assertion about what the field is, so it
    runs on the metadata's result. An ``Enum`` class and a type carrying a
    ``__probatio_validate__`` protocol (ADR-007) are bare types too, but they *coerce* a
    raw value into the validated form when compiled, so they are producers and run first
    (like a registry coercer, a nested schema, or a container).
    """
    return (
        isinstance(base_schema, type)
        and not issubclass(base_schema, enum.Enum)
        and not callable(getattr(base_schema, "__probatio_validate__", None))
    )


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
        # Callable Annotated metadata are extra validators; other metadata is for
        # other tools and is ignored here.
        base, *meta = get_args(annotation)
        base_schema = _annotation_to_schema(base, self_refs)
        extras = [item for item in meta if callable(item)]
        if not extras:
            return base_schema
        # A plain type compiles to an ``isinstance`` check: an assertion about what the
        # field *is*, so it runs on the result, after the metadata. A coercing hint
        # (``Annotated[int, Coerce(int)]``, ``Annotated[datetime, AsDatetime()]``) then
        # produces the value the type confirms, keeping the field honestly typed. A base
        # that *produces* the value runs first, so a constraint layers on top of the
        # produced value (ADR-008): a registry coercer, a nested schema, a container, and
        # also a bare type that coerces when compiled (an ``Enum`` class, or a type with a
        # ``__probatio_validate__`` protocol from ADR-007, both turn a raw value into the
        # validated form).
        if _base_asserts_the_result(base_schema):
            return All(*extras, base_schema)
        return All(base_schema, *extras)

    if _is_dataclass_type(annotation):
        if annotation in self_refs:
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
        if isinstance(annotation, type):
            return annotation
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
    # For other generics, validate the container type instead of accepting
    # everything. Some origins are not runtime types, so those stay open.
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


def _field_key_spec(annotation: TypingAny) -> Key | None:
    """Return the ``Key`` spec in a field annotation's ``Annotated`` metadata, or None."""
    if get_origin(annotation) is not Annotated:
        return None
    _, *meta = get_args(annotation)
    specs = [item for item in meta if isinstance(item, Key)]
    if len(specs) > 1:
        message = "a field carries more than one Key spec"
        raise SchemaError(message)
    return specs[0] if specs else None


def _check_facets(spec: Key, name: TypingAny) -> None:
    """Reject a ``Key`` that sets two role-defining facets at once.

    ``alias``/``forbidden``/``remove``/``inclusive``/``exclusive`` define what the
    key *is* and are mutually exclusive; ``secret`` layers on top and is exempt.
    """
    facets = [
        facet
        for facet in ("alias", "forbidden", "remove", "inclusive", "exclusive")
        if getattr(spec, facet) not in (None, False)
    ]
    if len(facets) > 1:
        message = f"field {name!r} Key sets conflicting facets: {', '.join(facets)}"
        raise SchemaError(message)


def _key_from_spec(  # noqa: PLR0913
    name: TypingAny,
    spec: Key | None,
    *,
    inferred_required: bool,
    default: TypingAny,
    has_default: bool,
    constructs: bool,
) -> TypingAny:
    """Turn a field's ``Key`` spec and inferred presence into one mapping key (ADR-013).

    ``inferred_required`` is the presence the field implies on its own (no default
    for a dataclass, ``total``/``Required`` for a TypedDict). ``default`` is the
    marker ``default=`` argument the field's own default supplies (``UNDEFINED`` when
    it has none). ``constructs`` is true for a dataclass, whose constructor needs a
    value for every field.
    """
    if spec is None:
        return Required(name) if inferred_required else Optional(name, default=default)

    _check_facets(spec, name)
    if spec.required is not None and (
        spec.forbidden or spec.remove or spec.inclusive is not None
    ):
        # ``required`` governs presence; it is meaningless for a forbidden or removed
        # field (never taken from the input) or an inclusive group (all-or-none).
        target = (
            "Forbidden"
            if spec.forbidden
            else "Remove"
            if spec.remove
            else "an inclusive group"
        )
        message = f"field {name!r}: required does not apply to {target}"
        raise SchemaError(message)
    required = spec.required if spec.required is not None else inferred_required

    if spec.forbidden:
        _guard_never_supplied(name, "Forbidden", constructs=constructs, has=has_default)
        base: TypingAny = Forbidden(name, msg=spec.msg, description=spec.description)
    elif spec.remove:
        _guard_never_supplied(name, "Remove", constructs=constructs, has=has_default)
        base = Remove(name)
    elif spec.alias is not None:
        names = (spec.alias,) if isinstance(spec.alias, str) else tuple(spec.alias)
        base = Alias(
            name,
            *names,
            accept_canonical=spec.accept_canonical,
            required=required,
            # A required alias is always supplied, so it carries no default.
            default=UNDEFINED if required else default,
            msg=spec.msg,
            description=spec.description,
        )
        _guard_absent(
            name, "Alias", constructs=constructs, present=required, has=has_default
        )
    elif spec.inclusive is not None:
        base = Inclusive(
            name,
            spec.inclusive,
            msg=spec.msg,
            default=default,
            description=spec.description,
        )
        _guard_absent(
            name, "Inclusive", constructs=constructs, present=False, has=has_default
        )
    elif spec.exclusive is not None:
        # ``required`` names the group requirement (one member present), not this
        # member's presence. A required group must not be satisfied by a default (that
        # would neutralize ``required``), so it gets none; the non-selected member then
        # takes its dataclass default at construction. An optional group keeps the
        # default, which fills (and coerces) a member when the group is empty.
        base = Exclusive(
            name,
            spec.exclusive,
            msg=spec.msg,
            description=spec.description,
            required=bool(spec.required),
            default=UNDEFINED if spec.required else default,
        )
        _guard_absent(
            name, "Exclusive", constructs=constructs, present=False, has=has_default
        )
    elif required:
        base = Required(name, msg=spec.msg, description=spec.description)
    else:
        base = Optional(
            name, default=default, msg=spec.msg, description=spec.description
        )
        _guard_absent(
            name, "Optional", constructs=constructs, present=False, has=has_default
        )

    if spec.secret:
        base = Secret(base, msg=spec.msg, description=spec.description)
    return base


def _guard_never_supplied(
    name: TypingAny, marker: str, *, constructs: bool, has: bool
) -> None:
    """Reject a Forbidden/Remove dataclass field with no default (never supplied)."""
    if constructs and not has:
        message = (
            f"{marker} field {name!r} needs a default, "
            "since it is never taken from the input"
        )
        raise SchemaError(message)


def _guard_absent(
    name: TypingAny, marker: str, *, constructs: bool, present: bool, has: bool
) -> None:
    """Reject a dataclass field that can be absent yet has no default to construct."""
    if constructs and not present and not has:
        message = (
            f"{marker} field {name!r} needs a default: it can be absent from the "
            "input, and the dataclass constructor needs a value"
        )
        raise SchemaError(message)


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
            default: TypingAny = _constant(field.default)
            has_default = True
        elif field.default_factory is not dataclasses.MISSING:
            default = field.default_factory
            has_default = True
        else:
            default = UNDEFINED
            has_default = False

        key = _key_from_spec(
            field.name,
            _field_key_spec(annotation),
            inferred_required=not has_default,
            default=default,
            has_default=has_default,
            constructs=True,
        )
        mapping[key] = value_schema

    return mapping


class _Constructor:
    """Turn a validated dict into a dataclass instance (the final ``All`` step)."""

    __slots__ = ("_filter_keys", "_init_fields", "dataclass_type")

    def __init__(
        self,
        dataclass_type: type,
        remove: frozenset[TypingAny] = frozenset(),
        *,
        filter_keys: bool = True,
    ) -> None:
        """Remember the type and which of its fields the constructor accepts.

        ``remove`` names the ``Key(remove=True)`` fields, whose value is always
        dropped, so they take their dataclass default regardless of the input (even a
        value ``ALLOW_EXTRA`` kept because it failed the field's own validation).

        ``filter_keys=False`` is the caller asserting the validated dict can only
        hold init-field keys (no ``ALLOW_EXTRA``, no ``Remove`` fields);
        ``_fuse_validate_and_construct`` reads it to splat the validated dict
        straight into the constructor, skipping both this object and its filter.
        """
        self.dataclass_type = dataclass_type
        self._filter_keys = filter_keys
        self._init_fields = (
            frozenset(field.name for field in _iter_init_fields(dataclass_type))
            - remove
        )

    def __call__(self, data: dict[TypingAny, TypingAny]) -> TypingAny:
        """Construct the dataclass, passing only the keys it accepts.

        Extra keys (kept by ``ALLOW_EXTRA``) and dropped ``Remove`` keys are left out
        here, since a dataclass cannot take an unexpected keyword argument. The
        hot paths never get here (the fused interpreted engine and the generated
        code construct directly); this runs only through the ``All`` tower kept
        for a ``Self``-using schema, where an always-on filter costs nothing that
        matters.
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

    # Register the deferred reference before field schemas are built, so recursive
    # fields can point at it.
    self_refs = dict(_self_refs or {})
    ref = _RecursiveSchemaRef()
    self_refs[dataclass_type] = ref
    mapping = _field_mapping(dataclass_type, additional_constraints or {}, self_refs)

    # DataclassSchema compiles mapping validation and construction together, so it
    # needs an interpreted inner mapping to read from.
    inner = Schema(mapping, required=required, extra=extra, compile=False)
    # Resolve through the chain so a nested Remove (``Secret(Remove(...))``) counts too.
    remove = frozenset(
        facets.key
        for facets in map(resolve_key, mapping)
        if isinstance(facets.marker, Remove)
    )
    # Under PREVENT_EXTRA/REMOVE_EXTRA with no Remove fields (the default and the
    # overwhelmingly common case), the mapping is built exclusively from the init
    # fields, so every key surviving validation is an init-field name by
    # construction and the constructor's filter would be a per-call no-op.
    constructor = _Constructor(
        dataclass_type, remove, filter_keys=extra == ALLOW_EXTRA or bool(remove)
    )
    schema = Schema(All(inner, constructor))
    # Fused before ``bind``, so a recursive field's captured engine is the fused
    # one too, not the slower combinator tower.
    _install_fused_interpreted(schema)
    ref.bind(schema)

    return schema


def _fuse_validate_and_construct(
    validate_mapping: CompiledSchema, constructor: _Constructor
) -> CompiledSchema:
    """Return one closure that validates the mapping and constructs the instance.

    The public schema shape stays ``Schema(All(inner, _Constructor))``; this is
    only a faster interpreted engine for it. Called generically, that ``All``
    tower is five frames of pure delegation per validation (the callable guard,
    ``All.__call__``, the inner ``Schema.__call__``, and the shim around the
    constructor) around the two calls that do real work. The closure keeps just
    those two, with the guard's ``ValueError`` normalization replicated verbatim.

    Error-shape parity: the mapping engine's errors propagate untouched (a
    ``MultipleInvalid`` passed through the tower unchanged, and its bare
    wrong-type error reaches every consumer the same way, since
    ``Schema.__call__`` wraps a lone ``Invalid`` itself and the enclosing engines
    flatten a ``MultipleInvalid`` to the same leaves). A constructor failure is
    wrapped exactly as the tower did, exception chain included: the ``ValueError``
    normalization mirrors the callable guard, and the ``MultipleInvalid`` wrap
    mirrors ``All``, so tracebacks keep reading identically.
    """
    dataclass_type = constructor.dataclass_type
    construct: Callable[..., TypingAny] = constructor

    def _constructor_error(exc: ValueError) -> MultipleInvalid:
        """Build the tower-identical error for a constructor ``ValueError``."""
        if detail := str(exc):
            error = ValueInvalid(
                translation_key="not_a_valid_value_detail",
                placeholders={"detail": detail},
            )
        else:
            error = ValueInvalid(translation_key="not_a_valid_value")
        error.__cause__ = exc
        return MultipleInvalid([error])

    if constructor._filter_keys:  # noqa: SLF001

        def validate(data: TypingAny) -> TypingAny:
            """Validate the mapping, then construct through the filter."""
            validated = validate_mapping(data)
            try:
                return construct(validated)
            except MultipleInvalid:
                raise
            except Invalid as exc:
                raise MultipleInvalid([exc]) from exc
            except ValueError as exc:
                error = _constructor_error(exc)
                raise error from error.errors[0]

        return validate

    def validate_splat(data: TypingAny) -> TypingAny:
        """Validate the mapping, then splat it straight into the constructor."""
        validated = validate_mapping(data)
        try:
            return dataclass_type(**validated)
        except MultipleInvalid:
            raise
        except Invalid as exc:
            raise MultipleInvalid([exc]) from exc
        except ValueError as exc:
            error = _constructor_error(exc)
            raise error from error.errors[0]

    return validate_splat


def _install_fused_interpreted(schema: Schema) -> None:
    """Swap ``schema``'s interpreted engine for the fused validate-and-construct.

    ``schema`` wraps ``All(inner, _Constructor)``. The inner mapping schema is
    pinned interpreted (``compile=False``), so its engine can be captured
    directly. A ``Self``-using inner keeps the tower: its resolution runs through
    the inner ``Schema.__call__``'s active-root bookkeeping.

    The fused engine lands wherever the interpreted validator lives: in
    ``_interpreted`` when the schema armed for lazy compilation (it then also
    becomes the generated code's bail-out fallback), else in ``_compiled``.
    """
    inner, constructor = schema.schema.validators
    if inner._uses_self:  # noqa: SLF001
        return
    fused = _fuse_validate_and_construct(inner._compiled, constructor)  # noqa: SLF001
    if "_interpreted" in schema.__dict__:
        schema._interpreted = fused  # noqa: SLF001
    else:
        schema._compiled = fused  # noqa: SLF001


# Distinguishes "the fast constructor has not been built yet" from "built, and the
# shape is not handled, so it is None and we fall back to validating".
_UNSET = object()


def _mentions_dataclass(annotation: TypingAny) -> bool:
    """Whether a dataclass type appears anywhere in ``annotation`` (incl. its args)."""
    if _is_dataclass_type(annotation):
        return True
    return any(_mentions_dataclass(arg) for arg in get_args(annotation))


def _is_dict_shaped(annotation: TypingAny) -> bool:
    """Whether a value of ``annotation`` can arrive as a ``dict`` at runtime.

    A single-dataclass union dispatches on ``isinstance(value, dict)``, so any
    alternative a dict satisfies is ambiguous with the dataclass branch and must fall
    back to validation: a plain ``dict``, a ``Mapping``/``MutableMapping`` (whose
    origin is ``collections.abc.Mapping``, not ``dict``), or a ``TypedDict`` (a plain
    dict at runtime). Without this, a mapping input would be fed to the dataclass
    constructor instead of passing through as the mapping alternative.
    """
    if is_typeddict(annotation):
        return True
    if isinstance(annotation, type):
        return issubclass(annotation, Mapping)
    origin = get_origin(annotation)
    return isinstance(origin, type) and issubclass(origin, Mapping)


def _union_expr(
    annotation: TypingAny,
    var: str,
    namespace: dict[str, TypingAny],
    building: frozenset[type],
    tag: str,
) -> str | None:
    """Build a value from a ``Union`` (including ``Optional``), or ``None``.

    Handles the two shapes worth fast-building: a single non-``None`` member (an
    ``Optional[X]``), guarded so a ``None`` passes through; and one dataclass among
    plain alternatives (``IssueLabel | str``), told apart at runtime by being a dict.
    Several dataclasses, or a dict-shaped alternative, are ambiguous and fall back.
    """
    members = get_args(annotation)
    non_none = [member for member in members if member is not types.NoneType]
    has_none = len(non_none) != len(members)

    if len(non_none) == 1:
        inner = _value_expr(non_none[0], var, namespace, building, tag)
        if inner is None:
            return None
        # A passed-through value already carries a ``None`` fine; only a real
        # construction (a dataclass build) has to be guarded against it.
        if has_none and inner != var:
            return f"({inner} if {var} is not None else None)"
        return inner

    in_dataclasses = [member for member in non_none if _is_dataclass_type(member)]
    plain = [member for member in non_none if not _is_dataclass_type(member)]
    if len(in_dataclasses) == 1 and not any(
        _mentions_dataclass(member) or _is_dict_shaped(member) for member in plain
    ):
        sub = _build_constructor(in_dataclasses[0], building)
        if sub is None:
            return None
        name = f"_b{tag}"
        namespace[name] = sub
        inner = f"({name}({var}) if isinstance({var}, dict) else {var})"
        return f"({inner} if {var} is not None else None)" if has_none else inner
    return None


def _value_expr(  # noqa: PLR0911 - a dispatch with one return per value shape
    annotation: TypingAny,
    var: str,
    namespace: dict[str, TypingAny],
    building: frozenset[type],
    tag: str,
) -> str | None:
    """Return a source expression building one value of ``annotation`` from ``var``.

    ``None`` means the shape is not one the fast constructor handles, so the caller
    falls back to validating. A plain value passes straight through (the input is
    trusted); a dataclass recurses into its own constructor; a ``list``, an
    ``Optional``, or a single-dataclass ``Union`` recurses into its element or member.
    """
    if _is_dataclass_type(annotation):
        sub = _build_constructor(annotation, building)
        if sub is None:
            return None
        name = f"_b{tag}"
        namespace[name] = sub
        # Build from a dict; an already-constructed instance passes through, the same
        # guard the single-dataclass union uses, so a partially built input does not
        # crash on the constructor subscripting a non-dict.
        return f"({name}({var}) if isinstance({var}, dict) else {var})"

    origin = get_origin(annotation)
    if origin is list:
        args = get_args(annotation)
        if not args or not _mentions_dataclass(args[0]):
            return var  # a list of plain values passes through
        element = _value_expr(args[0], "_item", namespace, building, f"{tag}L")
        if element is None:
            return None
        return f"[{element} for _item in {var}]"
    if origin is TypingUnion or origin is types.UnionType:
        return _union_expr(annotation, var, namespace, building, tag)
    if _mentions_dataclass(annotation):
        return None  # a tuple, set, or dict hiding a dataclass: left to validation
    return var  # a plain value is trusted as-is


def _build_constructor(
    dataclass_type: type, building: frozenset[type] = frozenset()
) -> TypingAny:
    """Generate a flat constructor that builds ``dataclass_type`` from a trusted dict.

    Returns a callable ``data -> instance`` that skips all validation: it reads each
    field straight from ``data`` (recursing into nested dataclasses and lists of
    them, filling defaults for absent keys) and calls the constructor. Returns
    ``None`` if the shape is not one it handles (a recursive dataclass, a dataclass
    behind an Optional or a tuple, an unresolvable hint), so the caller can fall back
    to validating. The constructed instance equals what validating then constructing
    would build, with one trust-path difference: a plain container value (a
    ``list[int]``) is passed through as-is rather than rebuilt, so it may alias the
    input where the validating path returns a fresh copy.
    """
    if dataclass_type in building:
        return None  # a recursive dataclass: leave it to the validating path
    building = building | {dataclass_type}

    # Type hints were already resolved while building the schema. The plain hints
    # drive value construction; the extras-carrying hints only detect a Key facet.
    hints = get_type_hints(dataclass_type)
    hints_extras = get_type_hints(dataclass_type, include_extras=True)
    namespace: dict[str, TypingAny] = {"_Type": dataclass_type}
    parts: list[str] = []
    for index, field in enumerate(_iter_init_fields(dataclass_type)):
        annotation = _field_annotation(hints.get(field.name, TypingAny))
        spec = _field_key_spec(_field_annotation(hints_extras.get(field.name)))
        if spec is not None and (
            spec.alias is not None
            or spec.remove
            or spec.forbidden
            or spec.inclusive is not None
            or spec.exclusive is not None
            or spec.required is not None
        ):
            # These either change which key the field reads from (or drop it) or add a
            # presence rule the flat by-name reader cannot reproduce; leave them to the
            # validating path.
            return None

        expr = _value_expr(
            annotation, f"data[{field.name!r}]", namespace, building, str(index)
        )
        if expr is None:
            return None

        if field.default is not dataclasses.MISSING:
            namespace[f"_d{index}"] = field.default
            expr = f"({expr} if {field.name!r} in data else _d{index})"
        elif field.default_factory is not dataclasses.MISSING:
            namespace[f"_f{index}"] = field.default_factory
            expr = f"({expr} if {field.name!r} in data else _f{index}())"
        parts.append(f"{field.name}={expr}")

    source = f"def _construct(data):\n    return _Type({', '.join(parts)})"
    exec(source, namespace)  # noqa: S102 - generated from the trusted dataclass shape
    return namespace["_construct"]


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
        compile: bool | None = None,  # noqa: A002 - the public, re.compile-style name
    ) -> None:
        """Build and compile the schema for ``dataclass_type``."""
        self.dataclass_type = dataclass_type
        built = create_dataclass_schema(
            dataclass_type,
            additional_constraints,
            required=required,
            extra=extra,
        )
        super().__init__(built.schema, compile=compile)
        # ``built`` carries its own fused engine, but this instance recompiled the
        # ``All`` from scratch in ``super().__init__``, so it fuses again for
        # itself.
        _install_fused_interpreted(self)

    def extend(self, *_args: TypingAny, **_kwargs: TypingAny) -> Schema:
        """Refuse to extend: a ``DataclassSchema`` is built from a type, not a mapping.

        ``extend`` merges keys into a mapping schema and rebuilds the same class, but
        a ``DataclassSchema`` is defined by its dataclass type and could not construct
        anything coherent from the extra keys. Build a new ``DataclassSchema``, or
        extend a plain ``Schema`` of the fields instead, rather than fail obscurely.
        """
        message = (
            "extend is not supported on a DataclassSchema; it is built from a "
            "dataclass type, not a mapping. Build a new DataclassSchema, or extend a "
            "plain Schema of the fields."
        )
        raise SchemaError(message)

    def construct(self, data: TypingAny) -> DataclassT:
        """Build the dataclass from **trusted** ``data``, skipping validation.

        This is the opt-in fast path for spots where the input is already known to be
        correct: you validated it upstream, or it is your own data round-tripping
        back in. It reads each field straight from ``data`` and constructs the
        instance, recursing into nested dataclasses and lists of them and filling
        defaults, with no type checks, no constraints, and no coercion. It is faster
        than validating, but it trusts you: a wrong type lands unchecked in the
        instance, and a plain container (a ``list``) is used as given, not copied, so
        it may alias the input where the validating call returns a fresh copy.

        Use the schema's normal call (``schema(data)``) for untrusted input; that
        validates. For a dataclass shape this fast path does not handle, ``construct``
        falls back to validating, which builds the same instance.
        """
        constructor = self._fast_constructor()
        if constructor is None:
            validated: DataclassT = Schema.__call__(self, data)
            return validated
        built: DataclassT = constructor(data)
        return built

    def _fast_constructor(self) -> TypingAny:
        """Lazily build and cache the trusted constructor (``None`` means fall back)."""
        cached = self.__dict__.get("_construct_fn", _UNSET)
        if cached is _UNSET:
            cached = _build_constructor(self.dataclass_type)
            self._construct_fn = cached
        return cached

    if TYPE_CHECKING:
        # Declared for the type checker only, to narrow the base's ``Any`` return
        # to the dataclass type. At runtime the class uses ``Schema.__call__``
        # directly, so a validation does not pay a delegating wrapper frame.
        def __call__(
            self, data: TypingAny, *, context: TypingAny = _INHERIT_CONTEXT
        ) -> DataclassT:
            """Validate ``data`` and return the constructed dataclass instance."""

    def _compilable(self) -> bool:
        """Report that a dataclass compiles via its inner mapping, under the ``All``."""
        return isinstance(self.schema.validators[0]._compiled, _MappingValidator)  # noqa: SLF001

    def _compile_from(self, interpreted: CompiledSchema) -> CompiledSchema:
        """Compile the dataclass into one fused validate-and-construct function.

        The schema is ``All(inner_mapping, _Constructor)``. Compile the inner mapping
        and splat the validated fields straight into the dataclass, so neither the
        generic mapping loop nor the constructor's dict-comprehension runs. Any
        failure bails to ``interpreted`` (the ``All``), which validates and
        constructs the same way. An ``ALLOW_EXTRA`` dataclass is not generated
        (``compile_mapping`` returns ``None``), since the constructor would reject
        the unknown keys the mapping keeps.
        """
        mapping = self.schema.validators[0]._compiled  # noqa: SLF001
        if not isinstance(
            mapping, _MappingValidator
        ):  # pragma: no cover - the inner schema is always a mapping
            return interpreted

        generated = compile_mapping(
            mapping, construct=self.dataclass_type, fallback=interpreted
        )
        return generated if generated is not None else interpreted


def _typeddict_presence(
    annotation: TypingAny, *, default_required: bool
) -> tuple[bool, TypingAny]:
    """Read a TypedDict field's required-ness and strip its Required/NotRequired.

    ``Required``/``NotRequired`` may wrap the whole annotation or sit inside an
    ``Annotated`` (``Annotated[NotRequired[int], Key(...)]``). Handle both, returning
    the presence and the annotation with the qualifier removed but the ``Annotated``
    metadata (a ``Key``, a value validator) kept, so it is still read. Without such a
    wrapper the field keeps ``default_required``, the presence its class and totality
    already imply.
    """
    origin = get_origin(annotation)
    if origin is RequiredHint:
        return True, get_args(annotation)[0]
    if origin is NotRequired:
        return False, get_args(annotation)[0]
    if origin is Annotated:
        base, *meta = get_args(annotation)
        base_origin = get_origin(base)
        if base_origin is RequiredHint:
            return True, Annotated[(get_args(base)[0], *meta)]
        if base_origin is NotRequired:
            return False, Annotated[(get_args(base)[0], *meta)]
    return default_required, annotation


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

    # A field's presence comes from two sources, in order. An explicit
    # ``Required``/``NotRequired`` wrapper on the resolved annotation wins, and it is
    # the only one ``__required_keys__`` misses: under ``from __future__ import
    # annotations`` the wrapper is a string at class-creation time, so Python cannot
    # see it. Otherwise ``__required_keys__`` decides, which stays correct across
    # inheritance and per-base ``total`` where the class's own ``__total__`` does not
    # (a required field inherited into a ``total=False`` child, and the reverse).
    required_keys = typeddict_type.__required_keys__
    mapping: dict[TypingAny, TypingAny] = {}
    for name, annotation in hints.items():
        required, field_type = _typeddict_presence(
            annotation, default_required=name in required_keys
        )
        value_schema = _annotation_to_schema(field_type, self_refs)
        if name in constraints:
            value_schema = All(value_schema, constraints[name])

        # A TypedDict is a plain dict at runtime: nothing is constructed and a field
        # has no default, so Forbidden/Remove need none and absence is fine.
        key = _key_from_spec(
            name,
            _field_key_spec(field_type),
            inferred_required=required,
            default=UNDEFINED,
            has_default=False,
            constructs=False,
        )
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

    # Register the deferred reference before field schemas are built.
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
        compile: bool | None = None,  # noqa: A002 - the public, re.compile-style name
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
        super().__init__(built.schema, extra=extra, compile=compile)

    def extend(self, *_args: TypingAny, **_kwargs: TypingAny) -> Schema:
        """Refuse to extend: a ``TypedDictSchema`` is built from a type, not a mapping.

        ``extend`` merges keys and rebuilds the same class, but a ``TypedDictSchema``
        is defined by its TypedDict type. Build a new ``TypedDictSchema``, or extend a
        plain ``Schema`` of the fields instead, rather than fail obscurely.
        """
        message = (
            "extend is not supported on a TypedDictSchema; it is built from a "
            "TypedDict type, not a mapping. Build a new TypedDictSchema, or extend a "
            "plain Schema of the fields."
        )
        raise SchemaError(message)

    if TYPE_CHECKING:
        # Type-checker-only override, exactly like ``DataclassSchema.__call__``:
        # narrows the return type without costing a runtime wrapper frame.
        def __call__(
            self, data: TypingAny, *, context: TypingAny = _INHERIT_CONTEXT
        ) -> TypedDictT:
            """Validate ``data`` and return it typed as the TypedDict."""

    def construct(self, data: TypingAny) -> TypedDictT:
        """Return **trusted** ``data`` typed as the TypedDict, skipping validation.

        A TypedDict is a plain dict at runtime, so for input you already know is
        correct this is the dict itself, returned unchanged with no checks. It is the
        opt-in fast path; use the normal call (``schema(data)``) for untrusted input.
        """
        trusted: TypedDictT = data
        return trusted
