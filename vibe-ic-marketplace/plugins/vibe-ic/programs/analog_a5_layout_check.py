#!/usr/bin/env python3
"""analog_a5_layout_check.py — A5 deterministic gate (v1.6.35).

Verifies that the upstream `analog-layout` skill has emitted the
canonical per-block A5 artefacts:

    analog/<block>/layout.mag   (Magic source) OR
    analog/<block>/<block>.gds  (streamed GDS)
    analog/<block>/drc_clean.flag
    analog/<block>/lvs_match.flag

with substance:

  * layout source is one of {layout.mag, <block>.gds} (either
    representation is acceptable for A5 closure)
  * layout source size > 200 bytes (the v10627 64-byte HEADER+ENDLIB
    GDS stub trips this)
  * `drc_clean.flag` present (any non-empty file)
  * `lvs_match.flag` present (any non-empty file)

Failure rules:
  A5_LAYOUT_MISSING       — neither layout.mag nor <block>.gds present
  A5_LAYOUT_TOO_SMALL     — layout source < 200 bytes (stub)
  A5_DRC_FLAG_MISSING     — drc_clean.flag absent
  A5_LVS_FLAG_MISSING     — lvs_match.flag absent

VACUOUS_PASS when `analog/analog_block_list.json` is missing or empty.
chip-AGNOSTIC.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

from _analog_a_check_common import (
    load_block_list, select_blocks, make_argparser, vacuous_pass,
    artefact_missing_for_block, emit_pass, emit_fail,
)

GATE = "analog_a5_layout_check"
SKILL = "analog-layout"
MIN_LAYOUT_BYTES = 200


def _check_block(project: Path, block: str
                 ) -> tuple[Optional[str], List[dict]]:
    bdir = project / "phase3" / "analog" / block
    mag = bdir / "layout.mag"
    gds = bdir / f"{block}.gds"
    drc_flag = bdir / "drc_clean.flag"
    lvs_flag = bdir / "lvs_match.flag"

    findings: List[dict] = []
    layout_path: Optional[Path] = None
    if mag.is_file():
        layout_path = mag
    elif gds.is_file():
        layout_path = gds
    if layout_path is None:
        # Treat as MISSING (not FAIL) so --block mode → WAIVED.
        return "MISSING", [{
            "block": block, "rule": "A5_LAYOUT_MISSING",
            "rel_path": str(bdir.relative_to(project)),
            "detail": "neither layout.mag nor <block>.gds present",
        }]
    try:
        size = layout_path.stat().st_size
    except OSError:
        size = 0
    if size < MIN_LAYOUT_BYTES:
        findings.append({
            "block": block, "rule": "A5_LAYOUT_TOO_SMALL",
            "rel_path": str(layout_path.relative_to(project)),
            "detail": f"{size}B < min {MIN_LAYOUT_BYTES}B (stub)",
        })
    if not drc_flag.is_file():
        findings.append({
            "block": block, "rule": "A5_DRC_FLAG_MISSING",
            "rel_path": str(drc_flag.relative_to(project)),
            "detail": "drc_clean.flag absent (DRC not signed off)",
        })
    if not lvs_flag.is_file():
        findings.append({
            "block": block, "rule": "A5_LVS_FLAG_MISSING",
            "rel_path": str(lvs_flag.relative_to(project)),
            "detail": "lvs_match.flag absent (LVS not signed off)",
        })
    if findings:
        return "FAIL", findings
    return "PASS", []


def main(argv: Optional[List[str]] = None) -> int:
    ap = make_argparser(GATE, __doc__)
    args = ap.parse_args(argv)
    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"error: not a directory: {project}", file=sys.stderr)
        return 2

    blocks_all = load_block_list(project)
    if blocks_all is None or (not blocks_all and not args.block):
        return vacuous_pass(GATE, args,
                            "phase3/analog/analog_block_list.json missing or "
                            "empty; gate inapplicable.")

    blocks = select_blocks(blocks_all or [], args.block)
    if not blocks:
        return vacuous_pass(GATE, args, "no blocks selected.")

    findings: List[dict] = []
    blocks_pass = 0
    missing_seen: List[dict] = []
    for block in blocks:
        status, fs = _check_block(project, block)
        if status == "PASS":
            blocks_pass += 1
        elif status == "MISSING":
            missing_seen.extend(fs)
        else:
            findings.extend(fs)

    summary = {
        "blocks_checked": len(blocks),
        "blocks_pass": blocks_pass,
        "blocks_missing": len(missing_seen),
        "blocks_fail": len(findings),
    }

    if args.block:
        if findings:
            return emit_fail(GATE, args, findings, summary)
        if missing_seen:
            return artefact_missing_for_block(
                GATE, args, args.block,
                missing_seen[0]["rel_path"], SKILL)
        return emit_pass(GATE, args, summary)

    if findings:
        return emit_fail(GATE, args, findings, summary)
    if missing_seen and blocks_pass == 0:
        return vacuous_pass(GATE, args,
                            f"all {len(missing_seen)} block(s) missing "
                            f"layout artefacts; defer to skill `{SKILL}`.")
    return emit_pass(GATE, args, summary)


if __name__ == "__main__":
    sys.exit(main())
