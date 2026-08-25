#!/usr/bin/env python3
"""ppa_signoff_records.py — the flow's sign-off evidence, as canonical records.

WHAT IT ANSWERS
===============
"What do this run's own sign-off artefacts say about the physical, reliability
and equivalence feasibility axes?" — as `vibeic.ppa.metric.v1` records that
`ppa_feasibility_check.py` can read.

It is the missing half of the feasibility gate. The gate proves its axes from
canonical metric names; before this program, seven of those names were produced
by nothing in this tree, so a run that measured DRC, LVS, antenna, IR, EM and
LEC and passed every one of them still adjudicated UNDETERMINED — the evidence
existed and nothing could reach it. With no FEASIBLE candidate possible, "both
arms feasible" — one of the four conditions a head-to-head requires — could
never hold, so no PPA comparison could be defended.

THE TENTH AXIS ARRIVED IN EXACTLY THAT STATE, AND THIS IS WHERE IT IS FIXED
===========================================================================
`eco_readiness` — does this design still carry the spare/ECO cells that make a
post-tape-out bug fixable by a metal-only ECO instead of a base-layer respin —
proves from `design_for_eco.*` metric names. The flow already writes the
evidence: `phase3/stage3/pnr/spare_cells.json` is emitted on every run that
inserts spares, and `reports/spare_preservation.json` records which of them
survived to the shipped artefacts. Nothing turned either into a canonical
record, so on a real run the axis read UNDETERMINED however many spares the
design actually had — the same defect as the seven above, one axis later.

THE READER IS NOT REIMPLEMENTED HERE. `ppa_eco_spare_records.py` already reads
those two artefacts, and it holds rules that took measurement to get right: a
plan whose `count` disagrees with its own `instances` list is INVALID and every
row derived from that list is INVALID with it; a missing plan is NOT_MEASURED
and never a zero; a `NO_WITNESS` preservation report vouches for nothing. A
second reader here would be a second set of those rules, and the first time the
two disagreed the design would pass one gate and fail the other with nobody able
to say which was right. So this program calls that one's pure functions and
appends what they return.

WHAT IT IS NOT
==============
It is not a gate and it returns no design verdict. `rc=1` is reserved for a
finding about silicon and this program never makes one: it reports what the
artefacts state and `ppa_feasibility_check.py` adjudicates. It never writes a
number no artefact stated, and a missing artefact produces a NOT_MEASURED record
carrying the reason — never a zero, never an omitted row.

EXIT CODES (docs/PPA_INTERFACES.md 1)
=====================================
    0  at least one axis was MEASURED from the run's artefacts
    2  UNDETERMINED — the run directory holds no readable sign-off artefact, so
       every record came out NOT_MEASURED. Printed with `[CANNOT CHECK]`.
    3  bad invocation — the run path is not a directory. Never a design FAIL.
    1  never returned. See above.

An empty or artefact-less run tree is rc=2 and NOT rc=0. A producer that reports
success when it read nothing is the vacuous pass this whole fixture tree exists
to prevent: the bundle it would write is eight well-formed NOT_MEASURED records,
which is honest, and a 0 beside it would not be.

USAGE
=====
    python3 ppa_signoff_records.py <run-dir> [--json OUT] [--quiet]

`<run-dir>` is a project/run directory — the one holding `reports/phase3/`.
`--json` writes the `vibeic.ppa.signoff_records.v1` bundle; the `records` list
inside it is the bare list `_ppa/metrics.records_from_document` already accepts,
so it can be handed straight to `ppa_metric_extract.py --records`.

chip/PDK/vendor-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
from typing import List, Optional

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import _atomic_artefact  # noqa: E402
import ppa_eco_spare_records as eco  # noqa: E402
from _ppa import cli_exit, signoff  # noqa: E402

MARK_CANNOT = "[CANNOT CHECK]"

#: Where the flow puts the two design-for-ECO artefacts. Named here beside the
#: other `*_REL` constants rather than inside the reader, because "where the
#: flow writes it" is this program's question and "what it says" is that one's.
ECO_PLAN_REL = "phase3/stage3/pnr/spare_cells.json"
ECO_PRESERVATION_REL = "reports/spare_preservation.json"

#: The spare plan describes the placed-and-routed database, so the records are
#: scoped to the same stage the antenna and IR axes use. It is NOT
#: `post_route_extracted`: no parasitic extraction is involved in counting
#: cells, and claiming a stage the measurement did not come from is how two
#: incomparable numbers end up filed as one.
ECO_STAGE = "post_route"

RC_OK = 0
RC_UNDETERMINED = 2
RC_BAD_INVOCATION = 3


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Emit canonical metric records for the physical, "
                    "reliability and equivalence feasibility axes.")
    ap.add_argument("run", help="run / project directory holding reports/")
    ap.add_argument("--json", default=None, help="bundle artefact path")
    ap.add_argument("--quiet", action="store_true",
                    help="suppress the per-axis census on stdout")
    # argparse exits 2 on a usage error and the contract says a bad invocation
    # is 3, so its own exit has to be intercepted. It is intercepted BY CODE and
    # not by exception type: `--help` raises SystemExit(0) too, and the bare
    # `except SystemExit: return RC_BAD_INVOCATION` that stood here turned
    # asking this program what its flags are into a bad invocation. That is the
    # trap `_ppa/cli_exit.parse_or_refuse` exists to close, in one place, for
    # every `ppa_*` CLI.
    args, rc = cli_exit.parse_or_refuse(ap, argv)
    if args is None:
        return rc

    run = pathlib.Path(args.run)
    if not run.is_dir():
        print(f"{MARK_CANNOT} {run} is not a directory", file=sys.stderr)
        return RC_BAD_INVOCATION

    doc = signoff.bundle(run)
    _add_eco_records(run, doc)
    if args.json:
        _atomic_artefact.write_json(args.json, doc, indent=2, sort_keys=True)

    if not args.quiet:
        c = doc["census"]
        print(f"ppa_signoff_records: {c['records']} record(s), "
              f"{c['measured']} MEASURED, {c['not_measured']} NOT_MEASURED")
        for n in doc["notes"]:
            line = f"  {n['status']:<12} {n['metric']}"
            if n["reason"]:
                line += f"\n      {n['reason']}"
            print(line)

    if doc["census"]["measured"] == 0:
        # Every axis NOT_MEASURED. The bundle is honest and the run supports no
        # feasibility claim; saying 0 here would let a caller that reads only
        # the exit code treat "I read nothing" as "I read it and it was fine".
        print(f"{MARK_CANNOT} no sign-off artefact under {run} supported any "
              f"feasibility axis; this run makes no claim about any of them",
              file=sys.stderr)
        return RC_UNDETERMINED
    return RC_OK


def _add_eco_records(run: pathlib.Path, doc: dict) -> None:
    """Append the design-for-ECO records to the bundle, and re-count.

    The census is RECOMPUTED rather than incremented, so it cannot drift from
    the records it describes — the same reason `signoff.bundle` computes it
    instead of letting its caller quote one.
    """
    plan_path = run / ECO_PLAN_REL
    pres_path = run / ECO_PRESERVATION_REL
    plan, plan_digest, plan_reason = eco.read_artefact(str(plan_path),
                                                      "spare plan")
    scope = {"stage": ECO_STAGE, "tool": eco.PLAN_TOOL}
    source = (eco._source(str(plan_path), plan_digest, "spare_plan")
              if plan is not None and plan_digest else None)
    records = eco.records_from_plan(plan, scope, source, plan_reason)

    pres = pres_digest = pres_reason = None
    if pres_path.exists():
        pres, pres_digest, pres_reason = eco.read_artefact(
            str(pres_path), "spare preservation report")
    else:
        pres_reason = (f"{ECO_PRESERVATION_REL} is not in this run, so whether "
                       "the inserted spares are still named by the shipped "
                       "artefacts was not established")
    pres_source = (eco._source(str(pres_path), pres_digest,
                               "spare_preservation")
                   if pres is not None and pres_digest else None)
    records.append(eco.survival_record(pres, scope, pres_source, pres_reason))

    doc["records"].extend(records)
    for rec in records:
        doc["notes"].append({
            "metric": rec["metric"], "status": rec["status"],
            "artefact": (ECO_PRESERVATION_REL
                         if rec["metric"] == eco.feas.ECO_M_SURVIVING
                         else ECO_PLAN_REL),
            "present": (pres is not None
                        if rec["metric"] == eco.feas.ECO_M_SURVIVING
                        else plan is not None),
            "reason": rec.get("reason") or None})
    measured = [r for r in doc["records"] if r["status"] == signoff.MEASURED]
    doc["census"] = {"records": len(doc["records"]),
                     "measured": len(measured),
                     "not_measured": len(doc["records"]) - len(measured)}
    doc["eco_readiness_reader"] = {
        "program": eco.PROGRAM,
        "why": ("the two design-for-ECO artefacts have ONE reader in this "
                "tree, so no two gates can disagree about what the plan says"),
        "spare_plan": str(plan_path),
        "spare_plan_read": plan is not None,
        "preservation": str(pres_path),
        "preservation_read": pres is not None,
    }


if __name__ == "__main__":
    sys.exit(main())
