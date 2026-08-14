"""Tests for professional_tb_check — the Phase-2 gate that stops the new
professional cocotb TB path from silently passing a real functional mismatch.

Pure/structural (no container): drives the gate over synthetic report JSON.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import professional_tb_check as G  # noqa: E402


def _report(tmp: Path, obj) -> Path:
    d = tmp / "reports" / "phase2" / "gates"
    d.mkdir(parents=True, exist_ok=True)
    (d / "professional_tb.json").write_text(json.dumps(obj))
    return tmp


def test_absent_report_is_not_applicable(tmp_path):
    res = G.check(tmp_path)
    assert res["verdict"] == "NOT_APPLICABLE"
    # rc 2, not 0, since vibe-ic#564: rc 2 is the DISCLOSED-SKIP tier, not a
    # failure — `flow_compliance_check` maps it to "n/a (input not present)",
    # so this is still never a false FAIL. rc 0 said "I looked and it was
    # fine" to every consumer that reads exit codes rather than prose, and
    # `gate_zero_denominator_refuses_check` recorded it as the one
    # ZERO_DENOMINATOR_EXITS_ZERO finding out of 534 programs probed.
    assert G.main([str(tmp_path)]) == 2


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
