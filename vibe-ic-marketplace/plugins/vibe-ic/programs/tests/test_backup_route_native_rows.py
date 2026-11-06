"""Native simulation results reach the benchmark collector without receipts."""
import json
from pathlib import Path

import benchmark_dispatch as dispatch
import benchmark_io_adapter as adapter


def native_simulation(tmp_path, *, measured):
    adapter._stage_public_original("neutral", "Implement a neutral buffer.", {}, tmp_path)
    rtl = tmp_path / "phase2/stage1/rtl/neutral.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text("module neutral(input a,output y); assign y=a; endmodule\n")
    reports = tmp_path / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "flow_engine.json").write_text(json.dumps({
        "selected": 2, "verdict": "PASS" if measured else "NOT_MEASURED",
        "steps": [{"name": "rtl_authoring", "status": "PASS", "tool_ran": True, "tool_exit_code": 0},
                  {"name": "functional_simulation_and_coverage", "status": "PASS",
                   "tool_ran": True, "tool_exit_code": 0}] if measured else []}))
    argv = dispatch._solver_argv(Path(dispatch.__file__).with_name("vibe_ic_one_shot_runner.py"),
                                tmp_path, "4", "4", "ip", "original", "rtl")
    return argv, dispatch._ProcessOutcome(0, stdout="native simulation completed", stderr="")


def test_native_simulation_child_reaches_collection(tmp_path):
    argv, process = native_simulation(tmp_path, measured=True)
    got = dispatch._collect_runner_result(process, argv, "rtllm", "neutral", tmp_path,
                                          supplied_rtl=True)
    assert got["runner_diagnostics"]["status"] == "REPORTS_AVAILABLE", got
    assert got["ok"], got
    assert "module neutral" in got["completion"]


def test_native_simulation_child_requires_tool_results(tmp_path):
    argv, process = native_simulation(tmp_path, measured=False)
    got = dispatch._collect_runner_result(process, argv, "rtllm", "neutral", tmp_path,
                                          supplied_rtl=True)
    assert got["runner_diagnostics"]["status"] == "NOT_MEASURED", got
    assert got["ok"] is False
