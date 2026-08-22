#!/usr/bin/env python3
"""power_total_vs_budget_check.py — the total power figure must reach a
COMPARISON, or the step must REFUSE and name what it lacks.

ENFORCEMENT: advisory — no runner spawns this gate inline, so it cannot stop
step 33 while step 33 is running. That is the ONLY axis this token names, and
it is the one `flow_gate_enforcement_audit` measures. The other two axes are
unchanged, and are stated here so the declaration can never be read as
permission to defang the gate:

  * VERDICT SEVERITY — unchanged. rc 1 when a declared limit is exceeded,
    rc 2 on INCOMPLETE. The rc-2 half is vibe-ic#1022's repair, landed in
    #1026: on the whole published corpus this gate's honest answer is
    INCOMPLETE (17 published power reports across 15 run roots, 0 of
    those roots carrying a declared power budget), and while INCOMPLETE exited 0 the refusal was indistinguishable
    from a pass — which is the exact defect the gate was written to remove,
    one floor down.
  * FLOW SLOT — unchanged and BLOCKING. Step 33 wires this gate in
    `program_exit_zero`, never `advisory_program_exit_zero`.

WIRED AND DECLARED ARE DIFFERENT QUESTIONS (vibe-ic#1035). See the identically
shaped block in `em_peak_current_authority_check`, this gate's sibling from the
same two PRs: being wired into the flow's blocking slot has never been an
answer to "does this program say where its verdict is consumed", and the audit
reported both as `undeclared::` throughout, correctly.

WHAT CHANGED IN THE PPA WORK (spec §7.2, PPA-008)
=================================================
Two things, and the second is the one that matters.

1. THE THRESHOLD NOW COMES FROM THE CONTRACT, NOT FROM THIS FILE'S OWN IDEA OF
   ONE. Through v1.11.18 this gate knew exactly one authority — L19's
   `power_budget_uw` — because that is what the flow happened to carry. A power
   requirement is a CONTRACT term: `_ppa/power.resolve_power_requirement` reads
   a `vibeic.ppa.contract.v1` requirement on `power.total_w` first, falls back
   to L19 when no contract declares one, and discloses the superseded value
   rather than discarding it. `--budget-uw` still outranks both, because a
   caller that states a requirement has taken the authority on itself.

2. A POWER NUMBER IS NOT COMPARABLE TO ANYTHING UNTIL ITS ACTIVITY BASIS IS
   KNOWN. `PPA_INTERFACES.md` §2: "Vectorless power and VCD power are different
   metrics." A vectorless estimate and a VCD-driven measurement are both "total
   power" and they are not the same number, so a threshold written against one
   cannot judge the other, and a candidate that "beats" a baseline measured on
   a different activity model has not beaten anything. `_ppa/power.py` derives
   the basis from EVIDENCE in the artefact rather than from the label on it,
   and this gate refuses — rc 2, UNDETERMINED — when the basis is unknown,
   self-contradicted, or different from the one the requirement was written
   against. That refusal is a REFUSAL, never a FAIL: rc 1 is a claim about the
   design and "I do not know what activity model produced this watt figure" is
   not one.

MEASURED, WHICH IS WHY 2 IS NOT PARANOIA (2026-08-21, all 17 published power
reports in `benchmark-data`):

    POWER_ANALYSIS_MODE absent            6    -> basis UNSTATED
    POWER_ANALYSIS_MODE: vectorless_sdc   3    -> basis VECTORLESS
    POWER_ANALYSIS_MODE: vector_vcd       8    -> basis CONTRADICTED, all eight

All eight `vector_vcd` reports are falsified by their own transcript: five carry
`READ_VCD_FAIL: ...` from the `catch` around `read_power_activities`, three
carry OpenSTA's own `Annotated 0 pin activities.`. Not one published power
number in this repository is vector-driven and eight of them say they are. The
label is written by the runner from the EXISTENCE of a `.vcd` file, before the
read is attempted; the failure is caught and printed rather than raised. Until
that is fixed at the source, a gate that trusted the label would be certifying
a comparison against an activity model that never loaded.

THE DEFECT THIS GATE WAS ORIGINALLY WRITTEN FOR, MEASURED
=========================================================
`matrix_mutation_ledger.ARTEFACT_MUTATIONS` carried ART-POWER-FIGURES-X1000
recording that step 33's dimension-2 cell CANNOT BE REDDENED from artefact
content. The mutation multiplies every non-zero figure in the OpenSTA power
table by 1000 — internal, switching, leakage and total, per group and in the
Total row, 12 sites — leaving the zeros alone so the table still sums to its own
total. The wired gate (`power_report_check` = `eda_report_audit --mode power`)
stayed green.

That gate establishes that the report came from a real power tool and carries
leakage plus dynamic categories. It never reads the NUMBERS against anything. A
1000x power figure is the same PASS as the true one, and a PASS that names no
threshold is indistinguishable from one that never looked.

THE HONEST ANSWER ON TODAY'S CORPUS IS STILL A REFUSAL
======================================================
MEASURED over the published corpus, by CONTENT rather than by reputation
(counts re-run 2026-08-21):

    L19*.json copies in benchmark-data/       193
      with power_budget_uw set                  3   (all three are copies of
                                                    ONE design's L19)
    published power reports (17 files, 15 run roots)  17
      run roots with a declared power budget            0

So there is not one published run in which this comparison could have been made.
The budget is absent everywhere the power report exists, and the L19 of the run
the ledger replays states, in its own words, "Spec does not state PDK / timing
constraints".

**A green cell over a design whose power was never compared to anything is the
defect. A cell that REFUSES and names what it lacks is not.** This gate does not
invent an authority. It does not derive a budget from die area, supply voltage,
or a sibling tool's number, because every one of those would be a ruler chosen
to fit the corpus — and a threshold nobody declared is worse than no threshold,
since it turns an unanswered question into an answered one.

    limit declared, basis usable, total <= limit   -> PASS, naming both
    limit declared, basis usable, total >  limit   -> FAIL, naming both
    limit declared, basis unknown/contradicted     -> INCOMPLETE, naming why
    limit declared for a DIFFERENT activity basis  -> INCOMPLETE, naming both
    limit absent                                   -> INCOMPLETE, naming it
    no total power figure readable                 -> INCOMPLETE, naming that

`INCOMPLETE` is this repository's own tier for "the input WAS applicable and it
was not audited; someone must come back". `flow_compliance_check` promotes a
step to it when a passing gate prints the token at line-start; it aggregates
exactly as VACUOUS_PASS does, so no published design turns red on this, and the
per-step listing stops reporting step 33 as a bare PASS.

WHAT STEP 33 STILL NEEDS, AND IT DOES NOT COME FROM THIS REPOSITORY
===================================================================
A power budget is a REQUIREMENT, not a measurement: it has to arrive in the
design's own input documents and be extracted into the contract by Phase 1.
Until a design states one, this gate can only keep saying so. Nothing in the
plugin can close that, and closing it by picking a number would be the
fabrication the whole §4.05 doctrine exists to prevent.

WHAT THIS GATE DOES NOT DO — stated so a reviewer does not have to find it
=========================================================================
  * It does not FAIL on the group rows failing to sum to the Total row. The
    sums are computed and disclosed by `_ppa/power.py`, but the ledger's
    mutation was deliberately built to preserve them (the zeros are left alone
    and the table stays internally consistent), so a verdict built on them
    would not move on the entry this gate exists for. A check the mutation
    cannot move is not a check that discriminates.
  * It does not compare against any OTHER tool's power figure carried elsewhere
    in the run. The IR analysis states a per-net total power from a different
    engine on a different netlist view; on the run the ledger replays the two
    already differ by 4.3x at baseline, so a cross-tool tolerance would have to
    be chosen wide enough to admit that — a ruler fitted to the corpus. IR drop
    is power INTEGRITY and answers a different question; it is not folded in.
  * It reads the total power figure only. Per-group and per-category figures
    are parsed for disclosure but are not screened, because the contract
    declares one total-power limit.

chip-AGNOSTIC: it reads a watt figure and a power limit. No foundry, process or
chip token appears anywhere in this file.

Exit codes: 0 = PASS, 1 = the total exceeds the declared limit, 2 = the question
could not be put — INCOMPLETE (the disclosed-skip tier,
`_vacuous_exit.RC_VACUOUS`) or a bad argument.

INCOMPLETE EXITS 2, NOT 0 (vibe-ic#1017)
----------------------------------------
This gate is a BLOCKING `program_exit_zero` clause at step 33. Through #1000 it
returned 0 for INCOMPLETE, so an EMPTY tree — no power report, no L19, nothing —
PASSED the blocking clause while this file's own last line said ``total power
was NOT compared against anything``. That is the shape
`gate_zero_denominator_refuses_check` forbids and the one repaired for
`declared_pdk_is_the_pdk_used_check` in vibe-ic#1002.
`test_matrix_d2_falsifiable` had been red on main for five merges saying so.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _atomic_artefact as _aa  # noqa: E402
from _ppa import power as _pw  # noqa: E402

TOOL = "power_total_vs_budget_check"
VERSION = "1.1.0"

RC_OK, RC_FINDINGS, RC_ARG = 0, 1, 2
#: INCOMPLETE — the disclosed-skip tier (`_vacuous_exit.RC_VACUOUS`).
#: Named apart from RC_ARG because they mean different things to a
#: reader even though the flow maps both to VACUOUS_PASS today.
RC_NOT_COMPARED = 2

#: Where a power report may sit. DISCOVERED from the tree, never enumerated.
_RPT_GLOBS = ("reports/**/power*.rpt", "steps/**/power*.rpt")

_MICRO = 1e-6


def _rel(p: Path, project: Path) -> str:
    try:
        return str(p.relative_to(project))
    except ValueError:                                 # pragma: no cover
        return str(p)


def read_reports(project: Path) -> List[Dict[str, Any]]:
    """Every power report in the tree, parsed, with its activity provenance.

    A file that cannot be READ is recorded as unreadable rather than dropped.
    "I could not open it" and "I opened it and it held nothing" are different
    facts and must not produce the same verdict.
    """
    seen: Dict[str, Path] = {}
    for pat in _RPT_GLOBS:
        for p in project.glob(pat):
            if p.is_file():
                seen[str(p.resolve())] = p
    out: List[Dict[str, Any]] = []
    for key in sorted(seen):
        fp = seen[key]
        rep = _pw.read_power_report(fp)
        if rep is None:
            out.append({"file": _rel(fp, project), "unreadable": True})
            continue
        rep["file"] = _rel(fp, project)
        rep["path"] = _rel(fp, project)
        out.append(rep)
    return out


def _disclosure(rep: Dict[str, Any]) -> Dict[str, Any]:
    """The per-report row that goes into the JSON and drives the summary."""
    if rep.get("unreadable"):
        return {"file": rep["file"], "readable": False,
                "activity_basis": None, "total_power_W": None}
    act = rep.get("activity") or {}
    t = rep.get("total_row")
    row: Dict[str, Any] = {
        "file": rep["file"], "readable": True,
        "activity_basis": act.get("basis"),
        "activity_corroboration": act.get("corroboration"),
        "declared_mode": act.get("declared_mode"),
        "activity_reason": act.get("reason"),
        "activity_evidence": act.get("evidence"),
        "liberty": rep.get("liberty"),
        "split_consistency": rep.get("split_consistency"),
        "group_sum_consistency": rep.get("group_sum_consistency"),
    }
    if t:
        row.update({"total_power_W": t["total_w"],
                    "internal_power_W": t["internal_w"],
                    "switching_power_W": t["switching_w"],
                    "leakage_power_W": t["leakage_w"]})
    else:
        row["total_power_W"] = None
        row["total_not_measured_reason"] = "the artefact states no Total row"
    return row


def _worst_record(reports: List[Dict[str, Any]],
                  requirement: Optional[Dict[str, Any]],
                  project: Optional[Path] = None
                  ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]],
                             Optional[str]]:
    """The total-power record the requirement is entitled to judge.

    Highest of the eligible ones, because a limit is an upper bound and the run
    has to meet it everywhere it states a total. Ordering is by the RAW parsed
    total, never by the record's ``value``: a record that is not MEASURED
    carries no ``value`` at all (§2 — a not-measured record carries a reason,
    not a number), and sorting on a key that only some records have is how a
    refusal turns into a crash.

    AN UNUSABLE RECORD IS SELECTED, NOT SKIPPED. If any readable report in the
    tree states a total this gate cannot compare — a contradicted activity
    label, an unstated one — that report is what comes back, so the refusal is
    reached with the bad record in hand. Skipping it would let a run hide an
    unusable power report behind a usable one, and the whole tree's power axis
    is only as sound as its worst readable report.

    TWO BASES IN ONE TREE IS ITSELF A REFUSAL. When a requirement names the
    activity basis it was written against, only records on that basis are
    eligible. When it does not, and the readable reports span more than one
    known basis, taking the maximum would be picking the worse of two numbers
    that are not the same metric — so the gate says so instead.

    Returns ``(record, report, conflict)``.
    """
    eligible: List[Tuple[float, Dict[str, Any], Dict[str, Any]]] = []
    for rep in reports:
        if rep.get("unreadable") or not rep.get("total_row"):
            continue
        # `project` is what lets `_ppa/power` resolve the scope's `mode`
        # from `pvt_matrix.json`. Without it the record comes back one
        # required scope key short and no downstream comparison of it can
        # be decided -- which is what every power record did until now.
        rec = _pw.total_record(rep, stage="phase3_signoff",
                               scenario="default", project=project)
        if rec is None:                                # pragma: no cover
            continue
        eligible.append((rep["total_row"]["total_w"], rec, rep))
    if not eligible:
        return None, None, None

    unusable = [e for e in eligible if e[1].get("status") != _pw.STATUS_MEASURED]
    if unusable:
        worst = max(unusable, key=lambda e: e[0])
        return worst[1], worst[2], None

    req_basis = ((requirement or {}).get("scope") or {}).get("activity_basis")
    if req_basis is not None:
        matching = [e for e in eligible
                    if (e[1].get("scope") or {}).get("activity_basis")
                    == req_basis]
        # Nothing on the requirement's basis: fall through with the worst
        # record so `judge_against_requirement` states the mismatch itself.
        if matching:
            eligible = matching
    else:
        bases = sorted({(e[1].get("scope") or {}).get("activity_basis")
                        for e in eligible})
        if len(bases) > 1:
            worst = max(eligible, key=lambda e: e[0])
            return worst[1], worst[2], (
                f"the readable power reports state totals on more than one "
                f"activity basis ({', '.join(bases)}) and the requirement "
                f"names none, so there is no one number for it to bound")

    worst = max(eligible, key=lambda e: e[0])
    return worst[1], worst[2], None


def evaluate(project: Path, budget_override: Optional[float]
             ) -> Tuple[str, Dict[str, Any]]:
    """Return ``(verdict, report)``; verdict in {PASS, FAIL, INCOMPLETE}."""
    rep: Dict[str, Any] = {"program": TOOL, "version": VERSION,
                           "project": str(project), "findings": []}
    reports = read_reports(project)
    disclosures = [_disclosure(r) for r in reports]
    rep["reports_read"] = disclosures
    # Kept under its historical name: `totals_read` is the list of readable
    # total-power figures, which is what the summary line counts.
    totals = [d for d in disclosures if d.get("total_power_W") is not None]
    rep["totals_read"] = totals
    rep["unreadable_reports"] = [d["file"] for d in disclosures
                                 if not d.get("readable")]

    res = _pw.resolve_power_requirement(project, budget_uw=budget_override)
    requirement = res["requirement"]
    rep["requirement"] = requirement
    rep["requirement_sources"] = res["sources"]
    rep["requirement_superseded"] = res.get("superseded") or []
    # Historical key, still the thing a reader looks for first.
    rep["budget_sources"] = [s for s in res["sources"]
                             if s.get("authority") == _pw.AUTHORITY_L19]
    rep["power_budget_uw"] = (requirement["max_w"] / _MICRO
                              if requirement and requirement.get("max_w")
                              else None)

    record, source_rep, basis_conflict = _worst_record(reports, requirement,
                                                       project)
    rep["selected_total"] = (
        {"file": source_rep["file"], "record": record} if record else None)
    rep["activity_basis_conflict"] = basis_conflict

    if basis_conflict and requirement is not None:
        judged = {"verdict": _pw.J_UNDETERMINED,
                  "code": "ACTIVITY_BASIS_CONFLICT", "reason": basis_conflict}
    else:
        judged = _pw.judge_against_requirement(record, requirement)
    rep["judgement"] = judged

    if judged["verdict"] == _pw.J_UNDETERMINED:
        rep["verdict"] = "INCOMPLETE"
        lacks: List[str] = []
        code = judged.get("code")
        if code == "NO_REQUIREMENT":
            lacks.append(res["refusal"] or
                         "a declared total-power limit (ppa contract "
                         "requirement on power.total_w, or "
                         "L19_CONSTRAINTS_PDK.json fields.power_budget_uw)")
        elif code == "NO_TOTAL_POWER":
            lacks.append("a readable Total row in any power report")
        else:
            lacks.append(judged["reason"])
        if code != "NO_TOTAL_POWER" and not totals:
            lacks.append("a readable Total row in any power report")
        if code != "NO_REQUIREMENT" and res.get("refusal"):
            lacks.append(res["refusal"])
        rep["missing_authority"] = "; ".join(lacks)
        return "INCOMPLETE", rep

    rep["comparison"] = {
        "total_power_uw": judged["total_power_uw"],
        "power_budget_uw": judged["limit_uw"],
        "utilization": judged["utilization"],
        "stated_in": source_rep["file"],
        "activity_basis": judged["activity_basis"],
        "basis_policed": judged["basis_policed"],
        "authority": judged["authority"],
        "over": judged["verdict"] == _pw.J_FAIL,
    }
    if judged["verdict"] == _pw.J_FAIL:
        rep["findings"].append({
            "severity": "ERROR", "rule": "POWER_TOTAL_OVER_BUDGET",
            "message": (f"total power {judged['total_power_uw']:.4e} uW "
                        f"({source_rep['file']}, activity basis "
                        f"{judged['activity_basis']}) exceeds the declared "
                        f"budget {judged['limit_uw']:.4e} uW "
                        f"({judged['authority']}) by "
                        f"{judged['utilization']:.4g}x")})
        rep["verdict"] = "FAIL"
        return "FAIL", rep
    rep["verdict"] = "PASS"
    return "PASS", rep


def _scope_line(rep: Dict[str, Any]) -> str:
    l19 = len(rep["budget_sources"])
    contract = len([s for s in rep["requirement_sources"]
                    if s.get("authority") == _pw.AUTHORITY_CONTRACT])
    extra = f" and {contract} ppa contract requirement(s)" if contract else ""
    return (f"read {len(rep['totals_read'])} total-power figure(s) from the "
            f"power report family and {l19} L19 copy/copies{extra}")


def _basis_line(rep: Dict[str, Any]) -> str:
    counts: Dict[str, int] = {}
    for d in rep["reports_read"]:
        b = d.get("activity_basis") or "UNREADABLE"
        counts[b] = counts.get(b, 0) + 1
    if not counts:
        return "  Activity basis: no power report was read."
    inv = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    return f"  Activity basis of the reports read: {inv}."


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project", nargs="?", default=".",
                    help="project directory (default: cwd)")
    ap.add_argument("--budget-uw", type=float, default=None,
                    help="power budget in uW, overriding the contract (for "
                         "callers that carry the requirement themselves)")
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    project = Path(args.project)
    if not project.is_dir():
        print(f"ERROR: {args.project!r} is not a directory", file=sys.stderr)
        return RC_ARG
    if args.budget_uw is not None and args.budget_uw <= 0:
        print("ERROR: --budget-uw must be positive", file=sys.stderr)
        return RC_ARG

    verdict, rep = evaluate(project, args.budget_uw)
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        # PPA_INTERFACES.md §1: every CLI writes through `_atomic_artefact`, so
        # the declared destination never exists half-written. A reader that
        # finds the file finds a complete document or nothing.
        _aa.write_text(out, json.dumps(rep, indent=2, ensure_ascii=False)
                       + "\n")

    scope = _scope_line(rep)

    if verdict == "FAIL":
        print(f"[FAIL] {TOOL}: {scope}")
        print(_basis_line(rep))
        for f in rep["findings"]:
            print(f"  - {f.get('rule')}: {f.get('message')}")
        return RC_FINDINGS

    if verdict == "PASS":
        c = rep["comparison"]
        print(f"[PASS] {TOOL}: {scope}. Compared total power "
              f"{c['total_power_uw']:.4e} uW ({c['stated_in']}) against the "
              f"declared budget {c['power_budget_uw']:.4e} uW "
              f"({c['authority']}); utilization {c['utilization']:.4f}, "
              f"limit 1.0")
        print(_basis_line(rep))
        if not c["basis_policed"]:
            print(f"  The limit declares no activity basis, so it bounds a "
                  f"{c['activity_basis']} number without knowing that is what "
                  f"it bounds.")
        return RC_OK

    # The sentinel must START A LINE and survive the consumer's tail cut —
    # `flow_compliance_check.output_snippet` keeps only the LAST 300 characters
    # of stdout, so the detail goes FIRST and the token is the SHORT LAST LINE.
    # MEASURED: a first draft printed the token at the head of one long
    # paragraph and `_stdout_signals_token` returned False on it.
    print(f"{TOOL}: {scope}.")
    print(_basis_line(rep))
    # Say WHICH refusal this is. A gate that prints the same paragraph for
    # "nobody declared a budget" and "the number's activity model is a
    # fabrication" has told the reader nothing about which one to go and fix.
    code = (rep.get("judgement") or {}).get("code")
    if code in ("ACTIVITY_BASIS_UNUSABLE", "TOTAL_NOT_MEASURED",
                "ACTIVITY_BASIS_MISMATCH", "ACTIVITY_BASIS_CONFLICT"):
        print(f"  A threshold was declared and the gate still will not apply "
              f"it, because a watt figure is only comparable to something "
              f"written against the SAME activity model: vectorless power and "
              f"VCD power are different metrics. Fix the measurement or "
              f"declare the basis; do not widen the budget.")
    else:
        print(f"  A power budget is a REQUIREMENT and has to arrive in the "
              f"design's own input documents. This gate will not derive one "
              f"from die area, supply voltage or another tool's number, "
              f"because a threshold nobody declared would turn an unanswered "
              f"question into an answered one. Nor will it compare a watt "
              f"figure whose activity model is unknown: vectorless power and "
              f"VCD power are different metrics.")
    print(f"INCOMPLETE: total power was NOT compared against anything — "
          f"missing authority: {rep['missing_authority']}.")
    # A REFUSAL EXITS 2, NOT 0 (vibe-ic#1017). See the module docstring.
    return RC_NOT_COMPARED


if __name__ == "__main__":
    sys.exit(main())
