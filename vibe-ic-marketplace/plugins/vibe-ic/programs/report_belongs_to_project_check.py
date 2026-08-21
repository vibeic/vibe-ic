#!/usr/bin/env python3
"""report_belongs_to_project_check.py — a runner report must be ABOUT the
project it sits in.

THE DEFECT (vibe-ic#587)
========================
Runner reports record the project they were produced for::

    reports/phase3/analog_one_shot.json
      "project": "<another operator's home>/AI_IC_design/_c2_adc_run/proj"
      "verdict": "FAIL"

sitting inside a DIFFERENT project tree. The report was carried forward — copied
or inherited from another run — and it brought its verdict with it. Nothing
looked at the `project` field, so:

* the verdict is about someone else's design, and
* it contradicts every per-step gate that audits the same steps in the tree it
  now lives in.

A stale FAIL is the visible half. The dangerous half is a stale **PASS**: a
report attesting a clean run of a design that was never built here, in a
directory a reader takes as evidence about this one.

MEASURED before writing this, over `benchmark-data/`:

    *_one_shot.json found                364
    carrying a `project` field           303
    naming a DIFFERENT project tree       61   (20 %)

across sha256, edge_llm_matmul_accel, u_hawaii_adc and others, with both PASS
and FAIL verdicts among them. So this is not one stray file.

WHY AN EXISTING GATE DOES NOT COVER IT
======================================
`agent_report_presence_check` asks whether the final report EXISTS.
`agent_report_sha256_attestation_check` asks whether it carries a SHA256 table
for every canonical artefact. Both are about the report's CONTENT. Neither asks
the prior question — whether this report is about this project at all — and a
foreign report can satisfy both perfectly, because it was a complete, honest
report of a different run.

WHAT IS COMPARED
================
The `project` field, resolved, against the directory the report sits under —
the path above `reports/`. Both sides are `Path.resolve()`d, so a symlinked or
relative spelling of the same tree is not a finding.

Reports with NO `project` field are counted and reported as UNATTRIBUTED but do
not fail: a report that never claimed a project is not lying about one, and
promoting that to a failure would be a different (and much larger) change.

Exit: 0 = every attributed report belongs here, 1 = at least one is foreign,
2 = nothing could be checked (no reports found — never a pass).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

#: Runner reports that record their project. The `*_one_shot.json` family is the
#: orchestrator's own output; a glob rather than a list so a new runner is
#: covered on arrival instead of being invisible until someone adds it.
REPORT_GLOB = "**/*_one_shot.json"


def _project_root_of(report: Path) -> Optional[Path]:
    """The project a report SITS IN — the directory above its `reports/`.

    Returns None when the report is not under a `reports/` directory, which
    means this program cannot say where it belongs; that is reported as
    undecidable rather than guessed.
    """
    parts = report.parts
    if "reports" not in parts:
        return None
    return Path(*parts[:parts.index("reports")])


def audit(project: Path) -> Tuple[List[Dict[str, object]], Dict[str, int]]:
    """(findings, stats) over every runner report under `project`."""
    findings: List[Dict[str, object]] = []
    stats = {"reports": 0, "attributed": 0, "unattributed": 0,
             "undecidable": 0, "foreign": 0}

    for rp in sorted(project.glob(REPORT_GLOB)):
        if not rp.is_file():
            continue
        stats["reports"] += 1
        try:
            doc = json.loads(rp.read_text(encoding="utf-8", errors="replace"))
        except Exception:                                    # noqa: BLE001
            stats["undecidable"] += 1
            continue
        if not isinstance(doc, dict):
            stats["undecidable"] += 1
            continue

        claimed = doc.get("project")
        if not claimed or not isinstance(claimed, str):
            stats["unattributed"] += 1
            continue
        stats["attributed"] += 1

        owner = _project_root_of(rp)
        if owner is None:
            stats["undecidable"] += 1
            continue

        try:
            same = Path(claimed).resolve() == owner.resolve()
        except OSError:
            stats["undecidable"] += 1
            continue

        if not same:
            stats["foreign"] += 1
            findings.append({
                "report": str(rp),
                "claims_project": claimed,
                "sits_in": str(owner),
                "verdict": doc.get("verdict"),
            })

    return findings, stats


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project", nargs="?", default=".")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args(argv)

    root = Path(args.project).resolve()
    findings, stats = audit(root)

    # DENOMINATOR FIRST, on its own line. "0 foreign reports" over a tree with
    # no reports in it is not the same fact as "0 foreign reports" over 303, and
    # a verdict line carrying the count would be comparing differently on every
    # tree (the lesson from waveform_artifact_hygiene_check in v1.9.0).
    print(f"examined {stats['reports']} runner report(s) under {str(root)!r}: "
          f"{stats['attributed']} attributed, {stats['unattributed']} "
          f"unattributed, {stats['undecidable']} undecidable")

    for f in findings:
        print(f"  FOREIGN  {f['report']}")
        print(f"      claims project : {f['claims_project']}")
        print(f"      sits in        : {f['sits_in']}")
        print(f"      carries verdict: {f['verdict']}")

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps({"findings": findings, "stats": stats,
                        "verdict": "FAIL" if findings else "PASS"},
                       indent=2) + "\n", encoding="utf-8")

    if stats["reports"] == 0:
        print("VACUOUS_PASS — no runner report was found, so nothing was "
              "checked. This is not a clean result.", file=sys.stderr)
        return 2

    print(f"{'FAIL' if findings else 'PASS'} — "
          f"{len(findings)} report(s) belong to another project")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
