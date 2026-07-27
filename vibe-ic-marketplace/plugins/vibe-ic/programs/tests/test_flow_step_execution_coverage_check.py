"""Tests for flow_step_execution_coverage_check.analyze (synthetic data only)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flow_step_execution_coverage_check as cov  # noqa: E402

_FLOW_YAML = (Path(__file__).resolve().parents[2]
              / "flow" / "phase1_phase2_phase3.yaml")


def _report(*steps):
    return {"steps": list(steps)}


def _s(sid, name, status, stage="stage3"):
    return {"id": sid, "name": name, "status": status, "stage": stage}


def _pairs(res):
    return {(str(v["terminal_id"]), str(v["signoff_id"]))
            for v in res["ordering_violations"]}


def _flow_steps():
    """Every (id, name, stage) shipped in the real flow yaml."""
    import yaml
    doc = yaml.safe_load(_FLOW_YAML.read_text())
    out = []

    def walk(o):
        if isinstance(o, dict):
            if "id" in o and "name" in o:
                out.append((str(o["id"]), o["name"], str(o.get("stage", ""))))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(doc)
    return out


# A tiny synthetic flow graph: terminal GDS (37) depends on PV (31); PV depends
# on nothing here. Mirrors the real blocks_on shape without any vendor data.
GRAPH = {"37": ["31"], "31": ["30"], "30": []}


def test_ordering_violation_terminal_before_signoff():
    # GDS marked done while the PV step it blocks_on is MISSING → FAIL.
    r = _report(
        _s(30, "Post-Layout SPICE Verification", "PASS"),
        _s(31, "Physical Verification (DRC + LVS + ERC + Density)", "MISSING"),
        _s(37, "GDSII output (only if Step 31 PV fully clean)", "PASS"),
    )
    res = cov.analyze(r, GRAPH)
    assert res["verdict"] == "FAIL"
    assert res["counts"]["ordering_violations"] >= 1
    pair = res["ordering_violations"][0]
    assert str(pair["terminal_id"]) == "37" and str(pair["signoff_id"]) == "31"


def test_clean_flow_all_pass():
    r = _report(
        _s(30, "Post-Layout SPICE Verification", "PASS"),
        _s(31, "Physical Verification (DRC + LVS + ERC + Density)", "PASS"),
        _s(37, "GDSII output (only if Step 31 PV fully clean)", "PASS"),
    )
    res = cov.analyze(r, GRAPH)
    assert res["verdict"] == "PASS"
    assert res["counts"]["ordering_violations"] == 0
    assert res["counts"]["applicable_missing"] == 0


def test_na_signoff_does_not_block_terminal():
    # A legitimately SKIPPED-CONDITION predecessor must NOT flag the terminal.
    r = _report(
        _s(30, "Post-Layout SPICE Verification", "PASS"),
        _s(31, "Physical Verification (DRC + LVS + ERC + Density)",
           "SKIPPED-CONDITION"),
        _s(37, "GDSII output (only if Step 31 PV fully clean)", "PASS"),
    )
    res = cov.analyze(r, GRAPH)
    assert res["verdict"] == "PASS"


def test_applicable_missing_is_a_skip():
    # An applicable step that never produced output → no-skip violation.
    r = _report(
        _s(2, "Lint (RTL + Quartus-unsafe patterns)", "MISSING", stage="stage1"),
        _s(37, "GDSII output", "MISSING"),
    )
    res = cov.analyze(r, {})
    assert res["verdict"] == "FAIL"
    ids = {str(s["id"]) for s in res["applicable_missing"]}
    assert "2" in ids


def test_name_based_fallback_when_no_blocks_on_edges():
    # Terminal ships EMPTY blocks_on (the real GDSII/handoff data bug): the
    # name-based fallback must still guard it against an unfinished sign-off step.
    r = _report(
        _s(31, "Physical Verification (DRC + LVS + ERC)", "MISSING"),
        _s(38, "Foundry Handoff (mask spec + WAT plan)", "PASS"),
    )
    res = cov.analyze(r, {})  # empty graph → fallback path
    assert res["verdict"] == "FAIL"
    assert res["counts"]["ordering_violations"] >= 1


def test_vacuous_pass_SIGNOFF_ancestor_still_blocks():
    # A VACUOUS-PASS SIGN-OFF predecessor (SPICE verification verified nothing)
    # is dangerous → must still block a downstream done-claim.
    r = _report(
        _s(30, "Post-Layout SPICE Verification", "VACUOUS-PASS"),
        _s(31, "Physical Verification", "PASS"),
        _s(37, "GDSII output", "PASS"),
    )
    res = cov.analyze(r, GRAPH)
    assert res["verdict"] == "FAIL"


def test_vacuous_pass_NONsignoff_ancestor_is_acceptable():
    # A VACUOUS-PASS NON-sign-off PROCESS step (synth handoff had no tie-cells /
    # no yosys-template to check) RAN and did not fail — it must NOT flag the
    # downstream steps that depend on it. (The exact spm step-14 false positive.)
    graph = {"16": ["14"], "15": ["14"], "14": []}
    r = _report(
        _s(14, "Synthesis handoff gate (pre-PnR yosys script + netlist audit)",
           "VACUOUS-PASS", stage="stage2"),
        _s(15, "Floorplan + PDN", "PASS"),
        _s(16, "Clock planning", "PASS"),
    )
    res = cov.analyze(r, graph)
    assert res["verdict"] == "PASS"
    assert res["counts"]["ordering_violations"] == 0


# ── stage-5 silicon attestations: a VACUOUS-PASS there must still block ──────
# A sign-off that verified nothing already blocks. A fab-intake / wafer-sort /
# packaging / final-test / reliability gate that ATTESTED to nothing is the same
# hazard: the downstream step's own PASS asserts the upstream physical event
# happened. Measured hole (vibe-ic flow audit, step 41 / dim 6): with step 40
# VACUOUS-PASS and step 41 PASS the guard emitted violations for every other
# applicable ancestor of 41 and silently exempted 40 — its own blocks_on parent.

_FAB = "Fabrication (foundry mask-set + wafer fab — external)"
_SORT = "Wafer Sort / Probe Test (ATE + probe card)"


def test_wafer_sort_not_credited_over_vacuous_fab_intake():
    # The measured scenario, with step 40 as the ONLY non-PASSed ancestor of 41
    # so the assertion cannot be satisfied by unrelated upstream noise.
    graph = {"41": ["40"], "40": ["38"], "38": []}
    r = _report(
        _s(38, "Foundry Handoff (mask spec + WAT plan)", "PASS", stage="stage4"),
        _s(40, _FAB, "VACUOUS-PASS", stage="stage5_manufacturing"),
        _s(41, _SORT, "PASS", stage="stage5_manufacturing"),
    )
    res = cov.analyze(r, graph)
    assert res["verdict"] == "FAIL"
    assert ("41", "40") in _pairs(res)


def test_vacuous_silicon_ancestor_blocks_on_stage_alone():
    # Only the flow-declared `stage` says "silicon" here — the name carries no
    # manufacturing vocabulary at all. The stage limb must carry the decision,
    # so a future rewording of the step title cannot re-open the hole.
    graph = {"91": ["90"], "90": []}
    r = _report(
        _s(90, "External vendor step", "VACUOUS-PASS",
           stage="stage5_manufacturing"),
        _s(91, "Downstream silicon step", "PASS", stage="stage5_manufacturing"),
    )
    res = cov.analyze(r, graph)
    assert res["verdict"] == "FAIL"
    assert ("91", "90") in _pairs(res)


def test_vacuous_silicon_ancestor_blocks_on_name_when_report_has_no_stage():
    # A compliance report that carries no `stage` key at all (older/hand-built
    # report shape) must still be guarded, via the step-name limb.
    graph = {"41": ["40"], "40": []}
    r = _report(
        {"id": 40, "name": _FAB, "status": "VACUOUS-PASS"},
        {"id": 41, "name": _SORT, "status": "PASS"},
    )
    res = cov.analyze(r, graph)
    assert res["verdict"] == "FAIL"
    assert ("41", "40") in _pairs(res)


def _vacuous_ancestor_blocks(sid, name, stage):
    """Does a VACUOUS-PASS on this step block a PASS child that blocks_on it?"""
    child = f"{sid}__child"
    r = _report(
        {"id": sid, "name": name, "status": "VACUOUS-PASS", "stage": stage},
        {"id": child, "name": "downstream", "status": "PASS", "stage": stage},
    )
    res = cov.analyze(r, {child: [sid], sid: []})
    return (child, sid) in _pairs(res), res


def test_every_stage5_step_of_the_real_flow_blocks_when_vacuous():
    # Property, checked against the flow yaml actually shipped (names and stages
    # read from it, so a rename cannot silently narrow this test): NO stage-5
    # silicon attestation may be a silently-acceptable vacuous predecessor.
    stage5 = [(sid, name, stage) for sid, name, stage in _flow_steps()
              if stage.startswith("stage5")]
    assert stage5, "flow yaml declares no stage5 steps — fixture is stale"
    for sid, name, stage in stage5:
        blocked, res = _vacuous_ancestor_blocks(sid, name, stage)
        assert blocked, (
            f"stage5 step {sid} ({name}) vacuously passed and was still "
            f"accepted as a predecessor: {res['ordering_violations']}")


# ── direction-1: ordinary process steps must NOT start blocking ──────────────
# Step ids only — the name and stage are read from the shipped flow yaml, so a
# reworded title updates the guard instead of silently voiding it. These are the
# steps that were legitimately VACUOUS-PASS ancestors on the measured
# spm x ihp-sg13g2 run (D1 and 14), plus process steps whose names sit closest to
# the manufacturing vocabulary (Metal Fill, Power analysis, Foundry Handoff).
_ORDINARY_VACUOUS_OK = ["D1", "14", "15", "17", "21", "33", "34", "38"]


def test_ordinary_process_steps_still_acceptable_when_vacuous():
    by_id = {sid: (name, stage) for sid, name, stage in _flow_steps()}
    for sid in _ORDINARY_VACUOUS_OK:
        assert sid in by_id, f"step {sid} left the flow yaml — update this guard"
        name, stage = by_id[sid]
        assert not stage.startswith("stage5"), (
            f"step {sid} moved into stage5 — it is no longer an ordinary "
            f"process step and this guard needs rewriting")
        blocked, res = _vacuous_ancestor_blocks(sid, name, stage)
        assert not blocked, (
            f"{sid} ({name}) vacuous must stay an acceptable predecessor, "
            f"got {res['ordering_violations']}")


def test_skipped_condition_silicon_ancestor_does_not_block():
    # Direction-1: on every pre-silicon run the stage-5 steps are
    # SKIPPED-CONDITION (no silicon_received.json). That is legitimately "not
    # applicable" and must never flag anything.
    graph = {"41": ["40"], "40": []}
    r = _report(
        _s(40, _FAB, "SKIPPED-CONDITION", stage="stage5_manufacturing"),
        _s(41, _SORT, "PASS", stage="stage5_manufacturing"),
    )
    res = cov.analyze(r, graph)
    assert res["verdict"] == "PASS"


def test_real_fab_intake_pass_credits_wafer_sort():
    # Direction-1: a genuinely PASSed fab intake must still satisfy step 41.
    graph = {"41": ["40"], "40": []}
    r = _report(
        _s(40, _FAB, "PASS", stage="stage5_manufacturing"),
        _s(41, _SORT, "PASS", stage="stage5_manufacturing"),
    )
    res = cov.analyze(r, graph)
    assert res["verdict"] == "PASS"


def test_cli_exits_1_and_reports_the_pair_end_to_end(tmp_path):
    # The blocking wiring is only real if the rc=1 path of the actual CLI runs.
    # Drive main() through subprocess with a precomputed compliance report.
    import json
    import subprocess
    import sys as _sys

    comp = tmp_path / "compliance.json"
    comp.write_text(json.dumps({"overall": "FAIL", "steps": [
        {"id": 40, "name": _FAB, "status": "VACUOUS_PASS",
         "stage": "stage5_manufacturing"},
        {"id": 41, "name": _SORT, "status": "PASS",
         "stage": "stage5_manufacturing"},
    ]}))
    flow = tmp_path / "flow.yaml"
    flow.write_text(
        "steps:\n"
        f"  - id: 40\n    name: \"{_FAB}\"\n    blocks_on: []\n"
        f"  - id: 41\n    name: \"{_SORT}\"\n    blocks_on: [40]\n")
    out = tmp_path / "cov.json"
    r = subprocess.run(
        [_sys.executable,
         str(Path(cov.__file__)), str(tmp_path),
         "--compliance-json", str(comp),
         "--flow-def", str(flow),
         "--json", str(out)],
        capture_output=True, text=True)
    assert r.returncode == 1, f"rc={r.returncode} stdout={r.stdout}"
    res = json.loads(out.read_text())
    assert ("41", "40") in _pairs(res)
