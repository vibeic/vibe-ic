#!/usr/bin/env python3
"""Tests for bram_read_latency_consume_alignment_check.py
(Wave 26 / v0.119.58)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "bram_read_latency_consume_alignment_check.py")


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
            {"bram_latency_intentional_offset": waiver}))
    return proj


def _make_otp_unregistered() -> str:
    return """
    module otp_mem(input clk, input [6:0] addr, output [7:0] rdata);
      altsyncram #(
        .operation_mode("ROM"),
        .init_file("apple.mif"),
        .outdata_reg_a("UNREGISTERED"),
        .width_a(8), .widthad_a(7), .numwords_a(128)
      ) u_otp (
        .clock0(clk), .address_a(addr), .q_a(rdata)
      );
    endmodule
    """


def _make_otp_clock0() -> str:
    return """
    module otp_mem(input clk, input [6:0] addr, output [7:0] rdata);
      altsyncram #(
        .operation_mode("ROM"),
        .init_file("apple.mif"),
        .outdata_reg_a("CLOCK0"),
        .width_a(8), .widthad_a(7), .numwords_a(128)
      ) u_otp (
        .clock0(clk), .address_a(addr), .q_a(rdata)
      );
    endmodule
    """


# ----------------------------------------------------------------------

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0


def test_2_cycle_wait_unregistered_pass(tmp_path):
    """UNREGISTERED → required=2, FSM waits 2 cycles → PASS."""
    fsm = """
    module main_fsm(input clk, output reg [6:0] otp_addr,
                    input [7:0] otp_rdata);
      reg [3:0] state_q;
      localparam S_OTP_REQUEST = 4'd1;
      localparam S_OTP_WAIT1   = 4'd2;
      localparam S_OTP_WAIT2   = 4'd3;
      localparam S_OTP_CONSUME = 4'd4;
      reg [7:0] byte_buf;
      always @(posedge clk) begin
        case (state_q)
          S_OTP_REQUEST: begin
            otp_addr <= 7'd0;
            state_q <= S_OTP_WAIT1;
          end
          S_OTP_WAIT1: state_q <= S_OTP_WAIT2;
          S_OTP_WAIT2: state_q <= S_OTP_CONSUME;
          S_OTP_CONSUME: begin
            byte_buf <= otp_rdata;
            state_q <= S_OTP_REQUEST;
          end
        endcase
      end
    endmodule
    """
    proj = _make_project(tmp_path, {
        "otp_mem.sv": _make_otp_unregistered(),
        "main_fsm.sv": fsm,
    })
    r = _run([str(proj), "--json"])
    assert r.returncode == 0, r.stdout
    out = json.loads(r.stdout)
    assert out["verdict"] == "PASS"


def test_1_cycle_wait_unregistered_fail(tmp_path):
    """v0.119.57 bug: UNREGISTERED + 1-cycle wait → FAIL."""
    fsm = """
    module main_fsm(input clk, output reg [6:0] otp_addr,
                    input [7:0] otp_rdata);
      reg [3:0] state_q;
      localparam S_FETCH_OTP      = 4'd1;
      localparam S_FETCH_OTP_WAIT = 4'd2;
      reg [7:0] byte_buf;
      always @(posedge clk) begin
        case (state_q)
          S_FETCH_OTP: begin
            otp_addr <= 7'd0;
            state_q <= S_FETCH_OTP_WAIT;
          end
          S_FETCH_OTP_WAIT: begin
            byte_buf <= otp_rdata;
            state_q <= S_FETCH_OTP;
          end
        endcase
      end
    endmodule
    """
    proj = _make_project(tmp_path, {
        "otp_mem.sv": _make_otp_unregistered(),
        "main_fsm.sv": fsm,
    })
    r = _run([str(proj), "--json"])
    assert r.returncode == 1, r.stdout
    out = json.loads(r.stdout)
    assert out["verdict"] == "FAIL"


def test_3_cycle_wait_clock0_pass(tmp_path):
    """CLOCK0 → required=3, FSM waits 3 cycles → PASS."""
    fsm = """
    module main_fsm(input clk, output reg [6:0] otp_addr,
                    input [7:0] otp_rdata);
      reg [3:0] state_q;
      localparam S_REQUEST = 4'd1;
      localparam S_WAIT1   = 4'd2;
      localparam S_WAIT2   = 4'd3;
      localparam S_WAIT_FINAL = 4'd4;
      localparam S_CONSUME = 4'd5;
      reg [7:0] byte_buf;
      always @(posedge clk) begin
        case (state_q)
          S_REQUEST: begin
            otp_addr <= 7'd0;
            state_q <= S_WAIT1;
          end
          S_WAIT1: state_q <= S_WAIT2;
          S_WAIT2: state_q <= S_WAIT_FINAL;
          S_WAIT_FINAL: state_q <= S_CONSUME;
          S_CONSUME: begin
            byte_buf <= otp_rdata;
            state_q <= S_REQUEST;
          end
        endcase
      end
    endmodule
    """
    proj = _make_project(tmp_path, {
        "otp_mem.sv": _make_otp_clock0(),
        "main_fsm.sv": fsm,
    })
    r = _run([str(proj), "--json"])
    assert r.returncode == 0, r.stdout
    out = json.loads(r.stdout)
    assert out["verdict"] == "PASS"


def test_no_bram_skip(tmp_path):
    """No altsyncram → SKIP."""
    proj = _make_project(tmp_path, {"glue.sv":
        "module g(input a, output y); assign y = a; endmodule\n"})
    r = _run([str(proj), "--json"])
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["verdict"] == "SKIP"


def test_with_waiver_pass(tmp_path):
    """Waiver ≥40 chars → PASS_WITH_WAIVER even with off-by-one."""
    fsm = """
    module main_fsm(input clk, output reg [6:0] otp_addr,
                    input [7:0] otp_rdata);
      reg [3:0] state_q;
      localparam S_FETCH_OTP      = 4'd1;
      localparam S_FETCH_OTP_WAIT = 4'd2;
      reg [7:0] byte_buf;
      always @(posedge clk) begin
        case (state_q)
          S_FETCH_OTP: begin
            otp_addr <= 7'd0;
            state_q <= S_FETCH_OTP_WAIT;
          end
          S_FETCH_OTP_WAIT: begin
            byte_buf <= otp_rdata;
            state_q <= S_FETCH_OTP;
          end
        endcase
      end
    endmodule
    """
    proj = _make_project(
        tmp_path,
        {"otp_mem.sv": _make_otp_unregistered(),
         "main_fsm.sv": fsm},
        waiver=("Off-by-one is desired here because the OTP layout "
                "stores rotating-redundant bytes and we read addr-1 "
                "deliberately for parity-error recovery."))
    r = _run([str(proj), "--json"])
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["verdict"] == "PASS_WITH_WAIVER"
