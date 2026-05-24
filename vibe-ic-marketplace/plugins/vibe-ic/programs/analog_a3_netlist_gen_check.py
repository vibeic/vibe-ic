#!/usr/bin/env python3
"""analog_a3_netlist_gen_check.py — A3 deterministic gate (v1.6.35).

Verifies that the upstream `analog-netlist-gen` skill has emitted the
canonical per-block A3 artefact:

    analog/<block>/<block>.sp

with substance:

  * file size ≥ 200 bytes (the v1.6.30 substance threshold for .sp;
    a placeholder `* netlist stub\\n.end\\n` is < 50 bytes).
  * contains a `.subckt` / `.SUBCKT` declaration (the canonical
    SPICE module wrapper). Without this, the file is at best a
    raw stimulus file, not a reusable analog block netlist.

Failure rules:
  A3_NETLIST_MISSING        — <block>.sp absent
  A3_NETLIST_TOO_SMALL      — < 200 bytes
  A3_NETLIST_NO_SUBCKT      — no .subckt declaration

Note: this is a thin wrapper aligned with
`analog_artefact_substance_check`'s .sp size rule, plus the additional
`.subckt` semantic check.

VACUOUS_PASS when `analog/analog_block_list.json` is missing or empty.

chip-AGNOSTIC.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List, Optional

from _analog_a_check_common import (
    load_block_list, select_blocks, make_argparser, vacuous_pass,
    artefact_missing_for_block, emit_pass, emit_fail,
)

GATE = "analog_a3_netlist_gen_check"
SKILL = "analog-netlist-gen"
MIN_BYTES = 200

_SUBCKT_RE = re.compile(r"(?im)^\s*\.subckt\s+\S+")


def _check_block(project: Path, block: str
                 ) -> tuple[Optional[str], List[dict]]:
    path = project / "phase3" / "analog" / block / f"{block}.sp"
    if not path.is_file():
        return "MISSING", [{
            "block": block, "rule": "A3_NETLIST_MISSING",
            "rel_path": str(path.relative_to(project)),
            "detail": f"{block}.sp not found",
        }]
    try:
        size = path.stat().st_size
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return "FAIL", [{
            "block": block, "rule": "A3_NETLIST_TOO_SMALL",
            "rel_path": str(path.relative_to(project)),
            "detail": f"OSError: {exc}",
        }]
    if size < MIN_BYTES:
        return "FAIL", [{
            "block": block, "rule": "A3_NETLIST_TOO_SMALL",
            "rel_path": str(path.relative_to(project)),
            "detail": f"{size}B < min {MIN_BYTES}B (placeholder?)",
        }]
    if not _SUBCKT_RE.search(text):
        return "FAIL", [{
            "block": block, "rule": "A3_NETLIST_NO_SUBCKT",
            "rel_path": str(path.relative_to(project)),
            "detail": "no `.subckt <name>` declaration found",
        }]
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
                            f"<block>.sp; defer to skill `{SKILL}`.")
    return emit_pass(GATE, args, summary)


if __name__ == "__main__":
    sys.exit(main())
