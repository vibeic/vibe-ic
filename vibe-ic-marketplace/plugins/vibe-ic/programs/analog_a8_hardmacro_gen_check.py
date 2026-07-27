#!/usr/bin/env python3
"""analog_a8_hardmacro_gen_check.py — A8 deterministic gate.

Verifies that the upstream `analog-hardmacro-gen` skill has emitted
the canonical per-block A8 artefact triple (LEF + Liberty + Verilog):

    analog/hardmacro/<block>/<block>.lef
    analog/hardmacro/<block>/<block>.lib
    analog/hardmacro/<block>/<block>.v

with substance (matching the v1.6.30 thresholds enforced by
`analog_artefact_substance_check`):

  * .lef ≥ 250 bytes
  * .lib ≥ 200 bytes
  * .v   ≥ 150 bytes
  * none of the three contains a v1.6.30 stub-marker phrase.

Failure rules:
  A8_HARDMACRO_LEF_MISSING    — analog/hardmacro/<block>/<block>.lef absent
  A8_HARDMACRO_LIB_MISSING    — .lib absent
  A8_HARDMACRO_V_MISSING      — .v absent
  A8_HARDMACRO_TOO_SMALL      — present but below per-ext threshold
  A8_HARDMACRO_STUB_MARKER    — file matches stub-marker panel
                                  (`ai_authored_methodology_stub`,
                                  `behavioral stub`, `placeholder
                                  hardmacro`, `do not tape out`, ...)

VACUOUS_PASS when `analog/analog_block_list.json` is missing or empty.
chip-AGNOSTIC.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

from _analog_a_check_common import (
    load_block_list, select_blocks, make_argparser, vacuous_pass,
    no_block_list_reason,
    artefact_missing_for_block, emit_pass, emit_fail,
)

GATE = "analog_a8_hardmacro_gen_check"
SKILL = "analog-hardmacro-gen"

# Per-ext thresholds (aligned with v1.6.30
# analog_artefact_substance_check defaults).
_MIN_BYTES = {".lef": 250, ".lib": 200, ".v": 150}

# Substring markers (lower-cased) — chip-AGNOSTIC. Mirrors the panel
# in `analog_artefact_substance_check._STUB_MARKERS_DEFAULT`.
_STUB_MARKERS = (
    "ai_authored_methodology_stub", "ai_authored_stub",
    "methodology_stub", "methodology placeholder",
    "behavioral stub", "behavioural stub",
    "placeholder netlist", "placeholder layout",
    "placeholder hardmacro",
    "stub: do not tape out", "do not tape out",
    "todo implement", "todo: implement",
    "__stub__", "@stub",
)


def _check_block(project: Path, block: str
                 ) -> tuple[Optional[str], List[dict]]:
    hdir = project / "phase3" / "analog" / "hardmacro" / block
    triples = (
        (".lef", hdir / f"{block}.lef", "A8_HARDMACRO_LEF_MISSING"),
        (".lib", hdir / f"{block}.lib", "A8_HARDMACRO_LIB_MISSING"),
        (".v",   hdir / f"{block}.v",   "A8_HARDMACRO_V_MISSING"),
    )
    findings: List[dict] = []
    missing_count = 0
    for ext, path, missing_rule in triples:
        if not path.is_file():
            findings.append({
                "block": block, "rule": missing_rule,
                "rel_path": str(path.relative_to(project))
                            if path.exists()
                            else f"analog/hardmacro/{block}/{block}{ext}",
                "detail": f"hardmacro {ext} not found",
            })
            missing_count += 1
            continue
        try:
            size = path.stat().st_size
            text = path.read_text(encoding="utf-8", errors="replace").lower()
        except OSError as exc:
            findings.append({
                "block": block, "rule": "A8_HARDMACRO_TOO_SMALL",
                "rel_path": str(path.relative_to(project)),
                "detail": f"OSError: {exc}",
            })
            continue
        if size < _MIN_BYTES[ext]:
            findings.append({
                "block": block, "rule": "A8_HARDMACRO_TOO_SMALL",
                "rel_path": str(path.relative_to(project)),
                "detail": f"{size}B < min {_MIN_BYTES[ext]}B for {ext}",
            })
        hits = [m for m in _STUB_MARKERS if m in text]
        if hits:
            findings.append({
                "block": block, "rule": "A8_HARDMACRO_STUB_MARKER",
                "rel_path": str(path.relative_to(project)),
                "detail": f"file matches stub marker(s): "
                          f"{', '.join(hits)}",
            })
    # All three missing → MISSING (per-block --block mode → WAIVED).
    if missing_count == 3:
        return "MISSING", findings
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
                            no_block_list_reason())

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
        "blocks_fail": len({f["block"] for f in findings}),
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
                            f"all blocks missing hardmacro triple; "
                            f"defer to skill `{SKILL}`.")
    return emit_pass(GATE, args, summary)


if __name__ == "__main__":
    sys.exit(main())
