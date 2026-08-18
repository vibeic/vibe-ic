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
