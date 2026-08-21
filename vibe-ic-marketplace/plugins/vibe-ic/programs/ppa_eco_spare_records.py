#!/usr/bin/env python3
"""ppa_eco_spare_records.py — the design-for-ECO spare population, as canonical
metric records the promotion gate can adjudicate.

WHY THIS PRODUCER EXISTS
========================
`_ppa/feasibility.py` grew an `eco_readiness` axis because a place-and-route
search deleted a design's entire spare-cell population and scored BETTER for it:
smaller area, lower power, and no axis anywhere that said the resulting layout
can no longer be repaired by a metal-only ECO. The axis is the refusal. This
program is the evidence it refuses from.

Two gates already read the flow's own `spare_cells.json`:
`spare_cell_coverage_check.py` (were enough inserted, spread and tied off) and
`spare_cell_preservation_check.py` (did they survive to the shipped artefacts).
Neither produces a `vibeic.ppa.metric.v1` record, so neither fact could enter a
PPA candidate comparison at all. This program is the bridge, and it delegates
the one shared definition -- what counts as a distinct spare POSITION -- to
`spare_cell_coverage_check.compute_distribution` rather than reimplementing it,
because two gates that disagree about the meaning of a number is how a design
passes one and fails the other with nobody able to say which is right.

WHAT IT WILL NOT DO, AND THIS IS THE WHOLE DISCIPLINE
=====================================================
IT NEVER TURNS AN ABSENCE INTO A ZERO. A spare plan that is missing, unreadable
or not an object produces NOT_MEASURED records carrying the reason -- never
`count: 0`. Those two inputs must not produce the same number, because one of
them convicts a run nobody looked at and the other reports a real deletion, and
the gate's verdict differs: NOT_MEASURED is UNDETERMINED, a measured 0 below a
declared floor is INFEASIBLE.

IT NEVER ADJUDICATES. No floor, no density, no required kind list appears in
this file. Whether 10 spares is enough is the DESIGN's declaration and
`_ppa/feasibility.py`'s comparison. A producer that knew the requirement would
be grading its own homework, and the gate downstream would be a rubber stamp.

IT CROSS-CHECKS THE PLAN AGAINST ITSELF. A plan whose `count` disagrees with the
length of its own `instances` list is INVALID -- somebody looked and the
artefact cannot answer -- and not quietly resolved in favour of whichever field
the reader happened to trust.

WHAT IT EMITS
=============
    design_for_eco.spares.count                     the inserted population
    design_for_eco.spares.kind.<kind>.count         per kind, from `instances`
    design_for_eco.spares.distinct_positions.count  spread PROXY, not reach
    design_for_eco.spares.tie_off.verdict           TIED_OFF / NOT_TIED_OFF
    design_for_eco.spare_pads.count                 reserved spare ECO pads
    design_for_eco.spares.surviving.count           from a preservation report,
                                                    NOT_MEASURED without one

EXIT CODES (docs/PPA_INTERFACES.md 1)
=====================================
    0  records were emitted from a spare plan that was READ
    2  [CANNOT CHECK] the plan could not be read; a record document was still
       written and every row in it is NOT_MEASURED with the reason. Never 0:
       a caller that saw 0 would treat "no plan" as a measured population.
    3  bad invocation

chip-AGNOSTIC: no IC, vendor, SKU, process or PDK name appears in this file.
The cell kinds are whatever the plan itself names.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from typing import Any, Dict, List, Mapping, Optional, Tuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import _atomic_artefact  # noqa: E402
from _ppa import cli_exit  # noqa: E402
from _ppa import feasibility as feas  # noqa: E402
from _ppa import metrics as M  # noqa: E402
from spare_cell_coverage_check import compute_distribution  # noqa: E402

PROGRAM = "ppa_eco_spare_records"
RECORDS_SCHEMA = "vibeic.ppa.metric_bundle.v1"

RC_PASS = 0
RC_UNDETERMINED = 2
RC_BAD_INVOCATION = 3

MARK_CANNOT = "[CANNOT CHECK]"

#: The tool that WROTE the plan. Not the placer: the plan is serialised by the
#: flow runner from what the placer did, and naming the placer would send a
#: reader looking for a file the placer never wrote.
PLAN_TOOL = "phase3_one_shot_runner"

V_TIED_OFF = "TIED_OFF"
V_NOT_TIED_OFF = "NOT_TIED_OFF"


# ---------------------------------------------------------------------------
# reading, with the failures kept apart
# ---------------------------------------------------------------------------
def read_artefact(path: Optional[str], what: str
                  ) -> Tuple[Optional[Dict[str, Any]], Optional[str],
                             Optional[str]]:
    """(document, sha256-of-the-bytes, reason-it-could-not-be-read).

    "not given", "not there", "not JSON" and "not an object" are four different
    facts about why there is no measurement, and a single None for all of them
    is how a producer's caller loses the ability to fix the right thing.
    """
    if not path:
        return None, None, f"no {what} path was given to {PROGRAM}"
    p = pathlib.Path(path)
    if not p.is_file():
        return None, None, f"{what} does not exist at {p}"
    try:
        raw = p.read_bytes()
    except OSError as exc:
        return None, None, f"{what} at {p} could not be read: {exc}"
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, digest, f"{what} at {p} is not JSON: {exc}"
    if not isinstance(doc, dict):
        return None, digest, (f"{what} at {p} is a "
                              f"{type(doc).__name__}, not an object")
    return doc, digest, None


def _source(path: str, digest: str, role: str) -> Dict[str, Any]:
    return {"path": path, "sha256": digest, "tool": PLAN_TOOL,
            "parser": f"{PROGRAM}.py", "role": role}


def _with_source(rec: Dict[str, Any],
                 source: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Attach the artefact a NON-measured row was read FROM.

    `M.not_measured` / `M.not_applicable` / `M.invalid` take no `source`
    keyword -- `_base` already fills that slot with None -- but a row saying
    "this artefact does not state the fact" is worth far more when it names the
    artefact, and every other producer in this lane emits one. So it is
    attached after construction and the record is RE-VALIDATED, rather than
    dropped or the shared helper's signature bent for one caller.
    """
    if source:
        rec["source"] = dict(source)
        M.validate_or_raise(rec)
    return rec


def _int_or_none(v: Any) -> Optional[int]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if isinstance(v, float) and v != int(v):
        return None
    return int(v)


# ---------------------------------------------------------------------------
# the plan -> records
# ---------------------------------------------------------------------------
def records_from_plan(plan: Optional[Mapping[str, Any]],
                      scope: Mapping[str, Any],
                      source: Optional[Mapping[str, Any]],
                      unreadable_reason: Optional[str]
                      ) -> List[Dict[str, Any]]:
    """Every spare-population record one plan supports, and NOT_MEASURED rows
    for the ones it does not. Pure: no filesystem, so a test drives it
    directly."""
    out: List[Dict[str, Any]] = []
    if plan is None:
        reason = unreadable_reason or "the spare plan could not be read"
        for metric in (feas.ECO_M_COUNT, feas.ECO_M_POSITIONS,
                       feas.ECO_M_PADS, feas.ECO_M_TIE_OFF):
            out.append(M.not_measured(metric, reason, scope))
        return out

    instances = plan.get("instances")
    instances = instances if isinstance(instances, list) else None
    declared = _int_or_none(plan.get("count"))

    # --- the total ---------------------------------------------------------
    if declared is None and instances is None:
        out.append(_with_source(M.not_measured(
            feas.ECO_M_COUNT,
            "the plan names neither a `count` nor an `instances` list, so it "
            "states no spare population at all", scope), source))
    elif (declared is not None and instances is not None
            and declared != len(instances)):
        out.append(_with_source(M.invalid(
            feas.ECO_M_COUNT,
            f"the plan says count={declared} and lists {len(instances)} "
            "instance(s). One of the two is wrong and this program will not "
            "pick the flattering one", scope), source))
    else:
        total = declared if declared is not None else len(instances or [])
        if total < 0:
            out.append(_with_source(M.invalid(
                feas.ECO_M_COUNT,
                f"the plan says count={total}; a negative population is a "
                "broken parse, not a very small one", scope), source))
        else:
            out.append(M.measured(feas.ECO_M_COUNT, total, "count", scope,
                                  dict(source or {})))

    # --- per kind ----------------------------------------------------------
    out.extend(_kind_records(plan, instances, scope, source))

    # --- spread ------------------------------------------------------------
    if instances is None:
        out.append(_with_source(M.not_measured(
            feas.ECO_M_POSITIONS,
            "the plan lists no `instances`, so no placement position could be "
            "read from it", scope), source))
    else:
        distinct, _total, _ok = compute_distribution(instances)
        out.append(M.measured(
            feas.ECO_M_POSITIONS, distinct, "count", scope,
            dict(source or {}),
            provenance={
                "definition": ("distinct (llx, lly) pairs over the plan's own "
                               "instance list, via "
                               "spare_cell_coverage_check.compute_distribution "
                               "-- the same function the readiness gate uses, "
                               "so the two cannot disagree about what a "
                               "position is"),
                "is_not": ("a reachability measurement. Two spares at distinct "
                           "positions may still both be unreachable from the "
                           "net a future ECO has to repair")}))

    # --- tie-off -----------------------------------------------------------
    out.append(_tie_off_record(plan, instances, declared, scope, source))

    # --- spare ECO pads ----------------------------------------------------
    pads = plan.get("spare_pads")
    if isinstance(pads, list):
        out.append(M.measured(feas.ECO_M_PADS, len(pads), "count", scope,
                              dict(source or {})))
    else:
        out.append(_with_source(M.not_measured(
            feas.ECO_M_PADS,
            "the plan names no `spare_pads` list, so whether any spare ECO pad "
            "was reserved is not stated by it", scope), source))
    return out


def _kind_records(plan: Mapping[str, Any], instances: Optional[List[Any]],
                  scope: Mapping[str, Any],
                  source: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """One record per spare KIND the plan is able to talk about.

    THE ZERO HERE IS A MEASUREMENT AND THE ABSENCE IS NOT. When the instance
    list was read, a kind that appears in none of the instances really has none
    -- the list is the population, not a sample -- so 0 is the right number and
    the record says where it came from. When there is no instance list, no kind
    count can be attributed at all and every kind is NOT_MEASURED.

    The kinds are the plan's OWN vocabulary: the union of the cell map it was
    built from, the type tally it published and the types it actually placed. A
    kind a design requires that this flow cannot even name produces no record,
    and the gate reads that as an absent metric -- UNDETERMINED -- which is
    correct: nothing here can say whether the design has it.
    """
    kinds = set()
    cell_map = plan.get("cell_map")
    if isinstance(cell_map, Mapping):
        kinds |= {k.strip() for k in cell_map
                  if isinstance(k, str) and k.strip()}
    types = plan.get("types")
    if isinstance(types, Mapping):
        kinds |= {k.strip() for k in types if isinstance(k, str) and k.strip()}
    for inst in (instances or []):
        if isinstance(inst, Mapping) and isinstance(inst.get("type"), str) \
                and inst["type"].strip():
            kinds.add(inst["type"].strip())

    out: List[Dict[str, Any]] = []
    for kind in sorted(kinds):
        metric = feas.eco_metric_for_kind(kind)
        if instances is None:
            out.append(_with_source(M.not_measured(
                metric,
                "the plan lists no `instances`, so no spare could be "
                f"attributed to the {kind!r} kind", scope), source))
            continue
        n = sum(1 for i in instances
                if isinstance(i, Mapping) and i.get("type") == kind)
        out.append(M.measured(
            metric, n, "count", scope, dict(source or {}),
            provenance={"counted_from": "the plan's own `instances` list",
                        "population": len(instances),
                        "zero_is_a_measurement": (
                            "the instance list IS the population, so a kind "
                            "absent from it has none. This is not the absence "
                            "of a measurement")}))
    return out


def _tie_off_record(plan: Mapping[str, Any], instances: Optional[List[Any]],
                    declared: Optional[int], scope: Mapping[str, Any],
                    source: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """TIED_OFF / NOT_TIED_OFF, or the honest absence.

    A spare with floating inputs is not a spare you can use; it is a leakage
    path and a potential latch-up site. But "the log carried no tie-off count"
    and "the tie-off ran and connected nothing" are different findings, and the
    plan already distinguishes them in `tie_off.measured`, so this record does
    too rather than flattening both to false.
    """
    total = declared if declared is not None else (
        len(instances) if instances is not None else None)
    if total == 0:
        return _with_source(M.not_applicable(
            feas.ECO_M_TIE_OFF,
            "the plan records no spare cells, so there is no spare input that "
            "could be tied off. This is not a tie-off that passed", scope),
            source)
    tie = plan.get("tie_off")
    if not isinstance(tie, Mapping):
        legacy = plan.get("tied_off")
        if isinstance(legacy, bool):
            return M.measured(
                feas.ECO_M_TIE_OFF,
                V_TIED_OFF if legacy else V_NOT_TIED_OFF,
                M.VERDICT_UNIT, scope, dict(source or {}),
                provenance={"read_from": "the plan's top-level `tied_off` flag",
                            "caveat": ("the plan carries no `tie_off` block, so "
                                       "how many inputs were checked is not "
                                       "stated")})
        return _with_source(M.not_measured(
            feas.ECO_M_TIE_OFF,
            "the plan names neither a `tie_off` block nor a `tied_off` flag",
            scope), source)
    if not tie.get("measured"):
        return _with_source(M.not_measured(
            feas.ECO_M_TIE_OFF,
            str(tie.get("reason") or "the plan's tie-off block states it was "
                                     "not measured and gives no reason"),
            scope), source)
    ok = bool(tie.get("tied_off"))
    return M.measured(
        feas.ECO_M_TIE_OFF, V_TIED_OFF if ok else V_NOT_TIED_OFF,
        M.VERDICT_UNIT, scope, dict(source or {}),
        provenance={"connected": tie.get("connected"),
                    "candidates": tie.get("candidates"),
                    "reason": tie.get("reason")})


def survival_record(report: Optional[Mapping[str, Any]],
                    scope: Mapping[str, Any],
                    source: Optional[Mapping[str, Any]],
                    unreadable_reason: Optional[str]) -> Dict[str, Any]:
    """How many spares the SHIPPED artefacts still name, from a preservation
    report -- or the honest absence when there is none.

    This is the fact that actually bears on a post-tape-out repair. The
    insertion count says what the placer put down; every optimisation pass
    after it (CTS, hold fixing, routing, ECO, metal fill) could have stripped
    them, and a count of what was inserted cannot see that.
    """
    if report is None:
        return M.not_measured(
            feas.ECO_M_SURVIVING,
            unreadable_reason or (
                "no spare-preservation report was supplied, so whether the "
                "inserted spares are still named by the shipped artefacts was "
                "not established by this run"),
            scope)
    agreement = report.get("artefact_agreement")
    if isinstance(agreement, Mapping) \
            and agreement.get("status") == "NO_WITNESS":
        return _with_source(M.not_measured(
            feas.ECO_M_SURVIVING,
            "the preservation report states NO_WITNESS: no name-bearing final "
            "artefact could be read, so nothing vouched for any spare",
            scope), source)
    survived = _int_or_none(report.get("survived"))
    if survived is None or survived < 0:
        return _with_source(M.invalid(
            feas.ECO_M_SURVIVING,
            f"the preservation report's `survived` is "
            f"{report.get('survived')!r}, which is not a count", scope), source)
    return M.measured(
        feas.ECO_M_SURVIVING, survived, "count", scope, dict(source or {}),
        provenance={"inserted": report.get("inserted"),
                    "artefact_agreement": (dict(agreement)
                                           if isinstance(agreement, Mapping)
                                           else None),
                    "is_not": ("a claim that a repair built from these spares "
                               "would route or would meet timing")})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Emit design-for-ECO spare-population metric records.")
    ap.add_argument("--spare-plan", required=True,
                    help="the flow's spare_cells.json")
    ap.add_argument("--preservation", default=None,
                    help="reports/spare_preservation.json, when one exists")
    ap.add_argument("--stage", required=True,
                    help="the scope stage these records are about")
    ap.add_argument("--json", default=None, help="record document path")
    args, rc = cli_exit.parse_or_refuse(ap, argv)
    if args is None:
        return rc

    plan, plan_digest, plan_reason = read_artefact(args.spare_plan,
                                                   "spare plan")
    scope: Dict[str, Any] = {"stage": args.stage, "tool": PLAN_TOOL}
    source = (_source(args.spare_plan, plan_digest, "spare_plan")
              if plan is not None and plan_digest else None)
    records = records_from_plan(plan, scope, source, plan_reason)

    pres: Optional[Dict[str, Any]] = None
    pres_digest = pres_reason = None
    if args.preservation:
        pres, pres_digest, pres_reason = read_artefact(
            args.preservation, "spare preservation report")
    pres_source = (_source(args.preservation, pres_digest,
                           "spare_preservation")
                   if pres is not None and pres_digest else None)
    records.append(survival_record(pres, scope, pres_source, pres_reason))

    doc = {
        "schema": RECORDS_SCHEMA,
        "program": PROGRAM,
        "records": records,
        "sources": {"spare_plan": args.spare_plan,
                    "spare_plan_sha256": plan_digest,
                    "spare_plan_unreadable": plan_reason,
                    "preservation": args.preservation,
                    "preservation_sha256": pres_digest,
                    "preservation_unreadable": pres_reason},
        "not_measured_by_this_program": [dict(x)
                                         for x in feas.ECO_NEVER_PROVED],
    }
    if args.json:
        _atomic_artefact.write_json(args.json, doc, indent=2, sort_keys=True)
    else:
        print(json.dumps(doc, indent=2, sort_keys=True))

    if plan is None:
        print(f"{MARK_CANNOT} {plan_reason}; every spare-population record in "
              f"this document is NOT_MEASURED and none of them is a zero",
              file=sys.stderr)
        return RC_UNDETERMINED
    return RC_PASS


if __name__ == "__main__":
    sys.exit(main())
