#!/usr/bin/env python3
"""Tests for tx_bit_timing_units_check.py — see ROOT_CAUSE_ANALYSIS Area 1."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "tx_bit_timing_units_check.py"


def _run(tmp_path: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path)],
        capture_output=True, text=True,
    )


def _write(p: Path, body: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def _l8_with_clock(tmp_path: Path, clk_hz: float, **us_fields):
    body = {"tx_clock_hz": clk_hz}
    body.update(us_fields)
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps(body))


def _rtl(tmp_path: Path, body: str, name: str = "tx_phy.v"):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / name).write_text(body)


def test_no_tx_phy_silent_pass(tmp_path):
    """Project with no rtl/tx_phy* file — gate skips."""
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "no rtl" in r.stdout.lower() or "not applicable" in r.stdout


def test_no_l8_silent_pass(tmp_path):
    """phase2/stage1/rtl/tx_phy* exists but L8/L11 absent — gate skips."""
    _rtl(tmp_path, "module tx_phy; localparam TX_BIT0_LOW = 36; endmodule\n")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "L8/L11 absent" in r.stdout or "skipped" in r.stdout


def test_within_tolerance_passes(tmp_path):
    """At 2.5MHz, BIT0_LOW=17 → 6.8µs == spec 6.8µs ⇒ PASS."""
    _l8_with_clock(tmp_path, 2_500_000.0, tx_bit0_low_us=6.8)
    _rtl(tmp_path, """module tx_phy;
  localparam TX_BIT0_LOW = 17;   // expected 6.8 us
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_outside_tolerance_fails(tmp_path):
    """At 5MHz, BIT0_LOW=36 → 7.2µs vs spec 6.8µs (band 6.46..7.14) ⇒ FAIL."""
    _l8_with_clock(tmp_path, 5_000_000.0, tx_bit0_low_us=6.8)
    _rtl(tmp_path, """module tx_phy;
  localparam TX_BIT0_LOW = 36;   // ours: 7.2us — outside band
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "outside" in r.stdout.lower()


def test_waiver_skips(tmp_path):
    _l8_with_clock(tmp_path, 5_000_000.0, tx_bit0_low_us=6.8)
    _rtl(tmp_path, "module tx_phy; localparam TX_BIT0_LOW = 36; endmodule\n")
    (tmp_path / "waivers.json").write_text(json.dumps({
        "tx_bit_timing_units_alternative":
            "Custom asymmetric tuning per chip-specific lab measurement",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "PASS_WITH_WAIVER" in r.stdout


def test_asymmetric_ibt_after_0_and_after_1(tmp_path):
    """At 2.5MHz, IBT_AFTER_0=49→19.6µs and IBT_AFTER_1=35→14.0µs both
    within ±5% of separately-declared specs ⇒ PASS. Generic IBT param
    not present — and the gate would skip the generic IBT key when
    asymmetric variants exist anyway."""
    _l8_with_clock(tmp_path, 2_500_000.0,
                   tx_ibt_after_0_us=19.6, tx_ibt_after_1_us=14.0)
    _rtl(tmp_path, """module tx_phy;
  localparam IBT_AFTER_0 = 49;   // 19.6us
  localparam IBT_AFTER_1 = 35;   // 14.0us
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_l9_clock_binding_resolved(tmp_path):
    """L9.clock_binding.tx_phy → 'sys_clk_2p5m' should resolve to L8
    clocks table at 2.5MHz, NOT default to a faster L8 clock."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "clocks": {
            "sys_clk_5m":   {"hz": 5_000_000},
            "sys_clk_2p5m": {"hz": 2_500_000},
        },
        "tx_clock_hz": 5_000_000,    # decoy: should be ignored
        "tx_bit0_low_us": 6.8,
    }))
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "clock_binding": {"tx_phy": "sys_clk_2p5m"},
    }))
    _rtl(tmp_path, "module tx_phy; localparam TX_BIT0_LOW = 17; endmodule\n")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "2.500 MHz" in r.stdout or "2.5" in r.stdout


def test_no_spec_us_silent_skip(tmp_path):
    """L8 has clock but no _us spec for the constants — gate skips."""
    _l8_with_clock(tmp_path, 2_500_000.0)
    _rtl(tmp_path, "module tx_phy; localparam TX_BIT0_LOW = 17; endmodule\n")
    r = _run(tmp_path)
    assert r.returncode == 0
    # Either skipped at param-level (no_spec_us) or at gate-level (no pair).
    assert "skipped" in r.stdout.lower() or "PASS" in r.stdout
