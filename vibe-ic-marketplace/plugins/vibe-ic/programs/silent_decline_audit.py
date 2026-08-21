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

ENFORCEMENT: advisory on the individual site — this reports call sites for a
human to judge. Some declines legitimately need no record; the point is that
the CHOICE be visible rather than implicit.

BUT ADVISORY IS NOT THE SAME AS ALWAYS-GREEN (vibe-ic#693)
----------------------------------------------------------
Without `--strict` this returned 0 unconditionally. Wiring THAT into CI adds a
gate that cannot fail — the same defect the campaign is chasing, one level up.
Turning `--strict` on instead reddens `main` today: MEASURED at this commit,
1091 files scanned, 15 silent declines in 6 files, none of which this change
triages.

So the enforceable form is a RATCHET, the shape `checker_execution_wiring_audit`
already uses: `--max N` (or a recorded baseline file) passes at or below N and
FAILS above it. The 15 existing sites stay visible and are not blessed; a
SIXTEENTH cannot land quietly. Blocking on `--strict` becomes correct once the
15 are triaged.

AND THE RATCHET IS THE DEFAULT, NOT AN OPT-IN (vibe-ic#1705)
------------------------------------------------------------
`--ratchet` used to select whether the recorded baseline was consulted AT ALL.
Without it this program printed every finding it had just measured and then
returned 0 without opening the baseline — so rc 0 meant either "compared, and
at or below the record" or "never compared", and nothing in the exit status
told the two apart. Probed on `main` at ee849c19e that read as a clean sweep
over 15 live findings, with the baseline present AND with it moved aside.

The comparison is now unconditional, which makes rc 0 mean one thing:

  * a baseline this program could READ, and a count at or below it -> 0;
  * a count ABOVE that record -> 1, as before;
  * a baseline that is absent, unreadable or truncated -> 2, NOT CHECKED,
    with the path named. An absent artefact is not a measurement of zero.

An explicitly recorded count IS a measurement — including a recorded 0, which
asserts a clean tree and against which the FIRST silent decline is still NEW
and still exits 1. Only the absence of a readable record declines to attribute.

`--ratchet` is retained and accepted so the wired invocation
(`tools/ci/repo_hygiene_gates.sh`) and #693's tests keep working verbatim; it
now selects nothing, because the behaviour it selected is the only behaviour.

chip-AGNOSTIC: pure Python AST. No design, PDK or vendor literals.

Exit codes:
    0  audit completed at or below the recorded baseline
    1  --strict with any finding, or the count GREW past the baseline
    2  I/O error, an empty scan, or NO READABLE BASELINE to compare against
       (NOT CHECKED — never a quiet pass)
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


BASELINE_NAME = "silent_decline_baseline.json"


def _load_baseline(p: Path) -> Optional[int]:
    """The recorded count, or ``None`` when NO count could be read.

    ``None`` and ``0`` are deliberately different values and must never be
    collapsed (vibe-ic#1705). ``0`` is a measurement — of a tree with no silent
    decline in it — and the first decline against it is NEW. ``None`` says the
    record could not be read at all, so nothing here can be called new or old.

    Every way of failing to read one lands on ``None``: a missing path, a
    directory, unreadable or truncated bytes, a document that is not an object,
    a ``count`` that is absent or not a number. ``bool`` is excluded because
    ``True`` is an ``int`` in Python and ``{"count": true}`` would otherwise
    ratchet against 1; a negative count is excluded because no scan can produce
    one, so it is a corrupt record rather than a measurement.
    """
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    n = d.get("count")
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        return None
    return n


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Find remedy decisions whose refusal is silent (#313 §6).")
    ap.add_argument("targets", nargs="*",
                    help="files or dirs (default: this programs dir)")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when any silent decline is found")
    ap.add_argument("--ratchet", action="store_true",
                    help="compare the count against the recorded baseline: at "
                         "or below passes, GROWTH is exit 1. Without a "
                         "baseline this is exit 2 (NOT CHECKED), never a "
                         "quiet pass.")
    ap.add_argument("--baseline", default=None,
                    help=f"baseline file (default: {BASELINE_NAME} beside this "
                         f"program)")
    ap.add_argument("--write-baseline", action="store_true",
                    help="record the current count as the baseline")
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

    bl = (Path(a.baseline) if a.baseline
          else Path(__file__).resolve().parent / BASELINE_NAME)
    if a.write_baseline:
        by_file: dict = {}
        for f in rep["silent_declines"]:
            by_file[Path(f["file"]).name] = by_file.get(Path(f["file"]).name, 0) + 1
        bl.write_text(json.dumps(
            {"_comment": (
                "Remedy call sites whose DECLINE path records nothing "
                "(vibe-ic#313 §6, wired vibe-ic#693). MAY ONLY SHRINK — each "
                "entry is a place the flow can refuse its own rescue with "
                "nobody told. The wrong repair is to widen the disclosure "
                "table until the number falls."),
             "count": rep["count"],
             "scanned": rep["scanned"],
             "by_file": by_file}, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {bl} (count={rep['count']})")
        return 0

    if a.strict and rep["count"]:
        return 1
    # UNCONDITIONAL, not gated on `--ratchet` (vibe-ic#1705). While the
    # comparison was opt-in, the DEFAULT run printed every finding it had just
    # measured and returned 0 without ever opening the baseline — so rc 0 said
    # both "compared, and at or below the record" and "never compared", and no
    # caller could tell which it had been handed. `--ratchet` is still accepted
    # so the wired invocation and #693's tests read the same; it now selects
    # nothing, because the behaviour it selected is the only behaviour.
    if rep["scanned"] == 0:
        print("VACUOUS_PASS: 0 files scanned — the audit examined nothing.")
        return 2
    base = _load_baseline(bl)
    if base is None:
        print(f"[NOT CHECKED] no silent-decline baseline states a readable "
              f"measurement at {bl} — absent, unreadable or truncated is not a "
              f"measurement of zero, so the {rep['count']} finding(s) above "
              f"can be called neither new nor recorded. Measure this tree and "
              f"record it with --write-baseline before asking this audit to "
              f"attribute anything. See vibe-ic#1705.")
        return 2
    if rep["count"] > base:
        print(f"[FAIL] silent remedy declines GREW {base} -> "
              f"{rep['count']}: a new remedy can now refuse with nobody "
              f"told. Disclose the decline path, or triage the existing "
              f"backlog and lower the baseline.")
        return 1
    if rep["count"] < base:
        print(f"[PASS] {base} -> {rep['count']}; lower the baseline so the "
              f"recorded number stops claiming debt that is paid.")
        return 0
    print(f"[PASS] no NEW silent remedy decline ({rep['count']} recorded "
          f"over {rep['scanned']} file(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
