"""The scorer reports the host simulator it actually invoked."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parents[2]
          / "benchmark" / "score_iverilog_tb.py")
SPEC = importlib.util.spec_from_file_location(
    "score_iverilog_tb_host_version_test", SCRIPT)
SCORER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(SCORER)

FALLBACK = (
    "tool-gap only: Shape B escalates to container Verilator 5.x; "
    "Shape C escalates to vibeic-eda fork-iverilog-14"
)


def _shape_c_summary(tmp_path, monkeypatch, version_probe, *, tag="empty",
                     verdicts=None):
    verdicts = verdicts or {}
    dataset = tmp_path / f"dataset_{tag}"
    run = tmp_path / f"run_{tag}"
    dataset.mkdir()
    (run / "samples").mkdir(parents=True)
    (run / "problems.list").write_text(
        "".join(f"{problem}\n" for problem in verdicts))
    for problem in verdicts:
        (run / "samples" / f"{problem}_sample01.sv").write_text(
            "module TopModule; endmodule\n")

    monkeypatch.setattr(SCORER, "_load_bench", lambda _name: {
        "title": "probe benchmark",
        "shape": "C",
        "layout": {
            "prompt_suffix": "_prompt.txt",
            "tb_suffix": "_test.sv",
            "ref_suffix": "_ref.sv",
        },
        "scorer_args": {},
    })
    monkeypatch.setattr(
        SCORER, "_score_shape_c",
        lambda problem, *_args: {
            "problem": problem,
            "verdict": verdicts[problem],
            **({} if verdicts[problem] == "PASS"
               else {"reason": "functional_mismatch"}),
        })
    monkeypatch.setattr(SCORER.subprocess, "run", version_probe)
    monkeypatch.setattr(sys, "argv", [
        str(SCRIPT), "--bench", "probe", "--dataset", str(dataset),
        "--run", str(run),
    ])

    SCORER.main()
    return json.loads((run / "pass_at_1.json").read_text())


def test_pass_at_1_reports_probed_host_iverilog_11(monkeypatch, tmp_path):
    calls = []

    def probe(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(
            argv, 0, "Icarus Verilog version 11.0 (stable) ()\n", "")

    summary = _shape_c_summary(tmp_path, monkeypatch, probe)

    assert calls and calls[0][0] == ["iverilog", "-V"]
    assert summary["tool"] == (
        "iverilog 11.0 (host) substituting for Synopsys VCS / Cadence Xcelium")
    assert summary["tool_gap_fallback"] == FALLBACK


def test_pass_at_1_reports_unknown_when_version_probe_fails(
        monkeypatch, tmp_path):
    def unavailable(_argv, **_kwargs):
        raise FileNotFoundError("iverilog unavailable for version probe")

    summary = _shape_c_summary(tmp_path, monkeypatch, unavailable)

    assert summary["tool"] == (
        "iverilog unknown (host) substituting for Synopsys VCS / Cadence Xcelium")
    assert summary["tool_gap_fallback"] == FALLBACK


def test_version_probe_changes_metadata_not_scoring_semantics(
        monkeypatch, tmp_path):
    verdicts = {"ProbA": "PASS", "ProbB": "FAIL"}

    def version_11(argv, **_kwargs):
        return subprocess.CompletedProcess(
            argv, 0, "Icarus Verilog version 11.0 (stable) ()\n", "")

    def failed_probe(_argv, **_kwargs):
        raise subprocess.TimeoutExpired(["iverilog", "-V"], 10)

    known = _shape_c_summary(
        tmp_path, monkeypatch, version_11, tag="known", verdicts=verdicts)
    unknown = _shape_c_summary(
        tmp_path, monkeypatch, failed_probe, tag="unknown", verdicts=verdicts)

    semantic_keys = (
        "results", "total", "passed", "skipped_scorer_gap",
        "pass_at_1_pct", "pass_at_1_pct_no_skip_excluded",
    )
    assert {key: known[key] for key in semantic_keys} == {
        key: unknown[key] for key in semantic_keys}
    assert known["tool"] != unknown["tool"]
