#!/usr/bin/env python3
"""
analog_per_block_pv_completeness_check.py — strict per-block deliverable
completeness gate for the analog A1-A9 track.

Complements `analog_a6_block_pv_check` (the A6 per-block DRC+LVS
verification gate): this gate enforces that EVERY analog block listed in
`analog/analog_block_list.json` ships the full per-block PV deliverable
set on disk:

    analog/<block>/spec.json           (extracted A1 spec)
    analog/<block>/topology.md         (A2 topology choice)
    analog/<block>/<block>.sp          (A3 SPICE netlist)
    analog/<block>/corner_results.json (A4 PVT corner sweep)
    analog/<block>/layout.mag          (A5 Magic layout)
    analog/<block>/<block>.gds         (A5 streamed GDS)
    analog/<block>/drc_clean.flag      (A6 DRC clean marker)
    analog/<block>/lvs_match.flag      (A6 LVS match marker)
    analog/<block>/pre_vs_post.json    (A7 post-layout resim diff)

Real-world inspiration: phase2+3_v10619 shipped this exact set across
6 blocks; phase2+3_v10619-vendor shipped only an A8 packaging for
ldo_default and skipped per-block PV. Both projects passed the wider
flow_compliance audit, but only one had the structural depth this
gate enforces. v1.6.24 promotes that depth from convention to gate.

VACUOUS_PASS contract (Wave 93):
  * No `analog/analog_block_list.json` → digital-only project, gate
    inapplicable. Emit VACUOUS_PASS, exit 0.
  * Empty `blocks: []` array → same.

Usage:
    python3 analog_per_block_pv_completeness_check.py <project_dir> [--json <out>]

Exit codes:
    0  PASS / VACUOUS_PASS / WAIVED
    1  one or more blocks missing required deliverables
    2  argument or I/O error

chip-AGNOSTIC. No vendor / IC / pin / byte / specific block-name
hardcoded. Block names come from `analog_block_list.json`.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)


# Per-block deliverable file patterns. `<block>` is the placeholder for
# the block name; rendered via str.format. Order is A1→A7 to match the
# canonical analog flow order so a partial-progress project surfaces
# the earliest gap first in the findings list.
_REQUIRED_PER_BLOCK = (
    "spec.json",                # A1
    "topology.md",               # A2
    "{block}.sp",               # A3
    "corner_results.json",       # A4
    "layout.mag",                # A5
    "{block}.gds",              # A5
    "drc_clean.flag",            # A6
    "lvs_match.flag",            # A6
    "pre_vs_post.json",          # A7
)


@dataclass
class BlockFinding:
    block: str
    missing: List[str] = field(default_factory=list)


def _load_block_list(project: Path) -> Optional[List[str]]:
    """Return the list of block names from analog_block_list.json, or
    None when the file is missing (digital-only project)."""
    path = project / "phase3" / "analog" / "analog_block_list.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    blocks = data.get("blocks") or []
    out: List[str] = []
    for entry in blocks:
        if isinstance(entry, str) and entry:
            out.append(entry)
        elif isinstance(entry, dict):
            name = entry.get("name") or entry.get("block")
            if isinstance(name, str) and name:
                out.append(name)
    return out


def _check_block(project: Path, block: str) -> BlockFinding:
    bdir = project / "phase3" / "analog" / block
    finding = BlockFinding(block=block)
    if not bdir.is_dir():
        finding.missing.append(f"<directory analog/{block}/>")
        return finding
    for pattern in _REQUIRED_PER_BLOCK:
        rel = pattern.format(block=block)
        if not (bdir / rel).exists():
            finding.missing.append(rel)
    return finding


def audit(project: Path) -> tuple[str, List[BlockFinding]]:
    blocks = _load_block_list(project)
    if blocks is None or not blocks:
        return "VACUOUS_PASS", []
    findings = [_check_block(project, b) for b in blocks]
    incomplete = [f for f in findings if f.missing]
    return ("FAIL" if incomplete else "PASS"), findings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Strict per-block analog PV deliverable completeness.")
    ap.add_argument("project_dir")
    ap.add_argument("--json", help="write JSON report to this path")
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"error: project dir not found: {project}", file=sys.stderr)
        return 2

    verdict, findings = audit(project)
    incomplete = [f for f in findings if f.missing]

    report = {
        "gate": "analog_per_block_pv_completeness_check",
        "verdict": verdict,
        "project": str(project),
        "blocks_total": len(findings),
        "blocks_complete": len(findings) - len(incomplete),
        "blocks_incomplete": len(incomplete),
        "required_per_block": list(_REQUIRED_PER_BLOCK),
        "findings": [asdict(f) for f in findings],
    }
    if verdict == "VACUOUS_PASS":
        report["reason"] = ("phase3/analog/analog_block_list.json missing or "
                            "empty; gate inapplicable to digital-only "
                            "projects.")

    if args.json:
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out_path, json.dumps(report, indent=2) + "\n")

    if verdict == "VACUOUS_PASS":
        print(f"VACUOUS_PASS: {report['reason']}")
        return 0
    if verdict == "PASS":
        print(f"PASS: all {len(findings)} analog block(s) ship the full "
              f"per-block PV deliverable set "
              f"({len(_REQUIRED_PER_BLOCK)} files each)")
        return 0
    print(f"FAIL: {len(incomplete)}/{len(findings)} analog block(s) "
          f"missing PV deliverables:", file=sys.stderr)
    for f in incomplete:
        print(f"  [{f.block}] missing: {', '.join(f.missing[:6])}"
              f"{' …' if len(f.missing) > 6 else ''}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
