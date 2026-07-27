#!/usr/bin/env python3
"""analog_a1_spec_extract_check.py — A1 deterministic gate (v1.6.35).

Verifies that the upstream `analog-spec-extract` skill has emitted the
canonical per-block A1 artefact:

    analog/<block>/spec.json

with substance:

  * file is JSON-parsable
  * declares ≥ 1 spec field — accepts either of two layouts:
      (a) `specs: [...]` list with at least one entry that has a
          `name` and at least one of {`min`, `typ`, `max`,
          `value`, `target`}.
      (b) flat dict carrying a recognisable spec key (`Vout`,
          `gain`, `bandwidth`, `psrr_db`, `tc_ppmpc`, `vref_v`,
          `iq_ua`, `iout_ma`, ...).

Failure rules:
  A1_SPEC_MISSING        — spec.json absent for the block
  A1_SPEC_INVALID_JSON   — spec.json present but unparsable
  A1_SPEC_EMPTY          — parsed but empty / no fields
  A1_SPEC_NO_FIELDS      — declares 0 spec entries

VACUOUS_PASS when no `analog_block_list.json` exists under
`phase3/analog/` (the analog runner's root) or `phase1/analog/` (the root
every A-step's flow `condition:` names), or it declares no blocks — the
project is digital-only / pre-A1.

INCOMPLETE (rc=1) in project mode when SOME declared blocks have a
spec.json and others have none: A1 cannot be certified done while a
declared block has produced nothing. All blocks missing stays
VACUOUS_PASS (defer to the skill).

Artefact resolution: `phase3/analog/<block>/spec.json` (what the analog
runner writes) OR `phase1/analog/<block>/spec.json` (what the flow
declares as A1's required_output).

Usage:
    python3 analog_a1_spec_extract_check.py <project_dir>
    python3 analog_a1_spec_extract_check.py <project_dir> --block ldo_default
    python3 analog_a1_spec_extract_check.py <project_dir> --json reports/gates/a1.json

Exit codes:
    0  PASS / VACUOUS_PASS
    1  FAIL (artefact present but stub / empty / unparsable)
       OR INCOMPLETE (project mode, partial block coverage)
    2  artefact missing in --block mode (runner translates → WAIVED)
       OR project_dir is not a directory.

chip-AGNOSTIC. No vendor / chip / block-name hardcoded.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Optional

from _analog_a_check_common import (
    BLOCK_LIST_ABSENT_REASON,
    load_block_list, select_blocks, make_argparser, vacuous_pass,
    artefact_missing_for_block, emit_pass, emit_fail, emit_incomplete,
    resolve_block_artefact,
)

GATE = "analog_a1_spec_extract_check"
SKILL = "analog-spec-extract"
# The flow declares A1's output at `phase1/analog/*/spec.json`; the analog
# runner writes it to the canonical `phase3/analog/<block>/`. Read both.
DECLARED_PHASE = 1

# Recognised flat-dict spec keys (chip-AGNOSTIC sample of common
# analog block performance specs across amp / regulator / timing /
# protection classes). Any one of these satisfies layout (b).
# Lower-cased substring match.
#
# v1.6.605 — extended the vocabulary so the check works across the
# full analog block taxonomy (POR / ESD / level-shifter / clamp),
# not just amp- and regulator-class blocks. Field evidence
# (mabrains LDO benchmark, 2026-05-23): pre-extension the check
# FAIL'd on `analog/por/spec.json` (`reset_delay_ms` + `vdd_high_V`
# + `internal_current_nA`) and `analog/esd/spec.json`
# (`series_resistor_ohm` + `clamp_type` + `vdd_high_domain_V`)
# despite those being the canonical performance specs for those
# block classes. Chip-AGNOSTIC: new tokens cover block CLASSES,
# never a specific chip.
_FLAT_SPEC_KEYS_LC = (
    # amplifier / regulator
    "vout", "vref", "gain", "bandwidth", "bw", "psrr",
    "cmrr", "iq", "iout", "tc_ppmpc", "ppmpc", "noise",
    "slew", "phase_margin", "pm_deg", "drop_v", "vdrop",
    # bandgap / reference
    "vbg", "vbgr",
    # timing (POR / oscillator / delay-line class)
    "delay", "reset_delay", "startup", "settling", "period",
    "frequency", "freq_hz",
    # protection (ESD / clamp class)
    "clamp", "series_resistor", "esd",
    # supply domains (multi-rail block class)
    "vdd_high", "vdd_low", "vin_min", "vin_max", "vin_nominal",
    # current spec
    "internal_current", "current_n", "iref",
    # load
    "iload", "load_range",
    # categorical descriptor fields that imply a real spec block
    "temperature_compensated", "clamp_type",
)


def _check_block(project: Path, block: str) -> tuple[Optional[str], List[dict]]:
    """Return (status, findings) where status is one of
    "PASS" | "MISSING" | "FAIL".  MISSING is per-block-only and
    becomes either WAIVED (--block mode) or a FAIL (project mode)."""
    spec_path, found = resolve_block_artefact(
        project, block, "spec.json", DECLARED_PHASE)
    if not found:
        return "MISSING", [{
            "block": block,
            "rule": "A1_SPEC_MISSING",
            "rel_path": str(spec_path.relative_to(project)),
            "detail": "spec.json not found",
        }]
    try:
        data = json.loads(spec_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return "FAIL", [{
            "block": block,
            "rule": "A1_SPEC_INVALID_JSON",
            "rel_path": str(spec_path.relative_to(project)),
            "detail": f"unparsable: {exc}",
        }]
    if not isinstance(data, dict) or not data:
        return "FAIL", [{
            "block": block,
            "rule": "A1_SPEC_EMPTY",
            "rel_path": str(spec_path.relative_to(project)),
            "detail": "spec.json is empty / not a JSON object",
        }]
    # Layout (a): specs: [...]
    specs = data.get("specs")
    if isinstance(specs, list):
        valid = [s for s in specs
                 if isinstance(s, dict) and s.get("name")
                 and any(k in s for k in ("min", "typ", "max",
                                           "value", "target"))]
        if valid:
            return "PASS", []
        return "FAIL", [{
            "block": block,
            "rule": "A1_SPEC_NO_FIELDS",
            "rel_path": str(spec_path.relative_to(project)),
            "detail": (f"specs[] present but 0 entries carry a "
                       f"name + numerical field "
                       f"(saw {len(specs)} entries)"),
        }]
    # Layout (b): flat dict — any recognisable spec key counts.
    keys_lc = {str(k).lower() for k in data.keys()}
    if any(any(needle in k for needle in _FLAT_SPEC_KEYS_LC)
           for k in keys_lc):
        return "PASS", []
    return "FAIL", [{
        "block": block,
        "rule": "A1_SPEC_NO_FIELDS",
        "rel_path": str(spec_path.relative_to(project)),
        "detail": (f"no `specs:[]` and no recognised flat spec key "
                   f"(saw keys: {sorted(keys_lc)[:6]}...)"),
    }]


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
        return vacuous_pass(GATE, args,
                            "no blocks selected after --block filter.")

    findings: List[dict] = []
    blocks_pass = 0
    missing_seen: List[dict] = []
    for block in blocks:
        status, fs = _check_block(project, block)
        if status == "PASS":
            blocks_pass += 1
        elif status == "MISSING":
            missing_seen.extend(fs)
        else:  # FAIL
            findings.extend(fs)

    summary = {
        "blocks_checked": len(blocks),
        "blocks_pass": blocks_pass,
        "blocks_missing": len(missing_seen),
        "blocks_fail": len(findings),
    }

    # --block mode: missing artefact → WAIVED (rc=2). Stub → FAIL (rc=1).
    if args.block:
        if findings:
            return emit_fail(GATE, args, findings, summary)
        if missing_seen:
            return artefact_missing_for_block(
                GATE, args, args.block,
                missing_seen[0]["rel_path"], SKILL)
        return emit_pass(GATE, args, summary)

    # Project mode: any FAIL → FAIL. All blocks missing → VACUOUS (the
    # skill has not run yet). SOME blocks missing → INCOMPLETE (rc=1):
    # the declared block list is the denominator, so a step cannot be
    # certified done while a declared block has no spec at all.
    if findings:
        return emit_fail(GATE, args, findings, summary)
    if missing_seen and blocks_pass == 0:
        # No PASSes, only missing → project-level VACUOUS so this gate
        # does not block flow_compliance_check; the runner / audit
        # surface WAIVED via per-block rc=2 in --block mode.
        return vacuous_pass(GATE, args,
                            f"all {len(missing_seen)} block(s) missing "
                            f"spec.json; defer to skill `{SKILL}`.")
    if missing_seen:
        # Mixed PASS + missing. Until v1.7.36 this fell through to
        # emit_pass, certifying A1 done on partial block coverage.
        return emit_incomplete(GATE, args, missing_seen, summary, SKILL)
    return emit_pass(GATE, args, summary)


if __name__ == "__main__":
    sys.exit(main())
