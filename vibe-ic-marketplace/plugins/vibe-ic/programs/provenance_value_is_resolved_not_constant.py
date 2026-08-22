#!/usr/bin/env python3
"""provenance_value_is_resolved_not_constant.py — an artefact says where its
numbers came from by RESOLVING it, never by typing it.

WHY THIS EXISTS
===============
A field that states where an artefact's numbers came from must hold a value the
emitter resolved. A path typed into the emitter's own format string reports the
path the AUTHOR INTENDED to read rather than the path that was READ, so it stays
correct-looking:

    * when the read failed,
    * when the layout moved,
    * and when the artefact is about a different design entirely.

MEASURED: a published antenna report was 487 bytes BYTE-IDENTICAL across two
different designs on two different open process kits, citing a source path
neither design contains.

THE RESIDUE THIS RULE ACTUALLY REFUSES
======================================
The subject half of that defect is already fixed and landed: the phase-3 runner
resolves and stamps the design plus each input with its hash, and two report
gates refuse an artefact naming a design the project does not declare.

What that fix LEFT BEHIND is the population here — an artefact that now carries
TWO source claims in one write: a resolved subject block, and beside it a
sentence naming a fixed path. The resolved one moves with the run; the typed one
cannot, so the two can disagree and only one of them can ever be wrong.

    FINDING   a single artefact write emits a RESOLVED subject block AND a
              string constant containing a run-relative artefact path.

WHY NOT THE BROADER RULE
========================
"Refuse any path-shaped constant under a source-naming key" was measured first
and produces 16 hits on this repository, of which the great majority are
correct: a record whose input genuinely IS a fixed canonical location names it
accurately, and a constant is the honest way to say so. A rule that reddens 16
accurate statements to reach one inaccurate one is a false-finding generator.

The narrow rule fires where the two claims COEXIST, which is precisely where one
of them must be redundant. On this repository it found exactly one instance —
the antenna emitter's `Source:` sentence — and that instance is fixed in the
same change that adds this checker.

    rc 0   N>0 resolved-subject writes read; none also types a source path.
    rc 1   a write carries a resolved subject and a typed source path.
    rc 2   NOT CHECKED — no resolved-subject write found, or a file could not
           be parsed.
    rc 3   bad invocation.
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

NAME = "provenance_value_is_resolved_not_constant"
SKIP_DIRS = {".git", "docs/capture", "node_modules", "__pycache__"}

# Calls that render the RESOLVED identity of what was measured.
RESOLVED_CALLS = ("_measured_subject_lines", "_measured_subject")
# A run-relative artefact path typed into the emitter's own text.
PATH_LIT = re.compile(
    r"\b(?:reports|phase\d|run|logs?|stage\d)/[\w./-]+"
    r"\.(?:rpt|log|json|v|def|lef|spef|sdc|tcl)\b")


class Finding:
    def __init__(self, path: str, line: int, literal: str):
        self.path, self.line, self.literal = path, line, literal

    def __str__(self) -> str:
        return (f"{self.path}:{self.line}: this write emits a RESOLVED subject "
                f"block and also types the source path {self.literal!r}. The "
                f"artefact then carries two source claims, and the typed one "
                f"cannot look wrong however the run moved. Render it from the "
                f"value the emitter resolved.")


def _walk(root: Path) -> List[Path]:
    out: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS
                       and not os.path.islink(os.path.join(dirpath, d))]
        if "tests" in Path(dirpath).parts:
            continue
        for fn in sorted(filenames):
            if fn.endswith(".py") and not fn.startswith("test_"):
                out.append(Path(dirpath) / fn)
    return sorted(out)


def _str_constants(tree: ast.AST) -> dict:
    """`{name: value}` for simple module-level string assignments.

    MEASURED FALSE PASS: the scan only read constants lexically inside the
    write, so

        LOGPATH = "phase3/stage3/pnr/openroad.log"
        rpt.write_text(_measured_subject_lines(s) + "# Source: " + LOGPATH)

    reported PASS — the same typed source claim, moved one assignment away.
    """
    out: dict = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            out[node.targets[0].id] = node.value.value
    return out


def audit(root: Path) -> Tuple[List[Finding], List[str], int]:
    findings: List[Finding] = []
    unread: List[str] = []
    writes = 0
    for path in _walk(root):
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            unread.append(f"{rel}: {exc}")
            continue
        if not any(c in text for c in RESOLVED_CALLS):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            unread.append(f"{rel}: could not be parsed ({exc.msg})")
            continue
        names = _str_constants(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "write_text"):
                continue
            resolved = False
            literals: List[Tuple[int, str]] = []
            for sub in ast.walk(node):
                # A name bound to a string constant is the same typed claim,
                # one assignment away.
                if isinstance(sub, ast.Name) and sub.id in names:
                    for m in PATH_LIT.finditer(names[sub.id]):
                        literals.append((getattr(sub, "lineno", node.lineno),
                                         m.group(0)))
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) \
                        and sub.func.id in RESOLVED_CALLS:
                    resolved = True
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    for m in PATH_LIT.finditer(sub.value):
                        literals.append((getattr(sub, "lineno", node.lineno),
                                         m.group(0)))
            if not resolved:
                continue
            writes += 1
            for lineno, lit in literals:
                findings.append(Finding(rel, lineno, lit))
    return findings, unread, writes


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", nargs="?", default=".")
    try:
        args = ap.parse_args(argv if argv is not None else sys.argv[1:])
    except SystemExit:
        return 3
    root = Path(args.root)
    if not root.is_dir():
        print(f"[{NAME}] BAD INVOCATION — {args.root!r} is not a directory.",
              file=sys.stderr)
        return 3
    try:
        findings, unread, writes = audit(root)
    except Exception as exc:                        # noqa: BLE001
        print(f"[{NAME}] NOT CHECKED — the scan itself failed: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    for f in findings:
        print(str(f))
    for u in unread:
        print(f"NOT CHECKED — {u}", file=sys.stderr)
    print(f"examined {writes} resolved-subject artefact write(s) under "
          f"{str(root)!r}")
    if writes == 0:
        print(f"[{NAME}] NOT CHECKED — no artefact write emits a resolved "
              f"subject block, so there was nothing to judge.", file=sys.stderr)
        return 2
    if findings:
        print(f"[{NAME}] FAIL — an artefact carries a typed source claim beside "
              f"a resolved one")
        return 1
    if unread:
        print(f"[{NAME}] NOT CHECKED — a candidate file could not be read")
        return 2
    print(f"[{NAME}] PASS — no artefact write that emits a resolved subject also types a source path")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
