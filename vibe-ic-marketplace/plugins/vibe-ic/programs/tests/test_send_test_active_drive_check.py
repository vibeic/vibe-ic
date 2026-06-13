#!/usr/bin/env python3
"""Tests for send_test_active_drive_check.py — Wave 27 Gate 1."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "send_test_active_drive_check.py")


def _run(args, **kw):
    return subprocess.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True, **kw)


L3_DEFAULT = {
    "doc": "L3",
    "commands": [
        {"opcode": "0x40", "name": "Connect / Wake", "cmd_len": 2,
         "rsp_op": "0x41", "rsp_len": 2},
        {"opcode": "0x74", "name": "SEND_TEST Get ID", "cmd_len": 4,
         "rsp_op": "0x75", "rsp_len": 8},
    ],
}


def _make(tmp_path: Path, l3: dict | None = None,
          rtl: dict[str, str] | None = None,
          waiver: str | None = None) -> Path:
    proj = tmp_path / "p"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "l_docs").mkdir(parents=True, exist_ok=True)
    if l3 is not None:
        (proj / "l_docs" / "L3.json").write_text(json.dumps(l3))
    if rtl:
        (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True, exist_ok=True)
        for name, body in rtl.items():
            (proj / "phase2" / "stage1" / "rtl" / name).write_text(body)
    if waiver is not None:
        (proj / "waivers.json").write_text(json.dumps(
            {"send_test_silent_intentional": waiver}))
    return proj


def test_help():
    r = _run(["--help"])
    assert r.returncode == 0


def test_active_drive_present_pass(tmp_path):
    """SEND_TEST → S_TX_BIT_LOW with tx_oe=1 and bit_idx counter → PASS."""
    rtl_main = """\
module main_fsm(input clk, output reg tx_oe);
  typedef enum { S_IDLE, S_DISPATCH, S_TX_BIT_LOW, S_TX_BIT_HIGH } st_t;
  st_t state;
  reg [7:0] cur_op;
  reg [3:0] bit_idx;
  always @(posedge clk) begin
    case (state)
      S_DISPATCH: begin
        if (cur_op == 8'h74) begin
          state <= S_TX_BIT_LOW;
        end
      end
      S_TX_BIT_LOW: begin
        tx_oe <= 1'b1;
        bit_idx <= bit_idx + 1;
        state <= S_TX_BIT_HIGH;
      end
      S_TX_BIT_HIGH: begin
        tx_oe <= 1'b0;
        state <= S_TX_BIT_LOW;
      end
    endcase
  end
endmodule
"""
    proj = _make(tmp_path, l3=L3_DEFAULT, rtl={"main_fsm.sv": rtl_main})
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_no_dispatch_fail(tmp_path):
    """0x74 appears in case but the arm has no `state <=` → FAIL."""
    rtl_main = """\
module main_fsm(input clk, output reg tx_oe);
  typedef enum { S_IDLE, S_DISPATCH, S_TX_BIT_LOW } st_t;
  st_t state;
  reg [7:0] cur_op;
  always @(posedge clk) begin
    case (state)
      S_DISPATCH: begin
        // bug: opcode known but no state transition (falls through)
        if (cur_op == 8'h74) begin
          // intentionally empty
        end
      end
      S_TX_BIT_LOW: begin
        tx_oe <= 1'b1;
      end
    endcase
  end
endmodule
"""
    proj = _make(tmp_path, l3=L3_DEFAULT, rtl={"main_fsm.sv": rtl_main})
    r = _run([str(proj), "--json", str(tmp_path / "out.json")])
    assert r.returncode == 1, r.stdout + r.stderr
    out = json.loads((tmp_path / "out.json").read_text())
    assert any(f["rule"].startswith("SEND_TEST_NO")
               for f in out["findings"])


def test_dispatch_no_oe_fail(tmp_path):
    """Dispatch leads to a state but TX path never asserts OE → FAIL."""
    rtl_main = """\
module main_fsm(input clk, output reg tx_oe);
  typedef enum { S_IDLE, S_DISPATCH, S_TX_DUMMY } st_t;
  st_t state;
  reg [7:0] cur_op;
  always @(posedge clk) begin
    case (state)
      S_DISPATCH: begin
        if (cur_op == 8'h74) begin
          state <= S_TX_DUMMY;
        end
      end
      S_TX_DUMMY: begin
        // bug: never drives tx_oe
        state <= S_IDLE;
      end
    endcase
  end
endmodule
"""
    proj = _make(tmp_path, l3=L3_DEFAULT, rtl={"main_fsm.sv": rtl_main})
    r = _run([str(proj), "--json", str(tmp_path / "out.json")])
    assert r.returncode == 1, r.stdout
    out = json.loads((tmp_path / "out.json").read_text())
    assert any(f["rule"] == "SEND_TEST_NO_ACTIVE_DRIVE"
               for f in out["findings"])


def test_short_drive_warn(tmp_path):
    """Drives tx_oe but no bit-cell counter / no back-edge → WARN."""
    rtl_main = """\
module main_fsm(input clk, output reg tx_oe);
  typedef enum { S_IDLE, S_DISPATCH, S_TX_ONE_SHOT } st_t;
  st_t state;
  reg [7:0] cur_op;
  always @(posedge clk) begin
    case (state)
      S_DISPATCH: begin
        if (cur_op == 8'h74) begin
          state <= S_TX_ONE_SHOT;
        end
      end
      S_TX_ONE_SHOT: begin
        tx_oe <= 1'b1;
        state <= S_IDLE;
      end
    endcase
  end
endmodule
"""
    proj = _make(tmp_path, l3=L3_DEFAULT, rtl={"main_fsm.sv": rtl_main})
    r = _run([str(proj), "--json", str(tmp_path / "out.json")])
    # WARN-only must not fail
    assert r.returncode == 0, r.stdout
    out = json.loads((tmp_path / "out.json").read_text())
    assert any(w["rule"] == "SEND_TEST_SHORT_DRIVE"
               for w in out.get("warnings", []))


def test_with_waiver_pass(tmp_path):
    """No-OE FAIL silenced by ≥40-char waiver → PASS_WITH_WAIVER."""
    rtl_main = """\
module main_fsm(input clk, output reg tx_oe);
  typedef enum { S_IDLE, S_DISPATCH, S_TX_DUMMY } st_t;
  st_t state;
  reg [7:0] cur_op;
  always @(posedge clk) begin
    case (state)
      S_DISPATCH: if (cur_op == 8'h74) state <= S_TX_DUMMY;
      S_TX_DUMMY: state <= S_IDLE;
    endcase
  end
endmodule
"""
    proj = _make(tmp_path, l3=L3_DEFAULT, rtl={"main_fsm.sv": rtl_main},
                 waiver="SEND_TEST silence is intentional in this "
                        "diagnostic stub build, see ticket WAV-27-1.")
    r = _run([str(proj)])
    assert r.returncode == 0
    assert "PASS_WITH_WAIVER" in r.stdout


def test_no_fsm_skip(tmp_path):
    """No FSM file → SKIP/PASS."""
    proj = _make(tmp_path, l3=L3_DEFAULT)
    r = _run([str(proj)])
    assert r.returncode == 0
    assert "PASS" in r.stdout
