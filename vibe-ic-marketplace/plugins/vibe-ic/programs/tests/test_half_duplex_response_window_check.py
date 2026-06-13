#!/usr/bin/env python3
"""Tests for half_duplex_response_window_check.py (LL-4)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "half_duplex_response_window_check.py"


def _run(tmp_path: Path, strict: bool = False):
    cmd = [sys.executable, str(PROG), str(tmp_path),
           "--json", str(tmp_path / "rep.json")]
    if strict:
        cmd.append("--strict")
    return subprocess.run(cmd, capture_output=True, text=True)


def _setup(tmp_path: Path, frame_end_ticks: int = 1500,
           tsrs_min_ticks: int = 1500,
           bit0_low_ticks: int = 355,
           bit1_low_ticks: int = 90,
           clk_mhz: int = 50,
           ibt_max: float = 22.0,
           tsrs_min: float = 20.0):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_TIMING_WAVEFORM.json").write_text(json.dumps({
        "ibt_us": [20.0, ibt_max],
        "tSRS_min_us": tsrs_min,
    }))
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "internal_clock_MHz": clk_mhz,
        "fpga_prediv_clock_MHz": clk_mhz,
    }))
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "pkg.sv").write_text(f"""\
package my_pkg;
  localparam int FRAME_END_GAP = {frame_end_ticks};
  localparam int TSRS_MIN = {tsrs_min_ticks};
  localparam int TX_BIT0_LOW = {bit0_low_ticks};
  localparam int TX_BIT1_LOW = {bit1_low_ticks};
endpackage
""")


def test_within_budget_passes(tmp_path):
    """v0118 working: FE=30us, TSRS=30us, total ~67us, budget 82us."""
    _setup(tmp_path, frame_end_ticks=1500, tsrs_min_ticks=1500)
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0


def test_v0118_bug_fails(tmp_path):
    """v0118 bug: FE=80us, total ~117us > 82us budget."""
    _setup(tmp_path, frame_end_ticks=4000, tsrs_min_ticks=1500)
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert any(f["rule"] == "HALF_DUPLEX_RESPONSE_WINDOW_EXCEEDED"
               for f in rep["findings"])


def test_l2_tsrs_max_used_when_present(tmp_path):
    """If L2.tSRS_max_us present, it's the budget basis (overrides default)."""
    _setup(tmp_path, frame_end_ticks=1500, tsrs_min_ticks=1500)
    docs = tmp_path / "phase1" / "generated_docs"
    (docs / "L2_TIMING_WAVEFORM.json").write_text(json.dumps({
        "ibt_us": [20.0, 22.0],
        "tSRS_min_us": 20.0,
        "tSRS_max_us": 50.0,  # tighter than default 82us → 67us > 50us
    }))
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert "L2.tSRS_max_us" in rep["summary"]["budget_basis"]


def test_non_half_duplex_skipped(tmp_path):
    """No L2 with required fields → skip."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "pkg.sv").write_text("module foo; endmodule")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0  # skip


def test_waiver_skips(tmp_path):
    _setup(tmp_path, frame_end_ticks=4000, tsrs_min_ticks=1500)  # over-budget
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waivers": [{
            "id": "half_duplex_response_window_override",
            "rationale": "Master is custom slow-tolerant FPGA emulator",
        }],
    }))
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0


def test_l2_response_window_factor_override(tmp_path):
    """Project may declare a wider factor when master genuinely tolerates."""
    _setup(tmp_path, frame_end_ticks=4000, tsrs_min_ticks=1500)  # default-fail
    docs = tmp_path / "phase1" / "generated_docs"
    (docs / "L2_TIMING_WAVEFORM.json").write_text(json.dumps({
        "ibt_us": [20.0, 22.0],
        "tSRS_min_us": 20.0,
        "response_window_factor": 6.0,  # 22 + 6*20 = 142us > 117us
    }))
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0


def test_clock_auto_detection(tmp_path):
    """RTL has 50MHz-scale ticks; L8 says internal=5MHz, prediv=50MHz.
    Gate should pick 50MHz (the rate at which FE is plausible)."""
    _setup(tmp_path, frame_end_ticks=1500, tsrs_min_ticks=1500)
    docs = tmp_path / "phase1" / "generated_docs"
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "internal_clock_MHz": 5,        # wrong for these tick values
        "fpga_prediv_clock_MHz": 50,    # correct
    }))
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert rep["summary"]["clk_mhz"] == 50


def test_dispatch_l8_override_increases_budget_pressure(tmp_path):
    """v0.119.1: L8.dispatch_cycles_at_50MHz override.
    
    Setup picks budget = 82us (default factor 3.0 * tSRS_min 20 + ibt_max 22).
    With default 4-cycle dispatch @ 50MHz = 0.08us, FE+dispatch+TSRS+bitlow
    = 30 + 0.08 + 30 + 7.1 = 67.18us → PASS.
    With L8 override 1000-cycle dispatch @ 50MHz = 20us, total
    = 30 + 20 + 30 + 7.1 = 87.1us > 82us budget → FAIL under --strict.
    """
    _setup(tmp_path, frame_end_ticks=1500, tsrs_min_ticks=1500)
    docs = tmp_path / "phase1" / "generated_docs"
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "internal_clock_MHz": 50,
        "fpga_prediv_clock_MHz": 50,
        "dispatch_cycles_at_50MHz": 1000,
    }))
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1, \
        "1000-cycle dispatch override must inflate latency past budget"
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert rep["summary"]["dispatch_cycles"] == 1000
    assert rep["summary"]["dispatch_cycles_source"] == \
        "L8.dispatch_cycles_at_50MHz"


def test_dispatch_default_when_l8_no_override(tmp_path):
    """v0.119.1: default 4 cycles when L8 doesn't override."""
    _setup(tmp_path, frame_end_ticks=1500, tsrs_min_ticks=1500)
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert rep["summary"]["dispatch_cycles"] == 4
    assert rep["summary"]["dispatch_cycles_source"] == "default"


def test_latency_constants_not_found_warns(tmp_path):
    """v0.119.1: RTL has constants but none match FRAME_END_GAP /
    CYC_FRAME_END / TSRS_MIN / CYC_TX_RSP_DELAY → WARNING (not silent
    skip). Forces engineer to either rename or file a waiver."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    # Half-duplex L2 markers present so gate triggers
    (docs / "L2_TIMING_WAVEFORM.json").write_text(json.dumps({
        "ibt_us": [20.0, 22.0],
        "tSRS_min_us": 20.0,
    }))
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "internal_clock_MHz": 50,
    }))
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    # Project uses vendor-specific names — gate's known names not present
    (rtl / "pkg.sv").write_text("""\
package vendor_pkg;
  localparam int RESPONSE_IDLE_MIN = 1500;
  localparam int PRE_RESPONSE_GAP = 1500;
  localparam int VENDOR_BIT_LOW = 200;
endpackage
""")
    # No --strict — WARNING by default exits 0
    r = _run(tmp_path, strict=False)
    assert r.returncode == 0
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert any(f["rule"] == "HALF_DUPLEX_LATENCY_CONSTANTS_NOT_FOUND"
               for f in rep["findings"]), \
        "WARNING must fire when RTL has constants but no recognised " \
        "latency-class names"
    # --strict upgrades WARNING → ERROR exits 1
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1


def test_no_constants_at_all_silent_skip(tmp_path):
    """v0.119.1 hardening: zero-constants RTL still silent-skips
    (the gate has no input to verify)."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_TIMING_WAVEFORM.json").write_text(json.dumps({
        "ibt_us": [20.0, 22.0],
        "tSRS_min_us": 20.0,
    }))
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "internal_clock_MHz": 50,
    }))
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "empty.sv").write_text("module empty; endmodule\n")
    r = _run(tmp_path, strict=False)
    assert r.returncode == 0  # silent skip (gate convention: 0 for skipped_reason)
