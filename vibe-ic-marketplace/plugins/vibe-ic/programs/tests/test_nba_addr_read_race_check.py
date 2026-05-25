"""Tests for nba_addr_read_race_check.py — generic addr/data pipeline lint."""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

PROGRAM = Path(__file__).parent.parent / "nba_addr_read_race_check.py"


def _run(tmp_path, rtl_src, name="dut.v"):
    p = tmp_path / name
    p.write_text(textwrap.dedent(rtl_src))
    r = subprocess.run(
        [sys.executable, str(PROGRAM), str(p), "--json"],
        capture_output=True, text=True,
    )
    return r.returncode, json.loads(r.stdout) if r.stdout else {}


def test_racy_form_flagged(tmp_path):
    """v068 fresh-agent shape: addr/data in same always block, no pre-advance."""
    src = """
    module dut(input clk, input rstn, output reg [6:0] otp_addr_o,
               input otp_valid_i, input [7:0] otp_data_i);
        reg [4:0] otp_step;
        reg [7:0] rsp [0:31];
        always @(posedge clk or negedge rstn) begin
            if (!rstn) begin
                otp_addr_o <= 7'd0;
                otp_step   <= 5'd0;
            end else begin
                otp_addr_o <= {2'b00, otp_step};
                if (otp_valid_i) begin
                    rsp[otp_step+1] <= otp_data_i;
                    otp_step <= otp_step + 5'd1;
                end
            end
        end
    endmodule
    """
    rc, out = _run(tmp_path, src)
    assert rc == 1
    assert out["verdict"] == "FAIL"
    rules = [f["rule"] for f in out["findings"]]
    assert "addr_data_no_pipeline" in rules


def test_pre_advance_form_passes(tmp_path):
    """v068 post-fix shape: explicit `+ 5'd1` pre-advance in store branch."""
    src = """
    module dut(input clk, input rstn, output reg [6:0] otp_addr_o,
               input otp_valid_i, input [7:0] otp_data_i);
        reg [4:0] otp_step;
        reg [7:0] rsp [0:31];
        always @(posedge clk or negedge rstn) begin
            if (!rstn) begin
                otp_addr_o <= 7'd0;
                otp_step   <= 5'd0;
            end else begin
                otp_addr_o <= {2'b00, otp_step};
                if (otp_valid_i) begin
                    rsp[otp_step+1] <= otp_data_i;
                    otp_step   <= otp_step + 5'd1;
                    otp_addr_o <= {2'b00, otp_step + 5'd1};
                end
            end
        end
    endmodule
    """
    rc, out = _run(tmp_path, src)
    assert rc == 0
    assert out["verdict"] == "PASS"


def test_silence_comment_silences(tmp_path):
    """Developer can silence with `// nba-addr-race-ok` on the addr line."""
    src = """
    module dut(input clk, input rstn, output reg [6:0] otp_addr_o,
               input otp_valid_i, input [7:0] otp_data_i);
        reg [4:0] otp_step;
        reg [7:0] rsp [0:31];
        always @(posedge clk or negedge rstn) begin
            if (!rstn) begin
                otp_addr_o <= 7'd0; // nba-addr-race-ok
                otp_step   <= 5'd0;
            end else begin
                otp_addr_o <= {2'b00, otp_step}; // nba-addr-race-ok
                if (otp_valid_i) begin
                    rsp[otp_step+1] <= otp_data_i;
                    otp_step <= otp_step + 5'd1;
                end
            end
        end
    endmodule
    """
    rc, out = _run(tmp_path, src)
    # The first-encountered addr assignment in the block is on the rstn
    # branch (line with silence marker); gate breaks after silence hit.
    assert rc == 0
    assert out["verdict"] == "PASS"


def test_nested_begin_end_case_statement(tmp_path):
    """cmd_fsm style with case statement + nested begin/end — parser must
    track depth, not stop at first `end`."""
    src = """
    module dut(input clk, input rstn, output reg [6:0] otp_addr_o,
               input otp_valid_i, input [7:0] otp_data_i, input [7:0] opcode);
        reg [4:0] otp_step;
        reg [7:0] rsp [0:31];
        always @(posedge clk or negedge rstn) begin
            if (!rstn) begin
                otp_addr_o <= 7'd0;
                otp_step   <= 5'd0;
            end else begin
                case (opcode)
                    8'h74: begin
                        if (otp_step < 5'd6) begin
                            otp_addr_o <= {2'b00, otp_step};
                            if (otp_valid_i) begin
                                rsp[otp_step+1] <= otp_data_i;
                                otp_step <= otp_step + 5'd1;
                            end
                        end
                    end
                    default: begin end
                endcase
            end
        end
    endmodule
    """
    rc, out = _run(tmp_path, src)
    assert rc == 1, "nested case/if must not hide the race from the gate"
    rules = [f["rule"] for f in out["findings"]]
    assert "addr_data_no_pipeline" in rules


def test_unrelated_module_passes(tmp_path):
    """A module that uses _data_i but no _addr_o — not a race."""
    src = """
    module dut(input clk, input rstn, input bit_valid_i, input [7:0] byte_data_i);
        reg [7:0] latch;
        always @(posedge clk or negedge rstn) begin
            if (!rstn) latch <= 8'h00;
            else if (bit_valid_i) latch <= byte_data_i;
        end
    endmodule
    """
    rc, out = _run(tmp_path, src)
    assert rc == 0
    assert out["verdict"] == "PASS"


def test_base_offset_not_mistaken_for_pre_advance(tmp_path):
    """v068's `otp_addr_o <= 7'h06 + otp_step` is a region-offset base,
    NOT a pre-advance — gate must still flag the race."""
    src = """
    module dut(input clk, input rstn, output reg [6:0] otp_addr_o,
               input otp_valid_i, input [7:0] otp_data_i);
        reg [4:0] otp_step;
        reg [7:0] rsp [0:31];
        always @(posedge clk or negedge rstn) begin
            if (!rstn) begin
                otp_addr_o <= 7'd0;
                otp_step <= 5'd0;
            end else begin
                otp_addr_o <= 7'h06 + {2'b00, otp_step};
                if (otp_valid_i) begin
                    rsp[otp_step+1] <= otp_data_i;
                    otp_step <= otp_step + 5'd1;
                end
            end
        end
    endmodule
    """
    rc, out = _run(tmp_path, src)
    assert rc == 1, "base offset `7'h06 + reg` is NOT pre-advance"


def test_raddr_rdata_pattern_flagged(tmp_path):
    """v076 BENCH-A fresh-agent: memory-module convention `<X>_raddr`/`<X>_rdata`
    (read addr / read data) was NOT caught by original `_addr` literal regex.
    Patched gate matches `_raddr`/`_rdata` suffix variants."""
    src = """
    module resp_rom (
        input clk, input rst_n, input start,
        output reg [6:0] otp_raddr,
        input  wire [7:0] otp_rdata,
        output reg [7:0] tx_byte
    );
        reg [2:0] st;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin st <= 0; otp_raddr <= 0; tx_byte <= 0; end
            else case (st)
                3'd0: if (start) begin otp_raddr <= 7'h61; st <= 3'd1; end
                3'd1: begin tx_byte <= otp_rdata; st <= 3'd2; end
                default: st <= 3'd0;
            endcase
        end
    endmodule
    """
    rc, out = _run(tmp_path, src)
    assert rc == 1, "raddr/rdata pattern must trigger the race lint"
    rules = [f["rule"] for f in out["findings"]]
    assert "addr_data_no_pipeline" in rules
    # Message should reference the actual matched names, not generic _addr_o.
    msg = out["findings"][0]["message"]
    assert "otp_raddr" in msg and "otp_rdata" in msg


def test_write_only_data_signal_not_flagged(tmp_path):
    """FSM that writes to `<X>_waddr` AND `<X>_wdata` (driving the memory's
    write port) is NOT a read race — the FSM is the data SOURCE, not sink.
    Filter LHS-assigned data signals to avoid this false positive."""
    src = """
    module ctrl (
        input clk, input rst_n, input we_req,
        output reg [6:0] otp_waddr,
        output reg [7:0] otp_wdata,
        output reg       otp_we
    );
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin otp_waddr <= 0; otp_wdata <= 0; otp_we <= 0; end
            else if (we_req) begin
                otp_waddr <= 7'h60;
                otp_wdata <= 8'hAA;
                otp_we    <= 1'b1;
            end else otp_we <= 1'b0;
        end
    endmodule
    """
    rc, out = _run(tmp_path, src)
    assert rc == 0, "write-port driver is not a read race"
    assert out["verdict"] == "PASS"


def test_missing_file_error(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROGRAM), str(tmp_path / "nope.v")],
        capture_output=True)
    assert r.returncode == 2


def test_dir_with_no_verilog_files_error(tmp_path):
    (tmp_path / "readme.md").write_text("no verilog here")
    r = subprocess.run(
        [sys.executable, str(PROGRAM), str(tmp_path)],
        capture_output=True)
    assert r.returncode == 2
