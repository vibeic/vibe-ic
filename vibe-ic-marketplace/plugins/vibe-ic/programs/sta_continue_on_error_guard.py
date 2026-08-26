#!/usr/bin/env python3
"""sta_continue_on_error_guard.py — REFUSE a tree that turns OpenSTA's
error-abort off.

WHAT IS BEING GUARDED
---------------------
OpenSTA carries a global Tcl variable (``tcl/Util.tcl:563`` and its use at
``tcl/Util.tcl:637-645``) that decides what ``sta_error`` does. At its default
value of 0 an error raises and, when the script came from a FILE, ``-exit``
turns that into a non-zero process exit. At any other value the error is
printed and execution CONTINUES.

That single variable is upstream of every other timing gate we have. It was
measured on openroad 26Q3-1797-g1c09d62b96:

    default (variable at 0), FILE script whose read_verilog fails
        -> rc=1                                       (caught)

    variable set to 1, SAME FILE script, SAME failure
        -> rc=0, link never happened, run reports success
                                                       (NOT caught)

So a tree in which anything sets this non-zero silently disarms the primary
gate: a correct ``-exit`` on a correct file script would still report success
on a run that linked no design. It also disarms the exit-code term of
``mcp-eda/src/lib/sta_evidence.mjs``. Nothing downstream can recover from it,
which is why it is guarded HERE — at the source text — and not only at the
point of use.

WHAT COUNTS AS A VIOLATION
--------------------------
Any assignment of the variable to a value that is not literally zero, in any
of the dialects that can reach the interpreter:

    Tcl    set <var> 1        set ::<var> 1        set ::sta::<var> true
    shell  <VAR>=1            export <VAR>=1
    py/js  <var> = 1          "<var>": 1

Setting it explicitly to ``0`` is NOT a violation — it is a restatement of the
default and is the one safe thing to write. Merely NAMING the variable (this
docstring does) is not a violation either; the guard fires on assignment, so
prose about it never trips it.

The pattern is assembled at runtime from fragments, so this file itself
contains no flagged literal and needs no self-exclusion. There is no exclusion
list at all.

EXIT STATUS
-----------
    0   no violation found
    1   at least one violation (each printed as path:line: text)
    2   usage / unreadable root

USAGE
-----
    sta_continue_on_error_guard.py [ROOT ...]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Assembled from fragments so this source never contains a flagged literal.
_VAR = "sta" + "_continue_on_error"

# Anything that is not an unambiguous zero. ``0``, ``0x0``, ``"0"``, ``{0}``
# are the safe restatements of the default; everything else is a violation.
_ZERO = re.compile(r'^[\s"\'{\[(]*0+(\.0+)?[\s"\'}\])]*$')

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache"}
_MAX_BYTES = 4 * 1024 * 1024

# Tcl:  set ?::?(sta::)?VAR VALUE
_TCL = re.compile(r"\bset\s+(?:::)?(?:sta::)?" + re.escape(_VAR) + r"\s+(\S+)")
# shell / env:  VAR=VALUE  (case-insensitive on the name, as env vars shout)
_ENV = re.compile(r"(?:^|[\s;&|(])(?:export\s+)?" + re.escape(_VAR) + r"=(\S+)", re.IGNORECASE)
# python / js / json:  var = VALUE   var: VALUE   "var": VALUE   'var' : VALUE
# The optional quote before the separator is load-bearing: without it the JSON
# dialect `{"<var>": 1}` did not match at all and the guard returned 0 on a
# config file that raises the variable (measured 2026-08-27 by the RED-pole
# case `json_config` in programs/tests/test_sta_continue_on_error_guard.py).
_ASSIGN = re.compile(r"(?:::)?\b" + re.escape(_VAR) + r"\b[\"\']?\s*(?:=(?!=)|:)\s*([^,;)\}\n]+)")

_PATTERNS = (("tcl", _TCL), ("env", _ENV), ("assign", _ASSIGN))


def _is_zero(value: str) -> bool:
    return bool(_ZERO.match(value.strip()))


def scan_text(text: str, path: str = "<text>") -> list[str]:
    """Return one message per violating line. Pure; used directly by the test."""
    out: list[str] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for _kind, pat in _PATTERNS:
            hit = pat.search(line)
            if hit and not _is_zero(hit.group(1)):
                out.append(f"{path}:{lineno}: {line.strip()}")
                break
    return out


def scan_tree(root: Path) -> list[str]:
    out: list[str] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.is_symlink():
            continue
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        try:
            if p.stat().st_size > _MAX_BYTES:
                continue
            text = p.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeDecodeError):
            continue  # binary or unreadable: cannot contain a Tcl/shell assignment
        # Case-INSENSITIVE pre-filter. The shell dialect shouts the name in
        # upper case, and a case-sensitive filter skipped every such file
        # before any pattern got to run — measured on 2026-08-27: the guard
        # returned 0 on a tree that exported the variable non-zero from a
        # shell script. Note the invariant this file keeps: it names the
        # variable but never spells a non-zero assignment of it, in code OR in
        # a comment, so the guard stays clean on its own source and needs no
        # self-exclusion. Writing the offending example into this comment is
        # what broke that invariant the first time.
        if _VAR not in text.lower():
            continue
        out.extend(scan_text(text, str(p)))
    return out


def main(argv: list[str]) -> int:
    roots = [Path(a) for a in argv[1:]] or [Path.cwd()]
    violations: list[str] = []
    for root in roots:
        if not root.exists():
            print(f"sta_continue_on_error_guard: no such root: {root}", file=sys.stderr)
            return 2
        violations.extend(scan_tree(root) if root.is_dir() else scan_text(
            root.read_text(encoding="utf-8", errors="replace"), str(root)))
    for v in violations:
        print(f"VIOLATION {v}")
    if violations:
        print(f"\nsta_continue_on_error_guard: {len(violations)} violation(s). "
              f"OpenSTA must abort on error, or every timing gate above it reports "
              f"success on a run that analysed nothing.", file=sys.stderr)
        return 1
    print(f"sta_continue_on_error_guard: clean ({len(roots)} root(s) scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
