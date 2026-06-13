#!/usr/bin/env python3
"""Tests for chip_clock_toggle_divider_when_master_already_target_check.py
(LL-30). Chip-agnostic — only triggers when L9/L2 declare master==chip
target."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "chip_clock_toggle_divider_when_master_already_target_check.py"


def _run(tmp_path: Path):
    return subprocess.run([sys.executable, str(PROG), str(tmp_path)],
                          capture_output=True, text=True)


def _put_rtl(tmp_path: Path, name: str, body: str):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / name).write_text(body)


def _put_l2(tmp_path: Path, freq_hz: int):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_FRS.json").write_text(json.dumps({
        "clock": {"primary": {"freq_hz": freq_hz, "source": "internal"}}
    }))


def _put_l9(tmp_path: Path, master_hz: int):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "fpga_master_clock_hz": master_hz
    }))


# 1. Silent-skip baseline: no rtl dir.
def test_no_rtl_silent_pass(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "skipped" in r.stdout.lower()


# 2. Silent-skip when no L9/L2 frequency declared.
def test_no_freq_decl_silent_pass(tmp_path):
    _put_rtl(tmp_path, "top.v",
             "module top; always_ff @(posedge mclk) clk <= ~clk; "
             "endmodule")
    r = _run(tmp_path)
    assert r.returncode == 0


# 3. Silent-skip when master != chip target (legit divider).
def test_master_differs_from_chip_silent_pass(tmp_path):
    _put_l2(tmp_path, 5_000_000)
    _put_l9(tmp_path, 50_000_000)
    _put_rtl(tmp_path, "top.v",
             "module top; always_ff @(posedge mclk) clk_5m <= ~clk_5m;"
             " chip_top u_chip(.clk(clk_5m)); endmodule")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "legitimate divider" in r.stdout.lower()


# 4. PASS — master == chip and direct connection (no divider).
def test_master_equals_chip_direct_pass(tmp_path):
    _put_l2(tmp_path, 50_000_000)
    _put_l9(tmp_path, 50_000_000)
    _put_rtl(tmp_path, "top.v",
             "module top; chip_top u_chip(.clk(mclk_50m)); endmodule")
    r = _run(tmp_path)
    assert r.returncode == 0


# 5. FAIL — master == chip target but RTL toggles a divider into chip.
def test_unnecessary_divider_fails(tmp_path):
    _put_l2(tmp_path, 50_000_000)
    _put_l9(tmp_path, 50_000_000)
    _put_rtl(tmp_path, "top.v",
             "module top;\n"
             "  always_ff @(posedge MAX10_CLK1_50) clk_2p5m <= ~clk_2p5m;\n"
             "  chip_top u_chip(.clk(clk_2p5m));\n"
             "endmodule\n")
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "clk_2p5m" in r.stdout


# 6. Waiver suppresses the failure.
def test_waiver_allows_divider(tmp_path):
    _put_l2(tmp_path, 50_000_000)
    _put_l9(tmp_path, 50_000_000)
    _put_rtl(tmp_path, "top.v",
             "module top;\n"
             "  always_ff @(posedge MAX10_CLK1_50) clk_2p5m <= ~clk_2p5m;\n"
             "  chip_top u_chip(.clk(clk_2p5m));\n"
             "endmodule\n")
    (tmp_path / "waivers.json").write_text(json.dumps({
        "chip_clock_intentional_divider":
            "Vendor reference uses divider for legacy STA target",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "PASS_WITH_WAIVER" in r.stdout


# 7. Edge case: toggle exists in RTL but isn't connected to chip clock.
def test_toggle_not_on_chip_clock_pass(tmp_path):
    _put_l2(tmp_path, 50_000_000)
    _put_l9(tmp_path, 50_000_000)
    _put_rtl(tmp_path, "top.v",
             "module top;\n"
             "  always_ff @(posedge mclk) blink <= ~blink;\n"
             "  chip_top u_chip(.clk(mclk));\n"
             "endmodule\n")
    r = _run(tmp_path)
    assert r.returncode == 0


# 8. Master freq declared via RTL comment hint.
def test_freq_via_rtl_comment_hint(tmp_path):
    _put_l2(tmp_path, 50_000_000)
    _put_rtl(tmp_path, "top.v",
             "// MASTER_CLOCK_HZ = 50000000\n"
             "module top;\n"
             "  always_ff @(posedge mclk) clk_div <= ~clk_div;\n"
             "  chip_top u_chip(.clk(clk_div));\n"
             "endmodule\n")
    r = _run(tmp_path)
    # Comment hint is read raw, so master == chip == 50 MHz, divider
    # connected to chip clock → FAIL.
    assert r.returncode == 1
    assert "clk_div" in r.stdout
