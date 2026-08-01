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
  A4_NETLIST_ABSENT        — the sweep declares simulated corners while
                              A3's declared output `<block>.sp` does not
                              exist, or the producer recorded BLOCKED on
                              A3. There is no design netlist behind the
                              measurement.
  A4_NETLIST_NOT_FROM_A3   — the artefact discloses a deck the sweep
                              program authored itself
                              (`netlist_provenance` != `a3_netlist`).
                              Real ngspice on a stand-in circuit measures
                              the template library, not the design.
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

VACUOUS_PASS when no `analog_block_list.json` exists under
`phase3/analog/` (the analog runner's root) or `phase1/analog/` (the
root every A-step's flow `condition:` names), or it declares no blocks.

INCOMPLETE (rc=1) in project mode when SOME declared blocks have a
corner_results.json and others have none: a PVT sweep run for a subset
of the declared blocks does not certify A4 done. All blocks missing
stays VACUOUS_PASS (defer to `ams-sim`).

Artefact resolution: `phase3/analog/<block>/corner_results.json` (what the
analog runner writes) OR `phase2/analog/<block>/corner_results.json` (what
the flow declares as A4's required_output).

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
    artefact_missing_for_block, emit_pass, emit_fail, emit_incomplete,
    resolve_block_artefact,
)

GATE = "analog_a4_corner_sweep_check"
SKILL = "ams-sim"
DECLARED_PHASE = 2

# ── A3→A4 netlist provenance (the subject-of-measurement rules) ────────────
#
# WHAT WENT WRONG (measured on a real run). Ten blocks carried a corner_results.json
# reading `_provenance: "real_ngspice"`, `corners_executed: 9`,
# `simulator_run: true` — and this gate certified seven of them. A1/A2/A3 were
# WAIVED for all ten and A3's declared output `<block>.sp` existed for NONE of
# them, so every deck ngspice consumed was the producer's own built-in
# testbench, selected by canonical block type. `_provenance` was true about the
# SIMULATOR and said nothing about the SUBJECT, and this gate read only the
# former. Nine real corners on a stand-in circuit is a self-test of the
# plugin's template library; it is not evidence about the design, and it must
# not reach PASS.
#
# TWO RULES, deliberately independent:
#
#   A4_NETLIST_NOT_FROM_A3 — the artefact DISCLOSES a deck the producer
#     authored (`netlist_provenance` present and not `a3_netlist`). Catches an
#     honest producer.
#
#   A4_NETLIST_ABSENT — the artefact declares simulated corners while A3's
#     declared output `<block>.sp` does not exist ANYWHERE on disk. Catches a
#     silent one: it is decided by the filesystem, so omitting the provenance
#     field evades nothing. This is the rule that would have caught the measured run, whose
#     artefacts carried no provenance field at all.
#
# Both are checked BEFORE the value rules below, so a block blocked on A3 is
# reported as blocked on A3 rather than as a corner-margin miss against a
# target its circuit never had.
NETLIST_PROV_OK = "a3_netlist"
A3_STEP = "A3_netlist_gen"
A3_SKILL = "analog-netlist-gen"


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


def _netlist_disclosed_fail(project: Path, block: str, data: dict,
                            rel: str) -> Optional[dict]:
    """The two rules decided by what the artefact SAYS about itself. Checked
    BEFORE the value rules: a block blocked on A3, or one whose deck the
    producer authored, must be reported as that rather than as a corner-margin
    miss against a target its circuit never had.

    chip-AGNOSTIC: block name, step name and paths only."""
    # Rule 1 — the producer refused upstream and said so.
    if data.get("_provenance") == "upstream_netlist_missing" \
            or data.get("blocked_on") == A3_STEP:
        return {
            "block": block, "rule": "A4_NETLIST_ABSENT",
            "rel_path": rel,
            "detail": (f"corner_results.json records status "
                       f"{data.get('status')!r} blocked on {A3_STEP}: "
                       f"{data.get('required_input')!r} was never produced. "
                       f"A4 has no netlist of this design to measure — run "
                       f"skill `{A3_SKILL}`."),
        }
    prov = data.get("netlist_provenance")
    # Rule 2 — disclosed: the deck was not derived from A3's output.
    if prov is not None and prov != NETLIST_PROV_OK:
        return {
            "block": block, "rule": "A4_NETLIST_NOT_FROM_A3",
            "rel_path": rel,
            "detail": (f"netlist_provenance={prov!r} — the simulated deck was "
                       f"authored by the sweep program "
                       f"({data.get('deck_authored_by') or 'built-in template'}), "
                       f"not derived from {A3_STEP}'s output "
                       f"{data.get('netlist_source') or '<none>'}. Real ngspice "
                       f"on a stand-in circuit measures the template library, "
                       f"not this design; it cannot certify A4."),
        }
    return None


def _netlist_absent_fail(project: Path, block: str, data: dict,
                         corners: list, rel: str) -> Optional[dict]:
    """The rule decided by the FILESYSTEM rather than by a self-report: the
    artefact claims a simulation while A3's declared output does not exist
    anywhere, so the sweep cannot have measured this design's netlist. Omitting
    `netlist_provenance` evades nothing — this is the rule that catches a
    producer that says nothing at all, which is how the measured round's
    artefacts were shaped.

    Checked LAST, immediately before the PASS: it answers "may this be
    certified?", and must not displace the existing diagnosis of an artefact
    that is already failing for a value reason. An artefact that claims no
    simulation is left alone entirely — `A4_NO_SIMULATOR_RUN` already owns
    that case and says it better."""
    if data.get("netlist_provenance") is not None:
        return None                       # disclosed → handled by rules 1-2
    if not any(isinstance(c, dict) and c.get("simulator_run") is True
               for c in corners):
        return None                       # claims no sim → value rules own it
    sp_path, sp_found = _a3_netlist(project, block)
    if sp_found:
        return None
    return {
        "block": block, "rule": "A4_NETLIST_ABSENT",
        "rel_path": rel,
        "detail": (f"corners declare `simulator_run: true` while {A3_STEP}'s "
                   f"declared output {sp_path!r} does not exist — the sweep "
                   f"cannot have simulated this design's netlist, and the "
                   f"artefact records no `netlist_provenance` saying what it "
                   f"did simulate. Run skill `{A3_SKILL}`, or have the producer "
                   f"stamp the deck's origin."),
    }


def _a3_netlist(project: Path, block: str) -> tuple:
    """(rel_path, found) for A3's declared per-block output. Resolution is the
    same two-root search `analog_a3_netlist_gen_check` uses, so the two gates
    can never disagree about whether the netlist exists."""
    path, found = resolve_block_artefact(
        project, block, f"{block}.sp", DECLARED_PHASE)
    try:
        rel = str(path.relative_to(project))
    except ValueError:
        rel = str(path)
    return rel, found


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
    # SUBJECT before value: a block the producer reported as blocked on A3, or
    # one whose deck the producer authored, must be reported as that — not as
    # an empty-corners or corner-margin problem.
    nl = _netlist_disclosed_fail(project, block, data, rel)
    if nl is not None:
        return "FAIL", [nl]
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
        # ── R10-FIX-2 — restore THIS GATE'S OWN STATED PREMISE ─────────────
        # The v1.6.223 rationale immediately above says PASS_INFORMATIONAL is
        # accepted because it means "real sim ran, THE BLOCK HAS NO FIXED
        # NUMERIC TARGET BY DESIGN … no target to compare against".
        #
        # That premise is FALSE about the artefacts this gate's own producer
        # writes. `analog_real_corner_sweep._verdict()` is three-valued
        # (PASS / PASS_INFORMATIONAL / FAIL), but the record it emits is
        # two-valued:
        #
        #     spec_status = verdict if verdict in ("PASS","PASS_INFORMATIONAL") \
        #                             else "PASS_INFORMATIONAL"
        #
        # — every FAIL is rewritten, unconditionally, BEFORE reaching disk.
        # So `status: PASS_INFORMATIONAL` conflates two structurally different
        # records: the no-target one the premise describes (`target: null`),
        # and a REAL MISS against a REAL number. The truth of the second is
        # preserved in `raw_sim_verdict` — a field NO consumer read, which is
        # why the `status == "FAIL"` branch below is unreachable against any
        # artefact the producer writes.
        #
        # Discriminate on the PROPERTY the premise actually names (is there a
        # concrete numeric target?) instead of on the LABEL. A record with
        # `target: null` still passes — that is the case v1.6.223 exists for
        # and it is untouched. A record whose own preserved verdict is FAIL
        # against a concrete target is not clean, and must not be reported as
        # clean.
        #
        # This does NOT relax or restate any target: the number stands exactly
        # as the producer computed it. What changes is that missing it stops
        # being laundered into a pass. A block whose miss is an accepted
        # environmental/modelling gap is disclosed through the project's
        # waiver file, where a reader can see it — not by a silent rewrite in
        # the producer.
        #
        # chip-AGNOSTIC: keyed on record shape (`target is None`) and on the
        # producer's own preserved verdict; no chip, block, vendor or PDK
        # literal.
        masked = [s for s in spec_results
                  if isinstance(s, dict)
                  and s.get("raw_sim_verdict") == "FAIL"
                  and s.get("target") is not None
                  and s.get("status") != "FAIL"]
        if masked:
            m = masked[0]
            return "FAIL", [{
                "block": block, "rule": "A4_RAW_SIM_FAIL_MASKED",
                "rel_path": rel,
                "detail": (
                    f"{len(masked)} spec(s) record raw_sim_verdict='FAIL' "
                    f"against a concrete target while status was rewritten to "
                    f"{m.get('status')!r} — e.g. {m.get('name','?')}: measured "
                    f"{m.get('value')} vs target {m.get('target')} "
                    f"(tolerance {m.get('tolerance_pct')}, target_source "
                    f"{m.get('target_source')!r}). PASS_INFORMATIONAL means "
                    f"'no target to compare against'; this record HAS a "
                    f"target and missed it. Fix the block or disclose the "
                    f"miss in waivers.json — do not report it as clean."),
            }]

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
    # LAST — an otherwise-clean sweep may still be certifying a circuit that
    # does not exist. Nothing above can see that: every rule so far reads the
    # artefact's own numbers.
    nl = _netlist_absent_fail(project, block, data, corners, rel)
    if nl is not None:
        return "FAIL", [nl]
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
