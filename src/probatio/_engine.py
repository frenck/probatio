"""The compiled runtime validators: the mapping and sequence engines.

A compiled ``Schema`` is built from these. Each holds pre-compiled per-key or
per-element checks (plain callables) and runs them against data, collecting
errors into a ``MultipleInvalid``. They never import ``Schema``, so the engine
sits below the public class that assembles them.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from typing import Any, NamedTuple

from probatio.error import (
    DictInvalid,
    ExclusiveInvalid,
    ExtraKeysInvalid,
    InclusiveInvalid,
    Invalid,
    MultipleInvalid,
    ObjectInvalid,
    RequiredFieldInvalid,
    SchemaError,
    SequenceTypeInvalid,
    TypeInvalid,
)
from probatio.markers import UNDEFINED, Undefined, VirtualPathComponent

# How a mapping schema treats keys that are not in the schema.
PREVENT_EXTRA = 0  # reject them (the default)
ALLOW_EXTRA = 1  # keep them as-is
REMOVE_EXTRA = 2  # drop them from the result

type CompiledSchema = Callable[[Any], Any]

# Shared empty set for the common mapping that has no secret keys, so building one
# does not allocate a fresh frozenset per compiled mapping.
_NO_SECRET_KEYS: frozenset[Any] = frozenset()


def _type_error(expected: str, path: list[Any], error_type: str | None) -> TypeInvalid:
    """Build the error an inlined type check raises (only hit when it fails).

    Matches what the compiled type check plus the engine's error tagging would
    produce, so inlining the isinstance is invisible to callers.
    """
    return TypeInvalid(
        f"expected {expected}",
        path=path,
        error_type=error_type,
        context={"expected": expected},
    )


class _Candidate(NamedTuple):
    """A compiled mapping key: how to match it and how to validate its value."""

    key_schema: Any
    check_key: CompiledSchema
    check_value: CompiledSchema
    required: bool
    default: Callable[[], Any] | Undefined
    remove: bool
    is_literal: bool
    forbidden: bool = False
    # This key's value is a secret: redact it from error output on failure.
    secret: bool = False
    exclusive_group: str | None = None
    inclusive_group: str | None = None
    msg: str | None = None
    # The type a plain type-valued key checks (``{"a": int}``), so the hot loop
    # can inline the isinstance; None when the value needs a real validator call.
    value_type: type | None = None
    # The type a plain type *key* matches (``{str: int}``), so an open mapping can
    # inline the key isinstance instead of calling and catching the key check.
    key_type: type | None = None
    # For a complex required key (``Required(Any("a", "b"))``): the candidate keys,
    # so a "none present" failure reports "at least one of [...] is required".
    complex_keys: list[Any] | None = None
    # For an Exclusive member built with ``required=True``: the group must hold
    # exactly one key, so an empty group is an error.
    exclusive_required: bool = False
    # For an ``Alias`` key: the input names accepted for this candidate, in
    # declaration order. Empty for a normal key. The value arriving under any of
    # these names is validated and stored under ``key_schema`` (the canonical).
    alias_input_names: tuple[Any, ...] = ()
    # The raw value schema this candidate compiled (the ``int``, ``Range(...)``,
    # ``All(...)`` written in the schema), kept so the code generator can inline
    # known validators instead of calling their compiled closures. ``None`` for a
    # candidate the generator never sees (the Extra catch-all).
    value_schema: Any = None


class _MappingValidator:
    """Validate a mapping against an ordered set of compiled key candidates."""

    def __init__(
        self,
        candidates: list[_Candidate],
        extra: int,
        invalid_msg: str = "dictionary value",
    ) -> None:
        """Index literal keys for O(1) lookup; keep validator keys as a list.

        ``invalid_msg`` tags a leaf value error; it is ``dictionary value`` for a
        mapping and ``object value`` when validating object attributes.
        """
        self._candidates = candidates
        self._extra = extra
        self._invalid_msg = invalid_msg
        # Everything the validator needs is derived from the candidate list in one
        # pass; the structures below were six separate walks, but each candidate's
        # attributes are read once here instead. What each piece is:
        #
        # ``_literal``: literal keys matched by an exact dict lookup (the common,
        #   fast path); a key not found there falls back to the validator keys
        #   (types and callables) tried one by one, so literals take precedence.
        # ``_literal_fast``: a flat tuple per literal key that is neither Forbidden
        #   nor Remove (the overwhelming case), holding exactly what the per-key
        #   validation loop reads (position, inlined value type, value check) so it
        #   skips the forbidden/remove branches.
        # ``_key_names``: the literal string keys a caller could legitimately give,
        #   the pool for "did you mean ...?" on an unknown key (Remove/Forbidden
        #   excluded; suggesting a dropped or must-be-absent key would be wrong).
        # ``_finalizers``: the candidates that can apply a default or report a
        #   missing required key; a mapping of purely optional keys needs none, so
        #   it skips seen-tracking and finalization entirely.
        # ``exclusive``/``inclusive``: group member lists, built once so a grouped
        #   validation does not rebuild them per call.
        self._literal: dict[Any, tuple[int, _Candidate]] = {}
        self._validators: list[tuple[int, _Candidate]] = []
        self._literal_fast: dict[Any, tuple[int, type | None, CompiledSchema]] = {}
        key_names: list[str] = []
        self._finalizers: list[tuple[int, _Candidate]] = []
        exclusive: dict[str, list[int]] = defaultdict(list)
        inclusive: dict[str, list[int]] = defaultdict(list)
        alias_candidates: list[_Candidate] = []
        # Literal keys whose value is a secret. A failure under one is redacted in
        # a single post-pass over the collected errors, so the hot success path and
        # the per-value error paths stay untouched. Secret keys are always literal
        # (the compiler rejects ``Secret`` around a type or callable key).
        secret_keys: list[Any] = []
        for index, candidate in enumerate(candidates):
            key = candidate.key_schema
            if candidate.secret:
                secret_keys.append(key)
            if candidate.is_literal:
                self._literal[key] = (index, candidate)
                if not candidate.forbidden and not candidate.remove:
                    self._literal_fast[key] = (
                        index,
                        candidate.value_type,
                        candidate.check_value,
                    )
                    if isinstance(key, str):
                        key_names.append(key)
            else:
                self._validators.append((index, candidate))
            if candidate.exclusive_group is not None:
                exclusive[candidate.exclusive_group].append(index)
            if candidate.inclusive_group is not None:
                inclusive[candidate.inclusive_group].append(index)
            if candidate.required or (
                candidate.is_literal
                and not isinstance(candidate.default, Undefined)
                # An Exclusive member's default is group-level: it fills in only
                # when the whole group is empty, applied in the group pass, not
                # here where it would fire whenever this one key is absent.
                and candidate.exclusive_group is None
            ):
                self._finalizers.append((index, candidate))
            if candidate.alias_input_names:
                alias_candidates.append(candidate)

        # A tuple, so an error can hold it as its suggestion pool without a
        # defensive copy per raise (the exclusion filter is applied lazily there).
        self._key_names = tuple(key_names)
        self._secret_keys = frozenset(secret_keys) if secret_keys else _NO_SECRET_KEYS
        self._exclusive_groups = list(exclusive.items())
        self._inclusive_groups = list(inclusive.items())
        self._has_groups = bool(self._exclusive_groups or self._inclusive_groups)
        self._track_seen = bool(self._finalizers) or self._has_groups
        self._build_alias_index(alias_candidates)

    def _build_alias_index(self, alias_candidates: list[_Candidate]) -> None:
        """Map each alias input name to its canonical key (rare; needs the literals).

        An accepted input name is renamed to the candidate's canonical key in a
        pre-pass, so the candidate machinery never sees the aliases.
        ``_alias_lookup`` maps an input name to its canonical and rank (declaration
        order, first-present-wins); ``_alias_claimed`` is every name an alias spec
        owns, so a leftover one (a superseded alias, or a canonical under
        ``accept_canonical=False``) is dropped rather than passed through as an
        unknown key. The collision checks need the full ``_literal`` map.
        """
        self._alias_lookup: dict[Any, tuple[Any, int]] = {}
        self._alias_claimed: set[Any] = set()
        for candidate in alias_candidates:
            canonical = candidate.key_schema
            self._alias_claimed.add(canonical)
            for rank, name in enumerate(candidate.alias_input_names):
                if name in self._alias_lookup:
                    message = f"alias {name!r} is used by more than one key"
                    raise SchemaError(message)
                if name != canonical and name in self._literal:
                    message = f"alias {name!r} collides with another key in the schema"
                    raise SchemaError(message)
                self._alias_lookup[name] = (canonical, rank)
                self._alias_claimed.add(name)

    def __call__(self, data: Any) -> dict[Any, Any]:  # noqa: PLR0912
        """Validate the mapping, gathering every error into one MultipleInvalid."""
        # A plain dict is the common, hot case, so it short-circuits first.
        # Anything else implementing the Mapping protocol (a MappingProxyType, a
        # multidict, a custom mapping) is validated too, returning a plain dict;
        # voluptuous accepts only dict, so this is a documented superset
        # (carry-forward of voluptuous issue #299). A non-Mapping is rejected.
        if not isinstance(data, dict) and not isinstance(data, Mapping):
            message = "expected a mapping"
            raise DictInvalid(message)

        # Preserve real dict subclasses, matching voluptuous. Other Mapping
        # implementations validate too, but rebuild as a plain dict.
        data_type = type(data)

        if self._alias_lookup:
            data = self._resolve_aliases(data)

        out: dict[Any, Any] = (
            {} if data_type is dict or not issubclass(data_type, dict) else data_type()
        )
        errors: list[Invalid] = []

        # Track matches by candidate position. A bytearray is cheaper than a set
        # here and lets the finalizer distinguish invalid keys from absent ones.
        seen: bytearray | None = (
            bytearray(len(self._candidates)) if self._track_seen else None
        )

        # Inline the literal-key fast path. More complex keys fall back to helpers.
        fast_get = self._literal_fast.get
        literal_get = self._literal.get
        for key, value in data.items():
            entry = fast_get(key)
            if entry is not None:
                index, value_type, check_value = entry
                if seen is not None:
                    seen[index] = 1
                if value_type is not None:
                    # Inlined ``{"k": <type>}``: isinstance, no validator call.
                    if isinstance(value, value_type):
                        out[key] = value
                    else:
                        errors.append(
                            _type_error(value_type.__name__, [key], self._invalid_msg),
                        )
                    continue
                try:
                    out[key] = check_value(value)
                except Invalid as exc:
                    self._collect(key, exc, errors)
                continue
            match = literal_get(key)
            if match is None:
                self._match_validator(key, value, out, errors, seen)
                continue
            # Only Forbidden and Remove literal keys reach here; plain literal
            # keys took the fast path above. ``_apply`` raises the forbidden
            # error or validates the Remove value, and a Remove whose value fails
            # has not consumed the key, so the type/callable candidates get a
            # turn (a ``str: str`` may take it) and ``_match_validator`` applies
            # the extra-key policy if none match.
            index, candidate = match
            if not self._apply(key, value, index, candidate, out, errors, seen):
                self._match_validator(key, value, out, errors, seen)

        if seen is not None:
            self._finalize(out, errors, seen)
        if self._has_groups and seen is not None:
            self._check_groups(out, errors, seen)

        if errors:
            if self._secret_keys:
                self._redact_secrets(errors)
            raise MultipleInvalid(errors)

        return out

    def _redact_secrets(self, errors: list[Invalid]) -> None:
        """Tag every error under a secret key so its value is redacted, not echoed.

        An error's leading path element is the top-level key it happened under, so
        an error anywhere in a secret key's value (a leaf, or deep in a nested
        structure) is caught by matching ``path[0]`` against the secret keys. This
        runs only when validation has already failed, so it never touches the hot
        success path.
        """
        for error in errors:
            if error.path and error.path[0] in self._secret_keys:
                error.secret = True

    def _resolve_aliases(self, data: Mapping[Any, Any]) -> dict[Any, Any]:
        """Rename accepted alias names to their canonical keys.

        Among the alias names present for one canonical, the lowest rank
        (earliest in declaration order) wins, regardless of input order. A name an
        alias spec owns but did not win (a superseded alias, or a canonical that is
        not an accepted input name) is dropped; every other key passes through.
        """
        lookup = self._alias_lookup
        claimed = self._alias_claimed
        normalized: dict[Any, Any] = {}
        chosen: dict[Any, tuple[int, Any]] = {}

        for key, value in data.items():
            info = lookup.get(key)
            if info is not None:
                canonical, rank = info
                previous = chosen.get(canonical)
                if previous is None or rank < previous[0]:
                    chosen[canonical] = (rank, value)
            elif key not in claimed:
                normalized[key] = value

        for canonical, (_, value) in chosen.items():
            normalized[canonical] = value

        return normalized

    def _match_validator(
        self,
        key: Any,
        value: Any,
        out: dict[Any, Any],
        errors: list[Invalid],
        seen: bytearray | None,
    ) -> None:
        """Match a key that is not a literal against the type/callable key schemas."""
        # The first key error is kept (a deeper one wins) so an unmatched key
        # reports why its key was rejected, the way voluptuous does, instead of a
        # generic extra-key error.
        key_error: Invalid | None = None
        for index, candidate in self._validators:
            key_type = candidate.key_type
            if key_type is not None:
                # Inlined type key (``{str: int}``): isinstance, no key-check call.
                if isinstance(key, key_type):
                    if self._apply(key, value, index, candidate, out, errors, seen):
                        return
                    # A Remove key matched but its value did not validate: keep
                    # trying the remaining candidates (a ``str: str`` may take it).
                    continue
                if key_error is None:
                    key_error = _type_error(key_type.__name__, [], None)
                continue
            try:
                new_key = candidate.check_key(key)
            except Invalid as exc:
                if key_error is None or len(exc.path) > len(key_error.path):
                    key_error = exc
                continue
            if self._apply(new_key, value, index, candidate, out, errors, seen):
                return

        self._unmatched(key, value, key_error, out, errors)

    def _apply(  # noqa: PLR0913
        self,
        key: Any,
        value: Any,
        index: int,
        candidate: _Candidate,
        out: dict[Any, Any],
        errors: list[Invalid],
        seen: bytearray | None,
    ) -> bool:
        """Validate a matched pair; return whether the candidate handled the key.

        Returns ``True`` once the pair is stored, removed, or reported. Returns
        ``False`` only when a ``Remove`` key matched but its value did not
        validate, so the key is not consumed and the caller keeps looking (another
        candidate may match, or the extra-key policy applies).
        """
        if candidate.forbidden:
            # A Forbidden key matched (here via a type/callable key schema): its
            # presence alone is the error, so the value is never validated.
            errors.append(self._forbidden_error(key, candidate))
            return True
        if candidate.remove:
            # A Remove key still validates its value (voluptuous semantics): only
            # a value that validates is dropped. A value that fails leaves the key
            # unmatched, so another candidate may take it (``Remove(str): int``
            # alongside ``str: str``), or the extra-key policy applies.
            try:
                candidate.check_value(value)
            except Invalid:
                return False
            if seen is not None:
                seen[index] = 1
            return True
        if seen is not None:
            seen[index] = 1
        value_type = candidate.value_type
        if value_type is not None:
            # Inlined type value (the ``int`` of ``{str: int}``): no value call.
            if isinstance(value, value_type):
                out[key] = value
            else:
                errors.append(
                    _type_error(value_type.__name__, [key], self._invalid_msg)
                )
            return True
        self._store(key, value, candidate.check_value, out, errors)
        return True

    @staticmethod
    def _forbidden_error(key: Any, candidate: _Candidate) -> Invalid:
        """Build the error for a key that a Forbidden marker says must be absent."""
        return Invalid(
            candidate.msg or "key not allowed",
            path=[key],
            code="forbidden_key",
        )

    def _store(
        self,
        key: Any,
        value: Any,
        check: CompiledSchema,
        out: dict[Any, Any],
        errors: list[Invalid],
    ) -> None:
        """Validate and store a value, prefixing any error with its key."""
        try:
            out[key] = check(value)
        except Invalid as exc:
            self._collect(key, exc, errors)

    def _collect(self, key: Any, exc: Invalid, errors: list[Invalid]) -> None:
        """Prefix a failed value's error(s) with its key and gather them."""
        # MultipleInvalid is an Invalid, so one branch covers both a bare leaf
        # error and a sub-schema's collected errors.
        leaf = exc.errors if isinstance(exc, MultipleInvalid) else [exc]
        for error in leaf:
            # voluptuous tags a *leaf* value error "dictionary value" (or "object
            # value" for an Object) via ``error_type``. The attribute is kept for
            # compatibility even though str() no longer renders it (ADR-015). A
            # leaf is recognized by its still-empty path; an error that already
            # descended into a nested structure keeps its own type.
            if not error.path and error.error_type is None:
                error.error_type = self._invalid_msg
            error.prepend([key])
            errors.append(error)

    def _unmatched(
        self,
        key: Any,
        value: Any,
        key_error: Invalid | None,
        out: dict[Any, Any],
        errors: list[Invalid],
    ) -> None:
        """Handle a key that matched no candidate, mirroring voluptuous's order.

        ``ALLOW_EXTRA`` keeps the pair, ``REMOVE_EXTRA`` drops it; both win over a
        wildcard key validator's rejection (``key_error``), because an unmatched
        key under those policies is not an error regardless of why it failed to
        match (voluptuous 0.16.0, PR #524). Otherwise (``PREVENT_EXTRA``) the key
        validator's own rejection is reported, or the generic extra-key error when
        no validator had an opinion.
        """
        if self._extra == ALLOW_EXTRA:
            out[key] = value
        elif self._extra == REMOVE_EXTRA:
            return
        elif key_error is not None:
            # A key validator like Any raises MultipleInvalid; report its leaf
            # errors (keyed by this key), not the wrapper. Key failures are not
            # tagged "dictionary value": they are about the key, not a value.
            leaf = (
                key_error.errors
                if isinstance(key_error, MultipleInvalid)
                else [key_error]
            )
            for error in leaf:
                error.prepend([key])
                errors.append(error)
        else:
            errors.append(self._extra_key_error(key))

    def _extra_key_error(self, key: Any) -> ExtraKeysInvalid:
        """Build the unmatched-key error, suggesting close schema keys when any.

        The offending key is never suggested back (``suggest_exclude``), so a key
        that failed only on its value (a Remove whose value did not validate) does
        not echo itself. Both the exclusion filter and the suggestion match are
        deferred to the error, so an unknown-key error raised in a discarded
        combinator branch never pays for the pool copy or difflib.
        """
        return ExtraKeysInvalid(
            "not a valid option",
            path=[key],
            suggest_value=key,
            suggest_pool=self._key_names,
            suggest_exclude=key,
        )

    def _finalize(
        self,
        out: dict[Any, Any],
        errors: list[Invalid],
        seen: bytearray,
    ) -> None:
        """Apply defaults for absent keys and flag missing required keys."""
        for index, candidate in self._finalizers:
            if seen[index]:
                continue
            if not isinstance(candidate.default, Undefined):
                default = candidate.default()
                if not isinstance(default, Undefined):
                    # The default is validated through the value schema, the way
                    # voluptuous does: a default is coerced (``default="1"``
                    # through ``Coerce(int)`` yields ``1``) and a default that
                    # fails its schema is reported, not stored raw.
                    self._store(
                        candidate.key_schema,
                        default,
                        candidate.check_value,
                        out,
                        errors,
                    )
                    continue
                # A default callable may return ``UNDEFINED`` to decline at
                # validation time, meaning "no default this run". The key is then
                # treated as if it had no default: an Optional is left absent, a
                # Required still reports the missing key below.
                if not candidate.required:
                    continue
            if candidate.complex_keys is not None:
                # Required(Any("a", "b")): at least one of the listed keys must be
                # present (voluptuous 0.16.0). A custom marker msg still wins.
                message = (
                    candidate.msg
                    or f"at least one of {candidate.complex_keys} is required"
                )
                errors.append(
                    RequiredFieldInvalid(message, path=[candidate.key_schema]),
                )
            else:
                # A finalizer reaching here is required and unfilled: it had no
                # default, or its default callable declined. A Required marker's
                # own ``msg`` wins, matching voluptuous.
                errors.append(
                    RequiredFieldInvalid(
                        candidate.msg or "required key not provided",
                        path=[candidate.key_schema],
                    ),
                )

    def _empty_exclusive_group(
        self,
        group: str,
        members: list[int],
        out: dict[Any, Any],
        errors: list[Invalid],
    ) -> None:
        """Handle an exclusive group with no key present: default in, or require one.

        A member's default fills the group (validated through its value schema,
        like any default), which satisfies the group, so it is tried first. With
        no default but a ``required`` member, an empty group is an error.
        """
        for index in members:
            candidate = self._candidates[index]
            if not isinstance(candidate.default, Undefined):
                default = candidate.default()
                if not isinstance(default, Undefined):
                    self._store(
                        candidate.key_schema,
                        default,
                        candidate.check_value,
                        out,
                        errors,
                    )
                    return
                # This default declined. Try the next member, then the required
                # check below.

        if any(self._candidates[index].exclusive_required for index in members):
            keys = [self._candidates[index].key_schema for index in members]
            message = f"exactly one of {keys} is required"
            errors.append(
                RequiredFieldInvalid(message, path=[VirtualPathComponent(group)]),
            )

    def _group_msg(self, members: list[int]) -> str | None:
        """Return the first group member's custom message, if a marker set one."""
        for index in members:
            if self._candidates[index].msg is not None:
                return self._candidates[index].msg
        return None

    def _check_groups(
        self,
        out: dict[Any, Any],
        errors: list[Invalid],
        seen: bytearray,
    ) -> None:
        """Enforce the Exclusive (at most one) and Inclusive (all or none) groups."""
        for group, members in self._exclusive_groups:
            # A plain counting loop: a genexpr plus sum() would allocate a generator
            # and a frame per group on every validation of the mapping.
            present = 0
            for index in members:
                if seen[index]:
                    present += 1
            if present > 1:
                message = self._group_msg(members) or (
                    f"two or more values in the same group of exclusion {group!r}"
                )
                errors.append(
                    ExclusiveInvalid(message, path=[VirtualPathComponent(group)]),
                )
            elif present == 0:
                self._empty_exclusive_group(group, members, out, errors)
        for group, members in self._inclusive_groups:
            # Only the count matters (the missing keys are never named), so count
            # instead of building a list.
            missing = 0
            for index in members:
                if not seen[index]:
                    missing += 1
            if missing and missing != len(members):
                message = self._group_msg(members) or (
                    f"some but not all values in the same group of inclusion {group!r}"
                )
                errors.append(
                    InclusiveInvalid(message, path=[VirtualPathComponent(group)]),
                )


def _iterate_object(obj: Any) -> Any:
    """Yield ``(name, value)`` for an object's attributes, ``__slots__`` included."""
    try:
        attributes = vars(obj)
    except TypeError:
        # A namedtuple (or similar) has no ``__dict__`` but exposes ``_asdict``.
        attributes = obj._asdict() if hasattr(obj, "_asdict") else {}
    yield from attributes.items()
    for key in getattr(obj, "__slots__", ()):
        if key != "__dict__":
            yield (key, getattr(obj, key))


class _ObjectValidator:
    """Validate an object's attributes like a mapping, then rebuild the object."""

    def __init__(self, mapping: _MappingValidator, cls: Any) -> None:
        """Store the attribute validator and the optional required class."""
        self._mapping = mapping
        self._cls = cls

    def __call__(self, data: Any) -> Any:
        """Validate the attributes and reconstruct an object of the same type."""
        if self._cls is not UNDEFINED and not isinstance(data, self._cls):
            message = f"expected a {self._cls!r}"
            raise ObjectInvalid(message)

        # voluptuous skips attributes that are None, so they fall to their schema
        # default (or are simply absent) rather than failing a typed value check.
        attributes = {
            name: value for name, value in _iterate_object(data) if value is not None
        }

        validated = self._mapping(attributes)
        return type(data)(**validated)


class _SequenceValidator:
    """Validate a sequence: every item must match one of the element schemas."""

    def __init__(
        self,
        base_type: Any,
        element_checks: list[CompiledSchema],
        remove_flags: list[bool],
    ) -> None:
        """Store the sequence category to match and the per-element validators."""
        self._base_type = base_type
        self._element_checks = element_checks
        self._remove_flags = remove_flags
        # A Remove element drops matching items, so the fast single-element paths
        # (which always keep a match) are disabled when any element is a Remove.
        has_remove = any(remove_flags)
        # The common case is a single element schema (``[int]``, ``[str]``); keep
        # it on a tight loop that skips the multi-candidate matching machinery.
        self._single = (
            element_checks[0] if len(element_checks) == 1 and not has_remove else None
        )
        # A single plain type element (``[int]``) is the hottest case: inline the
        # isinstance so each item costs no function call at all.
        self._single_type = getattr(self._single, "checked_type", None)

    def __call__(self, data: Any) -> Any:  # noqa: PLR0912
        """Validate each item, rebuilding the sequence of the original type."""
        if not isinstance(data, self._base_type):
            message = f"expected a {self._base_type.__name__}"
            raise SequenceTypeInvalid(message)

        result: list[Any] = []
        errors: list[Invalid] = []
        item_type = self._single_type

        if item_type is not None:
            # Inlined ``[<type>]``: isinstance per item, no per-item call.
            expected = item_type.__name__
            append = result.append
            for index, item in enumerate(data):
                if isinstance(item, item_type):
                    append(item)
                else:
                    errors.append(
                        TypeInvalid(
                            f"expected {expected}",
                            path=[index],
                            context={"expected": expected},
                        ),
                    )
        elif (check := self._single) is not None:
            append = result.append
            for index, item in enumerate(data):
                try:
                    append(check(item))
                except Invalid as exc:
                    exc.prepend([index])
                    if isinstance(exc, MultipleInvalid):
                        errors.extend(exc.errors)
                    else:
                        errors.append(exc)
        else:
            for index, item in enumerate(data):
                self._validate_item(index, item, result, errors)

        if errors:
            raise MultipleInvalid(errors)

        # A plain list is the hot case: ``result`` is already a fresh list of the
        # validated items, so return it directly rather than copying it into a new
        # one. Other types are rebuilt as the data's own type (voluptuous semantics),
        # so a subclass or namedtuple round-trips. A namedtuple takes its fields
        # positionally, not a single iterable, so it is rebuilt with a splat.
        out_type = type(data)
        if out_type is list:
            return result
        if issubclass(out_type, tuple) and hasattr(out_type, "_fields"):
            return out_type(*result)
        return out_type(result)

    def _validate_item(
        self,
        index: int,
        item: Any,
        result: list[Any],
        errors: list[Invalid],
    ) -> None:
        """Match an item against the element schemas, recording any failure.

        An item must match one of the element schemas. When none match,
        voluptuous reports the *last* candidate's error (so ``[int, str]`` on a
        float reports "expected str"), keeping its message and subclass. An item
        matching a ``Remove`` element is dropped instead of appended.
        """
        last_error: Invalid | None = None
        for check, is_remove in zip(
            self._element_checks, self._remove_flags, strict=True
        ):
            try:
                validated = check(item)
            except Invalid as exc:
                last_error = exc
            else:
                if not is_remove:
                    result.append(validated)
                return

        if last_error is None:
            # No element schemas at all: nothing can match this item.
            errors.append(Invalid("invalid value", path=[index]))
            return

        last_error.prepend([index])
        if isinstance(last_error, MultipleInvalid):
            errors.extend(last_error.errors)
        else:
            errors.append(last_error)
