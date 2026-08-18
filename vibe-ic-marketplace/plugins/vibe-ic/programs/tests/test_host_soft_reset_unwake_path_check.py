"""Tests for host_soft_reset_unwake_path_check.py."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from programs.host_soft_reset_unwake_path_check import main, audit

# ── fixtures ──────────────────────────────────────────────────────────

_PASS_RESET_CLEARS_AWAKE = textwrap.dedent("""\
    module dispatcher(
        input clk, rst_n,
        input [7:0] cmd_op
    );
        reg awake;
        localparam CMD_RST = 8'hFF;

        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                awake <= 0;
            end else if (cmd_op == CMD_RST) begin
                awake <= 0;
            end else begin
                awake <= 1;
            end
        end
    endmodule
""")

_PASS_NO_SOFT_RESET = textwrap.dedent("""\
    module simple_counter(
        input clk, rst_n
    );
        reg awake;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n)
                awake <= 0;
            else
                awake <= 1;
        end
    endmodule
""")

_FAIL_RESET_FORGETS_AWAKE = textwrap.dedent("""\
    module dispatcher(
        input clk, rst_n,
        input [7:0] cmd_op,
        input [7:0] rx_data
    );
        reg awake;
        reg [7:0] byte_buf;
        localparam CMD_RST = 8'hFF;

        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                awake <= 0;
                byte_buf <= 0;
            end else if (cmd_op == CMD_RST) begin
                byte_buf <= 0;
                // BUG: forgot to clear awake!
            end else begin
                awake <= 1;
                byte_buf <= rx_data;
            end
        end
    endmodule
""")

_PASS_NO_WAKE_FLAG = textwrap.dedent("""\
    module crc_engine(
        input clk, rst_n,
        input [7:0] data_in,
        output reg [7:0] crc_out
    );
        localparam CMD_RST = 8'hFF;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n)
                crc_out <= 8'hFF;
            else
                crc_out <= crc_out ^ data_in;
        end
    endmodule
""")

_FAIL_SOFT_RESET_SIGNAL = textwrap.dedent("""\
    module mac(
        input clk, rst_n,
        input soft_reset
    );
        reg active;
        reg [7:0] frame_cnt;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                active <= 0;
                frame_cnt <= 0;
            end else if (soft_reset) begin
                frame_cnt <= 0;
                // BUG: active not cleared on soft_reset
            end else begin
                active <= 1;
                frame_cnt <= frame_cnt + 1;
            end
        end
    endmodule
""")

_PASS_ABORT_CLEARS_WOKEN = textwrap.dedent("""\
    module session_mgr(
        input clk, rst_n,
        input cmd_abort
    );
        reg woken;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n)
                woken <= 0;
            else if (cmd_abort)
                woken <= 0;
            else
                woken <= 1;
        end
    endmodule
""")


# ── helper ────────────────────────────────────────────────────────────

def _write(tmp_path: Path, name: str, text: str) -> Path:
    d = tmp_path / "phase2" / "stage1" / "rtl"
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_text(text)
    return d


# ── tests ─────────────────────────────────────────────────────────────

def test_pass_reset_clears_awake(tmp_path):
    d = _write(tmp_path, "disp.v", _PASS_RESET_CLEARS_AWAKE)
    assert main([str(d)]) == 0


def test_pass_no_soft_reset(tmp_path):
    d = _write(tmp_path, "counter.v", _PASS_NO_SOFT_RESET)
    assert main([str(d)]) == 0


def test_fail_reset_forgets_awake(tmp_path):
    d = _write(tmp_path, "disp.v", _FAIL_RESET_FORGETS_AWAKE)
    assert main([str(d)]) == 1


def test_pass_no_wake_flag(tmp_path):
    d = _write(tmp_path, "crc.v", _PASS_NO_WAKE_FLAG)
    assert main([str(d)]) == 0


def test_fail_soft_reset_signal(tmp_path):
    d = _write(tmp_path, "mac.v", _FAIL_SOFT_RESET_SIGNAL)
    assert main([str(d)]) == 1


def test_pass_abort_clears_woken(tmp_path):
    d = _write(tmp_path, "session.v", _PASS_ABORT_CLEARS_WOKEN)
    assert main([str(d)]) == 0


def test_no_files_exit2(tmp_path):
    assert main([str(tmp_path / "nonexistent")]) == 2


def test_help(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_empty_dir_pass(tmp_path):
    d = tmp_path / "phase2" / "stage1" / "rtl"
    d.mkdir(parents=True, exist_ok=True)
    assert main([str(d)]) == 0
