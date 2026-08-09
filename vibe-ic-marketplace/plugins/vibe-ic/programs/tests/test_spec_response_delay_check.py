"""Tests for spec_response_delay_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

PROGRAM = Path(__file__).parent.parent / "spec_response_delay_check.py"


def _run(tmp_path, rtl_src, spec_doc, rtl_name="dut.v"):
    r_path = tmp_path / rtl_name
    r_path.write_text(textwrap.dedent(rtl_src))
    s_path = tmp_path / "spec.json"
    s_path.write_text(json.dumps(spec_doc))
    r = subprocess.run(
        [sys.executable, str(PROGRAM), str(r_path), "--spec", str(s_path), "--json"],
        capture_output=True, text=True,
    )
    return r.returncode, json.loads(r.stdout) if r.stdout else {}


TSRS_SPEC = {
    "timing_parameters": {
        "tSRS_us": {"min": 20, "max": 100, "nom": 30},
    }
}


def test_no_wait_state_flagged(tmp_path):
    """RTL goes S_BUILD → S_TX directly — flagged against tSRS spec."""
    src = """
    module dut(input clk, input rstn);
        reg [3:0] st;
        reg tx_start;
        always @(posedge clk or negedge rstn) begin
            if (!rstn) begin st <= 4'd0; tx_start <= 1'b0; end
            else begin
                case (st)
                    4'd0: begin  // S_IDLE
                    end
                    4'd4: begin  // S_BUILD
                        tx_start <= 1'b1;
                        st <= S_TX;
                    end
                    4'd5: begin  // S_TX
                        tx_start <= 1'b0;
                    end
                endcase
            end
        end
    endmodule
    """
    rc, out = _run(tmp_path, src, TSRS_SPEC)
    assert rc == 1, out
    assert out["verdict"] == "FAIL"


def test_with_s_tsrs_passes(tmp_path):
    """RTL has S_TSRS wait state before S_TX — passes."""
    src = """
    module dut(input clk, input rstn);
        reg [3:0] st;
        reg [10:0] tsrs_cnt;
        always @(posedge clk or negedge rstn) begin
            if (!rstn) begin st <= 4'd0; end
            else begin
                case (st)
                    4'd4: begin
                        st <= S_TSRS;
                        tsrs_cnt <= 0;
                    end
                    4'd9: begin // S_TSRS
                        if (tsrs_cnt == 11'd1499) st <= S_TX;
                        else tsrs_cnt <= tsrs_cnt + 1;
                    end
                    4'd5: begin  // S_TX
                    end
                endcase
            end
        end
    endmodule
    """
    rc, out = _run(tmp_path, src, TSRS_SPEC)
    assert rc == 0, out
    assert out["verdict"] == "PASS"


def test_no_spec_delay_no_op(tmp_path):
    """Spec without any response-delay field — gate is a no-op."""
    spec = {"timing_parameters": {"tClk_us": {"min": 0.02}}}
    src = """
    module dut(input clk);
        always @(posedge clk) begin
        end
    endmodule
    """
    rc, out = _run(tmp_path, src, spec)
    # No delay in spec → gate doesn't flag anything (PASS)
    assert rc == 0


def test_s_wait_state_also_recognised(tmp_path):
    """Any S_WAIT / S_DELAY / S_TURN name works as wait state."""
    src = """
    module dut(input clk, input rstn);
        always @(posedge clk or negedge rstn) begin
            case (st)
                S_BUILD: st <= S_WAIT_TSRS;
                S_WAIT_TSRS: if (done) st <= S_TX;
            endcase
        end
    endmodule
    """
    rc, out = _run(tmp_path, src, TSRS_SPEC)
    assert rc == 0


def test_resp_delay_alt_spec_shape(tmp_path):
    """Alt shape: {"name":"tIRT","min_us":5}."""
    spec = {"items": [{"name": "tIRT", "min_us": 5}]}
    src = """
    module dut(input clk);
        always @(posedge clk) begin
            st <= S_TX;
        end
    endmodule
    """
    rc, out = _run(tmp_path, src, spec)
    assert rc == 1  # has tIRT in spec, RTL has S_TX without wait


# ── Reachability of the FAIL verdict on the RTL the flow really produces ──
#
# The gate ships wired as
#     spec_response_delay_check phase2/stage1/rtl --spec .../L8_*.json
# and every FSM this flow writes into `phase2/stage1/rtl` names its state
# register `state` (one-process) or `next_state` (two-process).  The
# launch predicate used to be `st\s*<=\s*(S_TX\w*|...)`, which matches
# neither, so on the caller's real target no launch was ever seen, the
# only ERROR-emitting branch was dead, and this gate could print nothing
# but `verdict: PASS`.  The four tests below pin BOTH directions of that
# repair: an unguarded launch must reach FAIL, and a guarded one must
# still reach PASS with the gate armed (declared_delay non-null).

#: A one-process FSM that fires the response the cycle after it finishes
#: building it — the fail mode this gate exists for. No delay/wait/
#: turnaround token anywhere in the module, so nothing can excuse it.
_UNGUARDED_LAUNCH_RTL = """
module cmd_fsm(input clk, input rstn, input req_end, input tx_done,
               output reg tx_start);
    localparam S_IDLE = 3'd0, S_DECODE = 3'd1, S_BUILD = 3'd2,
               S_BUILD_CRC = 3'd3, S_TX = 3'd4, S_TX_DONE = 3'd5;
    reg [2:0] state;
    always @(posedge clk or negedge rstn) begin
        if (!rstn) begin state <= S_IDLE; tx_start <= 1'b0; end
        else case (state)
            S_IDLE:      if (req_end) state <= S_DECODE;
            S_DECODE:    state <= S_BUILD;
            S_BUILD:     state <= S_BUILD_CRC;
            S_BUILD_CRC: begin
                             tx_start <= 1'b1;
                             state <= S_TX;
                         end
            S_TX:        if (tx_done) state <= S_TX_DONE;
            S_TX_DONE:   state <= S_IDLE;
        endcase
    end
endmodule
"""

#: The same FSM with the hold-off put back: one extra state, counted out
#: against the spec minimum, between build and launch.
_GUARDED_LAUNCH_RTL = """
module cmd_fsm(input clk, input rstn, input req_end, input tx_done,
               output reg tx_start);
    localparam S_IDLE = 3'd0, S_DECODE = 3'd1, S_BUILD = 3'd2,
               S_BUILD_CRC = 3'd3, S_HOLDOFF = 3'd6,
               S_TX = 3'd4, S_TX_DONE = 3'd5;
    localparam [15:0] HOLDOFF_TICKS = 16'd1500;
    reg [2:0] state;
    reg [15:0] holdoff_cnt;
    always @(posedge clk or negedge rstn) begin
        if (!rstn) begin state <= S_IDLE; tx_start <= 1'b0; holdoff_cnt <= 0; end
        else case (state)
            S_IDLE:      if (req_end) state <= S_DECODE;
            S_DECODE:    state <= S_BUILD;
            S_BUILD:     state <= S_BUILD_CRC;
            S_BUILD_CRC: begin holdoff_cnt <= 0; state <= S_HOLDOFF; end
            S_HOLDOFF:   begin
                             holdoff_cnt <= holdoff_cnt + 1'b1;
                             if (holdoff_cnt >= HOLDOFF_TICKS) begin
                                 tx_start <= 1'b1;
                                 state <= S_TX;
                             end
                         end
            S_TX:        if (tx_done) state <= S_TX_DONE;
            S_TX_DONE:   state <= S_IDLE;
        endcase
    end
endmodule
"""


def test_conventional_state_register_unguarded_launch_reaches_fail(tmp_path):
    """FAIL is reachable on an FSM whose state register is called `state`.

    Fails against the unfixed program, which returns rc 0 / PASS here:
    its launch predicate required the register to be spelled `st`.
    """
    rc, out = _run(tmp_path, _UNGUARDED_LAUNCH_RTL, TSRS_SPEC)
    assert rc == 1, out
    assert out["verdict"] == "FAIL", out
    assert out["response_launch_seen"] is True, out
    assert [f["rule"] for f in out["findings"]] == [
        "response_delay_not_implemented"], out
    assert any("UNGUARDED" in n and "S_BUILD_CRC" in n
               for n in out["response_launches"]), out


def test_conventional_state_register_guarded_launch_still_reaches_pass(tmp_path):
    """The other direction: the gate is not always-fail.

    Same state-register spelling, same armed spec (declared_delay is
    non-null, so this PASS is earned rather than a no-op), but the
    hold-off state is present.
    """
    rc, out = _run(tmp_path, _GUARDED_LAUNCH_RTL, TSRS_SPEC)
    assert rc == 0, out
    assert out["verdict"] == "PASS", out
    assert out["declared_delay"] is not None, out
    assert out["errors"] == 0, out
    assert out["response_launch_seen"] is True, out
    assert not any(n.startswith(str(tmp_path)) and "UNGUARDED" in n
                   for n in out["response_launches"]), out


def test_two_process_fsm_blocking_next_state_reaches_fail(tmp_path):
    """A combinational next-state block launches with `=`, not `<=`."""
    src = """
    module cmd_fsm(input clk, input req_done, input tx_done);
        localparam S_IDLE = 2'd0, S_BUILD = 2'd1, S_RESP = 2'd2;
        reg [1:0] state, next_state;
        always @(*) begin
            next_state = state;
            case (state)
                S_IDLE:  if (req_done) next_state = S_BUILD;
                S_BUILD: next_state = S_RESP;
                S_RESP:  if (tx_done) next_state = S_IDLE;
            endcase
        end
        always @(posedge clk) state <= next_state;
    endmodule
    """
    rc, out = _run(tmp_path, src, TSRS_SPEC)
    assert rc == 1, out
    assert out["verdict"] == "FAIL", out
    assert any("S_BUILD -> S_RESP" in n for n in out["response_launches"]), out


def test_tx_pipeline_hops_are_not_response_launches(tmp_path):
    """S_TX_LOAD -> S_TX_ARM -> S_TX_BUSY are pipeline steps, not launches.

    Without this, widening the launch predicate would redden every
    multi-state TX pipeline in the flow's own RTL.
    """
    src = """
    module tx_seq(input clk, input go, input tx_done);
        localparam S_IDLE = 3'd0, S_HOLDOFF = 3'd1, S_TX_LOAD = 3'd2,
                   S_TX_ARM = 3'd3, S_TX_BUSY = 3'd4;
        reg [2:0] state;
        reg [7:0] holdoff_cnt;
        always @(posedge clk) begin
            case (state)
                S_IDLE:    if (go) state <= S_HOLDOFF;
                S_HOLDOFF: if (holdoff_cnt >= 8'd60) state <= S_TX_LOAD;
                S_TX_LOAD: state <= S_TX_ARM;
                S_TX_ARM:  state <= S_TX_BUSY;
                S_TX_BUSY: if (tx_done) state <= S_IDLE;
            endcase
        end
    endmodule
    """
    rc, out = _run(tmp_path, src, TSRS_SPEC)
    assert rc == 0, out
    assert out["verdict"] == "PASS", out
    launches = [n.split(": ", 1)[1] for n in out["response_launches"]]
    assert launches == [
        "guarded launch S_HOLDOFF -> S_TX_LOAD "
        "(launched from delay state S_HOLDOFF)"], out


def test_missing_file_error(tmp_path):
    s_path = tmp_path / "spec.json"
    s_path.write_text(json.dumps(TSRS_SPEC))
    r = subprocess.run(
        [sys.executable, str(PROGRAM),
         str(tmp_path / "nope.v"), "--spec", str(s_path)],
        capture_output=True)
    assert r.returncode == 2


def test_no_spec_arg_error(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROGRAM), str(tmp_path)],
        capture_output=True)
    assert r.returncode == 2
