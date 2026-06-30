r"""Catch catastrophically backtracking regular expressions before compiling them.

``from_json_schema`` turns a JSON Schema ``pattern`` into a ``Match`` validator,
and a ``pattern`` can come from an untrusted document. Python's ``re`` engine
backtracks, so a pattern like ``(a+)+$`` runs in exponential time on crafted
input: a denial-of-service vector when the schema author is not trusted.

There is no safe timeout for ``re`` in pure Python, so this module rejects the
common catastrophic shapes up front. One family is an unbounded quantifier on a
group that can match the same input more than one way:

- nested quantifiers: ``(a+)+``, ``(a*)*``;
- a nullable body or alternative: ``(a?)+``, ``(a|a?)+``;
- overlapping alternatives where one is a prefix of another: ``(a|aa)+``;
- a variable-length run of one character: ``(a{1,3})+``, ``([a-z]{1,5})+``.

The other family is two adjacent unbounded quantifiers on atoms whose character
sets overlap, where the engine can split the input between them many ways:

- ``a+a+``, ``\d+\d+``, ``.*.*``, ``[a-z]+[a-z]*``.

Disjoint adjacent quantifiers (``\w+\s+``, ``\d+\D+``) do not backtrack and are
left alone.

This is a heuristic, not a proof. It targets the dominant catastrophic shapes,
not every pathological pattern (a disjoint alternation like ``(foo|bar)+`` is
left alone, since it does not backtrack). Treat it as defense in depth for the
untrusted decode path, not a guarantee. Developer-written ``Match`` patterns are
not checked, matching voluptuous; only the untrusted decode path uses this.
"""

from __future__ import annotations

from typing import Any

# The quantifiers that allow unbounded repetition, the fuel for backtracking
# blow-up. ``?`` (zero or one) cannot drive it on its own and is ignored.
_UNBOUNDED_QUANTIFIERS = frozenset({"*", "+"})

# A repeat of this many or more on an ambiguous body backtracks dangerously, so a
# fixed ``{n}`` of two or more is treated like ``+``/``*``.
_MIN_DANGEROUS_REPEAT = 2

# Above this many alternatives in one group, the pairwise overlap scan is skipped
# and the group is treated as ambiguous, so analysis cannot itself become a DoS.
_MAX_ALTERNATIVES = 50

# A character class is never expanded past this many codepoints; a wider range is
# treated as ANY instead, so a crafted ``[\\x00-\\U0010ffff]`` cannot hang the guard.
_MAX_CLASS_SIZE = 1024

# Deepest group nesting the nullability check recurses into; past it a group body
# is conservatively treated as nullable, bounding the work on adversarial nesting.
_MAX_NULLABLE_DEPTH = 20


def _brace_is_unbounded(pattern: str, start: int) -> bool:
    """Return whether the ``{...}`` quantifier at ``start`` has no upper bound.

    Unbounded means a comma with nothing after it: ``{2,}`` and ``{,}`` repeat
    without limit. ``{2}`` (exact), ``{2,5}`` and ``{,5}`` (capped) are bounded.
    A ``{`` that does not open a well-formed quantifier is treated as a literal.
    """
    end = pattern.find("}", start)
    if end == -1:
        return False
    body = pattern[start + 1 : end]
    if "," not in body:
        return False
    return body.split(",", 1)[1] == ""


# Representative finite sets for the common escape categories, enough to decide
# whether two quantified atoms can match a shared character.
_DIGITS = frozenset("0123456789")
_WORD = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
_SPACE = frozenset(" \t\n\r\f\v")
_ESCAPE_SETS = {"d": _DIGITS, "w": _WORD, "s": _SPACE}

# A matchable set is one of: ``None`` (matches anything), a ``frozenset`` of
# characters (positive), or ``("neg", frozenset)`` (everything except the set).
_CharSet = Any


def _overlaps(left: _CharSet, right: _CharSet) -> bool:
    """Return whether two matchable sets can both match a shared character."""
    if left is None or right is None:
        return True
    left_neg = isinstance(left, tuple)
    right_neg = isinstance(right, tuple)
    left_set = left[1] if left_neg else left
    right_set = right[1] if right_neg else right
    if not left_neg and not right_neg:
        return bool(left_set & right_set)
    if left_neg and right_neg:
        # Two complements over a large alphabet always share characters.
        return True
    positive, negated = (right_set, left_set) if left_neg else (left_set, right_set)
    return bool(positive - negated)


def _class_set(body: str) -> _CharSet:
    r"""Best-effort matchable set for a ``[...]`` class body, or ANY if unsure.

    A range is never materialized past ``_MAX_CLASS_SIZE`` codepoints: a crafted
    class like ``[ -\\U0010ffff]`` would otherwise expand into a million-element
    set and turn the guard into the denial of service it exists to prevent. An
    oversized class is treated as ANY (``None``), which is conservative.
    """
    negated = body.startswith("^")
    chars = body[1:] if negated else body
    if "\\" in chars:
        return None  # Escapes inside a class: do not try to analyze, assume ANY.
    collected: set[str] = set()
    index = 0
    while index < len(chars):
        if index + 2 < len(chars) and chars[index + 1] == "-":
            start, end = chars[index], chars[index + 2]
            if start <= end:
                if ord(end) - ord(start) >= _MAX_CLASS_SIZE:
                    return None  # An enormous range: treat as ANY, do not expand it.
                collected.update(chr(code) for code in range(ord(start), ord(end) + 1))
            index += 3
        else:
            collected.add(chars[index])
            index += 1
        if len(collected) >= _MAX_CLASS_SIZE:
            return None  # Many ranges adding up: still cap the work.
    frozen = frozenset(collected)
    return ("neg", frozen) if negated else frozen


def _next_atom(pattern: str, index: int) -> tuple[_CharSet, int]:  # noqa: PLR0911
    """Parse one atom at ``index``, returning its matchable set and the next index.

    ``None`` (ANY) is returned for an atom this heuristic does not analyze (a
    group, an unknown escape), which is conservative: ANY overlaps everything.
    """
    char = pattern[index]
    if char == "\\":
        if index + 1 >= len(pattern):
            return frozenset({"\\"}), index + 1
        nxt = pattern[index + 1]
        if nxt in _ESCAPE_SETS:
            return _ESCAPE_SETS[nxt], index + 2
        if nxt.lower() in _ESCAPE_SETS and nxt.isupper():
            return ("neg", _ESCAPE_SETS[nxt.lower()]), index + 2
        if nxt.isalnum():
            return None, index + 2  # \b, \A, ... assume ANY.
        return frozenset({nxt}), index + 2  # An escaped literal like \. or \+.
    if char == "[":
        end = pattern.find("]", index + 1)
        if end == -1:
            return frozenset({"["}), index + 1
        return _class_set(pattern[index + 1 : end]), end + 1
    if char == "(":
        return None, _skip_group(pattern, index)
    if char == ".":
        return None, index + 1
    return frozenset({char}), index + 1


def _skip_group(pattern: str, index: int) -> int:
    """Return the index just past the group opening at ``index``."""
    depth = 0
    in_class = False
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            index += 2
            continue
        if in_class:
            in_class = char != "]"
        elif char == "[":
            in_class = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return index


def _has_adjacent_overlap(pattern: str) -> bool:
    r"""Return whether two adjacent unbounded-quantified atoms can overlap.

    ``a+a+`` / ``\d+\d+`` / ``.*.*`` backtrack catastrophically; ``\w+\s+`` and
    other disjoint pairs do not. Atoms inside a ``[...]`` class are not atoms in
    their own right, so the scan skips class interiors.
    """
    previous: _CharSet = "none"  # The prior atom's set if it was unbounded-quantified.
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char in "|^$":
            previous = "none"  # Alternation or an anchor breaks adjacency.
            index += 1
            continue
        if char == ")":
            index += 1
            continue
        current, after = _next_atom(pattern, index)
        unbounded = _quantifier_after(pattern, after)
        if unbounded and previous != "none" and _overlaps(previous, current):
            return True
        previous = current if unbounded else "none"
        index = _skip_quantifier(pattern, after) if unbounded else after
    return False


def _skip_quantifier(pattern: str, index: int) -> int:
    """Return the index past the quantifier (and any lazy ``?``).

    A malformed brace (``a{`` with no closing ``}``) advances by one, never back to
    the start: this primitive must always make progress, or a caller that walks a
    pattern with it spins forever.
    """
    if index < len(pattern) and pattern[index] == "{":
        end = pattern.find("}", index)
        index = end + 1 if end != -1 else index + 1
    else:
        index += 1
    if index < len(pattern) and pattern[index] in "?+":
        index += 1
    return index


def is_catastrophic(pattern: str) -> bool:
    """Return whether ``pattern`` has a known catastrophic-backtracking shape.

    Two families: an unbounded quantifier on an ambiguous group (nesting, a
    nullable body, or overlapping alternatives), and two adjacent unbounded
    quantifiers on overlapping character sets.

    The group scan tracks, for each open group, its body span and whether that
    body contains an unbounded quantifier; a quantified group also counts as an
    unbounded quantifier in its enclosing group, so nesting is caught at any depth.
    """
    if _has_adjacent_overlap(pattern):
        return True
    # Per open group: [body_start_index, body_has_unbounded_quantifier].
    stack: list[list[Any]] = []
    index = 0
    length = len(pattern)
    in_class = False
    while index < length:
        char = pattern[index]
        if char == "\\":
            index += 2  # Skip the escaped character; it is a literal.
            continue
        if in_class:
            in_class = char != "]"
            index += 1
            continue
        if char == "[":
            in_class = True
        elif char == "(":
            stack.append([index, False])
        elif char == ")":
            start, body_unbounded = stack.pop() if stack else [index, False]
            # A repeat of 2+ (``+``, ``*``, ``{2,}``, ``{2}``, ``{,3}`` ...) drives
            # backtracking; a fixed ``{15}`` on an unbounded body is just as
            # exponential as ``+``, so it counts too.
            quantified = _quantifier_repeats(pattern, index + 1)
            body = pattern[start + 1 : index]
            if quantified and (body_unbounded or _body_is_ambiguous(body)):
                return True
            if quantified and stack:
                stack[-1][1] = True
        elif stack and _quantifier_after(pattern, index):
            # An unbounded quantifier in this group's body marks it, so a quantifier
            # on the group itself later makes the nesting catastrophic.
            stack[-1][1] = True
        index += 1
    return False


def _quantifier_after(pattern: str, index: int) -> bool:
    """Return whether an unbounded quantifier sits at ``index``."""
    if index >= len(pattern):
        return False
    char = pattern[index]
    if char in _UNBOUNDED_QUANTIFIERS:
        return True
    return char == "{" and _brace_is_unbounded(pattern, index)


def _quantifier_repeats(pattern: str, index: int) -> bool:
    """Return whether a quantifier at ``index`` can repeat two or more times.

    ``+``, ``*`` and an unbounded ``{n,}`` repeat without limit; a fixed ``{n}``
    or capped ``{n,m}`` still drives backtracking when it repeats at least twice.
    ``?`` (zero or one) cannot.
    """
    if index >= len(pattern):
        return False
    char = pattern[index]
    if char in _UNBOUNDED_QUANTIFIERS:
        return True
    return char == "{" and _brace_repeats(pattern, index)


def _brace_repeats(pattern: str, start: int) -> bool:
    """Return whether the ``{...}`` quantifier at ``start`` can repeat 2+ times."""
    end = pattern.find("}", start)
    if end == -1:
        return False
    parts = pattern[start + 1 : end].split(",")
    try:
        if len(parts) == 1:
            return int(parts[0]) >= _MIN_DANGEROUS_REPEAT
        upper = parts[1]
        return upper == "" or int(upper) >= _MIN_DANGEROUS_REPEAT
    except ValueError:
        return False


def _body_is_ambiguous(body: str) -> bool:
    """Return whether a quantified group's body can match its input two ways.

    A nullable body (matches the empty string) blows up under repetition, and so
    do overlapping alternatives (one a prefix of another, or equal). Disjoint
    alternatives like ``foo|bar`` are not ambiguous. A leading group modifier
    (``?:``, ``?i:``, ``?P<name>``, a lookaround) is stripped first so the
    alternatives inside a non-capturing or flagged group are still compared.
    """
    body = _strip_group_modifier(body)
    alternatives = _split_top_level(body)
    if len(alternatives) == 1:
        return _is_nullable(body) or _is_homogeneous_run(body)
    if any(_is_nullable(alt) for alt in alternatives):
        return True
    # Cap the pairwise comparison so a pattern with a huge alternation cannot turn
    # the detector itself into the denial-of-service it is meant to prevent; a
    # very large alternation under a repeat is treated as ambiguous.
    if len(alternatives) > _MAX_ALTERNATIVES:
        return True
    atom_lists = [_atom_sets(alt) for alt in alternatives]
    for first, left in enumerate(atom_lists):
        for right in atom_lists[first + 1 :]:
            if _alternatives_overlap(left, right):
                return True
    return False


def _atom_sets(alternative: str) -> list[_CharSet] | None:
    """Parse an alternative into its sequence of atom char-sets, or None to bail.

    A quantifier or a group inside the alternative makes precise comparison hard,
    so it returns None and the caller treats the pair as overlapping (conservative).
    """
    sets: list[_CharSet] = []
    index = 0
    while index < len(alternative):
        if alternative[index] in "*+?{(":
            return None
        char_set, after = _next_atom(alternative, index)
        sets.append(char_set)
        index = after
    return sets


def _is_homogeneous_run(body: str) -> bool:
    r"""Return whether a flat body matches a variable-length run of one shared char.

    ``(a{1,3})+`` and ``([a-z]{1,5})+`` blow up exactly like ``(a+)+``: the inner
    quantifier is bounded, but it still matches a *variable*-length run of the same
    character, so an outer repeat can split a homogeneous run many ways. The tell is
    a body whose atoms all share a common character and where at least one atom
    repeats a variable number of times. A separator that cannot be that character
    (the ``\.`` in ``(\d{1,3}\.){3}``) breaks the run, so that pattern is left alone.

    Alternation or a nested group inside the body is out of scope here; the caller's
    other checks (nullability, overlapping alternatives) cover those shapes.
    """
    atoms: list[_CharSet] = []
    saw_variable = False
    index = 0
    while index < len(body):
        char = body[index]
        if char in "^$":
            index += 1
            continue
        if char in "|(":
            return False
        atom_set, after = _next_atom(body, index)
        atoms.append(atom_set)
        if _quantifier_is_variable(body, after):
            saw_variable = True
        index = _skip_quantifier(body, after) if _has_quantifier(body, after) else after
    return bool(atoms) and saw_variable and _shared_character_exists(atoms)


def _quantifier_is_variable(pattern: str, index: int) -> bool:
    """Return whether the quantifier at ``index`` repeats a *variable* number of times.

    ``*``, ``+`` and ``?`` vary, and so does a brace whose bounds differ (``{1,3}``,
    ``{2,}``). A fixed ``{n}`` does not, and neither does a bare atom.
    """
    if index >= len(pattern):
        return False
    char = pattern[index]
    if char in "*+?":
        return True
    return char == "{" and _brace_is_variable(pattern, index)


def _brace_is_variable(pattern: str, start: int) -> bool:
    """Return whether the ``{...}`` quantifier at ``start`` spans more than one count.

    ``{1,3}`` and ``{2,}`` vary; a fixed ``{n}`` and a malformed or non-numeric
    brace do not.
    """
    end = pattern.find("}", start)
    if end == -1:
        return False
    parts = pattern[start + 1 : end].split(",")
    if len(parts) == 1:
        return False  # ``{n}``: a fixed count.
    low, high = parts[0], parts[1]
    if high == "":
        return True  # ``{m,}``: unbounded.
    try:
        return int(high) > (int(low) if low else 0)
    except ValueError:
        return False


def _shared_character_exists(atoms: list[_CharSet]) -> bool:
    """Return whether a single character is matched by every atom set.

    ``None`` is ANY and matches everything; a ``("neg", set)`` matches everything
    outside the set. With no positive set in play a shared character always exists
    over a large alphabet, so only the positive sets need scanning, and only the
    smallest one at that.
    """
    positives = [atom for atom in atoms if isinstance(atom, frozenset)]
    if not positives:
        return True
    smallest = min(positives, key=len)
    return any(all(_set_matches(atom, char) for atom in atoms) for char in smallest)


def _set_matches(atom: _CharSet, char: str) -> bool:
    """Return whether one matchable set matches ``char``."""
    if atom is None:
        return True
    if isinstance(atom, tuple):
        return char not in atom[1]
    return char in atom


def _alternatives_overlap(
    left: list[_CharSet] | None, right: list[_CharSet] | None
) -> bool:
    """Return whether two alternatives can both match a common string.

    True when every atom up to the shorter length overlaps, so one alternative is
    a prefix of (or equal to) the other in a way the engine can split ambiguously
    under a repeat. ``ab`` vs ``a[b]`` overlap; ``cat`` vs ``car`` do not. A bail
    (``None`` from ``_atom_sets``) is treated as overlapping.
    """
    if left is None or right is None:
        return True
    return all(_overlaps(a, b) for a, b in zip(left, right, strict=False))


def _strip_group_modifier(body: str) -> str:
    """Strip a leading group-type prefix (``?:``, ``?i:``, ``?P<n>``, lookaround)."""
    if not body.startswith("?"):
        return body
    if body.startswith("?P<"):
        end = body.find(">")
        return body[end + 1 :] if end != -1 else body
    if body.startswith(("?<=", "?<!")):
        return body[3:]
    if body.startswith(("?=", "?!")):
        return body[2:]
    colon = body.find(":")
    return body[colon + 1 :] if colon != -1 else body


def _split_top_level(body: str) -> list[str]:
    """Split a group body on the ``|`` tokens that sit at its own nesting level."""
    parts: list[str] = []
    depth = 0
    in_class = False
    start = 0
    index = 0
    while index < len(body):
        char = body[index]
        if char == "\\":
            index += 2
            continue
        if in_class:
            in_class = char != "]"
        elif char == "[":
            in_class = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "|" and depth == 0:
            parts.append(body[start:index])
            start = index + 1
        index += 1
    parts.append(body[start:])
    return parts


def _is_nullable(alternative: str, depth: int = 0) -> bool:
    """Return whether an alternative can match the empty string.

    Walks the alternative atom by atom: it is nullable only when *every* atom can
    contribute nothing, since one mandatory atom forces at least one character. An
    atom contributes nothing when it carries a zero-allowing quantifier (``?``,
    ``*``, or a brace whose minimum is zero like ``{0,3}``), or, for a group, when
    its own body is nullable. This catches ``a?``, ``.*``, ``[a-z]*``, ``(...)?``,
    and the multi-atom forms ``a?b?`` / ``a*b*`` that a single-atom check missed,
    while still rejecting ``ab?`` (the ``a`` is mandatory). Zero-width anchors
    (``^``/``$``) consume nothing and are skipped.
    """
    index = 0
    length = len(alternative)
    while index < length:
        char = alternative[index]
        if char in "^$":
            index += 1
            continue
        if char == "(":
            after = _skip_group(alternative, index)
            optional = _quantifier_allows_zero(
                alternative, after
            ) or _group_is_nullable(
                alternative[index + 1 : after - 1],
                depth,
            )
        else:
            _, after = _next_atom(alternative, index)
            optional = _quantifier_allows_zero(alternative, after)
        if not optional:
            return False
        index = (
            _skip_quantifier(alternative, after)
            if _has_quantifier(alternative, after)
            else after
        )
    return True


def _has_quantifier(pattern: str, index: int) -> bool:
    """Return whether a quantifier (``*``, ``+``, ``?``, or ``{``) sits at ``index``."""
    return index < len(pattern) and pattern[index] in "*+?{"


def _quantifier_allows_zero(pattern: str, index: int) -> bool:
    """Return whether the quantifier at ``index`` lets its atom match zero times."""
    if index >= len(pattern):
        return False
    char = pattern[index]
    if char in "*?":
        return True
    if char == "{":
        end = pattern.find("}", index)
        if end == -1:
            return False
        lower = pattern[index + 1 : end].split(",", maxsplit=1)[0]
        return lower == "" or (lower.isdigit() and int(lower) == 0)
    return False


def _group_is_nullable(body: str, depth: int) -> bool:
    """Return whether a group body (any of its alternatives) can match the empty string."""
    if depth >= _MAX_NULLABLE_DEPTH:
        return True  # Too deeply nested to analyze: assume nullable (conservative).
    inner = _strip_group_modifier(body)
    return any(_is_nullable(alt, depth + 1) for alt in _split_top_level(inner))
