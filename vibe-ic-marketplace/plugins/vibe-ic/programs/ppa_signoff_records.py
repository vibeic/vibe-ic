#!/usr/bin/env python3
"""ppa_signoff_records.py — the flow's sign-off evidence, as canonical records.

WHAT IT ANSWERS
===============
"What do this run's own sign-off artefacts say about the physical, reliability
and equivalence feasibility axes?" — as `vibeic.ppa.metric.v1` records that
`ppa_feasibility_check.py` can read.

It is the missing half of the feasibility gate. The gate proves nine axes from
nine canonical metric names; before this program, seven of those names were
produced by nothing in this tree, so a run that measured DRC, LVS, antenna, IR,
EM and LEC and passed every one of them still adjudicated UNDETERMINED — the
evidence existed and nothing could reach it. With no FEASIBLE candidate
possible, "both arms feasible" — one of the four conditions a head-to-head
requires — could never hold, so no PPA comparison could be defended.

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
from _ppa import signoff  # noqa: E402

MARK_CANNOT = "[CANNOT CHECK]"

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
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        # argparse exits 2 on a usage error; the contract says a bad invocation
        # is 3, and a 2 there would be indistinguishable from "not checked".
        return RC_BAD_INVOCATION

    run = pathlib.Path(args.run)
    if not run.is_dir():
        print(f"{MARK_CANNOT} {run} is not a directory", file=sys.stderr)
        return RC_BAD_INVOCATION

    doc = signoff.bundle(run)
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


if __name__ == "__main__":
    sys.exit(main())
