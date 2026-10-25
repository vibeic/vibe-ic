"""Source catalogs are facts; an FSM implementation needs a complete contract.

Neutral prose artifacts retain the grammar of public extraction defects without
borrowing reference RTL, expected benchmark behavior, or a benchmark identity.
Every extraction check uses the shipped L6 producer and its real layer gate.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import time

import pytest

import phase1_doc_one_shot_runner as phase1
import l6_fsm_scaffold_actionable_check as gate
import phase2_scaffold_gen as scaffold


FIXTURES = Path(__file__).parent / "fixtures" / "fsm_source_contract"


def _produce(tmp_path, fixture):
    text = (FIXTURES / fixture).read_text()
    return _produce_text(tmp_path, text)


def _produce_text(tmp_path, text):
    (tmp_path / "input" / "docs").mkdir(parents=True)
    (tmp_path / "input" / "docs" / "control.md").write_text(text)
    phase1.gen_l6_control_logic(tmp_path, {"control.md": text})
    l6 = json.loads((tmp_path / "phase1" / "generated_docs" /
                     "L6_CONTROL_LOGIC.json").read_text())
    return l6, gate.evaluate(tmp_path)


def _names(l6):
    return [state["name"] for state in l6["fsm_states"]]


def _edges(l6):
    return [(state["name"], edge) for state in l6["fsm_states"]
            for edge in state.get("transitions", [])]


def test_operation_parameters_are_not_state_declarations(tmp_path):
    l6, report = _produce(tmp_path, "operation_codes.md")
    assert _names(l6) == []
    assert report["fsm_checked"] is False


def test_register_noun_is_not_a_state_and_numeric_states_survive(tmp_path):
    l6, report = _produce(tmp_path, "numeric_controller.md")
    assert set(_names(l6)) == {"0", "1"}
    assert {state["encoding_value"] for state in l6["fsm_states"]} == {0, 1}
    assert "REGISTER" not in _names(l6)
    # No implicit source for the conditional transition's current state.
    assert _edges(l6) == []
    assert report["verdict"] == "FAIL"


def test_lowercase_catalog_and_explicit_prose_edges_reach_consumer(tmp_path):
    l6, report = _produce(tmp_path, "lowercase_controller.md")
    assert _names(l6) == ["idle", "phase_a", "phase_b"]
    assert {(src, edge["to"]) for src, edge in _edges(l6)} == {
        ("idle", "phase_a"), ("phase_a", "phase_b"),
        ("phase_a", "phase_a"), ("phase_b", "idle"),
        ("phase_b", "phase_b")}
    text = (FIXTURES / "lowercase_controller.md").read_text()
    for _, edge in _edges(l6):
        assert edge["source_literal"] in text
        assert edge["trigger"] in edge["source_literal"]
    assert report["verdict"] == "PASS", report


def test_missing_behavior_is_not_replaced_by_synthetic_transitions(tmp_path):
    l6, report = _produce(tmp_path, "incomplete_detector.md")
    assert _names(l6) == ["REST", "Q1", "Q2"]
    assert _edges(l6) == []
    assert report["transitions_declared"] == 0
    assert report["verdict"] == "FAIL"
    assert "TODO" in scaffold.emit_fsm_v("neutral", scaffold.derive_fsm_states(l6))


def test_case_distinct_declared_states_and_transitions_stay_distinct(tmp_path):
    l6, _ = _produce_text(tmp_path, """FSM states:
idle: Transition to Idle state occurs immediately.
Idle: Transition to idle state occurs immediately.
""")
    assert _names(l6) == ["idle", "Idle"]
    assert {(src, edge["to"]) for src, edge in _edges(l6)} == {
        ("idle", "Idle"), ("Idle", "idle")}


def test_unsupported_prose_does_not_claim_an_edge(tmp_path):
    l6, report = _produce_text(tmp_path, """FSM states:
REST: The prose mentions BUSY state, but does not state a transition.
BUSY: A destination will be specified later.
""")
    assert _names(l6) == ["REST", "BUSY"]
    assert _edges(l6) == []
    assert report["verdict"] == "FAIL"


def test_case_distinct_catalog_elaborates_as_scaffold_only(tmp_path):
    l6, _ = _produce_text(tmp_path, """FSM states:
idle: Initial state.
Idle: Another explicitly named state.
""")
    rtl = scaffold.emit_fsm_v("neutral", scaffold.derive_fsm_states(l6))
    assert "TODO" in rtl  # elaboration is not implemented transition behavior
    if not shutil.which("iverilog"):
        pytest.skip("iverilog unavailable; actual elaboration unmeasured")
    source = tmp_path / "scaffold.v"
    source.write_text(rtl)
    compiled = subprocess.run(["iverilog", "-g2012", "-s", "neutral_fsm", "-o",
                               str(tmp_path / "scaffold.vvp"), str(source)],
                              capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stderr


def test_generic_parameters_need_local_state_ownership(tmp_path):
    l6, _ = _produce_text(tmp_path, """FSM state encodings:
parameter armed = 2'b00;
parameter Working = 2'b01;
parameter FINISHED = 2'b10;

Operation codes:
parameter SUM_UNSIGNED = 4'b0001;
""")
    assert set(_names(l6)) == {"armed", "Working", "FINISHED"}


def test_case_distinct_targets_are_not_resolved_by_case_guessing(tmp_path):
    l6, _ = _produce_text(tmp_path, """FSM states:
quiet: Transition to ACTIVE state occurs immediately.
active: A different case-sensitive identifier.
""")
    assert _names(l6) == ["quiet", "active"]
    assert _edges(l6) == []


def test_negated_guard_is_preserved_but_negated_transition_is_not(tmp_path):
    l6, _ = _produce_text(tmp_path, """FSM states:
QUIET: If not ready, transitions to ACTIVE state.
ACTIVE: Does not transition to QUIET state.
""")
    assert {(src, edge["to"]) for src, edge in _edges(l6)} == {("QUIET", "ACTIVE")}
    assert _edges(l6)[0][1]["trigger"] == "If not ready, transitions to ACTIVE state."


def test_gate_pass_is_counterfactual_source_contract_only(tmp_path):
    _, report = _produce(tmp_path, "lowercase_controller.md")
    assert report["verdict"] == "PASS"
    assert report.get("assessment_scope") == "source_fsm_scaffold_contract"
    assert report.get("fsm_contract_is_counterfactual") is True
    assert report.get("actual_rtl_entrypoint") == "design_one_shot_runner.step_rtl_gen"
    assert report.get("behavioral_implementation_status") == "NOT_MEASURED"
    # Preserve the legacy contract-applicability field and admission behavior.
    assert report["scaffold_consumer_runs"] is True


def test_real_phase2_table_dispatch_emits_and_executes(tmp_path):
    """Drive the same closed contract the production runner actually consumes."""
    import design_one_shot_runner as runner

    spec = {"module": "neutral_fsm", "kind": "moore_seq", "input": "sample",
            "output": "hit", "clk": "clk",
            "reset": {"name": "reset", "mode": "sync", "polarity": "high", "to": "rest"},
            "encoding": {"rest": 0, "seen": 1, "done": 2},
            "transitions": {"rest": {"0": "rest", "1": "seen"},
                            "seen": {"0": "done", "1": "seen"},
                            "done": {"0": "rest", "1": "seen"}},
            "outputs": {"rest": 0, "seen": 0, "done": 1}}
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "rtl_spec.json").write_text(json.dumps(spec))
    result = runner._try_deterministic_rtl_dispatch(tmp_path, time.time())
    assert result is not None and result.status == "PASS", result
    generated = list((tmp_path / "phase2" / "stage1" / "rtl").glob("*.sv"))
    assert len(generated) == 1
    assert "TODO" not in generated[0].read_text()
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        pytest.skip("iverilog/vvp unavailable; actual elaboration unmeasured")
    tb = tmp_path / "control_tb.v"
    tb.write_text("""module test;
reg clk=0, reset=1, sample=0; wire hit;
neutral_fsm dut(.clk(clk), .reset(reset), .sample(sample), .hit(hit));
always #5 clk=~clk;
task step; input value; input expected;
begin @(negedge clk); sample=value; @(posedge clk); #1;
if(hit!==expected) $fatal(1,"transition output mismatch"); end endtask
initial begin @(posedge clk); #1; reset=0;
step(0,0); step(1,0); step(1,0); step(0,1); step(1,0);
step(0,1); step(0,0); $display("FUNCTIONAL_PASS"); $finish; end
endmodule
""")
    image = tmp_path / "fsm.vvp"
    compiled = subprocess.run(["iverilog", "-g2012", "-s", "test", "-o", str(image),
                               str(generated[0]), str(tb)], capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stderr
    run = subprocess.run(["vvp", str(image)], capture_output=True, text=True)
    assert run.returncode == 0 and "FUNCTIONAL_PASS" in run.stdout, run.stdout + run.stderr
