#!/usr/bin/env python3
"""analog_a2_topology_select_check.py — A2 deterministic gate (v1.6.35).

Verifies that the upstream `analog-topology-select` skill has emitted
the canonical per-block A2 artefact:

    analog/<block>/topology.md

with substance:

  * file size ≥ 200 bytes (a placeholder line is < 50 bytes)
  * names at least one transistor / circuit primitive (chip-AGNOSTIC
    keyword panel: 'pmos', 'nmos', 'transistor', 'mirror',
    'cascode', 'differential', 'amplifier', 'topology selected',
    'opamp', 'op-amp', 'common-source', 'common-gate',
    'source-follower', 'comparator', 'bandgap', 'oscillator',
    'reference', 'driver', 'switch', 'capacitor', 'resistor',
    'inductor', 'load', 'bias', 'pole', 'zero', 'feedback',
    'open-loop', 'closed-loop', 'stage'). Lower-cased substring.

Failure rules:
  A2_TOPOLOGY_MISSING       — topology.md absent
  A2_TOPOLOGY_EMPTY         — present but < 200 bytes (placeholder)
  A2_TOPOLOGY_NO_PRIMITIVE  — present but lists no primitive

VACUOUS_PASS when no `analog_block_list.json` exists under
`phase3/analog/` (the analog runner's root) or `phase1/analog/` (the
root every A-step's flow `condition:` names), or it declares no blocks.

INCOMPLETE (rc=1) in project mode when SOME declared blocks have a
topology.md and others have none: A2 cannot be certified done while a
declared block has produced nothing. All blocks missing stays
VACUOUS_PASS (defer to the skill).

Artefact resolution: `phase3/analog/<block>/topology.md` (what the analog
runner writes) OR `phase2/analog/<block>/topology.md` (what the flow
declares as A2's required_output).

Exit codes / CLI: see `analog_a1_spec_extract_check.py`.
chip-AGNOSTIC — keyword panel is generic analog vocabulary.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

from _analog_a_check_common import (
    BLOCK_LIST_ABSENT_REASON,
    load_block_list, select_blocks, make_argparser, vacuous_pass,
    artefact_missing_for_block, emit_pass, emit_fail, emit_incomplete,
    resolve_block_artefact,
)

GATE = "analog_a2_topology_select_check"
SKILL = "analog-topology-select"
MIN_BYTES = 200
DECLARED_PHASE = 2

_PRIMITIVE_KEYWORDS_LC: tuple[str, ...] = (
    "pmos", "nmos", "transistor", "mirror", "cascode", "differential",
    "amplifier", "topology selected", "opamp", "op-amp",
    "common-source", "common-gate", "source-follower", "comparator",
    "bandgap", "oscillator", "reference", "driver", "switch",
    "capacitor", "resistor", "inductor", "load", "bias",
    "pole", "zero", "feedback", "open-loop", "closed-loop", "stage",
    "brokaw", "widlar", "wilson", "ldo", "regulator", "charge pump",
    "ring oscillator", "rc oscillator", "bjt",
)


def _check_block(project: Path, block: str
                 ) -> tuple[Optional[str], List[dict]]:
    path, found = resolve_block_artefact(
        project, block, "topology.md", DECLARED_PHASE)
    if not found:
        return "MISSING", [{
            "block": block, "rule": "A2_TOPOLOGY_MISSING",
            "rel_path": str(path.relative_to(project)),
            "detail": "topology.md not found",
        }]
    try:
        size = path.stat().st_size
        text = path.read_text(encoding="utf-8", errors="replace").lower()
    except OSError as exc:
        return "FAIL", [{
            "block": block, "rule": "A2_TOPOLOGY_EMPTY",
            "rel_path": str(path.relative_to(project)),
            "detail": f"OSError: {exc}",
        }]
    if size < MIN_BYTES:
        return "FAIL", [{
            "block": block, "rule": "A2_TOPOLOGY_EMPTY",
            "rel_path": str(path.relative_to(project)),
            "detail": f"{size}B < min {MIN_BYTES}B (placeholder?)",
        }]
    hits = [kw for kw in _PRIMITIVE_KEYWORDS_LC if kw in text]
    if not hits:
        return "FAIL", [{
            "block": block, "rule": "A2_TOPOLOGY_NO_PRIMITIVE",
            "rel_path": str(path.relative_to(project)),
            "detail": "no transistor/primitive keyword found "
                      "(panel = pmos|nmos|mirror|cascode|opamp|...)",
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
                            BLOCK_LIST_ABSENT_REASON)

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
                            f"topology.md; defer to skill `{SKILL}`.")
    if missing_seen:
        # Mixed PASS + missing. Until v1.7.36 this fell through to
        # emit_pass, certifying A2 done on partial block coverage.
        return emit_incomplete(GATE, args, missing_seen, summary, SKILL)
    return emit_pass(GATE, args, summary)


if __name__ == "__main__":
    sys.exit(main())
