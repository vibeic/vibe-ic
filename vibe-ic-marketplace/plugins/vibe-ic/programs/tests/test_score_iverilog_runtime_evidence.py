"""Keep completed Shape-B diagnostics in the report, outside blind feedback."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = (Path(__file__).resolve().parents[2]
          / "benchmark" / "score_iverilog_tb.py")
SPEC = importlib.util.spec_from_file_location("scorer_runtime_evidence_test", SCRIPT)
SCORER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(SCORER)


@pytest.fixture
def case(tmp_path, monkeypatch):
    dataset, run = tmp_path / "synthetic_inputs", tmp_path / "run"
    design = dataset / "case"
    design.mkdir(parents=True)
    samples = run / "samples"
    samples.mkdir(parents=True)
    (samples / "case.v").write_text("module dut; endmodule\n")
    (design / "tb.v").write_text("module tb; endmodule\n")
    (run / "problems.list").write_text("case\n")
    layout = {"prompt_filename": "prompt.txt", "tb_filename": "tb.v"}
    args = {"pass_regex": "OFFICIAL PASS", "fail_regex": "OFFICIAL FAIL"}
    state = {"compile_rc": 0, "runtime_rc": 0,
             "stdout": "private runtime payload\x00 α\n" + "x" * 1024,
             "stderr": "private stderr payload\r\n", "calls": []}

    def completed(argv, **kwargs):
        if argv == ["iverilog", "-V"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[0] == "iverilog":
            cp = subprocess.CompletedProcess(
                argv, state["compile_rc"], "compile stdout\n", "compile stderr\n")
        elif argv[0] == "vvp":
            if state.get("timeout"):
                raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
            cp = subprocess.CompletedProcess(
                argv, state["runtime_rc"], state["stdout"], state["stderr"])
        else:
            raise AssertionError(f"unexpected subprocess: {argv!r}")
        state["calls"].append((cp, kwargs))
        return cp

    # Synthetic process endpoints; the compile/run/report code remains real.
    monkeypatch.setattr(SCORER.subprocess, "run", completed)
    monkeypatch.setattr(SCORER, "_power_up_fixed", lambda sample, _td: str(sample))
    monkeypatch.setattr(SCORER, "_proactive_positional_port_normalize_shape_b",
                        lambda text, *_args: text)
    monkeypatch.setattr(SCORER, "_resolve_vvp_route", lambda: None)
    monkeypatch.setattr(SCORER, "_param_passthrough_retry_shape_b", lambda *_a: None)
    monkeypatch.setattr(SCORER, "_score_side_port_permutation_rescue_shape_b",
                        lambda *_a: None)
    monkeypatch.setattr(SCORER, "_golden_ref_fails_own_tb_runtime", lambda *_a: None)
    monkeypatch.setattr(SCORER, "_unsatisfiable_tb_compile_audit_shape_b",
                        lambda *_a: (False, ""))
    monkeypatch.setattr(SCORER, "_load_bench", lambda _name: {
        "title": "synthetic evidence", "shape": "B",
        "layout": layout, "scorer_args": args})
    return dataset, run, layout, args, state


@pytest.mark.parametrize("cwd_design_dir", [True, False])
@pytest.mark.parametrize("returncode", [0, 17])
def test_markerless_report_retains_completed_processes_without_feedback_leak(
        case, monkeypatch, capsys, cwd_design_dir, returncode):
    dataset, run, _layout, args, state = case
    args["cwd_design_dir"] = cwd_design_dir
    state["runtime_rc"] = returncode
    tasklist = run / "tasklist.json"
    monkeypatch.setattr(sys, "argv", [
        str(SCRIPT), "--bench", "synthetic", "--dataset", str(dataset),
        "--run", str(run), "--emit-close-loop-tasklist", str(tasklist)])

    SCORER.main()

    summary = json.loads((run / "pass_at_1.json").read_text())
    row = summary["results"][0]
    assert {key: row[key] for key in ("design", "verdict", "reason", "tool")} == {
        "design": "case", "verdict": "FAIL", "reason": "no_pass_marker",
        "tool": "iverilog-g2012"}
    assert (summary["total"], summary["passed"], summary["pass_at_1_pct"]) == (1, 0, 0.0)
    assert len(state["calls"]) == 2
    compile_cp, _compile_kwargs = state["calls"][0]
    runtime_cp, runtime_kwargs = state["calls"][1]
    expected_cwd = (str(dataset / "case") if cwd_design_dir
                    else SCORER._VVP_SCRATCH_CWD)
    assert runtime_kwargs["cwd"] == expected_cwd
    expected = {}
    for stage, cp, cwd in (("compile", compile_cp, "unknown"),
                           ("runtime", runtime_cp, expected_cwd)):
        expected[stage] = {"args": cp.args, "cwd": cwd,
                           "returncode": cp.returncode,
                           "stdout": cp.stdout, "stderr": cp.stderr}
    assert row.get("diagnostics") == expected
    feedback_text = tasklist.read_text()
    feedback = json.loads(feedback_text)["fails"][0]
    assert set(feedback) == {
        "id", "prior_sample", "prompt", "verdict", "reason", "retry_budget",
        "blind_contract"}
    assert (feedback["verdict"], feedback["reason"]) == ("FAIL", "no_pass_marker")
    author_output = feedback_text + capsys.readouterr().out
    assert "private runtime payload" not in author_output
    assert "private stderr payload" not in author_output
    assert "compile stdout" not in author_output
    assert "compile stderr" not in author_output


@pytest.mark.parametrize("stdout,compile_rc,runtime_rc,timeout,verdict,reason", [
    ("OFFICIAL PASS", 0, 0, False, "PASS", None),
    ("OFFICIAL PASS", 0, 17, False, "PASS", None),
    ("OFFICIAL PASS\nOFFICIAL FAIL\n2 / 3 failures", 0, 0, False,
     "FAIL", "functional_mismatch (2 / 3 failures)"),
    ("OFFICIAL FAIL", 0, 0, False, "FAIL", "no_pass_marker (some Test failed)"),
    ("", 1, 0, False, "FAIL", "compile_error"),
    ("", 0, 0, True, "FAIL", "sim_timeout"),
], ids=["pass", "pass_nonzero_rc", "functional_mismatch", "markerless_failure",
        "compile_error", "sim_timeout"])
def test_existing_shape_b_verdicts_stay_unchanged(
        case, stdout, compile_rc, runtime_rc, timeout, verdict, reason):
    dataset, run, layout, args, state = case
    state.update(stdout=stdout, compile_rc=compile_rc,
                 runtime_rc=runtime_rc, timeout=timeout)

    row = SCORER._score_shape_b("case", run / "samples", dataset, layout, args)

    assert row["verdict"] == verdict
    assert row.get("reason") == reason
    assert len(state["calls"]) == (1 if compile_rc or timeout else 2)
    if reason and reason.startswith("no_pass_marker"):
        assert row.get("diagnostics", {}).get("runtime", {}).get("stdout") == stdout
    else:
        assert "diagnostics" not in row
