#!/usr/bin/env python3
"""analog_a9_hw_verify_check.py — A9 deterministic gate (Co-Sim / HW Verify).

Verifies that the upstream `analog-hw-measure` (HIL) / `mixed-signal-cosim`
skills have emitted the canonical per-block A9 artefact:

    analog/<block>/hw_measurements.json

with substance:

  * file is JSON-parsable
  * declares some evidence-of-attempt: at least one of
    `scope_capture`, `adc_read`, `instrument`, `host_8hd_d`,
    `measurement_count`, or `measurements`
  * has at least one numerical measurement — accepts either of:
      (a) `measurements` dict with ≥ 1 numeric value, OR
      (b) `raw_list_for_humans` list with ≥ 1 entry that has
          `hw_value` (number).

This gate is intentionally LIGHT — it only checks A9 was attempted +
emitted real numbers.  Strict SPICE-vs-HIL correlation lives in the
existing `analog_hw_spice_correlation_check.py`; mixed-signal co-sim
depth lives in `mixed_signal_cosim` gates.

Failure rules:
  A9_HW_MEAS_MISSING       — hw_measurements.json absent
  A9_HW_MEAS_INVALID_JSON  — present but unparsable
  A9_HW_MEAS_NO_EVIDENCE   — no scope_capture / adc_read / instrument
                              / measurement_count keys
  A9_HW_MEAS_NO_NUMERICS   — no numeric measurement entries

Project-level verdicts (no `--block`):
  VACUOUS_PASS — no `analog_block_list.json` under `phase3/analog/` or
                 `phase1/analog/`, or it declares no blocks; or NO declared
                 block carries bench data at all. That last tier is the
                 deliberate simulation-only close: headless and CI analog
                 runs must remain possible, and they are DISCLOSED rather
                 than reported as a bench-verified PASS.
  INCOMPLETE   — SOME declared blocks carry bench data and others carry none
                 (exit 1). Such a run used to print "PASS: 1/N block(s)
                 clean", byte-identical in verdict to an N/N bench-verified
                 close; the gate now names the unmeasured blocks.
  PASS         — every declared block carries a substantive measurement.
chip-AGNOSTIC.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Optional

from _analog_a_check_common import (
    BLOCK_LIST_ABSENT_REASON,
    load_block_list, select_blocks, make_argparser, vacuous_pass,
    artefact_missing_for_block, emit_pass, emit_fail,
    emit_incomplete,
)

GATE = "analog_a9_hw_verify_check"
SKILL = "analog-hw-measure"

_EVIDENCE_KEYS = (
    "scope_capture", "adc_read", "instrument", "host_8hd_d",
    "measurement_count", "measurements", "raw_list_for_humans",
)


def _has_numeric_measurement(data: dict) -> bool:
    measurements = data.get("measurements")
    if isinstance(measurements, dict):
        for v in measurements.values():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return True
    raw = data.get("raw_list_for_humans")
    if isinstance(raw, list):
        for e in raw:
            if isinstance(e, dict):
                for k in ("hw_value", "value", "measured"):
                    v = e.get(k)
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        return True
    return False


def _check_block(project: Path, block: str
                 ) -> tuple[Optional[str], List[dict]]:
    path = project / "phase3" / "analog" / block / "hw_measurements.json"
    rel = (str(path.relative_to(project)) if path.exists()
           else f"analog/{block}/hw_measurements.json")
    if not path.is_file():
        return "MISSING", [{
            "block": block, "rule": "A9_HW_MEAS_MISSING",
            "rel_path": rel, "detail": "hw_measurements.json not found",
        }]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return "FAIL", [{
            "block": block, "rule": "A9_HW_MEAS_INVALID_JSON",
            "rel_path": rel, "detail": f"unparsable: {exc}",
        }]
    if not isinstance(data, dict) or not data:
        return "FAIL", [{
            "block": block, "rule": "A9_HW_MEAS_INVALID_JSON",
            "rel_path": rel, "detail": "top-level not a JSON object",
        }]
    if not any(k in data for k in _EVIDENCE_KEYS):
        return "FAIL", [{
            "block": block, "rule": "A9_HW_MEAS_NO_EVIDENCE",
            "rel_path": rel,
            "detail": (f"no evidence keys present (need any of "
                       f"{list(_EVIDENCE_KEYS)})"),
        }]
    if not _has_numeric_measurement(data):
        return "FAIL", [{
            "block": block, "rule": "A9_HW_MEAS_NO_NUMERICS",
            "rel_path": rel,
            "detail": ("no numeric measurement found in "
                       "`measurements` or `raw_list_for_humans`"),
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
                            f"hw_measurements.json; defer to skill "
                            f"`{SKILL}`; the hardware bench is external to "
                            f"this run.", reason_class="EXTERNAL")
    if missing_seen:
        # PARTIAL block coverage — see the A7 note. This is the tier A9's own
        # flow entry says it exists to differentiate: "a simulation-only close
        # stays legal ... but stops being reported as an undifferentiated
        # PASS". Only the ALL-missing tier was differentiated (VACUOUS_PASS,
        # above). A project with bench data for 1 of N declared blocks still
        # printed "PASS: 1/N block(s) clean" — byte-identical in verdict to an
        # N/N bench-verified close. INCOMPLETE names the unmeasured blocks
        # instead. The sim-only close is untouched: no bench data anywhere
        # still takes the VACUOUS_PASS above.
        return emit_incomplete(GATE, args, missing_seen, summary, SKILL)
    return emit_pass(GATE, args, summary)


if __name__ == "__main__":
    sys.exit(main())
