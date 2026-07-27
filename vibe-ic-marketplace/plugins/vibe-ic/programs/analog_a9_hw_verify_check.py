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

Project-mode tiers (no --block), in the order they are decided:

  rc 1  FAIL          a measured block's artefact is unparsable / evidence-free
  rc 0  VACUOUS_PASS  NO declared block was measured — a simulation-only close,
                      which is legal by design (a headless / CI analog run must
                      stay passable). Disclosed by PRINTING `VACUOUS_PASS:` and
                      exiting 0, which `flow_compliance_check` reads in both its
                      required and optional gate slots.
  rc 1  INCOMPLETE    SOME declared blocks were measured and others were not.
                      A bench demonstrably existed, so the unmeasured blocks are
                      unmeasured WORK, not a disclosed capability gap.
  rc 0  PASS          every declared block measured and sane.

VACUOUS_PASS also when `phase3/analog/analog_block_list.json` is missing or
empty. chip-AGNOSTIC.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Optional

from _analog_a_check_common import (
    load_block_list, select_blocks, make_argparser, vacuous_pass,
    artefact_missing_for_block, emit_pass, emit_fail, emit_incomplete,
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
                            f"hw_measurements.json; defer to skill "
                            f"`{SKILL}`.")
    # PARTIAL COVERAGE — the same hole v1.7.49 (A5) and v1.7.51 (A1-A4) closed,
    # which A9 was left out of. Measured on main before this line existed:
    #
    #     3 declared blocks, 1 with hw_measurements.json
    #     -> `PASS: analog_a9_hw_verify_check — 1/3 block(s) clean`, rc 0
    #
    # i.e. the gate stated "1/3" on the same line it certified the step done,
    # and emitted NO disclosure token — so A9's flow step read a bare PASS while
    # two declared blocks had no bench evidence at all. That is the exact shape
    # the disclosure wired in v1.7.46 exists to prevent.
    #
    # This tier is deliberately NOT the VACUOUS_PASS above. All-blocks-missing
    # means no bench was available and the gate has nothing applicable to judge
    # — a disclosed capability gap. Some-blocks-missing means a bench WAS
    # available (one block came off it) and the rest were simply not measured:
    # unmeasured work, which cannot certify the step done. The flow declaration
    # cannot compensate — A9's required_outputs is a single glob
    # (`analog/*/hw_measurements.json`) that one matching block satisfies, so
    # per-block coverage is knowable only here.
    if missing_seen:
        return emit_incomplete(GATE, args, missing_seen, summary, SKILL)
    return emit_pass(GATE, args, summary)


if __name__ == "__main__":
    sys.exit(main())
