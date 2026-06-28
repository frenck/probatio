#!/usr/bin/env python3
"""Execute every Python code block in the docs and check their output comments.

Walks the docs content tree, extracts fenced ```python blocks, and runs each in
a temporary working directory. Two things are checked:

1. **Every block runs.** A block may opt out or declare an expected exception
   with a trailing HTML marker comment on the line *before* the fence:

       <!-- verify: skip -->                  do not execute this block
       <!-- verify: raises MultipleInvalid -->   the block must raise that error

2. **Output comments match.** When a statement is followed (or trailed inline) by
   a comment showing its value, that value is verified against what the code
   actually produces. The checked forms are:

       expr            # {'a': 1}          bare expression, inline repr
       name = expr     # {'a': 1}          assignment, the variable's repr
       print(expr)     # 1                 the printed text
       value                               multi-line display:
       # a: 1                                a `str` value (or print output)
       # b: 2                               shown line by line

   A comment is only treated as an assertion when it *looks* like output (starts
   with a quote, bracket, digit, ``b'``/``b"``, or ``True``/``False``/``None``),
   so prose comments are ignored. Two conventions are tolerated so the docs stay
   readable: a trailing ``  (note)`` annotation after the value, and ``...`` as an
   elision marker (matched as a gap, which also absorbs volatile object
   addresses like ``0x...``).

Usage:
    python docs/verify_examples.py
"""

from __future__ import annotations
import __future__

import ast
import io
import os
import re
import sys
import tempfile
import traceback
import types
from contextlib import redirect_stdout
from pathlib import Path

DOCS = Path(__file__).resolve().parent / "src" / "content" / "docs"

# Capture an optional marker on the line before the fence, then the block body.
# The marker may be an HTML comment (Markdown) or an MDX expression comment.
BLOCK = re.compile(
    r"(?:(?:<!--|\{/\*)\s*verify:\s*(?P<marker>.*?)\s*(?:-->|\*/\})\s*\n)?"
    r"```python\n(?P<code>.*?)\n```",
    re.DOTALL,
)


def _is_instance_of(exc, name, env):
    """Whether ``exc`` is an instance of the class named by an expect marker.

    Resolves the name against the example's own namespace, the ``probatio``
    package (and its ``error`` module), and builtins, so a marker naming a base
    error matches any subclass actually raised.
    """
    import builtins
    import importlib

    candidates = [env.get("probatio"), builtins]
    try:
        candidates.append(importlib.import_module("probatio"))
        candidates.append(importlib.import_module("probatio.error"))
    except ImportError:
        pass
    for ns in candidates:
        cls = getattr(ns, name, None)
        if isinstance(cls, type) and isinstance(exc, cls):
            return True
    return False


def iter_pages():
    for path in sorted(DOCS.rglob("*.md")) + sorted(DOCS.rglob("*.mdx")):
        text = path.read_text()
        blocks = []
        for match in BLOCK.finditer(text):
            marker = (match.group("marker") or "").strip()
            line = text[: match.start("code")].count("\n") + 1
            blocks.append((line, marker, match.group("code")))
        if blocks:
            yield path, blocks


def _looks_like_output(text: str) -> bool:
    """Whether a comment value looks like a shown result rather than prose."""
    text = text.strip()
    if not text:
        return False
    if text[0] in "'\"{[(":
        return True
    if text[:2] in ("b'", 'b"'):
        return True
    return bool(re.match(r"-?\d", text) or re.match(r"(True|False|None)\b", text))


def _extract_value(text: str) -> str:
    """Isolate the leading Python repr token, dropping any trailing note.

    Docs append freeform asides after a shown value (``  (note)``, ``, note``,
    `` - note``). We compare only the value, so the token is scanned by
    structure: a quoted string/bytes literal to its closing quote, a bracketed
    literal to its matching close, or a bare number/keyword to the next comma or
    space.
    """
    text = text.strip()
    if not text:
        return text
    if text[:2] in ("b'", 'b"') or text[0] in "'\"":
        i = 2 if text[0] == "b" else 1
        quote = text[i - 1]
        while i < len(text):
            if text[i] == "\\":
                i += 2
                continue
            if text[i] == quote:
                return text[: i + 1]
            i += 1
        return text
    if text[0] in "{[(":
        depth = 0
        instr = None
        for i, ch in enumerate(text):
            if instr is not None:
                if ch == instr:
                    instr = None
            elif ch in "'\"":
                instr = ch
            elif ch in "{[(":
                depth += 1
            elif ch in "}])":
                depth -= 1
                if depth == 0:
                    return text[: i + 1]
        return text
    match = re.match(r"[^,\s]+", text)
    return match.group(0) if match else text


def _fuzzy_match(expected: str, actual: str) -> bool:
    """Match with ``...`` acting as a gap that absorbs any run of characters."""
    idx = 0
    for part in expected.split("..."):
        if not part:
            continue
        found = actual.find(part, idx)
        if found < 0:
            return False
        idx = found + len(part)
    return True


def _compare(expected: str, actual: str) -> bool:
    """Compare an isolated expected value against the actual text."""
    if "..." in expected:
        return _fuzzy_match(expected, actual)
    return expected == actual


def _strip_comment_prefix(raw: str) -> str:
    """Drop the leading ``#`` and at most one following space, keeping indent."""
    raw = raw.lstrip()[1:]
    if raw.startswith(" "):
        raw = raw[1:]
    return raw


def _following_comment(lines: list[str], end_lineno: int) -> list[str]:
    """Comment lines (``# ...``) immediately after a statement, prefix stripped."""
    out = []
    j = end_lineno  # 0-based index of the line after the statement
    while j < len(lines) and lines[j].lstrip().startswith("#"):
        out.append(_strip_comment_prefix(lines[j]))
        j += 1
    return out


def _inline_comment(lines: list[str], end_lineno: int, end_col: int) -> str | None:
    """A ``# ...`` comment trailing a statement on its own last line."""
    tail = lines[end_lineno - 1][end_col:]
    if "#" not in tail:
        return None
    return tail.split("#", 1)[1].strip()


def _is_print(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "print"
    )


def _checkable_target(node: ast.AST):
    """For ``name = expr``, the variable name whose value we can re-read."""
    if (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    ):
        return node.targets[0].id
    return None


def _check_output(node, value, is_print, lines, label, failures) -> None:
    """Compare a statement's shown value against its output comment, if any.

    ``value`` is the captured stdout text for a ``print`` call, otherwise the
    object the statement produced (compared by ``repr``, the form the docs show).
    """
    # The single-line form: a repr for expressions, the printed text for print
    # (which always appends exactly one newline).
    if is_print:
        single = value[:-1] if value.endswith("\n") else value
    else:
        single = repr(value)

    inline = _inline_comment(lines, node.end_lineno, node.end_col_offset)
    if inline is not None:
        if _looks_like_output(inline) and not _compare(_extract_value(inline), single):
            failures.append(f"{label}  expected {inline!r}  got {single!r}")
        return

    following = _following_comment(lines, node.end_lineno)
    if not following:
        return

    if len(following) == 1:
        expected = following[0]
        if _looks_like_output(expected) and not _compare(
            _extract_value(expected), single
        ):
            failures.append(f"{label}  expected {expected!r}  got {single!r}")
        return

    # Multi-line: a line-by-line display of decoded str or print output.
    if following[0].startswith(("b'", 'b"', "{", "[")):
        return  # a single repr never spans comment lines
    if is_print:
        actual = value.rstrip("\n")
    elif isinstance(value, bytes):
        actual = value.decode("utf-8").rstrip("\n")
    elif isinstance(value, str):
        actual = value.rstrip("\n")
    else:
        return
    # Only treat the comment as a display when its first line matches the output's
    # first line; otherwise it is prose about the value, not a transcript of it.
    actual_lines = actual.split("\n")
    if not actual_lines or following[0] != actual_lines[0]:
        return
    expected = "\n".join(following)
    if not _compare(expected, actual):
        failures.append(
            f"{label}  display mismatch\n"
            f"    expected: {following}\n"
            f"    got:      {actual_lines}"
        )


def _print_comment(node, lines) -> str | None:
    """The output comment on a ``print(...)`` statement, if it looks like output."""
    inline = _inline_comment(lines, node.end_lineno, node.end_col_offset)
    if inline is not None:
        return inline if _looks_like_output(inline) else None
    following = _following_comment(lines, node.end_lineno)
    if len(following) == 1 and _looks_like_output(following[0]):
        return following[0]
    return None


def _check_nested_prints(node, stdout, lines, label, failures) -> None:
    """Verify ``print`` comments nested inside a compound statement.

    The compound (a ``try``/``with``/``for``) is executed once with its stdout
    captured. Each nested ``print`` carrying an output-looking comment is matched,
    in source order, against the captured lines. Reconciliation only happens when
    the comment count equals the line count, so a loop that prints N times (one
    statement, N lines) is left alone rather than mismatched.
    """
    commented = sorted(
        (
            (sub.lineno, _print_comment(sub, lines))
            for sub in ast.walk(node)
            if _is_print(sub) and _print_comment(sub, lines) is not None
        ),
    )
    if not commented:
        return
    output = stdout.split("\n")
    if output and output[-1] == "":
        output = output[:-1]
    if len(commented) != len(output):
        return  # counts do not line up (a loop, or multi-line output); skip safely
    for (_lineno, expected), actual in zip(commented, output, strict=True):
        if not _compare(_extract_value(expected), actual):
            failures.append(
                f"{label}  nested print expected {expected!r} got {actual!r}"
            )


def _future_flags(tree: ast.Module) -> int:
    """Compiler flags for any ``from __future__`` import at the top of a block.

    Each statement is compiled on its own, so a block's ``from __future__ import
    annotations`` would not reach the later statements without this; the class that
    follows would then evaluate its annotations eagerly (before Python 3.14) and a
    self-referential dataclass field (``children: list[Tree]``) would raise a
    NameError before ``get_type_hints`` ever runs.
    """
    flags = 0
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            for alias in node.names:
                feature = getattr(__future__, alias.name, None)
                if feature is not None:
                    flags |= feature.compiler_flag
    return flags


def run_block(env, code, label, expect, failures) -> None:
    """Execute one block statement by statement, checking output comments.

    Mirrors a reader running the snippet top to bottom in one namespace. A
    ``raises`` marker is satisfied if any statement raises the expected error.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raised = exc
    else:
        raised = None
        lines = code.split("\n")
        flags = _future_flags(tree)
        for node in tree.body:
            filename = label.split("  ", 1)[0]
            try:
                if _is_print(node):
                    buf = io.StringIO()
                    with redirect_stdout(buf):
                        exec(_compile_node(node, filename, flags), env)
                    _check_output(node, buf.getvalue(), True, lines, label, failures)
                elif isinstance(node, ast.Expr) and not _is_docstring(node):
                    # eval/exec here is the whole point of this tool: it runs the
                    # project's own first-party documentation snippets. The input
                    # is our docs, not untrusted data, and the values are real
                    # probatio calls, so literal_eval cannot stand in.
                    value = eval(
                        compile(
                            ast.Expression(node.value),
                            filename,
                            "eval",
                            flags=flags,
                            dont_inherit=True,
                        ),
                        env,
                    )
                    _check_output(node, value, False, lines, label, failures)
                else:
                    # A compound statement (try/with/for/if) may print inside its
                    # body, so capture stdout and reconcile nested print comments.
                    buf = io.StringIO()
                    with redirect_stdout(buf):
                        exec(_compile_node(node, filename, flags), env)
                    target = _checkable_target(node)
                    if target is not None and target in env:
                        _check_output(node, env[target], False, lines, label, failures)
                    else:
                        _check_nested_prints(
                            node, buf.getvalue(), lines, label, failures
                        )
            except BaseException as exc:  # noqa: BLE001
                raised = exc
                break

    if raised is not None:
        got = type(raised).__name__
        # A raises marker is satisfied only by the exception class (an exact name
        # or a subclass), never by a message substring, so a wrong class with the
        # right words in its message cannot pass.
        if expect and (got == expect or _is_instance_of(raised, expect, env)):
            return
        tb = traceback.format_exception_only(type(raised), raised)[-1].strip()
        if expect:
            failures.append(f"{label}  expected {expect} but raised {got}: {tb}")
        else:
            failures.append(f"{label}  {got}: {tb}")
        return

    if expect:
        failures.append(f"{label}  expected {expect} but block succeeded")


def _compile_node(node: ast.AST, filename: str, flags: int = 0):
    # dont_inherit keeps the harness's own __future__ flags (e.g. PEP 563
    # annotations) from leaking into example blocks, so each runs exactly like a
    # reader's script. ``flags`` carries only the block's *own* __future__ imports,
    # which must reach every statement since they are compiled one at a time.
    return compile(
        ast.Module(body=[node], type_ignores=[]),
        filename,
        "exec",
        flags=flags,
        dont_inherit=True,
    )


def _is_docstring(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _is_ellipsis(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and node.value.value is Ellipsis
    )


def _is_stub(node: ast.AST) -> bool:
    """Whether a node is a signature stub: a ``def``/``class`` with a ``...`` body."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        body = node.body
        if body and _is_docstring(body[0]):
            body = body[1:]
        return bool(body) and all(_is_ellipsis(n) or _is_stub(n) for n in body)
    return False


def _is_signature_only(code: str) -> bool:
    """Whether a block is purely signatures, not a runnable example.

    The API reference shows signatures (``def __init__(self, ...): ...``). Their
    annotations name types a reader's script would not have imported, so such
    blocks carry no output to check and are skipped like an explicit
    ``verify: skip``.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    return bool(tree.body) and all(_is_stub(node) for node in tree.body)


def main() -> int:
    failures: list[str] = []
    ran = 0
    # Each page runs its blocks sequentially in one shared namespace and one
    # shared working directory, mirroring a reader copying blocks top to bottom.
    for path, blocks in iter_pages():
        rel = path.relative_to(DOCS)
        # Run the page's blocks inside a real module registered in ``sys.modules``,
        # not a bare dict, so ``get_type_hints`` can resolve a forward reference
        # (a self-referential dataclass like ``children: list[Tree]``) against the
        # namespace the class was defined in, as it would in a reader's module.
        module = types.ModuleType("__doc_example__")
        env = module.__dict__
        sys.modules[module.__name__] = module
        try:
            with tempfile.TemporaryDirectory() as tmp:
                cwd = os.getcwd()
                os.chdir(tmp)
                try:
                    for line, marker, code in blocks:
                        if marker == "skip":
                            continue
                        if not marker and _is_signature_only(code):
                            continue
                        expect = None
                        if marker.startswith("raises"):
                            expect = marker.split(None, 1)[1].strip()
                        elif marker:
                            # A typo'd marker must not silently run as a normal block.
                            failures.append(
                                f"{rel}:{line}  unknown verify marker: {marker!r}"
                            )
                            continue
                        ran += 1
                        run_block(env, code, f"{rel}:{line}", expect, failures)
                finally:
                    os.chdir(cwd)
        finally:
            sys.modules.pop(module.__name__, None)

    print(f"ran {ran} python blocks")
    if failures:
        print(f"\n{len(failures)} FAILED:")
        for f in failures:
            print(f"  {f}")
        return 1
    print("all blocks OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
