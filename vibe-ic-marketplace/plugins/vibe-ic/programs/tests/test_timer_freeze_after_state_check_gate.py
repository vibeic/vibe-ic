#!/usr/bin/env python3
"""Tests for timer_freeze_after_state_check.py."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "timer_freeze_after_state_check.py"


def _run(args, **kw):
    return subprocess.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True, **kw,
    )


def test_help():
    r = _run(["--help"])
    assert r.returncode == 0


def test_empty_rtl(tmp_path):
    (tmp_path / "top.v").write_text("module top; endmodule\n")
    r = _run(["--rtl-dir", str(tmp_path)])
    assert r.returncode == 0


def test_v029_primary_if_state_freeze_accepted(tmp_path):
    """v0.119.29: primary `if (state) cnt <= 0;` is logically equivalent
    to `else if (state) cnt <= 0;` and must also count as a valid freeze.
    The agent on v0.119.27 vendor was false-flagged for this form."""
    (tmp_path / "wake_ctrl.sv").write_text("""\
module wake_ctrl(input clk, input awake);
  reg [9:0] tito_cnt;
  always @(posedge clk) begin
    if (awake)
      tito_cnt <= 10'd0;        // primary-if freeze branch
    else
      tito_cnt <= tito_cnt + 1; // unfrozen
  end
endmodule
""")
    r = _run(["--rtl-dir", str(tmp_path)])
    assert r.returncode == 0, r.stdout


def test_else_if_state_freeze_still_accepted(tmp_path):
    """Regression: original `else if (state)` form still counts."""
    (tmp_path / "wake_ctrl.sv").write_text("""\
module wake_ctrl(input clk, input rst_n, input awake);
  reg [9:0] tito_cnt;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)        tito_cnt <= 10'd0;
    else if (awake)    tito_cnt <= 10'd0;
    else               tito_cnt <= tito_cnt + 1;
  end
endmodule
""")
    r = _run(["--rtl-dir", str(tmp_path)])
    assert r.returncode == 0, r.stdout


def test_no_freeze_branch_still_fails(tmp_path):
    """Negative: a counter that imports `awake` but has NO freeze branch
    in any form must still FAIL (the actual bug pattern this gate
    catches)."""
    (tmp_path / "wake_ctrl.sv").write_text("""\
module wake_ctrl(input clk, input awake);
  reg [9:0] tito_cnt;
  always @(posedge clk) begin
    tito_cnt <= tito_cnt + 1;   // unconditional — bug
  end
endmodule
""")
    r = _run(["--rtl-dir", str(tmp_path)])
    assert r.returncode == 1, r.stdout
