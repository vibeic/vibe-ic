#!/usr/bin/env python3
"""Tests for connect_vs_send_test_parity_check.py — Wave 27 Gate 2."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "connect_vs_send_test_parity_check.py")


def _run(args, **kw):
    return subprocess.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True, **kw)


L3 = {
    "doc": "L3",
    "commands": [
        {"opcode": "0x40", "name": "Connect", "cmd_len": 2,
         "rsp_op": "0x41", "rsp_len": 2},
        {"opcode": "0x72", "name": "Get State", "cmd_len": 2,
         "rsp_op": "0x73", "rsp_len": 4},
    ],
}


def _make(tmp_path: Path, l3: dict | None = L3,
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
            {"send_test_dispatch_intentionally_minimal": waiver}))
    return proj


def test_help():
    r = _run(["--help"])
    assert r.returncode == 0


def test_balanced_dispatch_pass(tmp_path):
    """CONNECT and SEND_TEST both have ~equal-volume dispatch chains."""
    rtl = {"main_fsm.sv": """\
module main_fsm(input clk, output reg tx_oe);
  typedef enum {S_IDLE,S_DISPATCH,S_CONN_A,S_CONN_B,S_CONN_C,
                S_TEST_A,S_TEST_B,S_TEST_C} st_t;
  st_t state;
  reg [7:0] cur_op;
  always @(posedge clk) begin
    case (state)
      S_DISPATCH: begin
        if (cur_op == 8'h40) state <= S_CONN_A;
        else if (cur_op == 8'h72) state <= S_TEST_A;
      end
      S_CONN_A: begin
        tx_oe <= 1'b1;
        // a few more lines of work
        // padding line 1
        // padding line 2
        state <= S_CONN_B;
      end
      S_CONN_B: begin
        tx_oe <= 1'b1;
        // padding 1
        // padding 2
        state <= S_CONN_C;
      end
      S_CONN_C: begin
        tx_oe <= 1'b0;
        state <= S_IDLE;
      end
      S_TEST_A: begin
        tx_oe <= 1'b1;
        // padding 1
        // padding 2
        state <= S_TEST_B;
      end
      S_TEST_B: begin
        tx_oe <= 1'b1;
        // padding 1
        // padding 2
        state <= S_TEST_C;
      end
      S_TEST_C: begin
        tx_oe <= 1'b0;
        state <= S_IDLE;
      end
    endcase
  end
endmodule
"""}
    proj = _make(tmp_path, rtl=rtl)
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_send_test_stub_fail(tmp_path):
    """CONNECT has heavy chain, SEND_TEST is 1-line stub → FAIL."""
    body_lines = "\n".join([f"        // line_{i}" for i in range(60)])
    rtl = {"main_fsm.sv": f"""\
module main_fsm(input clk, output reg tx_oe);
  typedef enum {{S_IDLE,S_DISPATCH,S_CONN_A,S_CONN_B,S_CONN_C}} st_t;
  st_t state;
  reg [7:0] cur_op;
  always @(posedge clk) begin
    case (state)
      S_DISPATCH: begin
        if (cur_op == 8'h40) state <= S_CONN_A;
        else if (cur_op == 8'h72) state <= S_IDLE;
      end
      S_CONN_A: begin
        tx_oe <= 1'b1;
{body_lines}
        state <= S_CONN_B;
      end
      S_CONN_B: begin
        tx_oe <= 1'b1;
        state <= S_CONN_C;
      end
      S_CONN_C: begin
        tx_oe <= 1'b0;
        state <= S_IDLE;
      end
    endcase
  end
endmodule
"""}
    proj = _make(tmp_path, rtl=rtl)
    r = _run([str(proj), "--json", str(tmp_path / "out.json")])
    assert r.returncode == 1, r.stdout
    out = json.loads((tmp_path / "out.json").read_text())
    assert any(f["rule"] == "SEND_TEST_DISPATCH_STUB"
               for f in out["findings"])


def test_with_waiver_pass(tmp_path):
    body_lines = "\n".join([f"        // line_{i}" for i in range(60)])
    rtl = {"main_fsm.sv": f"""\
module main_fsm(input clk, output reg tx_oe);
  typedef enum {{S_IDLE,S_DISPATCH,S_CONN_A,S_CONN_B}} st_t;
  st_t state;
  reg [7:0] cur_op;
  always @(posedge clk) begin
    case (state)
      S_DISPATCH: begin
        if (cur_op == 8'h40) state <= S_CONN_A;
        else if (cur_op == 8'h72) state <= S_IDLE;
      end
      S_CONN_A: begin
        tx_oe <= 1'b1;
{body_lines}
        state <= S_CONN_B;
      end
      S_CONN_B: begin
        tx_oe <= 1'b0;
        state <= S_IDLE;
      end
    endcase
  end
endmodule
"""}
    proj = _make(tmp_path, rtl=rtl,
                 waiver="SEND_TEST handler intentionally minimal in "
                        "Phase-2 partial bring-up build, see ticket "
                        "WAV-27-2.")
    r = _run([str(proj)])
    assert r.returncode == 0
    assert "PASS_WITH_WAIVER" in r.stdout
