"""#220 — the self-disabling-condition guard.

A flow step conditioned on the artefact whose absence IS its failure mode is
disabled by exactly the situation it was written for. This suite pins the four
rules that make that class detectable, and — just as importantly — pins the
cases that must NOT fire, because a sweep that stripped conditions would break
every legitimately-scoped step and be worse than the bug.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PROG = Path(__file__).resolve().parent.parent / (
    "flow_condition_reachability_check.py")
FLOW = Path(__file__).resolve().parent.parent.parent / (
    "flow/phase1_phase2_phase3.yaml")

sys.path.insert(0, str(PROG.parent))
import flow_condition_reachability_check as _g  # noqa: E402


def _write(tmp_path, steps):
    p = tmp_path / "flow.yaml"
    p.write_text(yaml.safe_dump({"steps": steps}, sort_keys=False))
    return _g.check_flow(p)


# ---------------------------------------------------------------------------
# R1 — self-output gating
# ---------------------------------------------------------------------------

def test_r1_fires_on_step_gated_by_its_own_required_output(tmp_path):
    """The step-44 shape: a step that can only run once it already succeeded."""
    res = _write(tmp_path, [{
        "id": 44,
        "name": "Reliability qualification",
        "condition": {"files_exist": ["mfg/htol_results.json"]},
        "condition_kind": "design_dependent",
        "required_outputs": ["mfg/htol_results.json"],
        "gate": {"program_exit_zero": "htol_attestation_check ."},
    }])
    r1 = [f for f in res["findings"] if f["rule"] == "R1"]
    assert len(r1) == 1
    assert r1[0]["step"] == 44
    assert res["verdict"] == "FAIL"


def test_r1_silent_on_upstream_gated_step(tmp_path):
    """The step-43 shape — gates on an UPSTREAM artefact. Legitimate scoping.

    This is the control that keeps the guard from becoming a condition-stripper:
    43 and 44 sit in the same stage and differ ONLY in which artefact they gate
    on, and exactly one of them is the defect.
    """
    res = _write(tmp_path, [{
        "id": 43,
        "name": "Final Test",
        "condition": {"files_exist": ["mfg/silicon_received.json"]},
        "condition_kind": "design_dependent",
        "required_outputs": ["mfg/final_test_yield.json"],
        "gate": {"program_exit_zero": "final_test_attestation_check ."},
    }])
    assert res["verdict"] == "PASS"
    assert res["findings"] == []


def test_r1_accepts_the_219_not_run_record_escape(tmp_path):
    """`any_of` with a non-self alternative trigger is the sanctioned repair."""
    res = _write(tmp_path, [{
        "id": "DT1",
        "name": "at-speed ATPG",
        "condition": {
            "any_of": True,
            "files_exist": ["dft/cut_netlist.v",
                            "dft/transition_atpg_not_run.json"],
        },
        "condition_kind": "design_dependent",
        "required_outputs": ["dft/cut_netlist.v"],
        "gate": {"program_exit_zero": "transition_coverage_check ."},
    }])
    assert [f for f in res["findings"] if f["rule"] == "R1"] == []


def test_r1_any_of_without_alternative_still_fires(tmp_path):
    """`any_of` over self-outputs ONLY is not an escape — nothing can reach it."""
    res = _write(tmp_path, [{
        "id": "X",
        "condition": {"any_of": True, "files_exist": ["a.json", "b.json"]},
        "condition_kind": "design_dependent",
        "required_outputs": ["a.json", "b.json"],
        "gate": {"program_exit_zero": "x ."},
    }])
    assert [f for f in res["findings"] if f["rule"] == "R1"]


def test_r1_gate_level_exempted_by_hard_sibling(tmp_path):
    """The step-18 shape: an unconditional sibling already fails loudly."""
    res = _write(tmp_path, [{
        "id": 18,
        "condition_kind": "design_dependent",
        "required_outputs": ["pnr/spare_cells.json"],
        "gate": {"all_of": [
            {"files_exist": ["pnr/spare_cells.json"]},
            {"optional_program_exit_zero": {
                "command": "spare_cell_coverage_check .",
                "condition_files_exist": ["pnr/spare_cells.json"]}},
        ]},
    }])
    assert res["verdict"] == "PASS"


def test_r1_gate_level_not_exempted_by_any_of_sibling(tmp_path):
    """The step-27 shape: an `any_of` sibling can be met by the OTHER path
    while the conditioned check still silently skips."""
    res = _write(tmp_path, [{
        "id": 27,
        "condition_kind": "design_dependent",
        "required_outputs": ["si.rpt", "si.json"],
        "gate": {"all_of": [
            {"files_exist": ["si.rpt", "si.json"], "any_of": True},
            {"optional_program_exit_zero": {
                "command": "si_crosstalk_check .",
                "condition_files_exist": ["si.rpt"]}},
        ]},
    }])
    assert [f for f in res["findings"] if f["rule"] == "R1"]


def test_r1_rationale_escape_requires_substance(tmp_path):
    """A rubber-stamp rationale does not buy an exemption."""
    def build(rationale):
        return _write(tmp_path, [{
            "id": 4,
            "condition_kind": "design_dependent",
            "required_outputs": ["sim/results.xml"],
            "gate": {"all_of": [{"optional_program_exit_zero": {
                "command": "waiver_check .",
                "condition_files_exist": ["sim/results.xml"],
                "condition_rationale": rationale}}]},
        }])
    assert [f for f in build("ok").get("findings") if f["rule"] == "R1"]
    long = ("validates a claim rather than measuring the design; with no "
            "waiver asserted there is nothing to judge")
    assert [f for f in build(long)["findings"] if f["rule"] == "R1"] == []


# ---------------------------------------------------------------------------
# R2 — undeclared condition intent
# ---------------------------------------------------------------------------

def test_r2_fires_when_condition_kind_omitted(tmp_path):
    res = _write(tmp_path, [{
        "id": "A1",
        "condition": {"files_exist": ["analog/blocks.json"]},
        "gate": {"program_exit_zero": "x ."},
    }])
    assert [f for f in res["findings"] if f["rule"] == "R2"]


def test_r2_silent_when_kind_declared(tmp_path):
    res = _write(tmp_path, [{
        "id": "A1",
        "condition": {"files_exist": ["analog/blocks.json"]},
        "condition_kind": "design_dependent",
        "gate": {"program_exit_zero": "x ."},
    }])
    assert res["verdict"] == "PASS"


def test_r2_rejects_unknown_kind(tmp_path):
    res = _write(tmp_path, [{
        "id": "A1",
        "condition": {"files_exist": ["analog/blocks.json"]},
        "condition_kind": "whenever",
        "gate": {"program_exit_zero": "x ."},
    }])
    assert [f for f in res["findings"] if f["rule"] == "R2"]


def test_r2_does_not_fire_on_unconditioned_step(tmp_path):
    res = _write(tmp_path, [{"id": 1, "gate": {"program_exit_zero": "x ."}}])
    assert res["verdict"] == "PASS"


# ---------------------------------------------------------------------------
# R3 — vacuous gate
# ---------------------------------------------------------------------------

def test_r3_fires_on_all_optional_gate(tmp_path):
    """The step-14 shape: passes with zero programs run, zero files checked."""
    res = _write(tmp_path, [{
        "id": 14,
        "required_outputs": ["synth/netlist.v"],
        "gate": {"all_of": [
            {"optional_program_exit_zero": {
                "command": "yosys_hilomap_required_check .",
                "condition_files_exist": ["synth"]}},
            {"optional_program_exit_zero": {
                "command": "yosys_script_template_check .",
                "condition_files_exist": ["synth"]}},
        ]},
    }])
    assert [f for f in res["findings"] if f["rule"] == "R3"]


def test_r3_silent_once_one_hard_subgate_exists(tmp_path):
    res = _write(tmp_path, [{
        "id": 14,
        "required_outputs": ["synth/netlist.v"],
        "gate": {"all_of": [
            {"files_exist": ["synth/netlist.v"]},
            {"optional_program_exit_zero": {
                "command": "yosys_hilomap_required_check .",
                "condition_files_exist": ["synth"]}},
        ]},
    }])
    assert [f for f in res["findings"] if f["rule"] == "R3"] == []


# ---------------------------------------------------------------------------
# R4 — a declared tracked defect stays visible
# ---------------------------------------------------------------------------

def test_r4_tracked_defect_is_reported_not_suppressed(tmp_path):
    """The marker moves a finding out of the BLOCKING set, never out of the
    report — and the verdict must never read PASS while one is present."""
    res = _write(tmp_path, [{
        "id": "DT1",
        "condition": {"files_exist": ["dft/cut_netlist.v"]},
        "condition_kind": "design_dependent",
        "condition_defect_tracked": "#219",
        "gate": {"program_exit_zero": "transition_coverage_check ."},
    }])
    assert res["verdict"] == "TRACKED_DEFECTS_ONLY"
    assert res["verdict"] != "PASS"
    r4 = [f for f in res["findings"] if f["rule"] == "R4"]
    assert len(r4) == 1 and r4[0]["tracked_by"] == "#219"
    assert res["blocking_count"] == 0


def test_r4_does_not_mask_an_untracked_blocking_finding(tmp_path):
    """One tracked step must not turn another step's real defect green."""
    res = _write(tmp_path, [
        {"id": "DT1",
         "condition": {"files_exist": ["dft/cut_netlist.v"]},
         "condition_kind": "design_dependent",
         "condition_defect_tracked": "#219",
         "gate": {"program_exit_zero": "x ."}},
        {"id": 44,
         "condition": {"files_exist": ["mfg/htol_results.json"]},
         "condition_kind": "design_dependent",
         "required_outputs": ["mfg/htol_results.json"],
         "gate": {"program_exit_zero": "y ."}},
    ])
    assert res["verdict"] == "FAIL"
    assert res["blocking_count"] >= 1


# ---------------------------------------------------------------------------
# The real flow — the regression this whole change exists to hold
# ---------------------------------------------------------------------------

def test_shipped_flow_has_no_blocking_self_disabling_condition():
    res = _g.check_flow(FLOW)
    blocking = [f for f in res["findings"] if not f.get("tracked_by")]
    assert not blocking, (
        "self-disabling condition(s) reintroduced into the shipped flow:\n"
        + "\n".join(f"  [{f['rule']}] step {f['step']}: {f['detail']}"
                    for f in blocking))


def test_shipped_flow_declares_every_condition_kind():
    """No condition may decide its own visibility by omission."""
    doc = yaml.safe_load(FLOW.read_text())
    undeclared = [s.get("id") for s in doc["steps"]
                  if isinstance(s, dict) and s.get("condition")
                  and s.get("condition_kind") is None]
    assert not undeclared, f"steps with a condition but no kind: {undeclared}"


def test_cli_exit_codes_and_banner():
    r = subprocess.run([sys.executable, str(PROG), "."],
                       capture_output=True, text=True)
    assert r.returncode == 0
    # TRACKED_DEFECTS_ONLY exits 0 but must never be rendered as PASS.
    if "TRACKED_DEFECTS_ONLY" in r.stdout:
        assert "[PASS]" not in r.stdout


def test_cli_fails_on_a_planted_self_disabling_condition(tmp_path):
    """Negative control: plant the defect, the gate must go red."""
    doc = yaml.safe_load(FLOW.read_text())
    for s in doc["steps"]:
        if s.get("id") == 43:
            s["condition"] = {"files_exist": s["required_outputs"][:1]}
            break
    p = tmp_path / "planted.yaml"
    p.write_text(yaml.safe_dump(doc, sort_keys=False))
    r = subprocess.run([sys.executable, str(PROG), ".", "--flow", str(p)],
                       capture_output=True, text=True)
    assert r.returncode == 1
    assert "R1" in r.stdout
