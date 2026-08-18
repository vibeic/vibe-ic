#!/usr/bin/env python3
"""Tests for wake_gen_silence_gate.py — Wave 58 BACKLOG-v12 P0.1.

Covers four applicability paths:
  1. POSITIVE_PASS — wake_gen module with counter that free-runs across
                     frame_active (no else-branch reset of period cnt).
  2. POSITIVE_FAIL — wake_gen module with `if (frame_active) cnt++; else
                     cnt <= 0;` — v0.121-vendor pathology.
  3. SKIP_NON_APPLICABLE — RTL has wake_gen but it does NOT increment a
                     period-class counter (no pulse_gen pathology).
  4. SKIP_NO_CONSTRUCT — RTL has no wake_gen / wake_pulse / pulse_gen
                     module at all.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "wake_gen_silence_gate.py"


def _run(project_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project_dir)],
        capture_output=True, text=True,
    )


# -- Test 1: POSITIVE_PASS — period_cnt free-runs (no else-reset) --

def test_positive_pass_free_running_counter(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "wake_gen.v").write_text(
        "module wake_gen(input clk, input frame_active, output reg pulse);\n"
        "  reg [23:0] period_cnt;\n"
        "  always @(posedge clk) begin\n"
        "    if (~frame_active) begin\n"
        "      if (period_cnt < 24'd250000) period_cnt <= period_cnt + 1;\n"
        "      else                          period_cnt <= 24'd0;\n"
        "      pulse <= (period_cnt == 24'd250000);\n"
        "    end\n"
        # No else-branch reset — counter free-runs.
        "  end\n"
        "endmodule\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout
    assert "no period-counter else-reset pathology" in r.stdout or \
        "wake-pulse generator" in r.stdout


# -- Test 2: POSITIVE_FAIL — period_cnt reset in frame_active else-branch --

def test_positive_fail_else_reset_pathology(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "wake_gen.v").write_text(
        "module wake_gen(input clk, input frame_active, output reg pulse);\n"
        "  reg [23:0] period_cnt;\n"
        "  always @(posedge clk) begin\n"
        "    if (frame_active) begin\n"
        "      period_cnt <= period_cnt + 1;\n"
        "    end else begin\n"
        "      period_cnt <= 24'd0;\n"  # ← pathology
        "    end\n"
        "  end\n"
        "endmodule\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
    assert "period_cnt" in r.stdout or "starvation" in r.stdout


# -- Test 3: SKIP_NON_APPLICABLE — wake_gen file but no period counter --

def test_skip_no_period_counter(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    # Filename hints wake_gen, but body has no period-class counter
    # increment AND no pulse-output port — is_wake_module() will be
    # True (filename hint) but no else-reset pathology can be found.
    (rtl / "wake_gen.v").write_text(
        "module wake_gen(input clk, output reg ready);\n"
        "  always @(posedge clk) begin\n"
        "    ready <= ~ready;\n"
        "  end\n"
        "endmodule\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


# -- Test 4: SKIP_NO_CONSTRUCT — no wake_gen RTL at all --

def test_skip_no_wake_module(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "byte_assembler.v").write_text(
        "module byte_assembler(input clk, output reg byte_vld);\n"
        "endmodule\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP" in r.stdout
    assert "no wake-pulse generator" in r.stdout


# -- Test 5: SKIP — no rtl/ directory at all --

def test_skip_no_rtl_dir(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP" in r.stdout
    assert "no rtl" in r.stdout.lower()


# -- Test 6: PASS_WITH_WAIVER --

def test_pass_with_waiver(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "wake_gen.v").write_text(
        "module wake_gen(input clk, input frame_active, output reg pulse);\n"
        "  reg [23:0] period_cnt;\n"
        "  always @(posedge clk) begin\n"
        "    if (frame_active) begin\n"
        "      period_cnt <= period_cnt + 1;\n"
        "    end else begin\n"
        "      period_cnt <= 24'd0;\n"
        "    end\n"
        "  end\n"
        "endmodule\n"
    )
    (tmp_path / "waivers.json").write_text(json.dumps({
        "wake_pulse_counter_else_reset_intentional":
        "Counter reset under frame_active is required for the test "
        "configuration; see ticket WG-321 for production behaviour.",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS_WITH_WAIVER" in r.stdout
