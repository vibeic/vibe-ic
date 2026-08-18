"""Tests for dispatch_fetch_loop_population_check.py (R8)."""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "dispatch_fetch_loop_population_check.py"

PROPER_LOOP = textwrap.dedent("""\
    module dispatcher(
        input clk, rst_n,
        input [3:0] rsp_total,
        output reg [7:0] tx_byte
    );
        reg [3:0] rsp_idx;
        reg [2:0] state;
        localparam S_IDLE = 0, S_FETCH = 1, S_DONE = 2;

        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                state <= S_IDLE;
                rsp_idx <= 0;
            end else case (state)
                S_IDLE: begin
                    rsp_idx <= 0;
                    state <= S_FETCH;
                end
                S_FETCH: begin
                    tx_byte <= 8'hAA;
                    if (rsp_idx < rsp_total) begin
                        rsp_idx <= rsp_idx + 1;
                        state <= S_FETCH;
                    end else
                        state <= S_DONE;
                end
                S_DONE: state <= S_IDLE;
            endcase
        end
    endmodule
""")

STUB_FETCH = textwrap.dedent("""\
    module dispatcher(
        input clk, rst_n,
        input [3:0] rsp_total,
        output reg [7:0] tx_byte
    );
        reg [2:0] state;
        localparam S_IDLE = 0, S_FETCH = 1, S_DONE = 2;

        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                state <= S_IDLE;
            end else case (state)
                S_IDLE: state <= S_FETCH;
                S_FETCH: begin
                    tx_byte <= 8'hAA;
                    state <= S_DONE;
                end
                S_DONE: state <= S_IDLE;
            endcase
        end
    endmodule
""")

SINGLE_FRAME = textwrap.dedent("""\
    module simple_resp(
        input clk, rst_n,
        output reg [7:0] tx_byte
    );
        reg [1:0] state;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n)
                state <= 0;
            else begin
                tx_byte <= 8'h55;
                state <= state + 1;
            end
        end
    endmodule
""")

HARDCODED_SINGLE = textwrap.dedent("""\
    module dispatcher(
        input clk, rst_n,
        output reg [7:0] tx_byte
    );
        reg [3:0] rsp_total;
        reg [2:0] state;
        localparam S_IDLE = 0, S_FETCH = 1, S_DONE = 2;

        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                state <= S_IDLE;
                rsp_total <= 4'd3;
            end else case (state)
                S_IDLE: state <= S_FETCH;
                S_FETCH: begin
                    tx_byte <= 8'hAA;
                    state <= S_DONE;
                end
                S_DONE: state <= S_IDLE;
            endcase
        end
    endmodule
""")

FOR_LOOP_STYLE = textwrap.dedent("""\
    module gen_frames(
        input clk, rst_n,
        input [3:0] num_responses
    );
        integer i;
        reg [7:0] buf [0:15];
        always @(posedge clk) begin
            for (i = 0; i < num_responses; i = i + 1)
                buf[i] <= 8'h00;
        end
    endmodule
""")


def _run(tmp_path: Path, *extra_args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", *extra_args],
        capture_output=True, text=True,
    )


def test_pass_proper_fetch_loop(tmp_path):
    (tmp_path / "disp.v").write_text(PROPER_LOOP)
    r = _run(tmp_path)
    assert r.returncode == 0
    j = json.loads(r.stdout)
    assert j["verdict"] == "PASS"
    assert j["errors"] == 0


def test_pass_single_frame_protocol(tmp_path):
    (tmp_path / "simple.v").write_text(SINGLE_FRAME)
    r = _run(tmp_path)
    assert r.returncode == 0
    j = json.loads(r.stdout)
    assert j["verdict"] == "PASS"


def test_fail_stub_fetch(tmp_path):
    (tmp_path / "disp.v").write_text(STUB_FETCH)
    r = _run(tmp_path)
    assert r.returncode == 1
    j = json.loads(r.stdout)
    assert j["verdict"] == "FAIL"
    assert j["errors"] >= 1
    assert "stub_fetch_loop" in j["findings"][0]["rule"]


def test_fail_hardcoded_single(tmp_path):
    (tmp_path / "disp.v").write_text(HARDCODED_SINGLE)
    r = _run(tmp_path)
    assert r.returncode == 1
    j = json.loads(r.stdout)
    assert j["verdict"] == "FAIL"


def test_pass_for_loop_style(tmp_path):
    (tmp_path / "gen.v").write_text(FOR_LOOP_STYLE)
    r = _run(tmp_path)
    assert r.returncode == 0
    j = json.loads(r.stdout)
    assert j["verdict"] == "PASS"


def test_no_files_exit2(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 2


def test_missing_dir():
    r = subprocess.run(
        [sys.executable, str(PROG), "/nonexistent/path"],
        capture_output=True, text=True,
    )
    assert r.returncode == 2


def test_help():
    r = subprocess.run(
        [sys.executable, str(PROG), "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "stub" in r.stdout.lower() or "fetch" in r.stdout.lower()


def test_multiple_files_mixed(tmp_path):
    """One clean file + one buggy file = overall FAIL."""
    (tmp_path / "ok.v").write_text(PROPER_LOOP)
    (tmp_path / "bad.v").write_text(STUB_FETCH)
    r = _run(tmp_path)
    assert r.returncode == 1
    j = json.loads(r.stdout)
    assert j["verdict"] == "FAIL"
    assert j["scanned"] == 2
