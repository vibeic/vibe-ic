#!/usr/bin/env python3
"""argparse_help_format_check.py — pin the bare-% argparse help-string class.

argparse percent-expands every help string (`self._get_help_string(action)
% params`), so a literal percent sign in `add_argument(help=...)` MUST be
written `%%` (or be a valid `%(name)s` expansion such as `%(default)s`).
A bare `%` followed by anything else — including end-of-string — makes
`--help` (and bad-flag usage rendering) crash with
`ValueError: incomplete format`.

This checker AST-walks every `*.py` under a root, finds `add_argument`
calls, and scans the literal fragments of their `help=` strings (plain
strings and the literal parts of f-strings) for invalid `%` usage.

Exit: 0 = PASS (no violations), 1 = FAIL (violations listed).
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Iterator, List, Tuple


def _bad_percent_offsets(text: str) -> List[int]:
    """Return offsets of `%` chars that argparse would choke on.

    Valid: `%%` (escaped literal) and `%(name)s`-style expansions.
    Everything else — `% `, `%.`, trailing `%` — is a violation.
    """
    bad: List[int] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] != "%":
            i += 1
            continue
        nxt = text[i + 1] if i + 1 < n else ""
        if nxt == "%":
            i += 2  # escaped literal percent
            continue
        if nxt == "(":
            close = text.find(")", i + 2)
            # %(name)<conv> — argparse uses mapping keys; require a
            # conversion char right after the closing paren.
            if close != -1 and close + 1 < n:
                i = close + 2
                continue
        bad.append(i)
        i += 1
    return bad


def _help_string_fragments(node: ast.expr) -> Iterator[Tuple[int, str]]:
    """Yield (lineno, literal_text) fragments of a help= value.

    Plain str constants yield themselves; f-strings yield only their
    literal parts (formatted {…} values are runtime data, not source).
    Implicit concatenation parses as a single Constant, so it is covered.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node.lineno, node.value
    elif isinstance(node, ast.JoinedStr):
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                yield node.lineno, part.value
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        yield from _help_string_fragments(node.left)
        yield from _help_string_fragments(node.right)


def scan_file(path: Path) -> List[Tuple[int, str]]:
    """Return [(lineno, offending_help_text)] for one Python file."""
    import warnings
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(path.read_text(errors="replace"))
    except SyntaxError:
        return []
    out: List[Tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else (
            func.id if isinstance(func, ast.Name) else "")
        if name != "add_argument":
            continue
        for kw in node.keywords:
            if kw.arg != "help" or kw.value is None:
                continue
            for lineno, text in _help_string_fragments(kw.value):
                if _bad_percent_offsets(text):
                    out.append((lineno, text))
    return out


def audit(root: str) -> List[str]:
    """Return human-readable violation lines for every .py under root."""
    root_p = Path(root)
    violations: List[str] = []
    for py in sorted(root_p.rglob("*.py")):
        if not py.is_file():
            continue
        for lineno, text in scan_file(py):
            violations.append(f"{py}:{lineno}: bare % in argparse help: {text!r}")
    return violations


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("root", nargs="?", default=".",
                   help="directory tree to scan (default: cwd)")
    args = p.parse_args(argv if argv is not None else sys.argv[1:])
    violations = audit(args.root)
    for v in violations:
        print(v)
    print(f"{'FAIL' if violations else 'PASS'} — "
          f"{len(violations)} bare-% argparse help string(s)")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
