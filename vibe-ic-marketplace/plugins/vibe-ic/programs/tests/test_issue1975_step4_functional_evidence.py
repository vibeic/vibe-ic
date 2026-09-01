"""Issue #1975 — Step 4 must not turn connectivity into functional evidence.

The bidirectional control is intentionally split across the same public gates
the flow runs:

* positive: a self-checking TB under ``sim_full_stack/`` is discovered, and a
  non-zero professional JUnit denominator closes the functional requirement;
* negatives: placeholder/no-DUT, connectivity-only, and absent TB trees do not
  release Step 4.

The tests are structural and chip-agnostic. No simulator is needed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import cpu_functional_oracle_waiver_check as ORACLE  # noqa: E402
import design_one_shot_runner as RUNNER  # noqa: E402
import flow_compliance_check as FLOW  # noqa: E402
import professional_tb_gen as PROFESSIONAL_GEN  # noqa: E402
import vacuous_testbench_check as VACUOUS  # noqa: E402
from _hostpaths import require_repo  # noqa: E402


SELF_CHECKING_TB = """\
module tb_dut_core;
  reg clk = 0;
  reg [7:0] a = 1, b = 2;
  wire [7:0] q;
  dut_core u_dut (.clk(clk), .a(a), .b(b), .q(q));
  always #5 clk = ~clk;
  initial begin
    #11;
    assert (q === (a + b)) else $fatal(1, "declared add behavior failed");
    $finish;
  end
endmodule
"""

CONNECTIVITY_ONLY_TB = """\
module tb_dut_core;
  reg clk = 0;
  wire alive;
  dut_core u_dut (.clk(clk), .alive(alive));
  always #5 clk = ~clk;
  initial begin #20; $display("FULL_STACK_TB_DONE"); $finish; end
endmodule
"""

PLACEHOLDER_TB = """\
module tb_dut_core;
  initial begin
    $display("PASS_PLACEHOLDER (replace with real stimulus)");
    $finish;
  end
  // dut_core u_dut (.clk(clk));
endmodule
"""

JUNIT_PASS = (
    "<testsuites><testsuite name='functional' tests='1' failures='0' "
    "errors='0' skipped='0'><testcase name='declared_behavior'/>"
    "</testsuite></testsuites>"
)


def _full_stack_tb(project: Path, body: str) -> Path:
    root = project / "phase2/stage1/sim_full_stack"
    root.mkdir(parents=True, exist_ok=True)
    (root / "tb_dut_core_full.v").write_text(body)
    return root


def _connectivity_bridge(project: Path) -> None:
    run = project / "phase2/stage1/sim_full_stack/generic_full_stack_run"
    run.mkdir(parents=True, exist_ok=True)
    log = run / "full_stack.log"
    log.write_text("FULL_STACK_TB_INIT\nFULL_STACK_TB_DONE bytes=0 bits=0\n")
    assert RUNNER._emit_connectivity_sim_bridge(
        project, log, "dut_core", "reference model not yet filled")


def _declarations_and_coverage(project: Path) -> None:
    docs = project / "phase1/generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L10_TEST_CASES.json").write_text(json.dumps({
        "test_cases": [{"id": "add_nominal"}, {"id": "add_corner"}]}))
    (docs / "L12_BEHAVIORAL_SEQUENCES.json").write_text(json.dumps({
        "sequences": [{"id": "reset_then_add"}]}))
    cov = project / "reports/phase2/coverage/coverage_verilator.json"
    cov.parent.mkdir(parents=True, exist_ok=True)
    cov.write_text(json.dumps({
        "tool": "verilator",
        "totals": {
            "line": {"covered": 8, "total": 8, "pct": 100.0},
            "toggle": {"covered": 7, "total": 8, "pct": 87.5},
            "branch": {"covered": 4, "total": 4, "pct": 100.0},
        },
    }))


def _professional_pass(project: Path) -> None:
    out = project / "phase2/stage1/sim_professional/dut_core"
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.xml").write_text(JUNIT_PASS)


def _step4_gate() -> dict:
    return {
        "id": 4,
        "name": "Simulation",
        "stage": "stage1",
        "gate": {"all_of": [
            {"files_exist": ["phase2/stage1/sim/results.xml",
                              "phase2/stage1/sim/pass.flag"],
             "any_of": True},
            {"optional_program_exit_zero": {
                "command": ("cpu_functional_oracle_waiver_check . --json "
                            "reports/phase2/gates/oracle_requirement.json"),
                "condition_files_exist": ["phase2/stage1/sim/results.xml"],
                "absent_condition_reason": "no simulation result to classify",
            }},
            {"program_exit_zero": ("vacuous_testbench_check . --json "
                                   "reports/phase2/gates/vacuous.json")},
        ]},
    }


def test_positive_sim_full_stack_tb_is_discovered_and_functional_passes(
        tmp_path):
    root = _full_stack_tb(tmp_path, SELF_CHECKING_TB)
    _connectivity_bridge(tmp_path)
    _professional_pass(tmp_path)
    _declarations_and_coverage(tmp_path)

    vac = VACUOUS.check(tmp_path)
    assert vac["verdict"] == "PASS", vac
    assert Path(vac["sim_root"]) == root
    code, message = ORACLE._evaluate(tmp_path)
    assert code == 0, message

    report = tmp_path / "reports/phase2/gates/oracle.json"
    assert ORACLE.main([str(tmp_path), "--json", str(report)]) == 0
    rec = json.loads(report.read_text())
    assert rec["functional_test_denominator"] == {
        "source": "phase2/stage1/sim_professional/dut_core/results.xml",
        "tests_run": 1,
        "tests_passed": 1,
        "tests_failed": 0,
        "tests_skipped": 0,
    }
    assert rec["declared_denominator"]["total_declared_rows"] == 3
    assert rec["coverage"]["measured"] is True

    result = FLOW.check_step(tmp_path, _step4_gate(), waivers={})
    assert result.status == "PASS", (result.status, result.reasons)
    inline = RUNNER.step_step4_functional_evidence(tmp_path, "digital")
    assert inline.status == "PASS", inline
    assert RUNNER._aggregate_verdict([inline]) == "PASS"


def test_real_reference_tb_in_sim_full_stack_is_not_hidden(tmp_path):
    real_tb = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "tools",
        "protocol_tb", "aid_class_reference_tb.v")
    root = tmp_path / "phase2/stage1/sim_full_stack"
    root.mkdir(parents=True)
    (root / "aid_class_reference_tb.v").symlink_to(real_tb)

    rec = VACUOUS.check(tmp_path)
    assert rec["verdict"] == "PASS", rec
    assert Path(rec["sim_root"]) == root
    assert rec["testbenches_scanned"] == 1


def test_placeholder_no_dut_tb_in_sim_full_stack_fails(tmp_path):
    root = _full_stack_tb(tmp_path, PLACEHOLDER_TB)
    res = VACUOUS.check(tmp_path)
    assert Path(res["sim_root"]) == root
    assert res["verdict"] == "FAIL", res
    assert "no_live_instantiation" in res["detectors_tripped"]


def test_connectivity_only_tb_is_incomplete_not_waived(tmp_path):
    _full_stack_tb(tmp_path, CONNECTIVITY_ONLY_TB)
    _connectivity_bridge(tmp_path)
    _declarations_and_coverage(tmp_path)

    # It is real connectivity, so the vacuity gate correctly stays silent.
    assert VACUOUS.check(tmp_path)["verdict"] == "PASS"
    code, message = ORACLE._evaluate(tmp_path)
    assert code == 1, message
    assert message.startswith("INCOMPLETE:")
    assert "0 functional tests ran for 3 declared" in message
    assert "No waiver is granted" in message

    report = tmp_path / "reports/phase2/gates/oracle.json"
    assert ORACLE.main([str(tmp_path), "--json", str(report)]) == 1
    rec = json.loads(report.read_text())
    assert rec["verdict"] == "INCOMPLETE"
    assert rec["enforcement"] == "BLOCKING"
    assert rec["functional_test_denominator"]["tests_run"] == 0
    assert rec["coverage"]["measured"] is True
    inline = RUNNER.step_step4_functional_evidence(tmp_path, "digital")
    assert inline.status == "FAIL", inline
    assert "INCOMPLETE" in inline.detail
    assert inline.extras["fallback_skill"] == "testbench-gen"
    assert RUNNER._aggregate_verdict([inline]) == "FAIL"


def test_connectivity_only_result_stops_step4_by_run(tmp_path):
    _full_stack_tb(tmp_path, CONNECTIVITY_ONLY_TB)
    _connectivity_bridge(tmp_path)
    result = FLOW.check_step(tmp_path, _step4_gate(), waivers={})
    assert result.status == "FAIL", (result.status, result.reasons)
    assert not any("WAIVED-DEFERRED" in reason for reason in result.reasons)


def test_absent_tb_cannot_release_step4(tmp_path):
    result = FLOW.check_step(tmp_path, _step4_gate(), waivers={})
    assert result.status not in {"PASS", "WAIVED"}, (
        result.status, result.reasons)
    vac = VACUOUS.check(tmp_path)
    assert vac["verdict"] == "NOT_APPLICABLE"
    assert VACUOUS.main([str(tmp_path)]) == 2
    inline = RUNNER.step_step4_functional_evidence(tmp_path, "digital")
    assert inline.status == "FAIL", inline
    assert RUNNER._aggregate_verdict([inline]) == "FAIL"


def test_generic_program_first_hook_routes_to_expert_as_incomplete(
        tmp_path, monkeypatch):
    out = tmp_path / "phase2/stage1/sim_professional/dut_core"
    out.mkdir(parents=True)
    monkeypatch.setattr(PROFESSIONAL_GEN, "generate", lambda _project: {
        "status": "PASS", "dut_kind": "generic", "out_dir": str(out),
        "files": ["tb_dut_core.py"], "reference_model_tier": "hook",
    })
    (out / "tb_dut_core.py").write_text("# unfilled reference hook\n")

    step = RUNNER.step_professional_tb_gen(
        tmp_path, "dut_core", "configured-container")
    assert step.status == "INCOMPLETE", step
    assert step.extras["program_first"] == "professional_tb_gen"
    assert step.extras["fallback_skill"] == "testbench-gen"
    rec = json.loads((tmp_path / "reports/phase2/gates/"
                      "professional_tb.json").read_text())
    assert rec["status"] == "INCOMPLETE"
    assert rec["fallback_skill"] == "testbench-gen"


def test_zero_test_junit_is_not_a_functional_denominator(tmp_path):
    out = tmp_path / "sim_professional"
    out.mkdir()
    (out / "results.xml").write_text(
        "<testsuite tests='0' failures='0' errors='0' skipped='0'/>")
    summary = RUNNER._cocotb_xml_summary(out)
    assert summary is not None
    assert summary["tests"] == 0 and summary["passed"] == 0
