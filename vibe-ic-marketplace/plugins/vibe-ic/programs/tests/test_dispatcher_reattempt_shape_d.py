"""Tests for v0.1.55 R5 capture: benchmark_dispatch.py --reattempt-floor must
also recognise Shape-D `cocotb_score.json` and RESULT.md when `pass_at_1.json`
is absent. Captured from v0.1.53 CVDP run where the dispatcher falsely said
'FIRST RUN' for a benchmark that DID have a prior run.
"""
import importlib
import json
import os
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]


def _load_dispatch():
    if "benchmark_dispatch" in sys.modules:
        del sys.modules["benchmark_dispatch"]
    sys.path.insert(0, str(PROGRAMS))
    return importlib.import_module("benchmark_dispatch")


def test_reattempt_falls_back_to_cocotb_score(tmp_path, monkeypatch, capsys):
    """When pass_at_1.json is absent but cocotb_score.json exists, report it."""
    mod = _load_dispatch()
    # Synthesise benchmark_external/cvdp/run_x/.../cocotb_score.json
    base = tmp_path / "benchmark-data" / "evaluation" / "cvdp" / "run_x" / "proj" / "reports"
    base.mkdir(parents=True)
    (base / "cocotb_score.json").write_text(json.dumps({
        "tests": 1, "passed": 1, "failed": 0, "skipped": 0, "verdict": "PASS",
        "variant_fallback_used": True,
        "variant_fallback_rtl": "work/rtl/foo_async.sv",
    }) + "\n")
    monkeypatch.chdir(tmp_path)
    rc = mod.cmd_reattempt_floor("cvdp")
    out = capsys.readouterr().out
    assert rc == 0
    assert "cocotb_score.json" in out
    assert "TESTS=1" in out
    assert "PASS=1" in out
    assert "variant_fallback used" in out
    assert "FIRST RUN" not in out


def test_reattempt_falls_back_to_result_md(tmp_path, monkeypatch, capsys):
    """No scoring JSON at all but a RESULT.md exists → report its headline."""
    mod = _load_dispatch()
    base = tmp_path / "benchmark-data" / "evaluation" / "cvdp" / "run_x"
    base.mkdir(parents=True)
    (base / "RESULT.md").write_text("# CVDP prior run — PASS 9/9\n\nSome detail.\n")
    monkeypatch.chdir(tmp_path)
    rc = mod.cmd_reattempt_floor("cvdp")
    out = capsys.readouterr().out
    assert rc == 0
    assert "RESULT.md" in out
    assert "CVDP prior run" in out
    assert "FIRST RUN" not in out


def test_reattempt_first_run_when_nothing_present(tmp_path, monkeypatch, capsys):
    """Truly empty bench dir → 'FIRST RUN' message remains."""
    mod = _load_dispatch()
    (tmp_path / "benchmark-data" / "evaluation" / "cvdp").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    rc = mod.cmd_reattempt_floor("cvdp")
    out = capsys.readouterr().out
    assert rc == 0
    assert "FIRST RUN" in out


def test_reattempt_cocotb_first_for_shape_d(tmp_path, monkeypatch, capsys):
    """When BOTH pass_at_1.json AND cocotb_score.json exist for Shape-D,
    cocotb_score.json wins (the shape-native artifact)."""
    mod = _load_dispatch()
    base = tmp_path / "benchmark-data" / "evaluation" / "cvdp" / "run_x"
    base.mkdir(parents=True)
    (base / "pass_at_1.json").write_text(json.dumps({
        "total": 1, "passed": 0, "pass_at_1_pct": 0.0,
        "results": [{"problem": "x", "verdict": "FAIL", "reason": "stale"}],
    }) + "\n")
    cocotb_path = base / "proj" / "reports"
    cocotb_path.mkdir(parents=True)
    (cocotb_path / "cocotb_score.json").write_text(json.dumps({
        "tests": 1, "passed": 1, "failed": 0, "skipped": 0, "verdict": "PASS",
    }) + "\n")
    # Make cocotb_score.json newer
    os.utime(cocotb_path / "cocotb_score.json", (10_000_000_000, 10_000_000_000))
    monkeypatch.chdir(tmp_path)
    rc = mod.cmd_reattempt_floor("cvdp")
    out = capsys.readouterr().out
    assert rc == 0
    # newer + shape-native wins
    assert "cocotb_score.json" in out


def test_reattempt_pass_at_1_first_for_shape_c(tmp_path, monkeypatch, capsys):
    """Shape-C (verilogeval-v2) uses pass_at_1.json as primary artifact."""
    mod = _load_dispatch()
    base = tmp_path / "benchmark-data" / "evaluation" / "verilogeval_v2" / "run_x"
    base.mkdir(parents=True)
    (base / "pass_at_1.json").write_text(json.dumps({
        "total": 156, "passed": 152, "pass_at_1_pct": 97.44,
        "results": [
            {"problem": "Prob062", "verdict": "FAIL", "reason": "Cat A"},
            {"problem": "Prob093", "verdict": "FAIL", "reason": "Cat A"},
        ],
    }) + "\n")
    monkeypatch.chdir(tmp_path)
    rc = mod.cmd_reattempt_floor("verilogeval-v2")
    out = capsys.readouterr().out
    assert rc == 0
    assert "Prior canonical: 152/156" in out
    assert "Prob062" in out
    assert "Prob093" in out
