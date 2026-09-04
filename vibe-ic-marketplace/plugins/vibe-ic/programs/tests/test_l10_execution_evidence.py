"""Step-4 L10 verdicts come from execution, never testbench prose."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import _l10_execution as EXEC  # noqa: E402
import design_one_shot_runner as RUNNER  # noqa: E402
import l10_tb_conformance_check as GATE  # noqa: E402
import testbench_gen as TBGEN  # noqa: E402


def _project(tmp_path: Path, names=("vector_alpha",)) -> tuple[Path, Path]:
    project = tmp_path / "project"
    docs = project / "phase1/generated_docs"
    docs.mkdir(parents=True)
    l10 = docs / "L10_TEST_CASES.json"
    l10.write_text(json.dumps({
        "test_cases": [{"name": name, "kind": "functional_vector"}
                       for name in names]
    }))
    tb = project / "phase2/stage1/sim/tb"
    tb.mkdir(parents=True)
    # This text really drives a DUT-shaped module; its comments still have no
    # verdict authority.
    (tb / "tb_driver.v").write_text(
        "module tb_driver; dut u_dut(); // vector_alpha PASS\nendmodule\n")
    return project, l10


def _run_gate(project: Path, l10: Path) -> tuple[int, dict]:
    out = project / "reports/phase2/gates/l10.json"
    rc = GATE.main([
        "--l10", str(l10),
        "--tb-dir", str(project / "phase2/stage1/sim/tb"),
        "--summary", str(project / "phase2/stage1/sim/summary.txt"),
        "--project", str(project),
        "--out", str(out),
    ])
    return rc, json.loads(out.read_text())


def _fake_sim(build_rc=0, run_rc=0, run_text=""):
    def dispatch(argv, run_dir, container, tool, timeout):
        if "--version" in argv:
            return 0, "Verilator test"
        if "--binary" in argv:
            return build_rc, "build"
        return run_rc, run_text
    return dispatch


def test_comment_and_summary_pass_cannot_credit_a_case(tmp_path):
    project, l10 = _project(tmp_path)
    (project / "phase2/stage1/sim/summary.txt").write_text(
        "vector_alpha PASS\n")
    rc, report = _run_gate(project, l10)
    assert rc == 1
    assert report["ok"] == 0 and report["not_executed"] == 1
    assert report["results"][0]["status"] == EXEC.NOT_EXECUTED


def test_completed_record_drives_explicit_pass_and_fail(tmp_path):
    project, l10 = _project(tmp_path, ("vector_alpha", "vector_beta"))
    EXEC.write_record(project, l10, [
        {"id": "vector_alpha", "verdict": "PASS", "sim_executed": True},
        {"id": "vector_beta", "verdict": "FAIL", "sim_executed": True},
    ], producer="test", source_junit=Path("results.xml"))
    rc, report = _run_gate(project, l10)
    assert rc == 1
    assert (report["ok"], report["fail"], report["not_executed"]) == (1, 1, 0)
    assert {row["status"] for row in report["results"]} == {"pass", "fail"}


def test_record_is_bound_to_exact_l10_bytes(tmp_path):
    project, l10 = _project(tmp_path)
    EXEC.write_record(project, l10, [
        {"id": "vector_alpha", "verdict": "PASS", "sim_executed": True},
    ], producer="test")
    l10.write_text(json.dumps({
        "test_cases": [{"name": "vector_alpha", "kind": "functional_vector",
                        "expected": "changed"}]
    }))
    loaded = EXEC.load_record(project, l10)
    assert loaded["available"] is False
    assert loaded["reason"] == "execution_record_l10_hash_mismatch"
    rc, report = _run_gate(project, l10)
    assert rc == 1 and report["not_executed"] == 1


def test_verdict_word_without_literal_execution_boolean_gets_no_credit(tmp_path):
    project, l10 = _project(tmp_path)
    for sim_executed in (None, False, "true"):
        row = {"id": "vector_alpha", "verdict": "PASS"}
        if sim_executed is not None:
            row["sim_executed"] = sim_executed
        EXEC.write_record(project, l10, [row], producer="test")
        rc, report = _run_gate(project, l10)
        assert rc == 1
        assert report["ok"] == 0 and report["not_executed"] == 1


def test_executor_publishes_case_record_from_actual_run(tmp_path):
    project, l10 = _project(tmp_path)
    tb = project / "phase2/stage1/sim/tb/vector_alpha.v"
    tb.write_text(
        "module vector_alpha; dut u_dut(); initial begin #1; $finish; end "
        "endmodule\n")
    report = {}
    assert TBGEN.run_unit_tbs(
        project, report=report, dispatch=_fake_sim()) == 2
    record = EXEC.load_record(project, l10)
    assert record["available"] is True
    assert record["rows"]["vector_alpha"]["verdict"] == EXEC.PASS
    assert record["rows"]["vector_alpha"]["sim_executed"] is True


def test_substance_scaffold_run_does_not_become_case_pass(tmp_path):
    project, l10 = _project(tmp_path)
    tb = project / "phase2/stage1/sim/tb/vector_alpha.v"
    tb.write_text(
        f"// {TBGEN.ORACLE_NONE_MARKER}\n"
        "module vector_alpha; dut u_dut(); initial begin #1; $finish; end "
        "endmodule\n")
    report = {}
    TBGEN.run_unit_tbs(project, report=report, dispatch=_fake_sim())
    record = EXEC.load_record(project, l10)
    row = record["rows"]["vector_alpha"]
    assert row["verdict"] == EXEC.NOT_EXECUTED
    assert row["sim_executed"] is False
    rc, gate_report = _run_gate(project, l10)
    assert rc == 1 and gate_report["not_executed"] == 1


def test_unavailable_rerun_clears_stale_record(tmp_path):
    project, l10 = _project(tmp_path)
    EXEC.write_record(project, l10, [
        {"id": "vector_alpha", "verdict": "PASS", "sim_executed": True},
    ], producer="old")
    tb = project / "phase2/stage1/sim/tb/vector_alpha.v"
    tb.write_text("module vector_alpha; endmodule\n")

    def unavailable(argv, run_dir, container, tool, timeout):
        return 127, "simulator unavailable"

    assert TBGEN.run_unit_tbs(project, report={}, dispatch=unavailable) == -2
    assert EXEC.resolve_record(project) is None


def test_executed_failure_cannot_be_waived():
    case = {"name": "intent", "kind": "verification_intent"}
    record = {
        "available": True,
        "rows": {"intent": {"verdict": EXEC.FAIL,
                              "sim_executed": True}},
    }
    results, ok, failed = GATE.evaluate(
        [case], "intent PASS", "intent PASS",
        analog_anchor="reviewable", execution_record=record)
    assert (ok, failed) == (0, 1)
    assert results[0]["status"] == "fail"
    assert results[0]["waived"] is False


def test_not_executed_vocabulary_matches_runner():
    assert EXEC.NOT_EXECUTED == RUNNER.NOT_EXECUTED_STATUS


def test_flow_declares_execution_record_consumer():
    flow = (PROGRAMS.parent / "flow/phase1_phase2_phase3.yaml").read_text()
    assert "l10_tb_conformance_check" in flow
    assert "reports/phase2/sim/l10_execution.json" in flow
    assert "never infers a verdict from testbench text" in flow
