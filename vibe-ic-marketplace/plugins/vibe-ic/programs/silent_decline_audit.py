#!/usr/bin/env python3
"""
silent_decline_audit.py — find remedy decisions whose REFUSAL is silent (#313 §6).

The rule this enforces
----------------------
When a flow-level remedy declines to act, it must say so. Measured twice in one
day, in two different subsystems:

  #307  `_route_feedback_loosen` returned None to refuse a die loosen. The call
        site was `if _lf is not None: ...` with NO else branch at all — no
        print, no history entry, no marker. The UPSIZE path in the SAME loop
        returns a named FAIL for the same kind of refusal. Across two live
        auto-die runs, cap/loosen/refusal strings appear ZERO times in stdout:
        the flow could refuse its own rescue with nobody told.

  #312  Phase 1's second track never ran, and its capture count of 0 read as
        "the AI found nothing" rather than "the AI was never asked".

Both are the same shape as the rest of this campaign: the system took a
decision, recorded nothing, and looked healthy afterwards. A remedy that
silently declines is indistinguishable from a remedy that was never needed.

What it flags
-------------
A call whose name carries REMEDY semantics, assigned to a variable, guarded by
`if <var> is not None:` (or `if <var>:`) with NO else branch and no disclosure
on the decline path. Reported per site with file and line.

Scoped to remedy-semantic names ON PURPOSE. Every `if x is not None:` in a
large codebase is not a defect; flagging all of them would produce the noise
that teaches people to ignore the tool — which #313 §2 names as the real cost
of a false-positive-prone gate.

DISCLOSURE side is satisfied by any of: an `else` branch, or a `print` /
logger / `.append(` / `return` reached when the remedy is absent.

ENFORCEMENT: advisory — this reports call sites for a human to judge. Some
declines legitimately need no record; the point is that the CHOICE be visible
rather than implicit.

chip-AGNOSTIC: pure Python AST. No design, PDK or vendor literals.

Exit codes:
    0  audit completed (findings are reported, not fatal)
    1  --strict and at least one silent decline was found
    2  I/O error
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Remedy semantics — a call that TRIES TO FIX something and may refuse.
_REMEDY_RE = re.compile(
    r"loosen|upsize|resize|repair|rescue|recover|retry|fallback|salvage"
    r"|mitigat|relax|escalat|remed|widen|reroute|refix",
    re.IGNORECASE)

# Things that count as disclosing the decline.
_DISCLOSE_CALLS = ("print", "warn", "warning", "error", "info", "log",
                   "append", "add", "write", "puts")


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Name):
            return f.id
        if isinstance(f, ast.Attribute):
            return f.attr
    return ""


def _discloses(nodes: List[ast.stmt]) -> bool:
    """Does this branch record anything a reader would see?"""
    for n in nodes:
        for sub in ast.walk(n):
            if isinstance(sub, ast.Call) and any(
                    d in _call_name(sub).lower() for d in _DISCLOSE_CALLS):
                return True
            if isinstance(sub, (ast.Return, ast.Raise)):
                return True
    return False


def _guarded_var(test: ast.expr) -> Optional[str]:
    """`x is not None` / `x` -> 'x'; anything else -> None."""
    if isinstance(test, ast.Name):
        return test.id
    if (isinstance(test, ast.Compare) and len(test.ops) == 1
            and isinstance(test.ops[0], ast.IsNot)
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value is None
            and isinstance(test.left, ast.Name)):
        return test.left.id
    return None


def audit_source(src: str, path: str = "<src>") -> List[Dict[str, Any]]:
    """Silent remedy declines in one module."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    # var -> remedy call name, from assignments anywhere in the module
    remedy_vars: Dict[str, str] = {}
    for n in ast.walk(tree):
        if not isinstance(n, (ast.Assign, ast.AnnAssign)):
            continue
        value = n.value
        if value is None:
            continue
        name = _call_name(value)
        if not (name and _REMEDY_RE.search(name)):
            continue
        targets = n.targets if isinstance(n, ast.Assign) else [n.target]
        for t in targets:
            if isinstance(t, ast.Name):
                remedy_vars[t.id] = name
            elif isinstance(t, ast.Tuple):     # (decision, reason) = remedy()
                for e in t.elts:
                    if isinstance(e, ast.Name):
                        remedy_vars[e.id] = name

    # Vars whose DECLINE is disclosed by a separate `if <var> is None:` block.
    # This is the shape the #307 fix actually landed in — disclose first, then
    # act — and flagging it would be a false positive on a CORRECT fix. #313 §2:
    # a gate that fires on a legitimate state is a bug, and its real cost is
    # that people learn to ignore it.
    disclosed_elsewhere: set = set()
    for n in ast.walk(tree):
        if not isinstance(n, ast.If):
            continue
        t = n.test
        is_none_test = (isinstance(t, ast.Compare) and len(t.ops) == 1
                        and isinstance(t.ops[0], ast.Is)
                        and isinstance(t.comparators[0], ast.Constant)
                        and t.comparators[0].value is None
                        and isinstance(t.left, ast.Name))
        if is_none_test and _discloses(n.body):
            disclosed_elsewhere.add(t.left.id)

    # A var that APPEARS INSIDE a disclosure call anywhere in the module is
    # already accounted for on both paths — e.g.
    #     plan.append(StepResult(..., "PASS" if remediated else "SKIP", ...))
    # records the decline BEFORE the `if remediated:` guard. Verified against a
    # real site (design_one_shot_runner eco_loop_remediation) that the first
    # draft flagged. Erring toward FEWER findings is deliberate: #313 §2 says a
    # gate that fires on a legitimate state is a bug whose real cost is that
    # people learn to ignore it.
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call)
                and any(d in _call_name(n).lower() for d in _DISCLOSE_CALLS)):
            continue
        for sub in ast.walk(n):
            if isinstance(sub, ast.Name):
                disclosed_elsewhere.add(sub.id)

    out: List[Dict[str, Any]] = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.If):
            continue
        var = _guarded_var(n.test)
        if var is None or var not in remedy_vars:
            continue
        if var in disclosed_elsewhere:
            continue
        if n.orelse and _discloses(n.orelse):
            continue
        if n.orelse:                     # has an else that says nothing
            out.append({"file": path, "line": n.lineno, "var": var,
                        "remedy": remedy_vars[var],
                        "why": "else branch present but discloses nothing"})
            continue
        out.append({"file": path, "line": n.lineno, "var": var,
                    "remedy": remedy_vars[var],
                    "why": "no else branch — the refusal is silent"})
    return out


def audit(paths: List[Path]) -> Dict[str, Any]:
    findings: List[Dict[str, Any]] = []
    scanned = 0
    for p in paths:
        try:
            src = p.read_text(errors="replace")
        except OSError:
            continue
        scanned += 1
        findings.extend(audit_source(src, str(p)))
    return {"scanned": scanned, "silent_declines": findings,
            "count": len(findings)}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Find remedy decisions whose refusal is silent (#313 §6).")
    ap.add_argument("targets", nargs="*",
                    help="files or dirs (default: this programs dir)")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when any silent decline is found")
    ap.add_argument("--json", help="write the report here")
    a = ap.parse_args(argv)
    roots = [Path(t) for t in a.targets] or [Path(__file__).resolve().parent]
    files: List[Path] = []
    for r in roots:
        if r.is_dir():
            files.extend(sorted(p for p in r.glob("*.py")
                                if not p.name.startswith("test_")))
        elif r.is_file():
            files.append(r)
        else:
            print(f"IO_ERROR: no such path: {r}", file=sys.stderr)
            return 2
    rep = audit(files)
    if a.json:
        Path(a.json).write_text(json.dumps(rep, indent=2, ensure_ascii=False))
    print("=== silent remedy declines ===")
    print(f"files scanned : {rep['scanned']}")
    print(f"silent declines: {rep['count']}")
    for f in rep["silent_declines"]:
        print(f"  {Path(f['file']).name}:{f['line']}  {f['remedy']}() -> "
              f"{f['var']}: {f['why']}")
    if a.strict and rep["count"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
