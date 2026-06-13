#!/usr/bin/env python3
"""Tests for tx_bit_width_min_resolution_check.py (LL-26).

The gate is GENERAL — protocol-agnostic, chip-agnostic. Triggered only
when both a chip TX clock period AND L2 tolerance windows are declared.
Silent-skips otherwise (no false alerts).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "tx_bit_width_min_resolution_check.py"


def _run(tmp_path: Path, *extra) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), *extra],
        capture_output=True, text=True,
    )


def _write_l9(tmp_path: Path, data: dict):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L9_INTEGRATION.json").write_text(json.dumps(data))


def _write_l2(tmp_path: Path, data: dict, name: str = "L2_FRS.json"):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / name).write_text(json.dumps(data))


def test_silent_skip_no_l9_no_rtl(tmp_path):
    """No TX clock declared → silent-skip (no false alert)."""
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "skipped" in r.stdout.lower() or "PASS" in r.stdout


def test_silent_skip_no_l2_tolerances(tmp_path):
    """L9 has TX clock but L2 has no tolerance windows → silent-skip."""
    _write_l9(tmp_path, {"tx_clk_ns": 200})
    _write_l2(tmp_path, {"setup_us": 5})  # single value, no range
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "no L2 timing tolerance" in r.stdout or "PASS" in r.stdout


def test_pass_when_clock_fast_enough(tmp_path):
    """5 MHz TX clock (T=200 ns), tolerances ≥ 4 us: edge-snap 100 ns is
    well within safety factor 4 → PASS."""
    _write_l9(tmp_path, {"tx_clk_ns": 200})
    _write_l2(tmp_path, {
        "tSRS_us": [20.0, 80.0],         # dT = 60 us
        "ibt_us": [8.5, 22.0],           # dT = 13.5 us
        "frame_end_gap_us": [27.0, 35.0], # dT = 8 us
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout
    assert "fine" in r.stdout


def test_warn_when_clock_borderline(tmp_path):
    """1 MHz TX clock (T=1000 ns, edge-snap 500 ns = 0.5us). With a
    1us-wide tolerance: 0.5us / (1us/4) = 2.0x → WARN (between 1x and 10x)."""
    _write_l9(tmp_path, {"tx_clk_ns": 1000})
    _write_l2(tmp_path, {"tight_us": [10.0, 11.0]})  # dT = 1us
    r = _run(tmp_path, "--safety-factor", "4", "--warn-factor", "10")
    assert r.returncode == 0, r.stdout
    assert "WARN" in r.stdout


def test_fail_when_clock_too_coarse(tmp_path):
    """100 kHz TX clock (T=10000 ns, edge-snap 5us). With 1us tolerance:
    5us / (1us/4) = 20x → FAIL (above warn-factor 10)."""
    _write_l9(tmp_path, {"tx_clk_ns": 10000})
    _write_l2(tmp_path, {"tight_us": [10.0, 11.0]})  # dT = 1us
    r = _run(tmp_path, "--safety-factor", "4", "--warn-factor", "10")
    assert r.returncode == 1, r.stdout
    assert "FAIL" in r.stdout
    assert "too coarse" in r.stdout


def test_clk_freq_mhz_form(tmp_path):
    """L9 may declare clk_freq_mhz instead of tx_clk_ns. Both must work."""
    _write_l9(tmp_path, {"clk_freq_mhz": 5})  # T = 200 ns
    _write_l2(tmp_path, {"tSRS_us": [20.0, 80.0]})
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "200.0ns" in r.stdout or "5" in r.stdout


def test_rtl_parameter_form(tmp_path):
    """Falls back to RTL parameter if no L9 declares the clock."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "example_chip_pkg.sv").write_text(
        "package example_chip_pkg;\n"
        "  parameter int TX_CLK_NS = 200;\n"
        "endpackage\n"
    )
    _write_l2(tmp_path, {"tSRS_us": [20.0, 80.0]})
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "TX_CLK_NS" in r.stdout


def test_dict_form_min_max(tmp_path):
    """L2 timing values may use the {min, max} dict form."""
    _write_l9(tmp_path, {"tx_clk_ns": 200})
    _write_l2(tmp_path, {
        "ibt_us": {"min": 8.5, "max": 22.0},
    })
    r = _run(tmp_path)
    assert r.returncode == 0


def test_waiver_skips_fail(tmp_path):
    """tx_bit_width_resolution_intentional waiver downgrades FAIL to PASS_WITH_WAIVER."""
    _write_l9(tmp_path, {"tx_clk_ns": 10000})
    _write_l2(tmp_path, {"tight_us": [10.0, 11.0]})
    (tmp_path / "waivers.json").write_text(json.dumps({
        "tx_bit_width_resolution_intentional":
            "Slow clock is intentional for low-power mode; oracle dump confirms accept",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "WAIVER" in r.stdout


def test_general_protocol_lin_bus(tmp_path):
    """Generality check: works for a non-half-duplex protocol (LIN-style
    timing tolerances). The gate doesn't care about protocol type."""
    _write_l9(tmp_path, {"tx_clk_ns": 50})
    _write_l2(tmp_path, {
        "lin_breakfield_ms": [13.0, 13.5],   # tight LIN tolerance
        "lin_byte_ms": [1.04, 1.05],
    })
    r = _run(tmp_path)
    assert r.returncode == 0  # 25ns edge-snap << ms tolerances


def test_v027_l8_clock_period_ns_accepted(tmp_path):
    """v0.119.27: L8_RTL_CONSTANTS.json `clock_period_ns` is now a
    valid source for the chip TX clock. The gate previously only
    looked in L9 → silent skip whenever the project lived in L8."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "clock_period_ns": 20,
    }))
    (docs / "L2_FRS.json").write_text(json.dumps({
        "tSRS_us": [20.0, 80.0],
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "20.0ns" in r.stdout
    assert "L8" in r.stdout


def test_v027_l8_clock_domain_hz_accepted(tmp_path):
    """v0.119.27: also accept `clock_domain_hz` and convert to ns."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "clock_domain_hz": 50_000_000,
    }))
    (docs / "L2_FRS.json").write_text(json.dumps({
        "tSRS_us": [20.0, 80.0],
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "20.0ns" in r.stdout
    assert "Hz" in r.stdout


def test_no_false_alert_on_single_value_keys(tmp_path):
    """Single-value (TYP-only) timing fields must NOT trigger anything —
    they have no tolerance window so the gate has nothing to check."""
    _write_l9(tmp_path, {"tx_clk_ns": 10000})  # very slow
    _write_l2(tmp_path, {
        "tSRS_us": 50,        # bare TYP
        "ibt_us": 15,         # bare TYP
        "frame_us": 100,      # bare TYP
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    # Even though clock is slow, no tolerance windows → silent skip
    assert "no L2 timing tolerance" in r.stdout or "tolerance window" in r.stdout


def test_v028_clock_source_disagree_emits_warn(tmp_path):
    """v0.119.28: when L8 has both `clock_period_ns` and a `*_hz` key
    that disagree by >1%, gate must emit a WARN to stderr (gross
    misconfig — factor-of-1000 in this fixture). Period still wins as
    the resolved value, but the user gets a heads-up."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "clock_period_ns": 20,        # 50 MHz
        "clock_domain_hz": 1_000_000, # 1 MHz → period 1000ns, OFF by 50×
    }))
    _write_l2(tmp_path, {"tSRS_us": [20, 80]})
    r = _run(tmp_path)
    assert "clock-source disagreement" in r.stderr, \
        f"expected WARN in stderr, got stderr={r.stderr!r}"
    # Period still resolves; no FAIL by virtue of the disagreement alone
    # (user might be intentionally exploring; the gate's job is to flag,
    # not block).


def test_v028_consistent_clock_sources_no_warn(tmp_path):
    """When both keys are present and consistent (50 MHz ≡ 20 ns),
    no WARN. This proves the threshold is generous enough to allow
    paired declarations."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "clock_period_ns": 20.0,
        "clock_domain_hz": 50_000_000,  # exact match
    }))
    _write_l2(tmp_path, {"tSRS_us": [20, 80]})
    r = _run(tmp_path)
    assert "clock-source disagreement" not in r.stderr, \
        f"unexpected WARN on consistent clocks: stderr={r.stderr!r}"


def test_v028_floating_point_noise_does_not_trip_warn(tmp_path):
    """50 MHz declared as period=20.0001 ns is well within 1% — no
    WARN. Prevents the WARN from being annoying on hand-rounded vals."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "clock_period_ns": 20.0001,
        "clock_domain_hz": 50_000_000,  # 20.0 ns exact, 0.0005% off
    }))
    _write_l2(tmp_path, {"tSRS_us": [20, 80]})
    r = _run(tmp_path)
    assert "clock-source disagreement" not in r.stderr, \
        f"sub-1% noise must not trip: stderr={r.stderr!r}"
