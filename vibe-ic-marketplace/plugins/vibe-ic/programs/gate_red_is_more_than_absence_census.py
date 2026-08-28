#!/usr/bin/env python3
"""A red that only means "nothing was there" has not shown a gate falsifiable.

CENSUS — informational. It reports a population; it does not refuse over it.
The exit code is 0 whatever the corpus holds, because a census that exits
non-zero gets wired as a gate by the next person who reads the exit code, and
the population it reports is a maintainer's backlog, not a landing condition.
`--self-test` is the mode the hygiene lane runs: it proves the CLASSIFIER can
still tell the two kinds apart, which is the part that can silently rot.

WHAT THIS REPORTS (census by default; `--strict` blocks)
=======================================================
For every gate module, the reds it can actually reach are classified into two
kinds, and a gate whose ONLY reachable red is an absence message is named.

WHY THIS EXISTS
===============
Matrix dimension D2 (`falsifiable`) asks "can this gate reach a genuine
non-zero exit?" and decides it with `if not passed: return RED`. It has no
absence tier, so it cannot tell the two apart.

MEASURED on the 68x9 matrix (mutation probe, plugin v1.12.33): 54 of the 121
reds D2 counted were earned on an EMPTY tree, where the FAIL text is literally
`REQUIRED_ARTEFACT_MISSING` / `MISSING_NETLIST` / `PLACED_DEF_MISSING` / "no
file on disk matches pattern" / "absent or not valid JSON". Three mutations,
same gate:

    M1  the gate always exits 0                              -> RED, correctly.
    M2  kill the namesake verdict, leave the absence arm      -> GREEN.
    M3  a gate registered as UNREDDENED always exits 0        -> GREEN.

After M2 the gate can no longer fail on anything a design DID -- only on a
design that is not there yet -- and D2 does not notice, because the absence
arm still returns non-zero. A gate in that state passes every project that
produced a file, whatever is IN the file.

THE TWO KINDS
=============
ABSENCE red    the message says the input is missing, empty, unreadable or
               unparseable: nothing was judged, so nothing was found wrong.
VERDICT red    the message says something about content that WAS read.

A gate needs at least one reachable VERDICT red before "it can fail" means
what a reader takes it to mean.

WHY IT DOES NOT BLOCK BY DEFAULT
================================
MEASURED on this repo (see `--json`), a large minority of gates are
absence-only TODAY, and several of them legitimately are: a presence gate's
whole subject IS whether the artefact is there. Turning this blocking would
redden that whole population in one step, which is a maintainer's call about
which of those gates should grow a content arm -- not something a new census
may decide for them. So the count is PRINTED, never silently capped, and
`--strict` is available the moment the population is agreed.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

GATE_SUFFIXES = ("_check.py", "_lint.py", "_audit.py", "_guard.py")

# The vocabulary the gates themselves already use when they judged NOTHING.
# Every entry was read out of a real FAIL message in this repo, not invented.
ABSENCE_RE = re.compile(
    r"(?i)("
    r"REQUIRED_ARTEFACT_MISSING|MISSING_[A-Z_]+|[A-Z_]+_MISSING|"
    r"\bmissing\b|\babsent\b|\bnot found\b|\bno such\b|\bdoes not exist\b|"
    r"\bno file\b|\bno .{0,24} on disk\b|\bnever (?:written|produced|ran)\b|"
    r"\bempty\b|\bunreadable\b|\bnot valid json\b|\bcannot parse\b|"
    r"\bcannot check\b|\bunparse|\bnot a directory\b|\bno run\b"
    r")")


def _rendered(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(p.value if isinstance(p, ast.Constant)
                       and isinstance(p.value, str) else "{}"
                       for p in node.values)
    return None


def _is_red(node: ast.AST) -> bool:
    """Does this statement hand a consumer a FAIL exit code?"""
    if isinstance(node, ast.Return):
        v = node.value
        return isinstance(v, ast.Constant) and v.value in (1, 3)
    if isinstance(node, ast.Raise):
        exc = node.exc
        if (isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name)
                and exc.func.id == "SystemExit" and len(exc.args) == 1
                and isinstance(exc.args[0], ast.Constant)
                and exc.args[0].value in (1, 3)):
            return True
    for sub in ast.walk(node):
        if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "exit" and len(sub.args) == 1
                and isinstance(sub.args[0], ast.Constant)
                and sub.args[0].value in (1, 3)):
            return True
    return False


def _messages_near(body: List[ast.stmt], index: int) -> List[str]:
    """Every message this branch would print before it reds.

    Scoped to the branch the red lives on: the statements of the same block up
    to and including the red. A message printed on some OTHER branch says
    nothing about what THIS exit means.
    """
    out: List[str] = []
    for stmt in body[:index + 1]:
        for sub in ast.walk(stmt):
            text = _rendered(sub)
            if text:
                out.append(text)
    return out


def _red_messages(tree: ast.Module) -> List[Tuple[int, List[str]]]:
    found: List[Tuple[int, List[str]]] = []
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            body = getattr(node, field, None)
            if not isinstance(body, list):
                continue
            for i, stmt in enumerate(body):
                if _is_red(stmt):
                    found.append((getattr(stmt, "lineno", 0),
                                  _messages_near(body, i)))
    return found


def classify_source(text: str) -> dict:
    """`{kind, reds, verdict_reds, absence_reds}` for one gate module."""
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return {"kind": "UNANALYSABLE", "reason": f"unparseable: {exc.msg}"}

    reds = _red_messages(tree)
    if not reds:
        # NOT "this gate cannot fail" — this gate's exit code is COMPUTED
        # (`return rc`, a verdict object, a helper's value), so the kind of
        # red it can reach is not decidable from the source alone. Named as
        # undecidable rather than folded into either answer.
        return {"kind": "NO-LITERAL-RED", "reds": 0,
                "verdict_reds": 0, "absence_reds": 0}

    verdict, absence = [], []
    for line, msgs in reds:
        joined = " ".join(msgs)
        if joined.strip() and not ABSENCE_RE.search(joined):
            verdict.append(line)
        else:
            absence.append(line)
    return {
        "kind": "VERDICT-BEARING" if verdict else "ABSENCE-ONLY",
        "reds": len(reds),
        "verdict_reds": len(verdict),
        "absence_reds": len(absence),
        "first_verdict_line": verdict[0] if verdict else None,
    }


def gate_files(root: Path) -> List[Path]:
    programs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    if not programs.is_dir():
        programs = root if root.name == "programs" else root / "programs"
    if not programs.is_dir():
        return []
    return [p for p in sorted(programs.glob("*.py"))
            if p.name.endswith(GATE_SUFFIXES)]


#: Two sources that differ in exactly one thing: whether a red can be reached
#: on a design that DID produce the artefact. If the classifier stops telling
#: them apart, every number this census prints is noise, and it says so rather
#: than printing the noise.
_CONTROL_ABSENCE = (
    "from pathlib import Path\n"
    "def main(p):\n"
    "    if not Path(p).exists():\n"
    "        print('REQUIRED_ARTEFACT_MISSING: no clock plan on disk')\n"
    "        return 1\n"
    "    return 0\n"
)
_CONTROL_VERDICT = _CONTROL_ABSENCE.replace(
    "    return 0\n",
    "    if not doc['clocks']:\n"
    "        print('CLOCK_PLAN_EMPTY: the plan declares zero clocks')\n"
    "        return 1\n"
    "    return 0\n")


def self_test(rows: Dict[str, dict]) -> int:
    """0 when the classifier still separates the two kinds; 2 when it cannot.

    Two controls, and both must hold. The SYNTHETIC pair proves the predicate
    still discriminates at all. The SUBJECT population proves it discriminates
    HERE: a tree in which every gate lands in one bucket exercises nothing, and
    a census over a set it cannot see apart is not a pass.
    """
    absence = classify_source(_CONTROL_ABSENCE)["kind"]
    verdict = classify_source(_CONTROL_VERDICT)["kind"]
    if absence != "ABSENCE-ONLY" or verdict != "VERDICT-BEARING":
        print(f"[CANNOT DETERMINE] self-test: the classifier reports "
              f"absence-control={absence!r} verdict-control={verdict!r}. It no "
              f"longer separates the two kinds, so its census means nothing. "
              f"NOT a pass.", file=sys.stderr)
        return 2
    kinds = {r["kind"] for r in rows.values()}
    for want in ("ABSENCE-ONLY", "VERDICT-BEARING"):
        if want not in kinds:
            print(f"[CANNOT DETERMINE] self-test: no gate in this tree "
                  f"classifies as {want}. The census ran over a population "
                  f"that exercises only one side of its own predicate, so its "
                  f"counts carry no information. NOT a pass.", file=sys.stderr)
            return 2
    print(f"[PASS] self-test: the two control sources still classify apart, "
          f"and this tree exercises both kinds.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when any gate is ABSENCE-ONLY (not for the flow)")
    ap.add_argument("--self-test", action="store_true",
                    help="prove the classifier still separates the two kinds")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    files = gate_files(root)
    if not files:
        print(f"CANNOT CHECK: no programs/ directory under {root}", file=sys.stderr)
        return 2

    rows: Dict[str, dict] = {}
    for path in files:
        rows[path.name] = classify_source(
            path.read_text(encoding="utf-8", errors="ignore"))

    if args.self_test:
        rc = self_test(rows)
        if rc:
            return rc

    counts: Dict[str, int] = {}
    for r in rows.values():
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    absence_only = sorted(n for n, r in rows.items() if r["kind"] == "ABSENCE-ONLY")

    if args.json:
        print(json.dumps({"scanned": len(files), "counts": counts,
                          "absence_only": absence_only, "rows": rows}, indent=2))
    else:
        print(f"scanned {len(files)} gate module(s) under {root}")
        for kind in sorted(counts):
            print(f"  {kind:<16} {counts[kind]}")
        for name in absence_only:
            print(f"  [ABSENCE-ONLY] {name}: every reachable red says the input "
                  f"was missing/empty/unreadable")
        print("PASS" if not absence_only
              else f"{len(absence_only)} gate(s) can only fail on an absent input")

    if absence_only and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
