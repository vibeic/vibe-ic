#!/usr/bin/env python3
"""Smoke tests for l19_pdk_floorplan_contract_check.

EXPLICIT NEGATIVE CONTROL. Every behavioural test asserts BOTH directions:
a deliberately-gutted L19 must FAIL (rc=1) and the well-formed sibling must
PASS (rc=0). A test that cannot fail proves nothing.

All fixtures are SYNTHESIZED neutral data — an invented PDK id, invented design
names, invented rects. No real design's files are copied and no real PDK,
foundry or part number appears anywhere.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
GATE = PROGRAMS / "l19_pdk_floorplan_contract_check.py"

# A completely invented PDK identifier — the gate never matches against a list
# of known PDKs, only against the design's own inputs, so a made-up id works.
NEUTRAL_PDK_ID = "neutralpdk7x"

DESIGN_DOC = (
    "# Neutral Block Metadata\n"
    "| target PDK family | " + NEUTRAL_PDK_ID + " |\n"
    "| package | neutral-48 |\n"
)

OPENLANE_CFG = {
    "DESIGN_NAME": "neutral_top",
    "FP_SIZING": "absolute",
    "DIE_AREA": [0, 0, 1200, 900],
    "CLOCK_PORT": "clk_a",
}


def _run(project: Path):
    proc = subprocess.run(
        [sys.executable, str(GATE), str(project)],
        capture_output=True, text=True, timeout=60)
    return proc.returncode, (proc.stdout + proc.stderr)


def _build(root: Path, fields: dict, *, with_doc=True, with_cfg=False,
           staged_pdk=False, evidence=None) -> Path:
    project = root / "proj"
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    doc = {
        "doc_id": "L19",
        "doc_name": "L19_CONSTRAINTS_PDK",
        "fields": fields,
        "extraction_status": "PARTIALLY_EXTRACTED",
        "emitted_by": "test_fixture",
    }
    if evidence is not None:
        doc["extraction_evidence"] = evidence
    (gd / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps(doc, indent=1))
    if with_doc:
        d = project / "phase1" / "input_doc"
        d.mkdir(parents=True, exist_ok=True)
        (d / "L1_metadata.txt").write_text(DESIGN_DOC)
    if with_cfg:
        c = project / "input" / "design_src" / "flowcfg" / "neutral_top"
        c.mkdir(parents=True, exist_ok=True)
        (c / "config.json").write_text(json.dumps(OPENLANE_CFG, indent=1))
    if staged_pdk:
        p = project / "input" / "pdk" / "liberty"
        p.mkdir(parents=True, exist_ok=True)
        (p / "neutral_cells_tt.lib").write_text(
            'library (neutral_cells_tt) {\n  time_unit : "1ns";\n}\n')
    return project


# --------------------------------------------------------------------------- #
# L19-3 NEGATIVE CONTROL PAIR — staged PDK, pdk_target present vs gutted
# --------------------------------------------------------------------------- #
def test_gutted_pdk_target_fails_and_populated_one_passes(tmp_path):
    """NEGATIVE CONTROL: identical design that STAGES a PDK enablement; only
    L19.pdk_target differs."""
    gutted = _build(tmp_path / "a",
                    {"pdk_target": None, "die_area_budget_um": None},
                    staged_pdk=True)
    rc_bad, out_bad = _run(gutted)
    assert rc_bad == 1, (
        "a design that stages its own PDK enablement while L19.pdk_target is "
        f"null MUST FAIL. got rc={rc_bad}\n{out_bad}")
    assert "L19-3" in out_bad
    assert "pdk_substitution" in out_bad, (
        "the finding must name the consumer whose disclosure goes vacuous")

    good = _build(tmp_path / "b",
                  {"pdk_target": NEUTRAL_PDK_ID, "die_area_budget_um": None},
                  staged_pdk=True)
    rc_ok, out_ok = _run(good)
    assert rc_ok == 0, (
        f"a populated, traceable pdk_target MUST PASS. got rc={rc_ok}\n{out_ok}")
    assert "[PASS]" in out_ok


def test_no_staged_pdk_means_null_target_is_not_flagged(tmp_path):
    """A design that stages no PDK enablement must not be failed for a null
    target — this is what keeps the gate at zero false positives."""
    project = _build(tmp_path,
                     {"pdk_target": None, "die_area_budget_um": None},
                     staged_pdk=False)
    rc, out = _run(project)
    assert rc == 0, f"no staged PDK => no L19-3. got rc={rc}\n{out}"


# --------------------------------------------------------------------------- #
# L19-2 NEGATIVE CONTROL PAIR — traceable vs fabricated pdk_target
# --------------------------------------------------------------------------- #
def test_untraceable_pdk_target_fails_and_traceable_one_passes(tmp_path):
    fabricated = _build(tmp_path / "a",
                        {"pdk_target": "ghostpdk99z",
                         "die_area_budget_um": None})
    rc_bad, out_bad = _run(fabricated)
    assert rc_bad == 1, (
        "a pdk_target traceable to nothing in the design's own inputs MUST "
        f"FAIL. got rc={rc_bad}\n{out_bad}")
    assert "L19-2" in out_bad
    assert "foundry" in out_bad.lower()

    traceable = _build(tmp_path / "b",
                       {"pdk_target": NEUTRAL_PDK_ID,
                        "die_area_budget_um": None})
    rc_ok, out_ok = _run(traceable)
    assert rc_ok == 0, (
        "a pdk_target that appears in the design's own input doc MUST PASS. "
        f"got rc={rc_ok}\n{out_ok}")


def test_verified_extraction_evidence_substantiates_the_target(tmp_path):
    """A target absent from the bulk corpus is still substantiated when L19's
    own evidence quote VERIFIABLY appears in the file it cites — and NOT when
    the quote is absent from that file (both directions)."""
    ok = _build(tmp_path / "ok",
                {"pdk_target": "sidebandpdk3", "die_area_budget_um": None},
                with_doc=True,
                evidence={"phase1/input_doc/L1_metadata.txt": [
                    {"literal": "| target PDK family | " + NEUTRAL_PDK_ID,
                     "label": "pdk_target (phase1/input_doc/L1_metadata.txt:2)"}
                ]})
    rc_ok, out_ok = _run(ok)
    assert rc_ok == 0, (
        f"a verifiable evidence quote must substantiate. got {rc_ok}\n{out_ok}")

    lying = _build(tmp_path / "lying",
                   {"pdk_target": "sidebandpdk3", "die_area_budget_um": None},
                   with_doc=True,
                   evidence={"phase1/input_doc/L1_metadata.txt": [
                       {"literal": "this sentence is nowhere in that file at all",
                        "label": "pdk_target (phase1/input_doc/L1_metadata.txt:2)"}
                   ]})
    rc_bad, out_bad = _run(lying)
    assert rc_bad == 1, (
        "an evidence quote that is NOT in the file it cites substantiates "
        f"nothing and MUST FAIL. got {rc_bad}\n{out_bad}")


# --------------------------------------------------------------------------- #
# L19-1 NEGATIVE CONTROL PAIR — fixed-die mandate
# --------------------------------------------------------------------------- #
def test_fixed_die_mandate_unresolved_fails_and_resolved_passes(tmp_path):
    """NEGATIVE CONTROL: identical design mandating DIE_AREA 0 0 1200 900;
    only L19.die_area_budget_um differs."""
    gutted = _build(tmp_path / "a",
                    {"pdk_target": NEUTRAL_PDK_ID,
                     "die_area_budget_um": None},
                    with_cfg=True)
    rc_bad, out_bad = _run(gutted)
    assert rc_bad == 1, (
        "a design that mandates a fixed die while L19 resolves none MUST FAIL. "
        f"got rc={rc_bad}\n{out_bad}")
    assert "L19-1" in out_bad
    assert "AUTO-SIZE" in out_bad

    good = _build(tmp_path / "b",
                  {"pdk_target": NEUTRAL_PDK_ID,
                   "die_area_budget_um": "1200x900"},
                  with_cfg=True)
    rc_ok, out_ok = _run(good)
    assert rc_ok == 0, (
        f"the mandated rect carried in L19 MUST PASS. got rc={rc_ok}\n{out_ok}")


def test_l19_die_that_contradicts_the_mandate_fails(tmp_path):
    """Pinning phase3 to a rect the design never asked for is worse than
    auto-sizing."""
    project = _build(tmp_path,
                     {"pdk_target": NEUTRAL_PDK_ID,
                      "die_area_budget_um": "500x400"},
                     with_cfg=True)
    rc, out = _run(project)
    assert rc == 1, f"contradicting die MUST FAIL. got rc={rc}\n{out}"
    assert "matches NONE" in out


def test_tcl_side_die_mandate_is_detected(tmp_path):
    """The mandate may arrive as Tcl rather than JSON."""
    project = _build(tmp_path,
                     {"pdk_target": NEUTRAL_PDK_ID,
                      "die_area_budget_um": None})
    t = project / "input" / "design_src"
    t.mkdir(parents=True, exist_ok=True)
    (t / "neutral_flow.tcl").write_text(
        'set ::env(FP_SIZING) "absolute"\n'
        'set ::env(DIE_AREA) "0 0 640 480"\n')
    rc, out = _run(project)
    assert rc == 1, f"Tcl-side mandate MUST be detected. got rc={rc}\n{out}"
    assert "L19-1" in out and "640x480" in out


def test_no_die_mandate_means_no_die_finding(tmp_path):
    """A design that mandates no fixed die must not be failed for a null
    die_area_budget_um — 118/136 real runs are in exactly this state."""
    project = _build(tmp_path,
                     {"pdk_target": NEUTRAL_PDK_ID,
                      "die_area_budget_um": None})
    rc, out = _run(project)
    assert rc == 0, f"no mandate => no L19-1. got rc={rc}\n{out}"


# --------------------------------------------------------------------------- #
# L19-4 is advisory ONLY
# --------------------------------------------------------------------------- #
def test_dead_sdc_constraints_path_is_advisory_not_blocking(tmp_path):
    """`sdc_constraints_path` is read by NOTHING. A phantom path must be
    REPORTED but must never change the exit code."""
    project = _build(tmp_path,
                     {"pdk_target": NEUTRAL_PDK_ID,
                      "die_area_budget_um": None,
                      "sdc_constraints_path": "input/constraints/nowhere.sdc"})
    rc, out = _run(project)
    assert rc == 0, f"advisory must not block. got rc={rc}\n{out}"
    assert "[note]" in out and "read by NOTHING" in out


def test_waiver_discloses_instead_of_hiding(tmp_path):
    project = _build(tmp_path,
                     {"pdk_target": None, "die_area_budget_um": None},
                     staged_pdk=True)
    (project / "waivers.json").write_text(json.dumps({
        "l19_pdk_floorplan_contract_disclosed":
            "This synthesized fixture deliberately leaves the PDK target "
            "unstated; the gap is disclosed for reviewer sign-off."}))
    rc, out = _run(project)
    assert rc == 0 and "PASS_WITH_WAIVERS" in out, f"rc={rc}\n{out}"
    assert "L19-3" in out, "a waiver must disclose, not hide"

    (project / "waivers.json").write_text(json.dumps({
        "l19_pdk_floorplan_contract_disclosed": "short"}))
    rc2, _ = _run(project)
    assert rc2 == 1, "a <40-char waiver must not suppress the finding"


def test_missing_l19_skips(tmp_path):
    project = tmp_path / "empty"
    (project / "phase1" / "generated_docs").mkdir(parents=True)
    rc, out = _run(project)
    assert rc == 2 and "SKIP" in out


def test_gate_reuses_the_consumers_own_die_resolvers():
    """Emitter/checker doctrine: the gate must delegate to
    phase3_one_shot_runner's OWN _l19_declared_die_area / _l9_declared_die_area
    so gate and consumer can never drift."""
    sys.path.insert(0, str(PROGRAMS))
    import importlib
    mod = importlib.import_module("l19_pdk_floorplan_contract_check")
    import phase3_one_shot_runner as p3
    assert mod._consumer_l19_die is p3._l19_declared_die_area
    assert mod._consumer_l9_die is p3._l9_declared_die_area


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

# --- the consumer binding is LIVE, not frozen at first import (v1.9.63) ------

def test_a_failed_consumer_import_does_not_permanently_downgrade_the_gate():
    """MEASURED: this file's identity assertion passed alone and FAILED in the
    full suite, and the gate went on answering.

    The binding was a module-level import inside `except Exception: = None`,
    and the runtime read that name before falling back to a REIMPLEMENTATION of
    the same rule kept in this gate. So one failed import — during the moment
    some other module was mid-import, in a suite that imports 500 of them —
    silently turned "reuse the consumer's resolver" into "use my own copy",
    which is the exact drift the doctrine forbids. Import-time binding cannot
    be retried; this proves the lazy one is."""
    import importlib
    sys.path.insert(0, str(PROGRAMS))
    saved = sys.modules.pop("phase3_one_shot_runner", None)
    try:
        sys.modules["phase3_one_shot_runner"] = None       # import raises
        mod = importlib.import_module("l19_pdk_floorplan_contract_check")
        assert mod._consumer_l19_die is None, "the window must really be shut"
    finally:
        sys.modules.pop("phase3_one_shot_runner", None)
        if saved is not None:
            sys.modules["phase3_one_shot_runner"] = saved
    import phase3_one_shot_runner as p3
    assert mod._consumer_l19_die is p3._l19_declared_die_area, (
        "the gate stayed downgraded after the import became possible again")
