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
  A4_CORNER_MARGIN_FAIL    — the nominal corner is in-spec but a REAL
                              process/temp corner is outside the spec
                              window (#185): the sweep is graded on its
                              WORST corner, not the nominal/best one.

This is a per-block companion to `analog_corner_sweep_check.py`
(which is project-wide and stricter on min-corner-count + MC yield).
The new gate is per-block + lighter so the runner can flip a block
WAIVED → PASS when the agent has emitted real corner data, even
before the project has a complete 9-corner Monte-Carlo set.

VACUOUS_PASS when no analog block list exists at ANY of
`phase3/analog/` (what the runner writes), `phase1/analog/` (what every
A-step's `condition:` pins) or the legacy top-level `analog/` — or when the
list that IS there declares no blocks.

INCOMPLETE (rc=1) in project mode when SOME declared blocks have a
corner_results.json and others have none: a PVT sweep run for a subset
of the declared blocks does not certify A4 done. All blocks missing
stays VACUOUS_PASS (defer to `ams-sim`).

Artefact resolution probes EVERY analog root, canonical runner dir first,
then the flow-declared phase dir, then the rest: the runner writes
`phase3/analog/<block>/`, the flow declares `phase2/analog/<block>/`, and
`migrate_to_layout_p.py` relocates a whole pre-v2 block dir to
`phase2/analog/<block>/` regardless of which step owns each file in it.

chip-AGNOSTIC.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Optional

from _analog_a_check_common import (
    load_block_list, select_blocks, make_argparser, vacuous_pass,
    no_block_list_reason,
    artefact_missing_for_block, emit_pass, emit_fail, emit_incomplete,
    resolve_block_artefact,
)

GATE = "analog_a4_corner_sweep_check"
SKILL = "ams-sim"
DECLARED_PHASE = 2


def _worst_corner_margin_fail(data: dict, corners: list) -> Optional[dict]:
    """#185 — a corner sweep must be graded on its WORST corner, not the
    nominal/best one. Return the worst offending corner ({name,value,rel_error,
    tol}) when the NOMINAL corner is IN-spec (so this is a genuine PVT-margin
    failure, NOT a template/env mismatch that v1.6.228 legitimately reports
    informationally) but a REAL-simulated process/temp corner falls OUTSIDE the
    spec window; else None.

    Only REAL (`simulator_run: true`) corners are graded — a DERIVED
    arithmetic-spread corner is not a measurement. chip-AGNOSTIC: keyed on the
    spec target center + per-corner value, never a chip name."""
    # spec target center + tolerance (a fraction, matching the corner `margin`).
    target = tol = None
    for s in (data.get("spec_results") or []):
        if isinstance(s, dict) and s.get("target") is not None:
            target, tol = s.get("target"), s.get("tolerance_pct")
            break
    try:
        target = float(target)
        tol = float(tol)
    except (TypeError, ValueError):
        return None                          # no gradable numeric target → skip
    if target == 0:
        return None

    def _val(c):
        for k in ("vout_v", "value"):
            if isinstance(c, dict) and c.get(k) is not None:
                return c.get(k)
        return None

    def _rel(v):
        try:
            return abs(float(v) - target) / abs(target)
        except (TypeError, ValueError):
            return None

    # The nominal (tt@27C sized point) — the env/template-mismatch guard. When the
    # nominal itself is out of spec, the sweep is an environmental modelling gap
    # (v1.6.228), not a corner-margin failure — do NOT newly FAIL it here.
    nominal_name = (data.get("best_corner") or {}).get("name")
    nominal = next((c for c in corners if isinstance(c, dict)
                    and c.get("name") == nominal_name), None)
    if nominal is None:
        return None                          # can't isolate the nominal → skip
    nom_rel = _rel(_val(nominal))
    if nom_rel is None or nom_rel > tol:
        return None                          # nominal out-of-spec → env-gap path

    worst = None
    for c in corners:
        if not isinstance(c, dict) or c is nominal:
            continue
        if c.get("simulator_run") is not True:
            continue                         # DERIVED corner — not a measurement
        rel = _rel(_val(c))
        if rel is None or rel <= tol:
            continue
        if worst is None or rel > worst["rel_error"]:
            worst = {"name": c.get("name"), "value": _val(c),
                     "rel_error": rel, "tol": tol}
    return worst


def _check_block(project: Path, block: str
                 ) -> tuple[Optional[str], List[dict]]:
    path, found = resolve_block_artefact(
        project, block, "corner_results.json", DECLARED_PHASE)
    rel = str(path.relative_to(project)) if found \
        else f"analog/{block}/corner_results.json"
    if not found:
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
    # #185 — WORST-corner gate: the best-corner spec_status can PASS while a real
    # process/temp corner is outside the spec window. Grade the worst REAL corner
    # (the helper applies the nominal-in-spec env-gap guard + only-real rule, and
    # works on the emitted corners[] + spec target so it also covers legacy
    # artifacts that carry no explicit `worst_corner`).
    wc = _worst_corner_margin_fail(data, corners)
    if isinstance(wc, dict) and wc.get("name"):
        return "FAIL", [{
            "block": block, "rule": "A4_CORNER_MARGIN_FAIL",
            "rel_path": rel,
            "detail": (f"worst REAL corner {wc['name']} value={wc.get('value')} "
                       f"is outside the spec window (rel error "
                       f"{wc.get('rel_error'):.4f} > tol {wc.get('tol')}) while "
                       f"the nominal corner is in-spec — a genuine PVT-margin "
                       f"failure the best-corner view hid (#185)"),
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
    if missing_seen:
        # Mixed PASS + missing. Until v1.7.36 this fell through to
        # emit_pass, certifying A4 done while a declared block never had
        # a PVT sweep run at all.
        return emit_incomplete(GATE, args, missing_seen, summary, SKILL)
    return emit_pass(GATE, args, summary)


if __name__ == "__main__":
    sys.exit(main())
