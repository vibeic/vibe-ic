"""Permanent production controls from the unchanged independent R3 probes."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = (Path(os.environ["REVIEW_CLONE"]) if "REVIEW_CLONE" in os.environ else
        Path(__file__).resolve().parents[5])
PROGRAMS = ROOT / "vibe-ic-marketplace/plugins/vibe-ic/programs"
FIXTURES = PROGRAMS / "tests/fixtures/pulse_width_rearm"
sys.path.insert(0, str(PROGRAMS))
import pulse_width_rearm_conformance_check as checker  # noqa: E402

pytestmark = pytest.mark.skipif(
    not (shutil.which("iverilog") and shutil.which("vvp")),
    reason="production adversarial controls require native iverilog/vvp")


def _independent_probes(monkeypatch):
    monkeypatch.setenv("REVIEW_CLONE", str(ROOT))
    path = Path(__file__).parent / "fixtures/pulse_width_rearm/r3_independent_probes.py"
    spec = importlib.util.spec_from_file_location("r3_independent_probes", path)
    probes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probes)
    return probes


def _project(tmp_path, bad=False):
    project = tmp_path / "project"
    source = project / "phase1/input_prompt/contract.json"
    rtl = project / "phase2/stage1/rtl/dut.sv"
    source.parent.mkdir(parents=True)
    rtl.parent.mkdir(parents=True)
    source.write_bytes((FIXTURES / "contract.json").read_bytes())
    rtl.write_bytes((FIXTURES / ("level_reacquire_bad.sv" if bad else "compliant.sv")).read_bytes())
    return project, source, rtl




def test_independent_r3_result_channel_forgery_is_refused(monkeypatch):
    probes = _independent_probes(monkeypatch)
    probes.result_channel_forgery_probe()
    got = probes.results[-1]
    assert got["ok"] is True, got
    assert got["ordinary_calls"] == 0
    assert got["overall_status"] in {"FAIL", "NOT_MEASURED"}
    assert got["native_verdict"] != "PASS"


def test_independent_r3_replace_boundary_race_is_refused(monkeypatch):
    probes = _independent_probes(monkeypatch)
    probes.race_at_atomic_replace_probe()
    got = probes.results[-1]
    assert got["ok"] is True, got
    assert got["rc"] == 3
    assert got["verdict"] == "NOT_MEASURED"
    assert got["measured"] is False and got["stability"]["stable"] is False
    assert got["published_source_sha"] != got["live_source_sha"]
    assert got["published_rtl_sha"] != got["live_rtl_sha"]




@pytest.mark.parametrize("attack", ["macro_file_task", "context_finish", "plusargs",
                                   "hierarchy", "escaped_hierarchy"])
def test_expanded_dut_cannot_acquire_harness_capabilities(tmp_path, attack):
    project, source, rtl = _project(tmp_path)
    original = rtl.read_text()
    context = []
    if attack == "macro_file_task":
        original = '`define PWR_ATTACK $fopen\n' + original
        injection = 'integer fd; initial fd = `PWR_ATTACK("anything", "w");'
    elif attack == "context_finish":
        helper = rtl.parent / "helper.sv"
        helper.write_text("module helper; initial $finish; endmodule\n")
        context = [helper]
        injection = "helper unsafe_helper();"
    elif attack == "plusargs":
        injection = 'string p; integer found; initial found = $value$plusargs("PWR_RESULT_FILE=%s", p);'
    elif attack == "hierarchy":
        injection = "initial pulse_width_rearm_measurement_tb.legal_accepts = 1;"
    else:
        injection = r"initial \pulse_width_rearm_measurement_tb .legal_accepts = 1;"
    rtl.write_text(original.rsplit("endmodule", 1)[0] + injection + "\nendmodule\n")
    rc, report = checker.run_check(source, rtl, top="pulse_width_rearm_fixture", context_files=context)
    assert rc == 3 and report["verdict"] == "NOT_MEASURED", report
    assert report["measured"] is False
    assert report["dut_admission"]["unsafe_constructs"]
    assert "simulation_command" not in report


def test_native_channel_identity_changes_between_identical_runs(tmp_path):
    _project_dir, source, rtl = _project(tmp_path)
    receipts = [checker.run_check(source, rtl, top="pulse_width_rearm_fixture")[1]
                for _ in range(2)]
    assert all(r["verdict"] == "PASS" for r in receipts)
    assert receipts[0]["run_binding"]["nonce"] != receipts[1]["run_binding"]["nonce"]
    assert receipts[0]["run_binding"]["channel"] != receipts[1]["run_binding"]["channel"]
    assert receipts[0]["stimulus"]["tb_sha256"] == receipts[1]["stimulus"]["tb_sha256"]
    counts, verdict, error = checker._parse_result_channel(
        "\n".join(receipts[0]["result_channel_tail"]),
        ":".join(receipts[1]["run_binding"][k]
                 for k in ("nonce", "input_sha256", "binary_sha256")))
    assert counts is None and verdict is None and "bound" in error


def test_measured_fail_remains_fail_at_replace_boundary(tmp_path, monkeypatch):
    project, source, rtl = _project(tmp_path, bad=True)
    report_path = project / "reports/gate.json"
    original = {p: p.read_bytes() for p in (source, rtl)}
    real_replace = checker.os.replace

    def race(src, dst):
        if Path(dst) == report_path:
            for p, data in original.items():
                p.write_bytes(data + b"\n ")
        return real_replace(src, dst)

    monkeypatch.setattr(checker.os, "replace", race)
    rc, report = checker.run_project(project, [rtl], "pulse_width_rearm_fixture",
                                     report_path=report_path)
    assert rc == 1 and report["verdict"] == "FAIL" and report["measured"] is True
    assert report["input_stability"]["stable"] is False
    assert "measured FAIL takes precedence" in report["reason"]
    assert json.loads(report_path.read_text()) == report
