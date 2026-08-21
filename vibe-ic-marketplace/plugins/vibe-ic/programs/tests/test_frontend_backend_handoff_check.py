#!/usr/bin/env python3
"""Tests for frontend_backend_handoff_check.py — frontend-backend handoff gate."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "frontend_backend_handoff_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "report.json")],
        capture_output=True, text=True,
    )


def _load_report(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text())


def _write_gate_netlist(tmp_path: Path):
    synth = tmp_path / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True, exist_ok=True)
    (synth / "top.v").write_text(
        "module top(input clk);\n"
        "  sky130_fd_sc_hd__inv_1 U1 (.A(clk), .Y(n1));\n"
        "  sky130_fd_sc_hd__dff_1 FF1 (.CLK(clk), .D(n1), .Q(q));\n"
        "endmodule\n"
    )


def _write_sdc(tmp_path: Path):
    (tmp_path / "constraints.sdc").write_text(
        "create_clock -period 10.0 [get_ports clk]\n"
    )


def _write_def(tmp_path: Path):
    (tmp_path / "floorplan.def").write_text(
        "VERSION 5.8 ;\nDIEAREA ( 0 0 ) ( 100000 100000 ) ;\nEND DESIGN\n"
    )


# -- Test 1: PASS with all deliverables present --

def test_pass_all_present(tmp_path):
    _write_gate_netlist(tmp_path)
    _write_sdc(tmp_path)
    _write_def(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is False


# -- Test 2: FAIL when netlist is missing --

def test_fail_missing_netlist(tmp_path):
    (tmp_path / "phase2" / "stage2" / "synth").mkdir(parents=True)
    _write_sdc(tmp_path)
    _write_def(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("MISSING_GATE_NETLIST" in f["rule"] for f in errors)


# -- Test 3: FAIL when SDC is missing --

def test_fail_missing_sdc(tmp_path):
    _write_gate_netlist(tmp_path)
    _write_def(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("MISSING_SDC" in f["rule"] for f in errors)


# -- Test 4: not-yet-at-backend is VACUOUS (rc 2), not a PASS (#515) --

def test_skip_no_backend(tmp_path):
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl" / "top.v").write_text("module top; endmodule\n")
    r = _run(tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True
    assert rpt["summary"]["reason"] == "not_backend_stage"
    assert "VACUOUS_PASS:" in r.stderr, r.stderr


# -- Test 5: FAIL when analog blocks exist but no hardmacro LEF --

def test_fail_missing_lef_with_analog(tmp_path):
    _write_gate_netlist(tmp_path)
    _write_sdc(tmp_path)
    _write_def(tmp_path)
    analog = tmp_path / "phase3" / "analog"
    analog.mkdir(parents=True)
    (analog / "analog_block_list.json").write_text(
        json.dumps({"blocks": [{"name": "ldo", "type": "regulator"}]})
    )
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("MISSING_HARDMACRO_LEF" in f["rule"] for f in errors)


# ---------------------------------------------------------------------------
# #515 JUDGEMENT — NO_DFT_EVIDENCE is a non-blocking rc-0 ADVISORY.
#
# #515 asked for a deliberate choice between rc 1 ("this design should have
# scan and does not") and rc 2 ("DFT is out of scope here"). The decision, with
# its reasoning, is written into `audit()`; these two tests pin it so it cannot
# drift silently in either direction.
#
# The load-bearing fact is the FIRST assertion: the finding fires on a run
# whose `summary["skipped"]` is False — every required deliverable WAS
# examined. Calling that run vacuous would be a false claim in the opposite
# direction to the one #515 removes.
# ---------------------------------------------------------------------------

def test_no_dft_evidence_is_an_advisory_not_a_skip_and_not_a_fail(tmp_path):
    _write_gate_netlist(tmp_path)      # no scan_en / scan_in / scan_out
    _write_sdc(tmp_path)
    _write_def(tmp_path)
    r = _run(tmp_path)
    rpt = _load_report(tmp_path)
    assert any(f["rule"] == "NO_DFT_EVIDENCE" for f in rpt["findings"])
    # The gate examined the handoff — this is NOT the vacuous case.
    assert rpt["summary"]["skipped"] is False
    assert r.returncode == 0, r.stdout + r.stderr
    assert "VACUOUS_PASS:" not in r.stderr
    dft = next(f for f in rpt["findings"] if f["rule"] == "NO_DFT_EVIDENCE")
    assert dft["severity"] == "WARN"
    assert "ADVISORY" in dft["message"]


def test_dft_evidence_present_suppresses_the_advisory(tmp_path):
    _write_gate_netlist(tmp_path)
    _write_sdc(tmp_path)
    _write_def(tmp_path)
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl" / "scan.v").write_text(
        "module scan(input scan_en, input scan_in, output scan_out);\n"
        "endmodule\n"
    )
    r = _run(tmp_path)
    rpt = _load_report(tmp_path)
    assert not any(f["rule"] == "NO_DFT_EVIDENCE" for f in rpt["findings"])
    assert r.returncode == 0, r.stdout + r.stderr
