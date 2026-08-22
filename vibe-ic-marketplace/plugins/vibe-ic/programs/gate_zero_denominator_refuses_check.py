#!/usr/bin/env python3
"""gate_zero_denominator_refuses_check.py — a gate that read NOTHING must not exit 0.

WHY (vibe-ic#564)
=================
Three gates were found by hand, each returning a verdict about a design it had
not read:

    interface_encoding_audit   "0 interfaces analyzed"            rc 0
    fpga_qsf_lint              "ERROR: QSF file not found"        rc 1
    oe_pattern_check           "analyzed 0 file(s)"               rc 0

`gate_discloses_denominator_check` audits the same 493-program population and
passes all three, CORRECTLY — its contract is "a PASS must say how much it
looked at", and all three said so. **Disclosing a zero denominator and refusing
on one are different properties**, and only the first was enforced anywhere.

The second is not stylistic. The P0 umbrella reads EXIT CODES, so a gate that
prints `0` in prose and returns `0` in rc contributes a silent pass to a
project-level verdict: the disclosure is in the output and the aggregation reads
the code.

THE LINE THIS TURNS ON, and it is the issue's own
=================================================
    "An empty artefact is not a missing one. An empty `.v` file was opened and
     read: `analyzed 1 file(s), found 0` is a real result and rc 0 is correct."

So the predicate keys on a zero beside a POPULATION word — analysed, scanned,
examined, read — and never beside a FINDING word. `found 0 violations` over a
real population is a real clean result; `analysed 0 files` is not a result at
all. A gate that says both (`analysed 12 file(s), found 0`) states a real
population and is not a finding here.

WHAT IT DOES NOT DO
===================
It does not make any gate refuse. #564 asks for the PROBE, not a blanket
behaviour change — and a blanket change is measurably wrong: forcing refusal on
four gates was tried and flipped 182 / 159 / 94 / 42 of 182 tracked run dirs,
so it was reverted. Knowing WHICH of the population has the defect is the
deliverable; each fix is then its own measured change.

THE POPULATION AND THE DRIVER ARE IMPORTED, NOT REBUILT.
`project_check_programs` and `_drive_on_empty_project` come from
`gate_discloses_denominator_check`. A second scanner over the same question is
how this repo has previously reproduced a bug the first one already defended
against — one fresh directory per gate, because gates write into the project
they audit and a shared scratch makes gate N's report gate N+1's input.

EXEMPTIONS ARE A DATED INVENTORY, not a bare allow-list — the shape the sibling
gate already uses. An entry states WHEN it was measured and WHY the zero is a
correct pass, so the list can only shrink by a visible edit.

Exit: 0 = every gate agrees / 1 = at least one states a zero population and
exits 0 / 2 = could not probe (empty population).
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from gate_discloses_denominator_check import (  # noqa: E402
    project_check_programs as _population,
    _drive_on_empty_project as _drive,
)

TOOL = "gate_zero_denominator_refuses_check"
RC_OK, RC_FINDINGS, RC_CANNOT_PROBE = 0, 1, 2

#: Words that name the POPULATION a gate read.
_POP = (r"file|files|design|designs|interface|interfaces|net|nets|cell|cells|"
        r"instance|instances|module|modules|pin|pins|gate|gates|record|records|"
        r"entry|entries|report|reports|artefact|artefacts|document|documents|"
        r"step|steps|block|blocks|port|ports|line|lines|test|tests")
#: Words that name a FINDING. A zero beside one of these is a real clean result.
_FIND = (r"violation|violations|error|errors|warning|warnings|finding|findings|"
         r"issue|issues|mismatch|mismatches|failure|failures|defect|defects|"
         r"problem|problems|gap|gaps")

#: `analysed 0 file(s)` / `0 interfaces analyzed` / `scanned 0 designs`
_ZERO_POP_RE = re.compile(
    r"(?i)(?:"
    r"\b(?:analy[sz]ed|scanned|examined|audited|probed|inspected|read|"
    r"processed|visited|collected)\s+0\b(?!\s*(?:" + _FIND + r")\b)"
    r"|"
    r"\b0\s+(?:" + _POP + r")\b\s*(?:\([^)]*\)\s*)?"
    r"(?:analy[sz]ed|scanned|examined|audited|probed|inspected|read|"
    r"processed|found|present|in\b)"
    r")")

#: A gate that says it could not find its input at all. Same class: it read
#: nothing. Kept separate so the finding can say which shape it was.
_NO_INPUT_RE = re.compile(
    r"(?im)^\s*(?:ERROR|WARNING)\b[^\n]*\b(?:not found|missing|does not exist|"
    r"no such file|could not (?:be )?(?:open|read|locate))\b")

_MEASURED_ON = "2026-08-01"

#: Gates whose ZERO over an empty project is a CORRECT pass, with the date the
#: exemption was measured and the reason. Dated inventory, never a bare
#: allow-list: an entry that stops being true raises STALE_INVENTORY_ENTRY.
_ZERO_IS_A_PASS: Dict[str, Dict[str, str]] = {
    name: {"measured": measured, "reason": reason}
    for name, measured, reason in (
        ("professional_tb_check", "2026-08-14",
         "A professional testbench is an OPTIONAL step. When it did not run there is "
         "no report to read, and the checker says so out loud "
         "(VACUOUS_PASS: professional_tb examined 0 testbench report(s)). Making it "
         "refuse with rc 2 would force every run WITHOUT that step to disclose a skip "
         "it does not owe, so rc 0 is the correct verdict here and the prose is the "
         "disclosure. See professional_tb_check.py:337-346, where this argument was "
         "already written in a comment this gate could not read. Recorded here so the "
         "argument lives where the gate looks, and so STALE_INVENTORY_ENTRY fires if it "
         "ever stops being true."),
    )
}


def states_zero_population(text: str) -> bool:
    """True iff the output says it read NOTHING.

    `found 0 violations` is not this — that is a finding over a population.
    `analysed 12 file(s), found 0` is not this either.
    """
    return bool(text) and bool(_ZERO_POP_RE.search(text))


def states_missing_input(text: str) -> bool:
    return bool(text) and bool(_NO_INPUT_RE.search(text))


def audit(programs_dir: Path, timeout: int = 120,
          workers: int = 0) -> Tuple[str, List[Dict], Dict]:
    # A PROBER MUST NOT BE IN ITS OWN POPULATION. `project_check_programs` is
    # `glob("*_check.py")`, so this file is in it: probing drove a nested copy,
    # which drove another, each spawning the whole population again. It hung a
    # landing gate for 35 minutes and left 75 orphaned processes.
    #
    # `gate_discloses_denominator_check` has the same shape and survives only
    # because its 120s per-gate budget truncates the recursion at depth 1 — and
    # that truncation is exactly the "1 unrunnable" in this gate's own first
    # census. A timeout absorbing a self-inflicted recursion is not the same as
    # not having one.
    progs = [p for p in _population(programs_dir) if p.stem != Path(__file__).stem]
    if not progs:
        # This program's own denominator — never a silent PASS.
        return "NOTHING_PROBED", [], {"gates_probed": 0}
    workers = workers or min(8, (os.cpu_count() or 2))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(lambda p: _drive(p, timeout), progs))

    findings: List[Dict] = []
    zero_rc0: List[str] = []
    zero_refused: List[str] = []
    unrunnable: List[str] = []
    for res in results:
        gate = res["gate"]
        if res.get("unrunnable") or res["rc"] is None:
            unrunnable.append(gate)
            continue
        tail = res.get("output_tail") or ""
        zero = states_zero_population(tail) or states_missing_input(tail)
        if not zero:
            continue
        if res["rc"] == 0:
            zero_rc0.append(gate)
            if gate not in _ZERO_IS_A_PASS:
                findings.append({
                    "gate": gate, "kind": "ZERO_DENOMINATOR_EXITS_ZERO",
                    "rc": 0, "output_tail": tail,
                    "detail": "the gate states it read NOTHING and still exits "
                              "0, so the P0 umbrella — which reads exit codes, "
                              "not prose — records a silent pass. Either make "
                              "it refuse (rc 2 is the disclosed-skip "
                              "convention) or record it in _ZERO_IS_A_PASS "
                              "with the reason its zero is a correct pass.",
                })
        else:
            zero_refused.append(gate)

    for name in sorted(_ZERO_IS_A_PASS):
        if name not in zero_rc0:
            findings.append({
                "gate": name, "kind": "STALE_INVENTORY_ENTRY",
                "detail": f"exempted on {_ZERO_IS_A_PASS[name]['measured']} but "
                          f"it no longer states a zero population while exiting "
                          f"0 — delete the entry rather than leave it "
                          f"suppressing something it no longer describes",
            })

    stats = {"gates_probed": len(progs),
             "stated_zero_population": len(zero_rc0) + len(zero_refused),
             "zero_and_exited_0": len(zero_rc0),
             "zero_and_refused": len(zero_refused),
             "exempted": len(_ZERO_IS_A_PASS),
             "unrunnable": len(unrunnable)}
    verdict = "FINDINGS" if findings else "PASS"
    return verdict, findings, stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project", nargs="?", default=".")
    ap.add_argument("--programs-dir", default=str(_HERE))
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args(argv)

    # vibe-ic#619 — THIS CHECK'S POPULATION IS THE PROGRAM REGISTRY, not a
    # project: it builds one fresh empty project PER GATE and never reads the
    # `project` argument. It still accepted one, ignored it, and answered PASS
    # — byte-identical output for a path that exists, a path that is empty, and
    # a path that is not there.
    #
    # That is the exact shape this file exists to detect. Its own subject is
    # "a zero denominator that exits 0 is a silent pass", and it was reporting
    # success over a population it had never established: a run pointed at a
    # typo'd path read PASS. Both registry-wide meta-checks caught it the moment
    # it joined the registry it audits — `PASS_ON_A_PROJECT_THAT_IS_NOT_THERE`.
    #
    # A path it will not read is a path it cannot vouch for, so an absent one is
    # NOT_CHECKED (rc 2, the disclosed-skip convention) rather than a pass. The
    # default `.` always exists, so the standing invocation
    # (`repo_hygiene_gates.sh`, no argument) is unchanged.
    _proj = Path(a.project)
    if not _proj.exists():
        print(f"[SKIP] {TOOL}: the project path {a.project!r} does not exist. "
              f"This check's population is the PROGRAM REGISTRY — it probes "
              f"each gate against its own fresh empty project and never reads "
              f"the project argument — so it cannot answer for that path, and "
              f"reporting PASS for a project that is not there is the very "
              f"defect it looks for in others.", file=sys.stderr)
        return RC_CANNOT_PROBE

    verdict, findings, stats = audit(Path(a.programs_dir), a.timeout, a.workers)
    rep = {"tool": TOOL, "verdict": verdict, "findings": findings, **stats}
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(rep, indent=2) + "\n")

    if verdict == "NOTHING_PROBED":
        print(f"[SKIP] {TOOL}: no gate program found under {a.programs_dir} — "
              f"nothing was probed, which is a gap in this check, not a pass",
              file=sys.stderr)
        return RC_CANNOT_PROBE
    for f in findings:
        print(f"[FAIL] {f['gate']}: {f['kind']} — {f['detail']}", file=sys.stderr)
        if f.get("output_tail"):
            print(f"    said: {f['output_tail']}", file=sys.stderr)
    # #619 — say WHAT was audited. "probed against an empty project" reads, to
    # anyone who passed a project path, as a statement about THEIR project.
    print(f"{TOOL}: {verdict} — {stats['gates_probed']} gate(s) probed, each "
          f"against its OWN fresh empty project (the population is the program "
          f"registry under {a.programs_dir}; {a.project!r} is not read); "
          f"{stats['stated_zero_population']} stated a zero "
          f"population, of which {stats['zero_and_refused']} refused and "
          f"{stats['zero_and_exited_0']} exited 0 "
          f"({stats['exempted']} exempted, {stats['unrunnable']} unrunnable)")
    return RC_FINDINGS if findings else RC_OK


if __name__ == "__main__":
    raise SystemExit(main())
