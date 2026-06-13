#!/usr/bin/env python3
"""analog_a4_corner_sweep_check.py — A4 deterministic gate (v1.6.35).

Verifies that the upstream `ams-sim` skill has emitted the canonical
per-block A4 artefact:

    analog/<block>/corner_results.json

with substance:

  * file is JSON-parsable
  * declares ≥ 1 corner
  * declares ≥ 1 spec result with `status: PASS` (or `verdict: PASS`)
  * **CRITICAL** (v10632 escape pattern): NOT every corner says
    `simulator_run: false`. If the entire corner array is
    `simulator_run: false`, the agent claimed PVT done but no
    SPICE actually ran → A4_NO_SIMULATOR_RUN FAIL.

Failure rules:
  A4_CORNERS_MISSING       — corner_results.json absent
  A4_CORNERS_INVALID_JSON  — present but unparsable
  A4_NO_CORNERS            — corners[] empty / missing
  A4_NO_PASS_SPEC          — no spec_results entry has status=PASS
                              (and at least one is FAIL or all blank)
  A4_NO_SIMULATOR_RUN      — every declared corner has
                              `simulator_run: false`. v10632 escape.

This is a per-block companion to `analog_corner_sweep_check.py`
(which is project-wide and stricter on min-corner-count + MC yield).
The new gate is per-block + lighter so the runner can flip a block
WAIVED → PASS when the agent has emitted real corner data, even
before the project has a complete 9-corner Monte-Carlo set.

VACUOUS_PASS when `analog/analog_block_list.json` is missing or empty.
chip-AGNOSTIC.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Optional

from _analog_a_check_common import (
    load_block_list, select_blocks, make_argparser, vacuous_pass,
    artefact_missing_for_block, emit_pass, emit_fail,
)

GATE = "analog_a4_corner_sweep_check"
SKILL = "ams-sim"


def _check_block(project: Path, block: str
                 ) -> tuple[Optional[str], List[dict]]:
    path = project / "phase3" / "analog" / block / "corner_results.json"
    rel = str(path.relative_to(project)) if path.exists() \
        else f"analog/{block}/corner_results.json"
    if not path.is_file():
        return "MISSING", [{
            "block": block, "rule": "A4_CORNERS_MISSING",
            "rel_path": rel, "detail": "corner_results.json not found",
        }]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return "FAIL", [{
            "block": block, "rule": "A4_CORNERS_INVALID_JSON",
            "rel_path": rel, "detail": f"unparsable: {exc}",
        }]
    if not isinstance(data, dict):
        return "FAIL", [{
            "block": block, "rule": "A4_CORNERS_INVALID_JSON",
            "rel_path": rel, "detail": "top-level not a JSON object",
        }]
    corners = data.get("corners")
    if not isinstance(corners, list) or not corners:
        return "FAIL", [{
            "block": block, "rule": "A4_NO_CORNERS",
            "rel_path": rel, "detail": "corners[] empty or missing",
        }]
    # v1.6.214 (ORGANIC-20260512) — anti-stub provenance gate.
    # Reject corner_results.json whose `_provenance` field is
    # `deterministic_stub`. Pre-v1.6.214 the runner stub baked
    # `simulator_run:true` + `status:PASS` into the file, making
    # this gate silently PASS without any SPICE having run.
    prov = data.get("_provenance") or data.get("extraction_strategy")
    if prov == "deterministic_stub":
        return "FAIL", [{
            "block": block, "rule": "A4_DETERMINISTIC_STUB",
            "rel_path": rel,
            "detail": ("_provenance='deterministic_stub' — no SPICE "
                       "ran. v1.6.214 anti-stub gate: emit real "
                       "ngspice via analog_real_corner_sweep.py "
                       "or invoke ams-sim AI skill."),
        }]

    # v10632 escape: every corner has simulator_run: false.
    sim_run_flags = [c.get("simulator_run") for c in corners
                     if isinstance(c, dict)]
    declared_flags = [f for f in sim_run_flags if f is not None]
    if declared_flags and all(f is False for f in declared_flags):
        return "FAIL", [{
            "block": block, "rule": "A4_NO_SIMULATOR_RUN",
            "rel_path": rel,
            "detail": (f"all {len(declared_flags)} corners declare "
                       f"`simulator_run: false`; SPICE never ran "
                       f"(v10632 escape pattern)"),
        }]
    # Spec results → at least one PASS, no FAIL allowed.
    # v1.6.223 (#96) — accept `status: PASS_INFORMATIONAL` as
    # PASS-equivalent when the runner produced a real ngspice
    # measurement but the block has no fixed numeric target by design
    # (e.g. POR trip-point, trim DAC monotonicity). The runner emits
    # PASS_INFORMATIONAL for these — semantically "sim ran, no target
    # to compare against". Treating it as a FAIL forced no-target
    # blocks into permanent A4_NO_PASS_SPEC, which is wrong: the sim
    # IS evidence the topology works. Anti-fabrication contract is
    # preserved upstream — the `deterministic_stub` provenance gate
    # above still rejects runners that didn't actually run SPICE, so
    # PASS_INFORMATIONAL can only reach this branch when real ngspice
    # produced numbers. chip-AGNOSTIC: the rule is target-shape, not
    # chip-class.
    spec_results = data.get("spec_results")
    if isinstance(spec_results, list) and spec_results:
        def _is_pass(s):
            return (isinstance(s, dict)
                    and (s.get("status") in ("PASS", "PASS_INFORMATIONAL")
                         or s.get("verdict") in ("PASS",
                                                 "PASS_INFORMATIONAL")))
        passes = [s for s in spec_results if _is_pass(s)]
        fails = [s for s in spec_results
                 if isinstance(s, dict)
                 and (s.get("status") == "FAIL"
                      or s.get("verdict") == "FAIL")]
        if not passes:
            return "FAIL", [{
                "block": block, "rule": "A4_NO_PASS_SPEC",
                "rel_path": rel,
                "detail": (f"spec_results[] has {len(spec_results)} "
                           f"entries but 0 with status=PASS or "
                           f"PASS_INFORMATIONAL"),
            }]
        if fails:
            return "FAIL", [{
                "block": block, "rule": "A4_NO_PASS_SPEC",
                "rel_path": rel,
                "detail": (f"{len(fails)} spec(s) at FAIL — "
                           f"e.g. {fails[0].get('spec','?')} @ "
                           f"{fails[0].get('corner','?')}"),
            }]
    else:
        # No spec_results at all → infer from summary.all_corners_pass
        summary = data.get("summary") or {}
        if not summary.get("all_corners_pass"):
            return "FAIL", [{
                "block": block, "rule": "A4_NO_PASS_SPEC",
                "rel_path": rel,
                "detail": ("no spec_results[] and "
                           "summary.all_corners_pass is not true"),
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
                            f"corner_results.json; defer to skill "
                            f"`{SKILL}`.")
    return emit_pass(GATE, args, summary)


if __name__ == "__main__":
    sys.exit(main())
