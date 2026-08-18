#!/usr/bin/env python3
"""power_total_vs_budget_check.py — the total power figure must reach a
COMPARISON, or the step must REFUSE and name the budget it lacks.

ENFORCEMENT: advisory — no runner spawns this gate inline, so it cannot stop
step 33 while step 33 is running. That is the ONLY axis this token names, and
it is the one `flow_gate_enforcement_audit` measures. The other two axes are
unchanged, and are stated here so the declaration can never be read as
permission to defang the gate:

  * VERDICT SEVERITY — unchanged. rc 1 when a declared budget is exceeded,
    rc 2 on INCOMPLETE. The rc-2 half is vibe-ic#1022's repair, landed in
    #1026: on the whole published corpus this gate's honest answer is
    INCOMPLETE (17 runs carry a power report, 0 carry an L19 power budget), and
    while INCOMPLETE exited 0 the refusal was indistinguishable from a pass —
    which is the exact defect the gate was written to remove, one floor down.
  * FLOW SLOT — unchanged and BLOCKING. Step 33 wires this gate in
    `program_exit_zero`, never `advisory_program_exit_zero`.

WIRED AND DECLARED ARE DIFFERENT QUESTIONS (vibe-ic#1035). See the identically
shaped block in `em_peak_current_authority_check`, this gate's sibling from the
same two PRs: being wired into the flow's blocking slot has never been an
answer to "does this program say where its verdict is consumed", and the audit
reported both as `undeclared::` throughout, correctly.

THE DEFECT, MEASURED
====================
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

THE HONEST ANSWER HERE IS A REFUSAL, AND THAT IS THE DELIVERABLE
================================================================
The declared authority for total power in this flow is L19's
``power_budget_uw``. It is written by `phase1_post_process.py`, and
`l19_pdk_floorplan_contract_check` already records — as an ADVISORY, correctly —
that "no program in the flow reads it".

MEASURED over the published corpus on 2026-08-11, by CONTENT rather than by
reputation:

    L19*.json copies in benchmark-data/       195
      with power_budget_uw set                  3   (all three are copies of
                                                    ONE design's L19)
    published runs carrying reports/**/power.rpt  17
      of those, with an L19 power budget          0

So there is not one published run in which this comparison could have been made.
The budget is absent everywhere the power report exists, and the L19 of the run
the ledger replays states, in its own words, "Spec does not state PDK / timing
constraints".

**A green cell over a design whose power was never compared to anything is the
defect. A cell that REFUSES and names the missing budget is not.** This gate
therefore does not invent an authority. It does not derive a budget from die
area, supply voltage, or a sibling tool's number, because every one of those
would be a ruler chosen to fit the corpus — and a threshold nobody declared is
worse than no threshold, since it turns an unanswered question into an answered
one.

    budget declared, total <= budget   -> PASS, naming budget and total
    budget declared, total >  budget   -> FAIL, naming both
    budget absent                      -> INCOMPLETE, naming L19.power_budget_uw
    no total power figure readable     -> INCOMPLETE, naming that too

`INCOMPLETE` is this repository's own tier for "the input WAS applicable and it
was not audited; someone must come back". `flow_compliance_check` promotes a
step to it when a passing gate prints the token at line-start; it aggregates
exactly as VACUOUS_PASS does, so no published design turns red on this, and the
per-step listing stops reporting step 33 as a bare PASS.

WHAT STEP 33 STILL NEEDS, AND IT DOES NOT COME FROM THIS REPOSITORY
===================================================================
A power budget is a REQUIREMENT, not a measurement: it has to arrive in the
design's own input documents and be extracted into L19 by Phase 1. Until a
design states one, this gate can only keep saying so. Nothing in the plugin can
close that, and closing it by picking a number would be the fabrication the
whole §4.05 doctrine exists to prevent.

WHAT THIS GATE DOES NOT DO — stated so a reviewer does not have to find it
=========================================================================
  * It does not check that the group rows SUM to the Total row. That is a real
    property and a real check, but it is not this one, and the ledger's mutation
    was deliberately built to preserve it (the zeros are left alone and the
    table stays internally consistent), so adding it here would not change the
    verdict on the entry this gate was written for.
  * It does not compare against any OTHER tool's power figure carried elsewhere
    in the run. The IR analysis states a per-net total power from a different
    engine on a different netlist view; on the run the ledger replays the two
    already differ by 4.3x at baseline, so a cross-tool tolerance would have to
    be chosen wide enough to admit that — a ruler fitted to the corpus.
  * It reads the total power figure only. Per-group and per-category figures are
    parsed for disclosure but are not screened, because L19 declares one budget.

chip-AGNOSTIC: it reads a watt figure and a micro-watt budget. No foundry,
process or chip token appears anywhere in this file.

Exit codes: 0 = PASS, 1 = the total exceeds the declared budget, 2 = the
question could not be put — INCOMPLETE (the disclosed-skip tier,
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

The refusal itself is unchanged and still correct: this gate will not derive a
budget from die area or supply voltage, because a threshold nobody declared
would turn an unanswered question into an answered one. What changes is only
that the refusal now leaves through the exit code as well as the text —
`flow_compliance_check` records rc 2 as VACUOUS_PASS, explicitly NOT a clean
result.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

TOOL = "power_total_vs_budget_check"
VERSION = "1.0.0"

RC_OK, RC_FINDINGS, RC_ARG = 0, 1, 2
#: INCOMPLETE — the disclosed-skip tier (`_vacuous_exit.RC_VACUOUS`).
#: Named apart from RC_ARG because they mean different things to a
#: reader even though the flow maps both to VACUOUS_PASS today.
RC_NOT_COMPARED = 2

#: Where a power report may sit. DISCOVERED from the tree, never enumerated.
_RPT_GLOBS = ("reports/**/power*.rpt", "steps/**/power*.rpt")
#: Where L19 may sit. Phase 1 publishes the same document into several
#: directories (ai_docs / generated_docs / merged_docs); all are read and the
#: budget must not disagree between them.
_L19_GLOBS = ("phase1/**/L19*.json", "generated_docs/L19*.json",
              "**/L19_CONSTRAINTS_PDK.json")

_NUM = r"([0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?)"
#: The Total row of the OpenSTA `report_power` table: four figures, the last of
#: which is the total power in watts, optionally followed by a percentage.
_TOTAL_ROW_RE = re.compile(
    r"^\s*Total\s+" + _NUM + r"\s+" + _NUM + r"\s+" + _NUM + r"\s+" + _NUM
    + r"\b", re.M)

_MICRO = 1e-6


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # reject NaN


def _rel(p: Path, project: Path) -> str:
    try:
        return str(p.relative_to(project))
    except ValueError:  # pragma: no cover - defensive
        return str(p)


def discover(project: Path, globs: Tuple[str, ...]) -> List[Path]:
    seen: Dict[str, Path] = {}
    for pat in globs:
        for p in project.glob(pat):
            if p.is_file():
                seen[str(p.resolve())] = p
    return [seen[k] for k in sorted(seen)]


def read_totals(project: Path) -> List[Dict[str, Any]]:
    """Every total-power figure (watts) the power report family states."""
    out: List[Dict[str, Any]] = []
    for fp in discover(project, _RPT_GLOBS):
        try:
            text = fp.read_text(errors="replace")
        except OSError:
            continue
        for m in _TOTAL_ROW_RE.finditer(text):
            total = _num(m.group(4))
            if total is None:
                continue
            out.append({"file": _rel(fp, project), "total_power_W": total,
                        "internal_power_W": _num(m.group(1)),
                        "switching_power_W": _num(m.group(2)),
                        "leakage_power_W": _num(m.group(3))})
    return out


def read_budget(project: Path) -> Tuple[Optional[float], List[Dict[str, Any]]]:
    """``(budget_uW, sources)`` from L19 ``power_budget_uw``.

    Every published copy is read. When copies DISAGREE the budget is treated as
    undeclared and the disagreement is reported: an authority two documents
    state differently is not an authority, and silently taking the first would
    make the verdict depend on glob order.
    """
    sources: List[Dict[str, Any]] = []
    for fp in discover(project, _L19_GLOBS):
        try:
            doc = json.loads(fp.read_text(errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict):
            continue
        fields = doc.get("fields")
        raw = fields.get("power_budget_uw") if isinstance(fields, dict) else None
        if raw is None and "power_budget_uw" in doc:
            raw = doc.get("power_budget_uw")
        val = _num(raw)
        sources.append({"file": _rel(fp, project), "power_budget_uw": val})
    stated = sorted({s["power_budget_uw"] for s in sources
                     if s["power_budget_uw"] is not None and
                     s["power_budget_uw"] > 0})
    if len(stated) == 1:
        return stated[0], sources
    return None, sources


def evaluate(project: Path, budget_override: Optional[float]
             ) -> Tuple[str, Dict[str, Any]]:
    """Return ``(verdict, report)``; verdict in {PASS, FAIL, INCOMPLETE}."""
    rep: Dict[str, Any] = {"program": TOOL, "version": VERSION,
                           "project": str(project), "findings": []}
    totals = read_totals(project)
    rep["totals_read"] = totals

    if budget_override is not None:
        budget, sources = budget_override, [{"file": "--budget-uw",
                                             "power_budget_uw": budget_override}]
    else:
        budget, sources = read_budget(project)
    rep["budget_sources"] = sources
    rep["power_budget_uw"] = budget

    disagreeing = sorted({s["power_budget_uw"] for s in sources
                          if s["power_budget_uw"] is not None
                          and s["power_budget_uw"] > 0})
    if budget is None and len(disagreeing) > 1:
        rep["budget_disagreement"] = disagreeing

    if budget is None or not totals:
        rep["verdict"] = "INCOMPLETE"
        lacks: List[str] = []
        if budget is None:
            lacks.append(
                "L19_CONSTRAINTS_PDK.json fields.power_budget_uw"
                + (f" (copies disagree: {disagreeing})" if len(disagreeing) > 1
                   else " (unset in "
                        f"{len([s for s in sources if s['power_budget_uw'] is None])}"
                        f" of {len(sources)} published copy/copies)"))
        if not totals:
            lacks.append("a readable Total row in any power report")
        rep["missing_authority"] = "; ".join(lacks)
        return "INCOMPLETE", rep

    worst = max(totals, key=lambda d: d["total_power_W"])
    total_uw = worst["total_power_W"] / _MICRO
    rep["comparison"] = {"total_power_uw": total_uw,
                         "power_budget_uw": budget,
                         "utilization": total_uw / budget if budget else None,
                         "stated_in": worst["file"],
                         "over": total_uw > budget}
    if total_uw > budget:
        rep["findings"].append({
            "severity": "ERROR", "rule": "POWER_TOTAL_OVER_BUDGET",
            "message": (f"total power {total_uw:.4e} uW ({worst['file']}) "
                        f"exceeds the declared budget {budget:.4e} uW "
                        f"(L19.power_budget_uw) by "
                        f"{total_uw / budget:.4g}x")})
        rep["verdict"] = "FAIL"
        return "FAIL", rep
    rep["verdict"] = "PASS"
    return "PASS", rep


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project", nargs="?", default=".",
                    help="project directory (default: cwd)")
    ap.add_argument("--budget-uw", type=float, default=None,
                    help="power budget in uW, overriding L19 (for callers that "
                         "carry the requirement outside the L-doc set)")
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
        out.write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n")

    scope = (f"read {len(rep['totals_read'])} total-power figure(s) from the "
             f"power report family and {len(rep['budget_sources'])} L19 "
             f"copy/copies")

    if verdict == "FAIL":
        print(f"[FAIL] {TOOL}: {scope}")
        for f in rep["findings"]:
            print(f"  - {f.get('rule')}: {f.get('message')}")
        return RC_FINDINGS

    if verdict == "PASS":
        c = rep["comparison"]
        print(f"[PASS] {TOOL}: {scope}. Compared total power "
              f"{c['total_power_uw']:.4e} uW ({c['stated_in']}) against the "
              f"declared budget {c['power_budget_uw']:.4e} uW "
              f"(L19.power_budget_uw); utilization {c['utilization']:.4f}, "
              f"limit 1.0")
        return RC_OK

    # The sentinel must START A LINE and survive the consumer's tail cut —
    # `flow_compliance_check.output_snippet` keeps only the LAST 300 characters
    # of stdout, so the detail goes FIRST and the token is the SHORT LAST LINE.
    # MEASURED: a first draft printed the token at the head of one long
    # paragraph and `_stdout_signals_token` returned False on it.
    print(f"{TOOL}: {scope}.")
    print(f"  A power budget is a REQUIREMENT and has to arrive in the "
          f"design's own input documents. This gate will not derive one from "
          f"die area, supply voltage or another tool's number, because a "
          f"threshold nobody declared would turn an unanswered question into "
          f"an answered one.")
    print(f"INCOMPLETE: total power was NOT compared against anything — "
          f"missing authority: {rep['missing_authority']}.")
    # A REFUSAL EXITS 2, NOT 0 (vibe-ic#1017). See the module docstring.
    return RC_NOT_COMPARED


if __name__ == "__main__":
    sys.exit(main())
