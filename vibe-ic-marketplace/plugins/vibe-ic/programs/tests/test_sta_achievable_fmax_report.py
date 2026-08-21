#!/usr/bin/env python3
"""Tests for sta_achievable_fmax_report.py — honest achievable-Fmax measurement.

Covers:
  * exact linear core (ibex real number: -2.64 ns @ 10 ns -> 12.64 ns / 79.1 MHz)
  * spec-MET headroom case (positive slack -> achievable < spec, design has margin)
  * HONESTY invariants: relaxation_applied is ALWAYS False; spec_met is False for
    ANY negative slack (never claims the spec target passed)
  * worst-slack parser: report_worst_slack line AND report_checks path tail;
    picks the most-negative; empty report -> honest None (not a fake 0)
  * spec-period parser: create_clock -period AND `set clk_period` variable idiom
  * verification-sweep TCL builder (contains periods + no chip/PDK literal)
  * human formatting (FAIL states "NOT a waiver / stays FAIL"; MET states headroom)
  * CLI exit code mirrors the SPEC verdict (0 met / 1 fail)
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sta_achievable_fmax_report as m  # noqa: E402

PROG = Path(__file__).resolve().parent.parent / "sta_achievable_fmax_report.py"


# ── exact deterministic core ────────────────────────────────────────────────

def test_ibex_real_number_exact():
    # The real ibex_top @ sky130 close-loop: worst setup slack -2.64 ns at the
    # 10 ns spec target. Re-STA at 13 ns measured +0.36 ns (perfectly linear),
    # confirming achievable_period = 10 - (-2.64) = 12.64 ns.
    rep = m.achievable_from_slack(10.0, -2.64)
    assert rep["achievable_period_ns"] == pytest.approx(12.64, abs=1e-6)
    assert rep["achievable_fmax_mhz"] == pytest.approx(79.114, abs=1e-2)
    assert rep["spec_met"] is False
    assert rep["spec_fmax_mhz"] == pytest.approx(100.0, abs=1e-6)
    assert rep["spec_margin_ns"] is None
    assert rep["relaxation_applied"] is False


def test_linearity_matches_reSTA_point():
    # slack(P) = slack(spec) + (P - spec). At P=13: -2.64 + 3 = +0.36.
    rep = m.achievable_from_slack(10.0, -2.64)
    p_probe = 13.0
    predicted = -2.64 + (p_probe - 10.0)
    assert predicted == pytest.approx(0.36, abs=1e-6)
    # achievable is where predicted == 0
    assert rep["achievable_period_ns"] == pytest.approx(10.0 - (-2.64))


def test_spec_met_headroom_case():
    # Positive slack -> design MEETs spec with margin; achievable period is
    # SMALLER than spec (it could run faster). spec_met True, margin recorded.
    rep = m.achievable_from_slack(10.0, 1.5)
    assert rep["spec_met"] is True
    assert rep["spec_margin_ns"] == pytest.approx(1.5)
    assert rep["achievable_period_ns"] == pytest.approx(8.5)
    assert rep["achievable_fmax_mhz"] == pytest.approx(117.647, abs=1e-2)
    assert rep["relaxation_applied"] is False


# ── HONESTY invariants (this is a measurement, never a relaxation) ───────────

@pytest.mark.parametrize("slack", [-0.01, -2.64, -11.45, -75.13])
def test_negative_slack_never_claims_spec_met(slack):
    rep = m.achievable_from_slack(10.0, slack)
    assert rep["spec_met"] is False          # spec target NEVER passes on FAIL
    assert rep["relaxation_applied"] is False  # SDC is never relaxed
    # achievable period is strictly larger than spec on a real shortfall
    assert rep["achievable_period_ns"] > rep["spec_period_ns"]


def test_bad_spec_period_raises():
    with pytest.raises(ValueError):
        m.achievable_from_slack(0.0, -1.0)
    with pytest.raises(ValueError):
        m.achievable_from_slack(None, -1.0)


# ── parsers ─────────────────────────────────────────────────────────────────

def test_parse_worst_slack_report_worst_slack_line():
    assert m.parse_worst_setup_slack("worst slack max -2.64\n") == pytest.approx(-2.64)


def test_parse_worst_slack_picks_most_negative_across_forms():
    txt = (
        "worst slack max -2.64\n"
        "                         -21.89   slack (VIOLATED)\n"
        "                           3.34   slack (MET)\n"
    )
    assert m.parse_worst_setup_slack(txt) == pytest.approx(-21.89)


def test_parse_worst_slack_empty_is_none_not_zero():
    # honest: an empty/irrelevant report yields None, never a fabricated 0
    assert m.parse_worst_setup_slack("no timing here\n") is None
    assert m.parse_worst_setup_slack("") is None


def test_parse_spec_period_create_clock():
    assert m.parse_spec_period_ns(
        "create_clock -name clk -period 10.0 [get_ports clk_i]\n"
    ) == pytest.approx(10.0)
    assert m.parse_spec_period_ns(
        "create_clock -period 25 [get_ports clk]\n"
    ) == pytest.approx(25.0)


def test_parse_spec_period_set_variable_idiom():
    # the wrapper-core staged-SDC convention (ibex: `set clk_period 10.0`)
    sdc = "current_design ibex_core\nset clk_period 10.0\ncreate_clock -period $clk_period $clk_port\n"
    assert m.parse_spec_period_ns(sdc) == pytest.approx(10.0)


# ── verification-sweep TCL builder ──────────────────────────────────────────

def test_sweep_tcl_is_general_and_complete():
    tcl = m.emit_verification_sweep_tcl(
        "tech.tlef", "cells.lef", "tt.lib", "routed.def", "clk_i",
        [10, 13, 15, 20],
    )
    assert "create_clock -name clk -period $P [get_ports clk_i]" in tcl
    assert "worst_slack -max" in tcl
    assert "ACHIEVABLE_SWEEP" in tcl
    assert "foreach P {10 13 15 20}" in tcl
    # benchmark/chip-agnostic: no ibex/sha256/sky130 literal baked in
    low = tcl.lower()
    for lit in ("ibex", "sha256", "sky130", "caravel"):
        assert lit not in low


# ── human formatting ────────────────────────────────────────────────────────

def test_format_human_fail_states_not_a_waiver():
    out = m.format_human(m.achievable_from_slack(10.0, -2.64))
    assert "FAIL" in out
    assert "ACHIEVABLE" in out
    assert "NOT a waiver" in out
    assert "stays FAIL" in out


def test_format_human_met_states_headroom():
    out = m.format_human(m.achievable_from_slack(10.0, 1.5))
    assert "MET" in out
    assert "HEADROOM" in out


# ── CLI ─────────────────────────────────────────────────────────────────────

def _cli(*args):
    return subprocess.run(
        [sys.executable, str(PROG), *args],
        capture_output=True, text=True,
    )


def test_cli_direct_fail_exit1():
    r = _cli("--period", "10", "--worst-slack", "-2.64")
    assert r.returncode == 1          # spec FAIL
    assert "ACHIEVABLE" in r.stdout
    assert "79.1 MHz" in r.stdout


def test_cli_direct_met_exit0():
    r = _cli("--period", "10", "--worst-slack", "1.5")
    assert r.returncode == 0          # spec MET
    assert "HEADROOM" in r.stdout


def test_cli_from_reports_and_json(tmp_path):
    sta = tmp_path / "sta.rpt"
    sta.write_text("worst slack max -2.64\n")
    sdc = tmp_path / "clk.sdc"
    sdc.write_text("create_clock -name clk -period 10.0 [get_ports clk_i]\n")
    out = tmp_path / "rep.json"
    r = _cli("--sta-report", str(sta), "--sdc", str(sdc), "--json", str(out))
    assert r.returncode == 1
    rep = json.loads(out.read_text())
    assert rep["achievable_fmax_mhz"] == pytest.approx(79.114, abs=1e-2)
    assert rep["spec_met"] is False
    assert rep["relaxation_applied"] is False


def test_cli_empty_report_errors_not_fake_pass(tmp_path):
    sta = tmp_path / "sta.rpt"
    sta.write_text("nothing timing-related\n")
    r = _cli("--sta-report", str(sta), "--period", "10")
    assert r.returncode == 2          # honest error, never a fabricated verdict
    assert "no worst setup slack" in r.stderr
