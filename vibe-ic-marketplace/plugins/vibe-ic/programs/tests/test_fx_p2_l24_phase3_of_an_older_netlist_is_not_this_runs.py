#!/usr/bin/env python3
"""FX_P2 (3b) — a phase-3 record older than this run's phase-2 netlist is not
evidence that phase 3 ran FOR THIS DESIGN.

MEASURED on subservient (8HD-4, 2026-09-28): the tree carried an earlier
supplementary phase-3 attempt (`reports/orchestrator/phase3_one_shot.json`
2026-09-27 22:24, halted at pad_ring, plus 14 `reports/phase3` JSONs), and the
new run's phase 2 re-synthesised (`phase2/stage2/synth/*.v` 2026-09-28 00:27).
`l24_signoff_evidence_backed_check` read "phase 3 has run", booked the four
sign-off requirements the input states (DRC/LVS/antenna/STA) UNMET, and the
phase-2 final_audit halted the run -- so the phase that would measure them
could not start. That is the R-0915 deadlock `_phase3_has_run` exists to
prevent, re-opened by stale files.

Driven through the real gate as a subprocess; mtimes are set explicitly.
chip-AGNOSTIC: synthetic project.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import phase1_post_process as P  # noqa: E402
import l24_signoff_evidence_backed_check as G  # noqa: E402
import pytest

GATE = PROGRAMS / "l24_signoff_evidence_backed_check.py"
T_OLD, T_NEW = 1_700_000_000, 1_700_100_000


def _project(tmp_path: Path) -> Path:
    d = tmp_path / "input" / "docs"
    d.mkdir(parents=True)
    (d / "spec.md").write_text("Sign-off requires DRC clean.\n")
    doc = P.emit_l_doc_skeleton("L24", "unknown", project_dir=tmp_path)
    doc.pop("evidence", None)
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L24_SIGNOFF.json").write_text(json.dumps(doc))
    return tmp_path


def _at(path: Path, text: str, t: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.utime(path, (t, t))
    return path


def _phase3_record(proj: Path, t: int) -> None:
    _at(proj / "reports" / "orchestrator" / "phase3_one_shot.json",
        json.dumps({"verdict": "FAIL"}), t)
    _at(proj / "reports" / "phase3" / "lvs_verdict.json",
        json.dumps({"status": "PASS"}), t)


def _netlist(proj: Path, t: int) -> None:
    _at(proj / "phase2" / "stage2" / "synth" / "top_synth.v",
        "module top; endmodule\n", t)


def _gate(proj: Path):
    r = subprocess.run([sys.executable, str(GATE), str(proj)],
                       capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


def test_phase3_of_an_older_netlist_is_not_yet_measurable(tmp_path):
    proj = _project(tmp_path)
    _phase3_record(proj, T_OLD)
    _netlist(proj, T_NEW)
    rc, out = _gate(proj)
    assert rc == 0, out
    assert "not yet measurable" in out
    assert "REQUIRES" not in out


def test_phase3_of_this_netlist_still_fails_an_unmeasured_requirement(
        tmp_path):
    """THE CONTROL: phase 3 ran after this run's synthesis, with no DRC
    report — the requirement is UNMET and the gate FAILs, as before."""
    proj = _project(tmp_path)
    _netlist(proj, T_OLD)
    _phase3_record(proj, T_NEW)
    rc, out = _gate(proj)
    assert rc == 1, out
    assert "the input REQUIRES DRC clean" in out


def test_with_no_phase2_netlist_the_records_are_taken_as_they_are(tmp_path):
    """Nothing to date them against: today's behaviour, unchanged."""
    proj = _project(tmp_path)
    _phase3_record(proj, T_OLD)
    rc, out = _gate(proj)
    assert rc == 1, out


def test_the_audits_own_stage3_publication_is_not_phase3_evidence(tmp_path):
    """MEASURED in the same run: the phase-2 final audit writes
    `reports/phase3/gates/stage3_compliance.json` (program
    flow_compliance_check) AFTER this run's synthesis, and the gate read it as
    "phase 3 has run". The audit's own record is not a measurement."""
    proj = _project(tmp_path)
    _phase3_record(proj, T_OLD)
    _netlist(proj, T_OLD + 10)
    _at(proj / "reports" / "phase3" / "gates" / "stage3_compliance.json",
        json.dumps({"program": "flow_compliance_check", "phase": "all"}),
        T_NEW)
    rc, out = _gate(proj)
    assert rc == 0, out
    assert "not yet measurable" in out


def test_a_real_phase3_record_after_synthesis_still_counts(tmp_path):
    """THE CONTROL for the exclusion: a phase-3 PRODUCER's record newer than
    the netlist is phase 3 having run, and an unmeasured requirement FAILs."""
    proj = _project(tmp_path)
    _netlist(proj, T_OLD)
    _at(proj / "reports" / "phase3" / "gates" / "stage3_compliance.json",
        json.dumps({"program": "flow_compliance_check"}), T_NEW)
    _at(proj / "reports" / "phase3" / "lvs_verdict.json",
        json.dumps({"status": "PASS"}), T_NEW)
    rc, out = _gate(proj)
    assert rc == 1, out


@pytest.mark.parametrize("kind", ["corner", "legacy_corner", "prelayout", "legacy_prelayout"])
def test_prelayout_inventory_and_audit_do_not_assert_physical_execution(tmp_path, kind):
    import phase3_one_shot_runner as physical
    proj = _project(tmp_path)
    _netlist(proj, T_OLD)
    if "corner" in kind:
        path = physical.emit_step7_corner_disclosure(proj, {
            "corners": [{"name": "SS"}, {"name": "TT"}, {"name": "FF"}]})
        record = json.loads(path.read_text())
        if kind == "corner":
            assert record["record_role"] == "configuration"
        else:
            record.pop("record_role", None)
    else:
        path = proj / "reports/phase3/sta/pre_pnr_summary.json"
        record = {"program": "eda_report_audit:sta", "verdict": "PASS",
                  "summary": {"slack_measurement": "NOT_MEASURED"}}
        if kind == "prelayout":
            record["record_role"] = "prelayout_audit"
    _at(path, json.dumps(record), T_NEW)
    rc, out = _gate(proj)
    assert rc == 0 and "not yet measurable" in out, out
    # The same inventory cannot hide a real current physical attempt.
    _at(proj / "reports/phase3/lvs_verdict.json", '{"status":"PASS"}', T_NEW)
    rc, out = _gate(proj)
    assert rc == 1 and "the input REQUIRES DRC clean" in out, out


def _current_inputs(project, bound):
    name = "netlist_yosys.v" if bound else "netlist.v"
    _at(project / "phase2/stage2/synth" / name,
        "module logic_core; endmodule\n", T_OLD + 10)
    current = G._pl.phase3_signoff_input_identity(project)
    assert (current is not None) == bound
    return current


def _pad_input(project, kind, current, stamp=T_NEW):
    if kind == "missing_report":
        # Run the real producer of the failing checker envelope, not a
        # hand-authored PASS/FAIL approximation of that envelope.
        proc = subprocess.run(
            [sys.executable, str(PROGRAMS / "pad_ring_check.py"), str(project)],
            capture_output=True, text=True, timeout=120)
        assert proc.returncode == 1, proc.stdout + proc.stderr
        path = project / "reports/phase3/padring.json"
        payload = json.loads(path.read_text())
        assert payload["producer"] is None
        assert [row["rule"] for row in payload["findings"]] == ["PADRING_REPORT_ABSENT"]
    else:
        program = {"assignment": "pad_assignment_gen",
                   "wrapper": "io_pad_chip_top_gen"}[kind]
        path = project / "reports/phase3" / (kind + ".json")
        payload = {"program": program, "verdict": "WROTE"}
    if current is not None:
        payload["phase3_inputs"] = current
    _at(path, json.dumps(payload), stamp)
    return path


@pytest.mark.parametrize("kind", ["assignment", "wrapper", "missing_report"])
@pytest.mark.parametrize("bound", [False, True], ids=["legacy", "content_bound"])
@pytest.mark.parametrize("stamp", [T_OLD, T_NEW], ids=["before_synth", "after_synth"])
def test_early_pad_records_do_not_assert_physical_execution(tmp_path, kind, bound, stamp):
    project = _project(tmp_path)
    current = _current_inputs(project, bound)
    path = _pad_input(project, kind, current, stamp)
    original = path.read_bytes()
    rc, out = _gate(project)
    assert rc == 0 and "not yet measurable" in out, out
    assert "BACKED" not in out
    assert path.read_bytes() == original  # still present, including its FAIL


@pytest.mark.parametrize("kind", ["pad_producer", "retained_producer", "tool_failure", "signoff"])
@pytest.mark.parametrize("bound", [False, True], ids=["legacy", "content_bound"])
def test_early_pad_inputs_do_not_hide_current_physical_failure(tmp_path, kind, bound):
    project = _project(tmp_path)
    current = _current_inputs(project, bound)
    for input_kind in ("assignment", "wrapper", "missing_report"):
        _pad_input(project, input_kind, current)
    failed_producer = {"schema": "vibe-ic/padring/1", "program": "pad_ring_gen",
                       "verdict": "FAIL", "reason": "physical tool refused"}
    records = {
        "pad_producer": failed_producer,
        "retained_producer": {
            "schema": "vibe-ic/padring/1", "gate": "pad_ring_check",
            "verdict": "FAIL", "producer": failed_producer,
            "findings": [{"rule": "PADRING_GENERATION_FAILED"}]},
        "tool_failure": {
            "schema": "vibe-ic/padring/1", "gate": "pad_ring_check",
            "verdict": "FAIL", "producer": None,
            "tool_state": "phase3/librelane/padring/state_out.json",
            "findings": [{"rule": "PADRING_TOOL_OUTPUT_UNREADABLE"}]},
        "signoff": {"program": "eda_report_audit:drc", "verdict": "FAIL"},
    }
    payload = records[kind]
    if current is not None:
        payload["phase3_inputs"] = current
    _at(project / "reports/phase3" / (kind + ".json"),
        json.dumps(payload), T_NEW)
    rc, out = _gate(project)
    assert rc == 1 and "the input REQUIRES DRC clean" in out, out


@pytest.mark.parametrize("change", ["netlist", "constraint"])
def test_current_pad_preparation_does_not_revive_stale_physical_attempt(tmp_path, change):
    project = _project(tmp_path)
    current = _current_inputs(project, True)
    _at(project / "reports/phase3/physical_attempt.json", json.dumps({
        "program": "pad_ring_gen", "verdict": "FAIL", "phase3_inputs": current,
    }), T_NEW)
    rc, out = _gate(project)
    assert rc == 1, out
    if change == "netlist":
        _at(project / "phase2/stage2/synth/netlist_yosys.v",
            "module revised_core; endmodule\n", T_OLD + 10)
    else:
        _at(project / "input/constraints/timing.sdc",
            "create_clock -period 12 [get_ports clk]\n", T_OLD + 10)
    current = G._pl.phase3_signoff_input_identity(project)
    for kind in ("assignment", "wrapper", "missing_report"):
        _pad_input(project, kind, current)
    rc, out = _gate(project)
    assert rc == 0 and "not yet measurable" in out, out


def test_pad_preparation_cannot_back_an_asserted_signoff_pass(tmp_path):
    project = _project(tmp_path)
    current = _current_inputs(project, True)
    _pad_input(project, "wrapper", current)
    layer = project / "phase1/generated_docs/L24_SIGNOFF.json"
    payload = json.loads(layer.read_text())
    payload["fields"]["drc_status"] = "PASS"
    layer.write_text(json.dumps(payload))
    rc, out = _gate(project)
    assert rc == 1 and "drc_status" in out, out


@pytest.mark.parametrize("tool_state", [None, "", False, 0, [], {}])
def test_malformed_tool_state_is_not_native_absent_producer_envelope(tmp_path, tool_state):
    project = _project(tmp_path)
    path = _pad_input(project, "missing_report", _current_inputs(project, True))
    payload = json.loads(path.read_text())
    payload["tool_state"] = tool_state
    _at(path, json.dumps(payload), T_NEW)
    rc, out = _gate(project)
    assert rc == 1 and "the input REQUIRES DRC clean" in out, out


def test_checked_in_requirements_remain_future_after_native_absent_pad_check(tmp_path):
    from _hostpaths import require_repo
    source = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
                          "tests", "fixtures", "stage_phase1_on_pass_review",
                          "reject_spm", "phase1", "input_doc", "L7_verification_plan.txt")
    project = _project(tmp_path)
    (project / "input/docs/spec.md").write_bytes(source.read_bytes())
    doc = P.emit_l_doc_skeleton("L24", "unknown", project_dir=project)
    doc.pop("evidence", None)
    (project / "phase1/generated_docs/L24_SIGNOFF.json").write_text(json.dumps(doc))
    assert any(row["stated"] and row["check"] == "DRC"
               for row in doc["fields"]["signoff_requirements"])
    _pad_input(project, "missing_report", _current_inputs(project, False))
    rc, out = _gate(project)
    assert rc == 0 and "not yet measurable" in out, out

