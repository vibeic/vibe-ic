#!/usr/bin/env python3
"""pvt_matrix_check.py — PVT-matrix substance gate (ORGANIC-20260606 #442).

The audited rot: Step 7 emitted `pvt_matrix.json` with `corners: []`
(single Liberty lib → empty discovery) and the existence-only gate still
counted it as a PVT matrix; downstream "multi-corner" sign-off then hung
off a matrix that names zero corners.

Rules (chip-AGNOSTIC — structural JSON shape only):
  * corners missing / not a list / EMPTY  → FAIL (an empty list is not a
    PVT matrix; say so instead of letting the filename carry the claim)
  * exactly 1 corner → exit 0 but verdict SINGLE_CORNER_ONLY — honest
    single-corner setup, must never be presented as multi-corner
  * >= 2 corners with distinct labels → MULTI_CORNER
  * a matrix that CLAIMS `multi_corner: true` with < 2 corners → FAIL
    (self-contradictory claim)

Exit codes: 0 = OK (incl. SINGLE_CORNER_ONLY), 1 = FAIL, 2 = no
pvt_matrix.json present (vacuous — the existence gate owns that).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_CANDIDATES = (
    "phase2/stage2/constraints/pvt_matrix.json",
    "constraints/pvt_matrix.json",
)


def audit(project: Path) -> dict:
    pvt_path = None
    for rel in _CANDIDATES:
        p = project / rel
        if p.is_file():
            pvt_path = p
            break
    if pvt_path is None:
        return {"verdict": "SKIP", "reason": "no pvt_matrix.json present",
                "rc": 2}
    try:
        data = json.loads(pvt_path.read_text(errors="replace"))
    except (OSError, ValueError):
        return {"verdict": "FAIL", "rc": 1,
                "reason": f"{pvt_path.name} unparseable"}
    corners = data.get("corners")
    if not isinstance(corners, list) or not corners:
        return {"verdict": "FAIL", "rc": 1,
                "corner_count": 0,
                "reason": ("corners is empty/missing — an empty list is "
                           "not a PVT matrix (#442); discover >=2 Liberty "
                           "corners or document single-corner explicitly")}
    labels = {str(c.get("label") or c.get("name") or i)
              for i, c in enumerate(corners) if isinstance(c, dict)}
    if data.get("multi_corner") is True and len(corners) < 2:
        return {"verdict": "FAIL", "rc": 1, "corner_count": len(corners),
                "reason": ("matrix claims multi_corner=true with "
                           f"{len(corners)} corner(s) — self-"
                           "contradictory claim (#442)")}
    if len(corners) < 2 or len(labels) < 2:
        return {"verdict": "SINGLE_CORNER_ONLY", "rc": 0,
                "corner_count": len(corners),
                "labels": sorted(labels),
                "reason": ("single corner — honest, but must never be "
                           "presented as multi-corner sign-off (#442)")}
    return {"verdict": "MULTI_CORNER", "rc": 0,
            "corner_count": len(corners), "labels": sorted(labels)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    if not args.project_dir.is_dir():
        print(f"ERROR: not a directory: {args.project_dir}", file=sys.stderr)
        return 2
    rep = audit(args.project_dir)
    rc = rep.pop("rc")
    rep = {"program": "pvt_matrix_check", "version": "1.0.0", **rep}
    out = json.dumps(rep, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    print(out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
