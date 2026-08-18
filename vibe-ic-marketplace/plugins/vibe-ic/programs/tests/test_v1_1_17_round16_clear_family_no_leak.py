"""Step-2.7 §4.05 guards for PR #12 (ORGANIC #811 round-16 clear-control family).

PR #12 broadened the latency clear-equivalent detector with (a) directional-
prefix strip and (b) localparam-resolved branch values. Step-2.7 reproduced 3
HIGH §4.05 leaks — all re-opening the v1.1.15 (#10) class of "a load-bearing
control held inactive masks a real canonical-value bug":

  F1 `i_finish_mode` — a MODE select (name passes clear-gate via `finish`) jams
     state<=IDLE and was held inactive → false PASS.
  F2 `drain_sel` — a path SELECT (name passes via `drain`) jams st<=IDLE → leak.
  F3 cross-module collision — a sibling `module submod; localparam RUN=0;`
     poisoned the DUT's `RUN=2'b01` so a jam-to-RUN (non-reset) branch resolved
     to the reset value and was mis-classified as a clear.

FIXES: (1) the clear-NAME gate denies a load-bearing-control SEGMENT
(mode/sel/select/load/...) even when a clear token is present; (2) `_const_value_map`
is resolved from the DUT MODULE BODY (a sibling localparam can't poison it);
(3) a RESET-CONSISTENCY guard binds BOTH detection paths — a branch that drives
any reset-tracked register to a NON-reset constant is never a clear.

chip-AGNOSTIC; end-to-end cases need iverilog/vvp (skipped otherwise).
"""
import shutil
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import latency_conformance_check as L  # noqa: E402

_NEED_SIM = pytest.mark.skipif(
    shutil.which("iverilog") is None or shutil.which("vvp") is None,
    reason="iverilog/vvp unavailable")


# ── name-gate: load-bearing control with a clear substring is NOT a clear ─────
@pytest.mark.parametrize("name", [
    "i_finish_mode", "finish_mode", "drain_sel", "flush_select", "clear_mode",
    "reset_sel", "done_mux", "abort_load", "purge_channel", "clr_idx"])
def test_loadbearing_names_with_clear_substring_denied(name):
    assert L._looks_like_clear_equiv_name(name) is False


@pytest.mark.parametrize("name", [
    "i_clear", "o_clr", "i_flush", "frame_flush", "Present_Processing_Completed",
    "rx_done", "sync_reset", "buf_purge"])
def test_genuine_clear_names_still_accepted(name):
    assert L._looks_like_clear_equiv_name(name) is True


# ── const map is DUT-scoped (sibling localparam cannot poison) ────────────────
def test_const_value_map_is_dut_scoped():
    rtl = ("module submod; localparam RUN = 0; endmodule\n"
           "module dut(input clk); localparam [1:0] IDLE=2'b00, RUN=2'b01;\n"
           "  reg [1:0] s; always @(posedge clk) s<=IDLE; endmodule\n")
    body = L._module_body(rtl, "dut")
    cv = L._const_value_map(body)
    assert cv.get("RUN") == 1          # DUT's RUN, not the sibling's 0
    assert cv.get("IDLE") == 0


# ── end-to-end: all 3 reviewer attacks hard-block ─────────────────────────────
def _run(tmp_path, rtl, *, top, event, output, expect, reset, active_low=False):
    p = tmp_path / "d.v"
    p.write_text(rtl)
    return L.run_latency_conformance(
        rtl_path=p, top=top, event=event, output=output, expect=str(expect),
        params_override={}, reset_override=reset,
        reset_active_low_flag=(True if active_low else None),
        input_const=-1, max_cycles_override=None, mode="latency",
        allow_no_handshake=False, context_files=None)


_F1 = ("module b_mode(input clk, input rst_n, input i_finish_mode, input go,\n"
       "  output reg valid);\n  localparam [1:0] IDLE=2'b00,S1=2'b01,S2=2'b10;\n"
       "  reg [1:0] state;\n  always @(posedge clk or negedge rst_n) begin\n"
       "    if(!rst_n) begin state<=IDLE; valid<=1'b0; end\n"
       "    else if(i_finish_mode) begin state<=IDLE; valid<=1'b0; end\n"
       "    else case(state) IDLE: if(go) state<=S1; S1: state<=S2;\n"
       "      S2: begin valid<=1'b1; state<=IDLE; end endcase\n  end\nendmodule\n")

_F2 = ("module c_drainsel(input clk, input rst, input drain_sel, input kick,\n"
       "  output reg valid);\n  localparam [1:0] IDLE=2'b00,A=2'b01,B=2'b10;\n"
       "  reg [1:0] st;\n  always @(posedge clk) begin\n"
       "    if(rst) begin st<=IDLE; valid<=1'b0; end\n"
       "    else if(drain_sel) begin st<=IDLE; valid<=1'b0; end\n"
       "    else case(st) IDLE: if(kick) st<=A;\n"
       "      A: begin valid<=1'b1; st<=IDLE; end endcase\n  end\nendmodule\n")

_F3 = ("module submod; localparam RUN = 0; endmodule\n"
       "module dut(input i_clk, input i_rst_n, input i_start, input i_done,\n"
       "  input [7:0] i_data, output reg o_ready);\n"
       "  localparam [1:0] IDLE=2'b00, RUN=2'b01, DONE=2'b10;\n"
       "  reg [1:0] state; reg [2:0] cnt;\n"
       "  always @(posedge i_clk or negedge i_rst_n) begin\n"
       "    if(!i_rst_n) begin state<=IDLE; cnt<=3'b0; o_ready<=1'b0; end\n"
       "    else if(i_done) begin state<=RUN; cnt<=3'b0; o_ready<=1'b0; end\n"
       "    else case(state)\n"
       "      IDLE: if(i_start) begin state<=RUN; cnt<=3'b0; o_ready<=1'b0; end\n"
       "      RUN: begin cnt<=cnt+3'b1; if(cnt==3'd2) begin state<=DONE; o_ready<=1'b1; end end\n"
       "      DONE: begin o_ready<=1'b0; state<=IDLE; end\n"
       "    endcase\n  end\nendmodule\n")


@_NEED_SIM
def test_f1_finish_mode_still_times_out(tmp_path):
    rc, rep = _run(tmp_path, _F1, top="b_mode", event="go", output="valid",
                   expect=3, reset="rst_n")
    assert rc == 1 and rep["verdict"] == "TIMEOUT", rep.get("verdict")


@_NEED_SIM
def test_f2_drain_sel_still_times_out(tmp_path):
    rc, rep = _run(tmp_path, _F2, top="c_drainsel", event="kick", output="valid",
                   expect=2, reset="rst")
    assert rc == 1 and rep["verdict"] == "TIMEOUT", rep.get("verdict")


@_NEED_SIM
def test_f3_cross_module_collision_jam_to_nonreset_still_times_out(tmp_path):
    rc, rep = _run(tmp_path, _F3, top="dut", event="i_start", output="o_ready",
                   expect=4, reset="i_rst_n", active_low=True)
    assert rc == 1 and rep["verdict"] == "TIMEOUT", rep.get("verdict")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
