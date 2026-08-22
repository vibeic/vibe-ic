#!/usr/bin/env python3
"""explicit_argument_outranks_the_environment_pointer.py — whatever a gate
scanned, it says so.

WHY THIS EXISTS
===============
MEASURED: a checker handed an explicit two-path subject answered about a shared
tree of 8309 paths, because it read the corpus pointer from the environment
AFTER parsing its location argument and let the pointer win. The caller's fixture
was never examined, its defect was never seen, and the verdict was complete and
confident about a tree the caller had not named.

WHAT THIS RULE DOES AND DOES NOT DECIDE — READ THIS BEFORE WIDENING IT
======================================================================
There is a LIVE CONTRACT SPLIT in this repository, and this program does not
arbitrate it.

`_corpus_location.py:56` states one rule in as many words:

    THE POINTER REPLACES A MISSING CORPUS; IT DOES NOT REPLACE A PRESENT ONE.

Three consumers state the opposite, deliberately, each with its own reasoning
and its own issue reference:

    tracked_symlink_target_present_check.py   "THE POINTER WINS OVER THE PATH,
    tracked_symlink_portability_check.py       ANNOUNCED (#1710)"
    benchmark_evidence_structure_check.py

Both sides are argued in comments; the resolver's own docstring records that
letting the pointer win outright turned 15 of 21 tests red for every developer
with the pointer set, and the three consumers record why their callers need the
override. Reddening the three would assert one side of an unsettled contract,
and a checker is the wrong instrument for that — the split is reported in this
lane's write-up instead.

WHAT IS UNCONTESTED, AND IS THEREFORE WHAT IS ENFORCED
======================================================
Every side agrees on the ANNOUNCEMENT. All three consumers already print which
tree they scanned and which pointer they followed, and the resolver announces
both. So the enforceable rule is:

    a site that reads the corpus pointer and can redirect its subject with it
    MUST say so on its output.

A new consumer that reads the pointer and silently redirects is a finding under
either side of the split. That is the whole population this refuses, and it is
the half that would have caught the measured failure: the caller could not tell
which tree had been walked.

SCOPE, AND THE TWO READERS IT DOES NOT REFUSE
=============================================
The refusal covers the plugin's own checkers (`plugins/vibe-ic/programs/`),
because that is the rule's measured subject: a CHECKER handed a named subject
that answered about another tree. Two readers outside that scope —
`tools/ci/benchmark_data_landing_checkout.py` and
`tools/ci/hermetic_landing_arm_receipt.py` — resolve a checkout rather than
answer a question about a subject, and they sit on the landing path, which is
gated separately and where an unrelated edit trips three other gates.

They are DISCLOSED BY PATH AND COUNT on every run rather than skipped, so the
scope cannot quietly become the answer. `_checkout_arg` in the first of them is
a real instance of the pattern: the explicit argument correctly wins, and which
tree was resolved is still never printed.

    rc 0   N>0 pointer readers in scope, each announces.
    rc 1   a reader redirects silently.
    rc 2   NOT CHECKED — no reader found, or a file could not be parsed.
    rc 3   bad invocation.
"""
from __future__ import annotations

import argparse
import ast
import os
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

NAME = "explicit_argument_outranks_the_environment_pointer"
SKIP_DIRS = {".git", "docs/capture", "node_modules", "__pycache__"}

POINTER_NAMES = ("CORPUS_ENV", "_CORPUS_ENV", "VIBE_IC_BENCHMARK_DATA")
# Tokens that make an announcement an announcement.
ANNOUNCE_HINTS = ("overrides", "override", "scanning", "scanned", "note:",
                  "UNDETERMINED", "in force", "is set")


def _skip(path: Path, root: Path) -> bool:
    rel = path.relative_to(root).as_posix()
    parts = rel.split("/")
    if any(rel == d or rel.startswith(d + "/") for d in SKIP_DIRS):
        return True
    # A test may set the pointer to build a fixture; that is not a consumer.
    return "tests" in parts or parts[-1].startswith("test_")


def _reads_pointer(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) \
                and sub.func.attr == "get":
            for a in sub.args:
                if isinstance(a, ast.Name) and a.id in POINTER_NAMES:
                    return True
                if isinstance(a, ast.Constant) and a.value in POINTER_NAMES:
                    return True
        if isinstance(sub, ast.Subscript):
            sl = sub.slice
            if isinstance(sl, ast.Constant) and sl.value in POINTER_NAMES:
                return True
    return False


def _announces(node: ast.AST) -> bool:
    """True when this scope prints something naming the pointer or the tree."""
    for sub in ast.walk(node):
        if not (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                and sub.func.id == "print"):
            continue
        texts: List[str] = []
        for a in sub.args:
            for n in ast.walk(a):
                if isinstance(n, ast.Constant) and isinstance(n.value, str):
                    texts.append(n.value)
                if isinstance(n, ast.Name) and n.id in POINTER_NAMES:
                    texts.append(n.id)
        blob = " ".join(texts)
        if any(h.lower() in blob.lower() for h in ANNOUNCE_HINTS):
            return True
        if any(p in blob for p in POINTER_NAMES):
            return True
    return False


class Finding:
    def __init__(self, path: str, line: int, scope: str):
        self.path, self.line, self.scope = path, line, scope

    def __str__(self) -> str:
        return (f"{self.path}:{self.line}: {self.scope} reads the corpus "
                f"pointer and can redirect its subject with it, and prints "
                f"nothing naming the tree it scanned. A caller who names a "
                f"location and is answered about another one cannot tell.")


IN_SCOPE = "vibe-ic-marketplace/plugins/vibe-ic/programs/"


def audit(root: Path) -> Tuple[List[Finding], List[Finding], List[str], int]:
    """(findings in scope, disclosed out of scope, unread, readers in scope)."""
    findings: List[Finding] = []
    disclosed: List[Finding] = []
    unread: List[str] = []
    readers = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS
                       and not os.path.islink(os.path.join(dirpath, d))]
        for fn in sorted(filenames):
            if not fn.endswith(".py"):
                continue
            path = Path(dirpath) / fn
            if _skip(path, root):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                unread.append(f"{path.relative_to(root).as_posix()}: {exc}")
                continue
            if not any(p in text for p in POINTER_NAMES):
                continue
            rel = path.relative_to(root).as_posix()
            try:
                tree = ast.parse(text)
            except SyntaxError as exc:
                unread.append(f"{rel}: could not be parsed ({exc.msg})")
                continue
            # MODULE granularity, not per function. Measured: at function
            # granularity this reported four findings and three were wrong —
            # `_corpus_location.env_pointer()` merely RETURNS the pointer and
            # its announcement lives in `resolve()`, one scope away, which is
            # the correct structure. The obligation is on the module that can
            # redirect a subject, not on whichever helper happens to touch
            # os.environ.
            if not _reads_pointer(tree):
                continue
            in_scope = (IN_SCOPE in f"/{rel}") or root.name == "programs"
            if in_scope:
                readers += 1
            if not _announces(tree):
                first = next((n.lineno for n in ast.walk(tree)
                              if isinstance(n, (ast.FunctionDef,
                                                ast.AsyncFunctionDef))
                              and _reads_pointer(n)), 1)
                (findings if in_scope else disclosed).append(
                    Finding(rel, first, "this module"))
    return findings, disclosed, unread, readers


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
        findings, disclosed, unread, readers = audit(root)
    except Exception as exc:                        # noqa: BLE001
        print(f"[{NAME}] NOT CHECKED — the scan itself failed: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    for f in findings:
        print(str(f))
    for d in disclosed:
        print(f"DISCLOSED (outside this rule's scope, not a finding) — {d}",
              file=sys.stderr)
    for u in unread:
        print(f"NOT CHECKED — {u}", file=sys.stderr)
    print(f"examined {readers} in-scope corpus-pointer reader(s) under "
          f"{str(root)!r}; {len(disclosed)} silent reader(s) outside the scope "
          f"disclosed")
    if readers == 0:
        print(f"[{NAME}] NOT CHECKED — no corpus-pointer reader was found.",
              file=sys.stderr)
        return 2
    if findings:
        print(f"[{NAME}] FAIL — a pointer reader redirects its subject silently")
        return 1
    if unread:
        print(f"[{NAME}] NOT CHECKED — a candidate file could not be read")
        return 2
    print(f"[{NAME}] PASS — no in-scope pointer reader redirects without naming the tree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
