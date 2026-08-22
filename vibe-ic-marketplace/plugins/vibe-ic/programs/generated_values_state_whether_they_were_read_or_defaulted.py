#!/usr/bin/env python3
"""generated_values_state_whether_they_were_read_or_defaulted.py — a value that
could have been read or defaulted says which.

WHY THIS EXISTS
===============
MEASURED: a generator emitted a clock period of 24 and the run signed off at the
generator's own last-resort default of 20 — a 20 % over-constraint nobody
requested — and emitted a declared input delay of 4.8 as a fixed 2. Neither
artefact marked which had happened, so the two cases were byte-identical: a
silently unread input produced a complete, plausible run about the wrong
constraint, and three full runs later the constraint had moved while the design
still "met" it.

A value that could have come either from the design's own documents or from the
generator's fallback is not self-describing. Unmarked, it is a claim with no
provenance that reads exactly like one with provenance.

WHAT ALREADY LANDED, AND WHAT DID NOT
=====================================
`declared_clock_period.py` (v1.11.5) resolves the period from a table keyed by
cell library and the input delay as the declared fraction of it, and returns a
report carrying the DISCLOSURE beside the value — `matched_key`, `source`,
`line`, `note`. That program marks TWO values correctly.

What did not land is the general rule: that every caller which takes such a value
must also carry its disclosure through. A caller that reads `period_ns` and drops
`matched_key`/`source`/`line` re-creates the original defect one layer up — the
value is used, the provenance is discarded, and the artefact is once again
identical whether the input was read or defaulted.

THE HELPERS ARE DISCOVERED, NOT LISTED
======================================
A hand-list of read-or-default helpers would cover the two that exist today and
silently miss the third. A helper is instead recognised by SHAPE: a function that
returns a mapping carrying at least three disclosure fields
(`matched_key`, `source`, `line`, `note`) alongside a value field. Adding a new
read-or-default helper therefore extends this rule automatically, which is the
whole difference between marking two values and stating the rule.

    FINDING   a non-test call site that binds such a helper's result and never
              references any disclosure field in the same scope. The value was
              taken and the provenance was dropped.

Tests are excluded: a test that asserts only the value is asserting exactly what
it means to, and reddening it would make this rule's PASS depend on weakening the
suite that proves the helper works.

    rc 0   N>0 call sites, each carrying its disclosure.
    rc 1   a call site takes the value and drops the disclosure.
    rc 2   NOT CHECKED — no read-or-default helper, or no call site, was found.
           A rule with no population certifies nothing.
    rc 3   bad invocation.
"""
from __future__ import annotations

import argparse
import ast
import collections
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

NAME = "generated_values_state_whether_they_were_read_or_defaulted"
SKIP_DIRS = {".git", "docs/capture", "node_modules", "__pycache__"}
DISCLOSURE_FIELDS = ("matched_key", "source", "line", "note")
VALUE_HINTS = ("_ns", "value", "fraction", "period", "delay", "default")
MIN_DISCLOSURE = 3


def _py_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS
                       and not os.path.islink(os.path.join(dirpath, d))]
        for fn in sorted(filenames):
            if fn.endswith(".py"):
                yield Path(dirpath) / fn


def _is_test(path: Path) -> bool:
    return "tests" in path.parts or path.name.startswith("test_")


def find_helpers(root: Path) -> Dict[str, Tuple[str, int]]:
    """`{function name: (file, line)}` for every read-or-default helper."""
    helpers: Dict[str, Tuple[str, int]] = {}
    for path in _py_files(root):
        if _is_test(path):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            rel = str(path)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.Dict):
                    continue
                keys = {k.value for k in node.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)}
                if len(keys & set(DISCLOSURE_FIELDS)) < MIN_DISCLOSURE:
                    continue
                if any(any(h in k for h in VALUE_HINTS) for k in keys):
                    helpers[fn.name] = (rel, fn.lineno)
                    break
    return helpers


class Finding:
    def __init__(self, where: str, scope: str, helper: str):
        self.where, self.scope, self.helper = where, scope, helper

    def __str__(self) -> str:
        return (f"{self.where}: {self.scope}() calls {self.helper}() and uses "
                f"its value without carrying any of its disclosure "
                f"({', '.join(DISCLOSURE_FIELDS)}). The artefact is then "
                f"identical whether the input was READ or DEFAULTED, which is "
                f"the defect that signed a run off at a default nobody asked "
                f"for.")


def audit(root: Path) -> Tuple[List[Finding], int, int]:
    helpers = find_helpers(root)
    findings: List[Finding] = []
    sites = 0
    if not helpers:
        return findings, 0, 0
    for path in _py_files(root):
        if _is_test(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(text)
        except (OSError, SyntaxError, ValueError):
            continue
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            rel = str(path)
        lines = text.splitlines()
        for scope in ast.walk(tree):
            if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            src = "\n".join(
                lines[scope.lineno - 1:getattr(scope, "end_lineno", scope.lineno)])
            discloses = any(d in src for d in DISCLOSURE_FIELDS) \
                or "disclosure" in src
            for node in ast.walk(scope):
                if not isinstance(node, ast.Call):
                    continue
                name = (node.func.attr if isinstance(node.func, ast.Attribute)
                        else getattr(node.func, "id", None))
                if name not in helpers:
                    continue
                if helpers[name][0] == rel:
                    continue                # the helper's own module
                sites += 1
                if not discloses:
                    findings.append(Finding(rel, scope.name, name))
    return findings, sites, len(helpers)


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
        findings, sites, helpers = audit(root)
    except Exception as exc:                        # noqa: BLE001
        print(f"[{NAME}] NOT CHECKED — the scan itself failed: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    for f in findings:
        print(str(f))
    print(f"examined {sites} call site(s) of {helpers} read-or-default "
          f"helper(s) under {str(root)!r}")
    if helpers == 0:
        print(f"[{NAME}] NOT CHECKED — no read-or-default helper was found, so "
              f"nothing was judged. A rule with no population certifies "
              f"nothing.", file=sys.stderr)
        return 2
    if sites == 0:
        print(f"[{NAME}] NOT CHECKED — no call site of a read-or-default helper "
              f"was found, so nothing was judged.", file=sys.stderr)
        return 2
    if findings:
        print(f"[{NAME}] FAIL — a generated value does not say whether it was "
              f"read or defaulted")
        return 1
    print(f"[{NAME}] PASS — every read-or-defaulted value carries its "
          f"disclosure")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
