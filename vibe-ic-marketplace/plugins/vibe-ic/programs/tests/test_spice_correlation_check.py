#!/usr/bin/env python3
"""Tests for spice_correlation_check.py — post-layout SPICE verification gate."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import test_step30_r4_current_failures as current_fixture

PROG = Path(__file__).resolve().parent.parent / "spice_correlation_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "report.json")],
        capture_output=True, text=True,
    )


def _load_report(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text())


def _setup_spef(tmp_path: Path):
    """Create minimal SPEF so the gate doesn't self-skip."""
    d = tmp_path / "phase3" / "stage3" / "extracted"
    d.mkdir(parents=True, exist_ok=True)
    (d / "parasitic.spef").write_text(
        "*SPEF \"IEEE 1481-1998\"\n*DESIGN \"test\"\n*DATE \"2026\"\n"
        "*D_NET net1 0.001\n*END\n"
    )


def _setup_sta(tmp_path: Path, worst_delay: float = 5.0):
    """Create minimal STA report."""
    d = tmp_path / "phase3" / "stage3" / "sta"
    d.mkdir(parents=True, exist_ok=True)
    (d / "post_route_timing.rpt").write_text(
        f"Startpoint: ff1 (rising edge-triggered flip-flop)\n"
        f"Endpoint: ff2 (rising edge-triggered flip-flop)\n"
        f"Path Delay       {worst_delay}\n"
        f"slack (MET)      0.5\n"
    )
    route = tmp_path / 'phase3/stage3/pnr/routed.def'
    route.parent.mkdir(parents=True, exist_ok=True)
    route.write_text('DESIGN neutral ;\nEND DESIGN\n')


def _current_correlation(tmp_path, monkeypatch, kind='CORRELATED'):
    """SOFTWARE_FIXTURE_ONLY transport; real current publication and consumer."""
    p, folder, lib = current_fixture.fixture.project(tmp_path)
    current_fixture.correlation_tool(p, folder, lib, monkeypatch,
                                     mismatch=kind, companion='success')
    result = current_fixture.SC.run_installed_pdk_path_correlation(p, str(lib))
    assert result['status'] == 'RAN'
    return p


def _run_current(project):
    rc = current_fixture.SC.main([str(project), '--json', str(project / 'report.json')])
    report = _load_report(project)
    assert report['summary']['current_binding'] == 'CURRENT'
    assert report['summary']['measurement'] == 'MEASURED'
    return rc, report


# -- Test: self-skip when no SPEF --

def test_skip_no_spef(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 2      # #521 — VACUOUS (rc 2): the gate examined nothing.
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True
    assert rpt["summary"]["reason"] == "asked_before_producer"
    assert rpt['summary']['reason_class'] == 'ASKED_BEFORE_PRODUCER'
    assert rpt['summary']['measurement'] == 'NOT_MEASURED'
    assert rpt['summary']['pass'] is False


# -- Test: self-skip when no STA --

def test_skip_no_sta(tmp_path):
    _setup_spef(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 2      # #521 — VACUOUS (rc 2): the gate examined nothing.
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True
    assert rpt["summary"]["reason"] == "asked_before_producer"
    assert rpt['summary']['current_binding'] == 'NOT_YET_PRODUCED'
    assert rpt['summary']['measurement'] == 'NOT_MEASURED'
    assert rpt['summary']['pass'] is False


# -- Test: FAIL when SPEF+STA exist but no SPICE run --

def test_fail_no_spice_verification(tmp_path):
    _setup_spef(tmp_path)
    _setup_sta(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any(f['rule'] == 'SPICE_CURRENT_INPUTS_UNBOUND' for f in errors)
    assert rpt['summary']['measurement'] == 'NOT_MEASURED'


# -- Test: PASS with correlation JSON within tolerance --

def test_pass_correlation_within_tolerance(tmp_path, monkeypatch):
    p = _current_correlation(tmp_path, monkeypatch)
    rc, rpt = _run_current(p)
    assert rc == 0
    assert rpt["passed"] is True
    assert rpt["summary"]["correlation"]["max_discrepancy_pct"] < 10


# -- Test: FAIL with >10% SPICE-STA mismatch --

def test_fail_correlation_mismatch(tmp_path, monkeypatch):
    p = _current_correlation(tmp_path, monkeypatch, 'MISMATCH')
    rc, rpt = _run_current(p)
    assert rc == 1
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("MISMATCH" in f["rule"] for f in errors)


# -- Test: FAIL with >25% critical mismatch --

def test_fail_critical_mismatch(tmp_path, monkeypatch):
    p = _current_correlation(tmp_path, monkeypatch, 'CRITICAL_MISMATCH')
    rc, rpt = _run_current(p)
    assert rc == 1
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("CRITICAL_MISMATCH" in f["rule"] for f in errors)


# -- Test: analog module detected but no SPICE → FAIL --

def test_fail_analog_missing_spice(tmp_path, monkeypatch):
    p = _current_correlation(tmp_path, monkeypatch)
    rtl = p / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "ldo_reg.v").write_text("module ldo_regulator(input vin, output vout);\nendmodule\n")
    rc, rpt = _run_current(p)
    assert rc == 1
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("ANALOG_SPICE_MISSING" in f["rule"] for f in errors)
    assert rpt['summary']['verdict'] == 'FAIL'
    assert rpt['summary']['correlation_verdict'] == 'PASS'
    assert current_fixture.fixture.bounded_step30_caller()(p, current_fixture.fixture.pdk(
        p / 'fixture_pdk/neutral/neutral.lib')).status == 'FAIL'


# -- Test: analog module with matching SPICE → PASS --

def test_pass_analog_covered(tmp_path, monkeypatch):
    p = _current_correlation(tmp_path, monkeypatch)
    sd = p / "phase3" / "stage3" / "spice"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "ldo_regulator.sp").write_text(".title LDO test\n.end\n")
    (sd / "ldo_regulator.log").write_text("vout_dc = 1.800\n")
    rtl = p / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "ldo_regulator.v").write_text("module ldo_regulator(input vin, output vout);\nendmodule\n")
    rc, rpt = _run_current(p)
    assert rc == 0
    assert rpt["passed"] is True
    assert rpt["summary"]["analog"]["covered"] == 1


@pytest.mark.parametrize('log', [None, 'no measured result\n', 'vout_dc = --\n', 'vout_dc = 1e999\n',
                               'vout_dc = 0.5 not measured\n', 'vout_dc = 0.5 (not measured)\n'])
def test_analog_deck_without_measurements_cannot_cover_a_module(tmp_path, monkeypatch, log):
    p = _current_correlation(tmp_path, monkeypatch)
    current_fixture.write(p / 'phase2/stage1/rtl/adc_neutral.v',
                          'module adc_neutral(input a, output z); endmodule\n')
    current_fixture.write(p / 'phase3/stage3/spice/adc_neutral.sp', '* deck only\n.end\n')
    if log is not None:
        current_fixture.write(p / 'phase3/stage3/spice/adc_neutral.log', log)
    rc, report = _run_current(p)
    assert rc == 1 and report['passed'] is False
    assert report['summary']['analog']['uncovered'] == ['adc_neutral']


def test_current_measured_failure_survives_malformed_analog_measurement(tmp_path, monkeypatch):
    p = _current_correlation(tmp_path, monkeypatch, 'MISMATCH')
    current_fixture.write(p / 'phase2/stage1/rtl/adc_neutral.v',
                          'module adc_neutral(input a, output z); endmodule\n')
    current_fixture.write(p / 'phase3/stage3/spice/adc_neutral.sp', '* deck\n.end\n')
    current_fixture.write(p / 'phase3/stage3/spice/adc_neutral.log', 'vout_dc = --\n')
    rc, report = _run_current(p)
    assert rc == 1 and report['summary']['verdict'] == 'FAIL'
    assert report['summary']['measurement'] == 'MEASURED'
    assert any(row['rule'] == 'SPICE_STA_MISMATCH' for row in report['findings'])
    assert any(row['rule'] == 'ANALOG_SPICE_MISSING' for row in report['findings'])


# -- Test: exit 2 on non-existent directory --

def test_exit2_bad_dir(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nonexistent")],
        capture_output=True, text=True,
    )
    assert r.returncode == 2


@pytest.mark.parametrize('line', ['vout_dc = 0.5 not measured', 'vout_dc = 0.5 (not measured)'])
def test_a_denied_spice_scalar_is_not_a_measurement(tmp_path, line):
    log = tmp_path / 'scalar.log'
    log.write_text(line + '\n')
    assert current_fixture.SC._parse_spice_measurements([log]) == {}


def test_native_spice_scalar_labels_and_timing_fields_keep_their_values(tmp_path):
    log = tmp_path / 'scalar.log'
    log.write_text('not = 0.5\ntpd = 3.2e-9 targ= 5e-9 trig= 1.8e-9\n')
    assert current_fixture.SC._parse_spice_measurements([log]) == {'not': 0.5, 'tpd': 3.2e-9}
