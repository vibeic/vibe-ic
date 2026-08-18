"""Tests for dispatch_register_default_reset_check.py."""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "dispatch_register_default_reset_check.py"


def _run(rtl_text: str, tmp_path: Path, *, extra_args: list[str] | None = None) -> subprocess.CompletedProcess:
    f = tmp_path / "dut.v"
    f.write_text(textwrap.dedent(rtl_text))
    cmd = [sys.executable, str(PROG), str(tmp_path), "--json"]
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(cmd, capture_output=True, text=True)


def test_pass_properly_reset_registers(tmp_path):
    """Registers reset in sync reset block → PASS."""
    rtl = """\
    module dispatcher(input clk, input rst_n, output reg [7:0] rsp_data, output reg rsp_valid);
        always @(posedge clk) begin
            if (!rst_n) begin
                rsp_data <= 8'd0;
                rsp_valid <= 1'b0;
            end else begin
                case (state)
                    S_IDLE: rsp_valid <= 1'b0;
                    S_SEND: begin
                        rsp_data <= payload;
                        rsp_valid <= 1'b1;
                    end
                endcase
            end
        end
    endmodule
    """
    r = _run(rtl, tmp_path)
    assert r.returncode == 0, r.stdout


def test_pass_default_assignment_before_case(tmp_path):
    """Registers with default assignment before case → PASS."""
    rtl = """\
    module dispatcher(input clk, input rst_n, output reg [7:0] tx_byte);
        always @(posedge clk) begin
            tx_byte <= 8'd0;
            case (state)
                S_SEND: tx_byte <= payload;
            endcase
        end
    endmodule
    """
    r = _run(rtl, tmp_path)
    assert r.returncode == 0, r.stdout


def test_fail_leaked_register(tmp_path):
    """Register assigned in states but no reset → FAIL."""
    rtl = """\
    module dispatcher(input clk, input rst_n, output reg [7:0] rsp_data, output reg [3:0] rsp_idx);
        always @(posedge clk) begin
            case (state)
                S_IDLE: ;
                S_BUILD: begin
                    rsp_data <= otp_out;
                    rsp_idx <= rsp_idx + 1;
                end
                S_SEND: ;
            endcase
        end
    endmodule
    """
    r = _run(rtl, tmp_path)
    assert r.returncode == 1, r.stdout
    import json
    data = json.loads(r.stdout)
    assert data["verdict"] == "FAIL"
    regs = {f["register"] for f in data["findings"]}
    assert "rsp_data" in regs
    assert "rsp_idx" in regs


def test_no_files_exit2(tmp_path):
    """Empty directory → exit 2."""
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path)],
        capture_output=True, text=True,
    )
    assert r.returncode == 2


def test_nonexistent_path_exit2(tmp_path):
    """Nonexistent path → exit 2."""
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nonexistent")],
        capture_output=True, text=True,
    )
    assert r.returncode == 2


def test_silence_marker(tmp_path):
    """Register with // dispatch-reset-ok → silenced, PASS."""
    rtl = """\
    module dispatcher(input clk, input rst_n);
        reg [7:0] rsp_data; // dispatch-reset-ok
        always @(posedge clk) begin
            case (state)
                S_SEND: rsp_data <= payload;
            endcase
        end
    endmodule
    """
    r = _run(rtl, tmp_path)
    assert r.returncode == 0, r.stdout


def test_mixed_reset_and_leaked(tmp_path):
    """One register reset, another not → FAIL only for the leaked one."""
    rtl = """\
    module dispatcher(input clk, input rst_n,
        output reg [7:0] rsp_data, output reg [7:0] frame_crc);
        always @(posedge clk) begin
            if (!rst_n) begin
                rsp_data <= 8'd0;
            end else begin
                case (state)
                    S_BUILD: begin
                        rsp_data <= payload;
                        frame_crc <= computed_crc;
                    end
                endcase
            end
        end
    endmodule
    """
    r = _run(rtl, tmp_path)
    assert r.returncode == 1, r.stdout
    import json
    data = json.loads(r.stdout)
    regs = {f["register"] for f in data["findings"]}
    assert "frame_crc" in regs
    assert "rsp_data" not in regs


def test_help_flag():
    """--help exits 0."""
    r = subprocess.run(
        [sys.executable, str(PROG), "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0


def test_no_response_regs_pass(tmp_path):
    """Module with no rsp/tx/resp/frame registers → PASS."""
    rtl = """\
    module counter(input clk, input rst_n, output reg [7:0] count);
        always @(posedge clk) begin
            if (!rst_n)
                count <= 8'd0;
            else
                count <= count + 1;
        end
    endmodule
    """
    r = _run(rtl, tmp_path)
    assert r.returncode == 0, r.stdout
