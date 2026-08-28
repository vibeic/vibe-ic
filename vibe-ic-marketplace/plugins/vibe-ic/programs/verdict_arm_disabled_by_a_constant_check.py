#!/usr/bin/env python3
"""A verdict arm a constant switched off — every structure intact, no decision.

THIS GATE BLOCKS (rc=1) on a boolean test the source has already decided.

WHY THIS EXISTS
===============
The 68x9 matrix campaign (2026-08-28) closed with a pass that injected defects
of a kind none of the nine dimensions had tried: leave EVERY structure intact —
every file present, every flag parsed, every dependency edge declared, every
artefact written and named — and change only what the gate DECIDES.

One of the two was a yield sign-off whose refusal arm was switched off with a
single token:

    if False and measured + 1e-9 < target:      # the arm never runs

MEASURED: a 12.5% wafer yield passes a 90% target, the gate exits 0, and **0 of
612 matrix cells change colour**. Neither does the ledger, nor the meta guards.
The matrix README says why in words the campaign has now measured: "NO cell
reads the CONTENT of the artefact a step produces."

This program does not close that class — reading content is a different
instrument. It closes the one shape of it that IS decidable from source: an arm
whose condition the source itself has already answered.

THE RULE
========
On the BOOLEAN SPINE of any test — the `if` / `while` / `assert` /
conditional-expression / comprehension guard, following only `and`, `or` and
`not`, never descending into a call, a compare or a subscript — a constant
operand that fixes the outcome is reported:

    if False and x:      the arm is dead
    if x and 0:          the arm is dead
    if True or x:        the arm always fires
    if False:            the block is dead

The spine restriction is what makes this usable. MEASURED on 627 gate modules:
judging every constant inside a test reports 260 sites, essentially all of them
the ordinary default-value idiom (`(w or 1) > 1`, `text[a:b] or " "`) where the
`or` is an operand of a compare or a call argument and decides a VALUE, not a
branch. On the spine, the same corpus reports **0**.

WHAT IT DOES NOT CLAIM
======================
A gate can stop deciding correctly in ways no constant marks — the campaign's
other injected defect was a sign-off gate that simply stopped reading its signed
memo, and nothing in the repository caught it. This rule sees one shape. It is
reported as one shape.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Iterator, List, Optional, Sequence, Tuple

GATE_SUFFIXES = ("_check.py", "_lint.py", "_audit.py", "_guard.py")


def _spine(test: ast.AST) -> Iterator[ast.AST]:
    """The nodes whose value decides the BRANCH, and no others.

    Follows `and` / `or` / `not` only. A constant reached through a call, a
    compare or a subscript is deciding a VALUE — `(w or 1) > 1` defaults a
    width; it does not disable an arm — and descending into those is what
    turns this rule from 0 findings into 260.
    """
    stack: List[ast.AST] = [test]
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, ast.BoolOp):
            stack.extend(node.values)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            stack.append(node.operand)


def _tests(tree: ast.Module) -> Iterator[Tuple[ast.AST, ast.AST]]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.While, ast.IfExp, ast.Assert)):
            yield node, node.test
        elif isinstance(node, ast.comprehension):
            for guard in node.ifs:
                yield guard, guard


def audit_source(text: str, label: str) -> Tuple[List[dict], Optional[str]]:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [], f"unparseable: {exc.msg} (line {exc.lineno})"

    findings: List[dict] = []
    for owner, test in _tests(tree):
        line = getattr(owner, "lineno", 0)
        if isinstance(test, ast.Constant) and not test.value:
            findings.append({"file": label, "line": line,
                             "shape": f"if {test.value!r}",
                             "why": "the block can never run"})
            continue
        for node in _spine(test):
            if not isinstance(node, ast.BoolOp):
                continue
            for value in node.values:
                if not isinstance(value, ast.Constant):
                    continue
                dead = isinstance(node.op, ast.And) and not value.value
                always = isinstance(node.op, ast.Or) and bool(value.value)
                if dead or always:
                    findings.append({
                        "file": label, "line": line,
                        "shape": f"{'and' if dead else 'or'} {value.value!r}",
                        "why": ("the arm can never run" if dead
                                else "the arm always runs"),
                    })
    return findings, None


def gate_files(root: Path) -> List[Path]:
    programs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    if not programs.is_dir():
        programs = root if root.name == "programs" else root / "programs"
    if not programs.is_dir():
        return []
    return [p for p in sorted(programs.glob("*.py"))
            if p.name.endswith(GATE_SUFFIXES)]


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".",
                    help="the SUBJECT tree to judge")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 on any finding (default: report and exit 0)")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    files = gate_files(root)
    if not files:
        print(f"CANNOT CHECK: no programs/ directory under {root}", file=sys.stderr)
        return 2

    findings: List[dict] = []
    unanalysable: List[dict] = []
    for path in files:
        found, reason = audit_source(
            path.read_text(encoding="utf-8", errors="ignore"), path.name)
        if reason:
            unanalysable.append({"file": path.name, "reason": reason})
        findings.extend(found)

    if args.json:
        print(json.dumps({"scanned": len(files), "findings": findings,
                          "unanalysable": unanalysable}, indent=2))
    else:
        print(f"scanned {len(files)} gate module(s) under {root}")
        for f in findings:
            print(f"  [DECIDED-IN-SOURCE] {f['file']}:{f['line']}  "
                  f"{f['shape']} — {f['why']}")
        for u in unanalysable:
            print(f"  [UNANALYSABLE] {u['file']}: {u['reason']}")
        print("PASS" if not findings
              else f"FAIL: {len(findings)} verdict arm(s) decided by a constant")

    return 1 if (findings and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
