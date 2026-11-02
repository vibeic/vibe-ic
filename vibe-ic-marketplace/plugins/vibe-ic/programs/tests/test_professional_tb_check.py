"""Tests for professional_tb_check — the Phase-2 gate that stops the new
professional cocotb TB path from silently passing a real functional mismatch.

Pure/structural (no container): drives the gate over synthetic report JSON.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import professional_tb_check as G  # noqa: E402
import _l10_execution as L10X  # noqa: E402


def _report(tmp: Path, obj) -> Path:
    d = tmp / "reports" / "phase2" / "gates"
    d.mkdir(parents=True, exist_ok=True)
    (d / "professional_tb.json").write_text(json.dumps(obj))
    return tmp


def _l10_unit_track(tmp: Path, *, failures: int = 0,
                    sim_executed: bool = True) -> Path:
    gd = tmp / "phase1/generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    l10 = gd / "L10_TEST_CASES.json"
    l10.write_text(json.dumps({"test_cases": [
        {"id": "case_a"}, {"id": "case_b"}]}))
    out = tmp / "phase2/stage1/sim_professional/l10_unit_tb"
    out.mkdir(parents=True, exist_ok=True)
    junit = out / "results.xml"
    junit.write_text(
        f'<testsuite tests="2" failures="{failures}" errors="0">'
        '<testcase name="case_a"/>'
        + ('<testcase name="case_b"><failure/></testcase>' if failures
           else '<testcase name="case_b"/>')
        + '</testsuite>')
    rows = [
        {"id": "case_a", "verdict": "PASS",
         "sim_executed": sim_executed},
        {"id": "case_b", "verdict": "FAIL" if failures else "PASS",
         "sim_executed": sim_executed},
    ]
    L10X.write_record(
        tmp, l10, rows, producer="testbench_gen.run_unit_tbs",
        tb_dir=tmp / "phase2/stage1/sim/tb", source_junit=junit)
    return tmp


def test_absent_report_is_not_applicable(tmp_path):
    res = G.check(tmp_path)
    assert res["verdict"] == "NOT_APPLICABLE"
    assert G.main([str(tmp_path)]) == 0  # exit 0 — never a false FAIL


def test_functional_mismatch_fails(tmp_path):
    _report(tmp_path, {"status": "FAIL", "dut_kind": "serial_stream",
                       "functional_mismatch": True, "cocotb_xml_failures": 3})
    res = G.check(tmp_path)
    assert res["verdict"] == "FAIL"
    assert res["cocotb_xml_failures"] == 3
    assert G.main([str(tmp_path)]) == 1  # exit 1 — real RTL bug, not waived


def test_clean_functional_pass(tmp_path):
    _report(tmp_path, {"status": "PASS", "dut_kind": "serial_stream",
                       "ran_cocotb": True, "cocotb_xml_failures": 0,
                       "functional_mismatch": False})
    assert G.check(tmp_path)["verdict"] == "PASS"
    assert G.main([str(tmp_path)]) == 0


def test_generated_but_deferred_is_pass(tmp_path):
    # TB generated, cocotb run deferred (tooling unreachable) → WAIVED status,
    # no functional_mismatch → the gate must PASS (never a false FAIL).
    _report(tmp_path, {"status": "PASS", "dut_kind": "serial_stream",
                       "ran_cocotb": False, "functional_mismatch": False,
                       "waiver": "iverilog/cocotb not reachable"})
    assert G.check(tmp_path)["verdict"] == "PASS"
    assert G.main([str(tmp_path)]) == 0


def test_corrupt_report_is_io_error(tmp_path):
    d = tmp_path / "reports" / "phase2" / "gates"
    d.mkdir(parents=True)
    (d / "professional_tb.json").write_text("{ not json")
    assert G.check(tmp_path)["verdict"] == "IO_ERROR"
    assert G.main([str(tmp_path)]) == 2


def test_independent_l10_unit_track_is_a_professional_pass(tmp_path):
    _report(tmp_path, {"status": "INCOMPLETE", "ran_cocotb": False,
                       "reason": "reference hook unfilled"})
    _l10_unit_track(tmp_path)
    res = G.check(tmp_path)
    assert res["verdict"] == "PASS"
    assert res["professional_track"] == "l10_unit_tb_execution"
    assert res["l10_cases"] == 2
    assert res["junit"] == {
        "tests": 2, "passed": 2, "failures": 0, "errors": 0}


def test_failed_l10_junit_cannot_be_hidden_by_generator_skip(tmp_path):
    _report(tmp_path, {"status": "SKIP", "ran_cocotb": False})
    _l10_unit_track(tmp_path, failures=1)
    assert G.check(tmp_path)["verdict"] == "FAIL"
    assert G.main([str(tmp_path)]) == 1


def test_unexecuted_l10_rows_cannot_become_professional_pass(tmp_path):
    _report(tmp_path, {"status": "SKIP", "ran_cocotb": False})
    _l10_unit_track(tmp_path, sim_executed=False)
    res = G.check(tmp_path)
    assert res["verdict"] == "NOT_CHECKED"
    assert res["reason_class"] == "BLOCKED_BY_UPSTREAM"


def test_generator_skip_without_measurement_is_not_checked(tmp_path):
    _report(tmp_path, {"status": "SKIP", "reason": "generate raised: invalid input"})
    res = G.check(tmp_path)
    assert res["verdict"] == "NOT_CHECKED", res
    assert res["reason_class"] == "BLOCKED_BY_UPSTREAM", res
    assert G.main([str(tmp_path)]) == 2


def test_generator_skip_can_use_valid_independent_l10_track(tmp_path):
    _report(tmp_path, {"status": "SKIP", "ran_cocotb": False})
    _l10_unit_track(tmp_path)
    res = G.check(tmp_path)
    assert res["verdict"] == "PASS", res
    assert res["professional_track"] == "l10_unit_tb_execution"
    assert res["l10_cases"] == 2


@pytest.mark.parametrize('defect', ['missing', 'empty'])
def test_generator_skip_keeps_declared_bundle_defect(tmp_path, defect):
    out = tmp_path / 'phase2/stage1/sim_professional/neutral'
    out.mkdir(parents=True)
    if defect == 'empty':
        (out / 'tb_neutral.py').write_bytes(b'')
    _report(tmp_path, {"status": "SKIP", "ran_cocotb": False,
                       "out_dir": str(out), "files": ["tb_neutral.py"]})
    res = G.check(tmp_path)
    assert res['verdict'] == 'FAIL', res
    assert res['bundle'][defect] == ['tb_neutral.py']


@pytest.mark.parametrize('status', ['SKIP', 'INCOMPLETE'])
def test_independent_l10_pass_cannot_hide_functional_mismatch(tmp_path, status):
    _report(tmp_path, {"status": status, "functional_mismatch": True,
                       "cocotb_xml_failures": 1})
    _l10_unit_track(tmp_path)
    res = G.check(tmp_path)
    assert res["verdict"] == "FAIL", res
    assert res["cocotb_xml_failures"] == 1


@pytest.mark.parametrize('status', ['PASS', 'SKIP', 'INCOMPLETE'])
def test_independent_l10_pass_cannot_hide_declared_bundle_defect(tmp_path, status):
    _l10_unit_track(tmp_path)
    out = tmp_path / "phase2/stage1/sim_professional/neutral"
    out.mkdir()
    _report(tmp_path, {"status": status, "ran_cocotb": True,
                       "functional_mismatch": False, "out_dir": str(out),
                       "files": ["tb_neutral.py"]})
    res = G.check(tmp_path)
    assert res["verdict"] == "FAIL", res
    assert res["bundle"]["missing"] == ["tb_neutral.py"]
