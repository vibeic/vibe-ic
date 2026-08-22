#!/usr/bin/env python3
"""A flow-declared invocation the invoked program's own parser refuses.

THIS GATE BLOCKS (rc=1) on a NEW one.

WHAT IT ASKS THE REPOSITORY
===========================
An invocation declared in the flow document is a CONTRACT with the invoked
program's argument parser. When the declared arguments omit something that
parser marks required, the parser refuses BEFORE the check ever runs — and
that refusal status, rc 2, is the same status the flow reserves for
input-not-applicable.

The gate then scores as a pass on every input forever, and the failure points
the wrong way: the worse the run, the more certainly it passes.

The class DID occur: a release-documents generator whose only declared
invocation omitted two arguments its parser marks required, exiting 2, scored
as a passing tier — and the same lane found a second instance of the identical
shape among 24 findings.

A POPULATION EXTENSION, AND BUILT AS ONE
========================================
`p0_gate_invocability_drift_check` already enforces exactly this shape over the
P0 UMBRELLA REGISTRY, and it records a non-invocable outcome as a VERDICT
rather than a skip. What was missing is not the predicate, it is the
POPULATION: the flow document's declared clauses were guarded only by a probe
inside one test suite.

So this program does not re-implement the predicate. It imports
`_gate_invocation.classify_not_invocable` — the same function, so one
definition of "accepted" survives — and applies it to the clauses of the flow
document.

WHY THE PARSER IS DRIVEN AND NOT COMPARED
=========================================
A static comparison of each declared argument vector against the required
arguments named in the program's source reports a FALSE POSITIVE on a program
whose modes are subcommands: the declared vector selects a subcommand, and the
required arguments of a DIFFERENT subcommand are not missing, they are
irrelevant. That was measured at exactly one such false positive over the
declared population.

Driving the real parser resolves subcommands for free, because the parser
resolves them. It is the only method that cannot be wrong about its own
subject.

A TIMEOUT IS AN ACCEPTANCE. If the program is still running when the deadline
expires it got past its parser, which is the entire question here.

EXIT
====
  0  every declared clause is accepted by the program it names
  1  a clause its program's parser refuses, or a stale inventory row
  2  cannot determine — no flow document, no programs directory, unreadable
  3  bad invocation
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _atomic_artefact as _aa  # noqa: E402 — vibe-ic#1082

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _gate_invocation                                        # noqa: E402

_INVENTORY_NAME = "declared_invocation_parser_inventory.json"
_FLOW_REL = "flow/phase1_phase2_phase3.yaml"

#: Both tiers are contracts with a parser. An advisory clause that cannot be
#: invoked is advisory about nothing.
_CLAUSE_KEYS = ("program_exit_zero", "advisory_program_exit_zero")

_PER_CLAUSE_TIMEOUT_S = 25


def _clauses(flow: Path) -> List[dict]:
    """(key, program, argv) for every declared invocation.

    Read line-wise rather than through a YAML loader on purpose: the document
    carries commented-out example clauses, and a loader would drop the line
    number that makes a finding actionable.
    """
    out: List[dict] = []
    for i, raw in enumerate(flow.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line.startswith("- "):
            continue
        body = line[2:].strip()
        for key in _CLAUSE_KEYS:
            if not body.startswith(key + ":"):
                continue
            value = body[len(key) + 1:].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            try:
                argv = shlex.split(value)
            except ValueError:
                argv = value.split()
            if not argv:
                continue
            out.append({"line": i, "key": key, "program": argv[0],
                        "argv": argv[1:], "declared": value})
            break
    return out


def _drive(programs: Path, clause: dict, scratch: Path) -> Optional[dict]:
    """Run the program with the declared argv and classify a refusal."""
    name = clause["program"]
    stem = name if name.endswith(".py") else name + ".py"
    prog = programs / stem
    if not prog.is_file():
        return {**clause, "why": f"no program {stem} under programs/"}
    workdir = Path(tempfile.mkdtemp(prefix="dic_", dir=str(scratch)))
    (workdir / "input" / "docs").mkdir(parents=True, exist_ok=True)
    (workdir / "reports").mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, str(prog)] + clause["argv"]
    try:
        r = subprocess.run(argv, cwd=str(workdir), capture_output=True,
                           text=True, timeout=_PER_CLAUSE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        # It got past its parser. That is the whole question.
        return None
    except OSError as exc:
        return {**clause, "why": f"could not be started: {exc}"}
    if r.returncode != 2:
        return None
    why = _gate_invocation.classify_not_invocable(
        r.stdout, r.stderr,
        supplied_flags=[a for a in clause["argv"] if a.startswith("--")])
    if why is None:
        return None                     # a genuine input-not-applicable skip
    return {**clause, "why": why}


def scan(root: Path, jobs: int) -> Tuple[List[dict], Dict[str, int]]:
    plugin = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    flow = plugin / _FLOW_REL
    programs = plugin / "programs"
    clauses = _clauses(flow)
    findings: List[dict] = []
    with tempfile.TemporaryDirectory(prefix="declared_invocation_") as scratch:
        sp = Path(scratch)
        with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
            for res in pool.map(lambda c: _drive(programs, c, sp), clauses):
                if res is not None:
                    findings.append(res)
    findings.sort(key=lambda f: f["line"])
    return findings, {"declared_clauses": len(clauses),
                      "blocking_clauses": sum(
                          1 for c in clauses if c["key"] == "program_exit_zero"),
                      "refused_by_their_own_parser": len(findings)}


def _key(f: dict) -> str:
    return f"{f['program']}::{' '.join(f['argv'])}"


def _repo_root(start: Path) -> Optional[Path]:
    for p in [start] + list(start.parents):
        if (p / ".git").exists() and (p / "vibe-ic-marketplace").is_dir():
            return p
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None)
    ap.add_argument("--inventory", default=None)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--json", dest="json_out", default=None)
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return 3
    try:
        root = Path(a.root).resolve() if a.root else _repo_root(
            Path(__file__).resolve())
        if root is None or not root.is_dir():
            print("[CANNOT DETERMINE] declared_invocation_accepted_by_its_own_"
                  "parser: no repository root. NOT a pass.", file=sys.stderr)
            return 2
        plugin = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
        if not (plugin / _FLOW_REL).is_file() or not (plugin / "programs").is_dir():
            print(f"[CANNOT DETERMINE] declared_invocation_accepted_by_its_own_"
                  f"parser: no flow document or no programs/ under {plugin}. "
                  f"NOT a pass.", file=sys.stderr)
            return 2
        findings, denom = scan(root, a.jobs)
        if denom["declared_clauses"] == 0:
            print("[CANNOT DETERMINE] declared_invocation_accepted_by_its_own_"
                  "parser: the flow document declares no invocation at all. A "
                  "verdict over an empty population is NOT a pass.",
                  file=sys.stderr)
            return 2
        inv_path = Path(a.inventory) if a.inventory else \
            Path(__file__).resolve().parent / _INVENTORY_NAME
        rows = json.loads(inv_path.read_text(encoding="utf-8")).get("known", []) \
            if inv_path.exists() else []
        known = {r["key"] for r in rows}
        if a.json_out:
            _aa.write_text(Path(a.json_out), json.dumps(
                {"denominators": denom, "findings": findings}, indent=2) + "\n")
    except Exception as exc:                    # noqa: BLE001 — see rc contract
        print(f"[CANNOT DETERMINE] declared_invocation_accepted_by_its_own_"
              f"parser: the probe did not complete ({type(exc).__name__}: "
              f"{exc}). NOT a pass.", file=sys.stderr)
        return 2

    print(f"  declared clauses driven:   {denom['declared_clauses']}")
    print(f"  of which blocking:         {denom['blocking_clauses']}")
    print(f"  refused by their parser:   {denom['refused_by_their_own_parser']}")
    print(f"  inventory rows applied:    {len(known)}")

    seen = {_key(f) for f in findings}
    new = sorted(seen - known)
    stale = sorted(known - seen)
    rc = 0
    if new:
        rc = 1
        print(f"\n[FAIL] {len(new)} declared invocation(s) the named program "
              f"refuses:")
        for f in findings:
            if _key(f) in new:
                print(f"   {_FLOW_REL}:{f['line']}  {f['key']}: "
                      f"{f['declared']!r}\n      {f['why']}")
        print("\n  A parser refusal is a DECLARATION defect and has its own "
              "tier. Folding it\n  into not-applicable is what makes the gate "
              "pass on every input forever.")
    if stale:
        rc = 1
        print(f"\n[FAIL] {len(stale)} inventory row(s) match nothing:")
        for k in stale:
            print(f"   {k}")
    if rc == 0:
        print("[PASS] declared_invocation_accepted_by_its_own_parser: every "
              "declared clause is accepted by the parser it names.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
