#!/usr/bin/env python3
"""Tests for crc_residue_settle_state_required_check.py
(Wave 26 / v0.119.58)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "crc_residue_settle_state_required_check.py")


def _run(args, **kw):
    return subprocess.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True, **kw)


def _make_project(tmp_path: Path,
                  rtl_files: dict[str, str],
                  waiver: str | None = None) -> Path:
    proj = tmp_path / "p"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    for fname, body in rtl_files.items():
        (proj / "phase2" / "stage1" / "rtl" / fname).write_text(body)
    if waiver:
        (proj / "waivers.json").write_text(json.dumps(
            {"crc_settle_in_validate_state_intentional": waiver}))
    return proj


# ----------------------------------------------------------------------

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0


def test_settle_state_pass(tmp_path):
    """RX_BIT → S_RX_BYTE_DONE → S_VALIDATE → PASS."""
    fsm = """
    module main_fsm(input clk, output reg verdict);
      reg [3:0] state_q;
      localparam S_RX_BIT_LOW    = 4'd1;
      localparam S_RX_BIT_HIGH   = 4'd2;
      localparam S_RX_BYTE_DONE  = 4'd3;
      localparam S_VALIDATE      = 4'd4;
      always @(posedge clk) begin
        case (state_q)
          S_RX_BIT_LOW: state_q <= S_RX_BIT_HIGH;
          S_RX_BIT_HIGH: state_q <= S_RX_BYTE_DONE;
          S_RX_BYTE_DONE: state_q <= S_VALIDATE;
          S_VALIDATE: verdict <= 1'b1;
        endcase
      end
    endmodule
    """
    proj = _make_project(tmp_path, {"main_fsm.sv": fsm})
    r = _run([str(proj), "--json"])
    assert r.returncode == 0, r.stdout
    out = json.loads(r.stdout)
    assert out["verdict"] == "PASS"


def test_no_settle_fail(tmp_path):
    """v0.119.57 bug: S_RX_BIT_HIGH → S_VALIDATE direct → FAIL."""
    fsm = """
    module main_fsm(input clk, output reg verdict);
      reg [3:0] state_q;
      localparam S_RX_BIT_LOW  = 4'd1;
      localparam S_RX_BIT_HIGH = 4'd2;
      localparam S_VALIDATE    = 4'd3;
      always @(posedge clk) begin
        case (state_q)
          S_RX_BIT_LOW: state_q <= S_RX_BIT_HIGH;
          S_RX_BIT_HIGH: state_q <= S_VALIDATE;
          S_VALIDATE: verdict <= 1'b1;
        endcase
      end
    endmodule
    """
    proj = _make_project(tmp_path, {"main_fsm.sv": fsm})
    r = _run([str(proj), "--json"])
    assert r.returncode == 1, r.stdout
    out = json.loads(r.stdout)
    assert out["verdict"] == "FAIL"


def test_with_waiver_pass(tmp_path):
    """Waiver ≥40 chars → PASS_WITH_WAIVER on otherwise-FAIL FSM."""
    fsm = """
    module main_fsm(input clk, output reg verdict);
      reg [3:0] state_q;
      localparam S_RX_BIT_HIGH = 4'd1;
      localparam S_VALIDATE    = 4'd2;
      always @(posedge clk) begin
        case (state_q)
          S_RX_BIT_HIGH: state_q <= S_VALIDATE;
          S_VALIDATE: verdict <= 1'b1;
        endcase
      end
    endmodule
    """
    proj = _make_project(
        tmp_path, {"main_fsm.sv": fsm},
        waiver=("CRC engine is purely combinational in this design "
                "so crc_out is valid in the same cycle the last bit "
                "is fed; settle state is not necessary."))
    r = _run([str(proj), "--json"])
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["verdict"] == "PASS_WITH_WAIVER"
