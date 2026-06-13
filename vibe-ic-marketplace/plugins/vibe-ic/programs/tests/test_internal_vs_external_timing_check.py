"""Tests for internal_vs_external_timing_check.py.

The gate was written from the v068 USB-HID tester FAIL forensics — v068 agent
produced an L8_TIMING_WAVEFORM with only host-side values, Phase 2
then copied those into DUT-side TX code, resulting in a 22μs IBT that
exceeded the far-side 12.7μs BR threshold. This test battery replays
both the FAIL shape (v068-style) and the PASS shape (v052-style).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAM = Path(__file__).parent.parent / "internal_vs_external_timing_check.py"


def _run(tmp_path, waveform, rtl_constants=None):
    w = tmp_path / "L8_TIMING_WAVEFORM.json"
    w.write_text(json.dumps(waveform))
    cmd = [sys.executable, str(PROGRAM), str(w), "--json"]
    if rtl_constants is not None:
        r = tmp_path / "L8_RTL_CONSTANTS.json"
        r.write_text(json.dumps(rtl_constants))
        cmd += ["--layer", str(r)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, json.loads(p.stdout) if p.stdout else {}


def test_v052_shape_passes(tmp_path):
    # v052 L8_TIMING_WAVEFORM shape: two explicit groups + both symbols.
    wf = {
        "rx_counters_at_2p5MHz": {
            "H1_low": [1, 9],
            "H0_low": [10, 30],
            "BR_low": [31, 65],
            "IBT_high": [12, 100],
        },
        "tx_cycles_at_5MHz": {
            "H1_low": 9, "H1_high": 41,
            "H0_low": 35, "H0_high": 15,
            "BR_low": 69, "BR_high": 18,
            "IBT_high": 60,
        },
    }
    rc, out = _run(tmp_path, wf)
    assert rc == 0
    assert out["verdict"] == "PASS"
    assert out["errors"] == 0


def test_v068_shape_flags_missing_both_groups(tmp_path):
    # v068 L8_TIMING_WAVEFORM: only host-side `timing_parameters` flat map.
    wf = {
        "clock_specification": {"main_clk_hz": 5_000_000},
        "timing_parameters": {
            "tDW0_us": {"nom": 7.2},
            "tDW1_us": {"nom": 2.2},
            "tB_break_us": {"nom": 13.8},
            "tIBT_us": {"nom": 22},
        },
        "internal_vs_external_note": "Some freeform prose that mentions internal and external.",
    }
    rc, out = _run(tmp_path, wf)
    assert rc == 1
    assert out["verdict"] == "FAIL"
    rules = [f["rule"] for f in out["findings"]]
    assert "missing_rx_group" in rules
    assert "missing_tx_group" in rules


def test_missing_only_tx_group(tmp_path):
    wf = {
        "rx_counters": {
            "H1_low": [1, 9], "H0_low": [10, 30],
            "BR_low": [31, 65], "IBT_high": [12, 100],
        },
    }
    rc, out = _run(tmp_path, wf)
    assert rc == 1
    rules = [f["rule"] for f in out["findings"]]
    assert "missing_tx_group" in rules
    assert "missing_rx_group" not in rules


def test_missing_only_rx_group(tmp_path):
    wf = {
        "tx_cycles": {
            "H1_low": 9, "H1_high": 41,
            "H0_low": 35, "H0_high": 15,
            "BR_low": 69, "BR_high": 18,
            "IBT_high": 60,
        },
    }
    rc, out = _run(tmp_path, wf)
    assert rc == 1
    rules = [f["rule"] for f in out["findings"]]
    assert "missing_rx_group" in rules
    assert "missing_tx_group" not in rules


def test_group_present_but_missing_br_symbol(tmp_path):
    wf = {
        "rx_counters": {"H1_low": [1, 9], "H0_low": [10, 30]},  # no BR/IBT
        "tx_cycles":   {"H1_low": 9, "H0_low": 35, "BR_low": 69, "IBT_high": 60},
    }
    rc, out = _run(tmp_path, wf)
    assert rc == 1
    rules = [f["rule"] for f in out["findings"]]
    assert "rx_missing_symbols" in rules


def test_ibt_vs_br_inversion_in_us_form(tmp_path):
    # Both values in μs; IBT > BR should trigger cross-check.
    wf = {
        "rx_counters_us": {
            "H1_low_us": [0.02, 3.84],
            "H0_low_us": [3.92, 12.24],
            "BR_low_us": [12.74, 26.28],
            "IBT_high_us": [4.68, 40.0],
        },
        "tx_cycles_us": {
            "H1_low_us": 1.8, "H1_high_us": 8.2,
            "H0_low_us": 7.0, "H0_high_us": 3.0,
            "BR_low_us": 13.8, "BR_high_us": 3.6,
            "IBT_high_us": 22.0,   # > rx BR min 12.74us
        },
    }
    rc, out = _run(tmp_path, wf)
    assert rc == 1
    rules = [f["rule"] for f in out["findings"]]
    assert "ibt_exceeds_br_threshold" in rules


def test_ibt_vs_br_no_inversion_us(tmp_path):
    wf = {
        "rx_counters_us": {
            "H1_low_us": [0.02, 3.84],
            "H0_low_us": [3.92, 12.24],
            "BR_low_us": [12.74, 26.28],
            "IBT_high_us": [4.68, 40.0],
        },
        "tx_cycles_us": {
            "H1_low_us": 1.8, "H1_high_us": 8.2,
            "H0_low_us": 7.0, "H0_high_us": 3.0,
            "BR_low_us": 13.8, "BR_high_us": 3.6,
            "IBT_high_us": 12.0,   # < rx BR min 12.74us — OK
        },
    }
    rc, out = _run(tmp_path, wf)
    assert rc == 0
    assert out["verdict"] == "PASS"


def test_tick_units_do_not_trigger_false_ibt_br(tmp_path):
    # Raw tick values without μs context: cross-check must be skipped,
    # not falsely report inversion based on raw magnitudes.
    wf = {
        "rx_counters_at_2p5MHz": {
            "H1_low": [1, 9],
            "H0_low": [10, 30],
            "BR_low": [31, 65],
            "IBT_high": [12, 100],
        },
        "tx_cycles_at_5MHz": {
            "H1_low": 9, "H1_high": 41,
            "H0_low": 35, "H0_high": 15,
            "BR_low": 69, "BR_high": 18,
            "IBT_high": 60,
            # 60 ticks @5MHz = 12us  ;  rx BR_low 31 ticks @2.5MHz = 12.4us.
            # Raw comparison 60>=31 would falsely FAIL — gate must NOT rely
            # on raw values when units are ambiguous.
        },
    }
    rc, out = _run(tmp_path, wf)
    assert rc == 0, f"raw-tick form must not trigger false IBT inversion: {out}"


def test_malformed_json_is_error(tmp_path):
    w = tmp_path / "bad.json"
    w.write_text("{ not: valid json")
    p = subprocess.run([sys.executable, str(PROGRAM), str(w)],
                       capture_output=True, text=True)
    assert p.returncode == 2


def test_missing_file(tmp_path):
    p = subprocess.run([sys.executable, str(PROGRAM), str(tmp_path / "nope.json")],
                       capture_output=True, text=True)
    assert p.returncode == 2
