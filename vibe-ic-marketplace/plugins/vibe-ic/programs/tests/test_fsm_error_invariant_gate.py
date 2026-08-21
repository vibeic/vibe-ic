#!/usr/bin/env python3
"""Tests for fsm_error_invariant.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "fsm_error_invariant.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_pass_clean_fsm(tmp_path):
    rtl = tmp_path / "fsm.v"
    rtl.write_text("module fsm;\n  reg [1:0] state;\n  always @(posedge clk) state <= next_state;\nendmodule\n")
    r = _run([str(rtl)])
    assert r.returncode == 0

def test_detect_error_invariant(tmp_path):
    rtl = tmp_path / "bad_fsm.v"
    rtl.write_text("module bad;\n  reg [1:0] state;\n  wire fsm_error = (state == 2'b11);\n  assign upper_error = fsm_error;\nendmodule\n")
    r = _run([str(rtl)])
    assert r.returncode == 0


def test_error_in_fsm_state_flags_warning(tmp_path):
    """Baseline: error assertion inside non-idle FSM state must trigger
    the warning (returncode 1) so the designer reviews invariants.
    Reset block kept in a SEPARATE always to avoid the existing
    `if (!rst_n)` context-skip from suppressing operational asserts."""
    rtl = tmp_path / "rx_fsm.v"
    rtl.write_text("""\
module rx_fsm(input clk, input rst_n);
  reg rx_error;
  reg [3:0] state;
  // Operational FSM in its own always block — no rst_n in scope here.
  always @(posedge clk) begin
    case (state)
      S_RX_BIT: begin
        rx_error <= 1'b1;
      end
    endcase
  end
endmodule
""")
    r = _run([str(rtl)])
    assert r.returncode == 1, r.stdout


def test_recoverable_annotation_silences_warning(tmp_path):
    """v0.119.25: `// fsm_error: recoverable` next to the assignment
    silences the warning. The docstring promised this; the v0.119.24
    code didn't implement it. Fixed here."""
    rtl = tmp_path / "rx_fsm.v"
    rtl.write_text("""\
module rx_fsm(input clk, input rst_n);
  reg rx_error;
  reg [3:0] state;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      rx_error <= 0;
    end else begin
      case (state)
        S_RX_BIT: begin
          // fsm_error: recoverable — 1-cycle glitch is tolerated by mac
          rx_error <= 1'b1;
        end
      endcase
    end
  end
endmodule
""")
    r = _run([str(rtl)])
    assert r.returncode == 0, \
        f"recoverable annotation should silence: {r.stdout}"


def test_intentional_annotation_silences_too(tmp_path):
    """`intentional` and `tolerated` are universal silencers."""
    rtl = tmp_path / "rx_fsm.v"
    rtl.write_text("""\
module rx_fsm(input clk, input rst_n);
  reg rx_error;
  reg [3:0] state;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) rx_error <= 0;
    else case (state)
      S_RX_BIT: begin
        rx_error <= 1'b1;  // fsm_error: intentional — packet end
      end
    endcase
  end
endmodule
""")
    r = _run([str(rtl)])
    assert r.returncode == 0, r.stdout


def test_v026_annotation_outside_window_does_not_silence(tmp_path):
    """v0.119.26 boundary test: the annotation override window is ±2
    lines around the assignment. An annotation 3+ lines before/after
    must NOT silence — otherwise stale comments pages away would mute
    real warnings. Boundary opposite of `recoverable_annotation_silences`."""
    rtl = tmp_path / "rx_fsm.v"
    rtl.write_text("""\
module rx_fsm(input clk);
  reg rx_error;
  reg [3:0] state;
  // fsm_error: recoverable
  // (comment is 4 lines before the assignment — outside the ±2 window)
  always @(posedge clk) begin
    case (state)
      S_RX_BIT: begin
        rx_error <= 1'b1;
      end
    endcase
  end
endmodule
""")
    r = _run([str(rtl)])
    assert r.returncode == 1, \
        f"annotation outside ±2 window must not silence: {r.stdout}"


def test_unrelated_comment_does_not_silence(tmp_path):
    """A nearby comment that isn't an `fsm_error: <kind>` annotation
    must NOT silence the warning."""
    rtl = tmp_path / "rx_fsm.v"
    rtl.write_text("""\
module rx_fsm(input clk);
  reg rx_error;
  reg [3:0] state;
  always @(posedge clk) begin
    case (state)
      S_RX_BIT: begin
        // TODO: revisit — recoverable per spec section 4.2
        rx_error <= 1'b1;
      end
    endcase
  end
endmodule
""")
    r = _run([str(rtl)])
    # The free-form "recoverable" word in a TODO is NOT the structured
    # `fsm_error:` annotation; warning must still fire.
    assert r.returncode == 1, r.stdout
