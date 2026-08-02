#!/usr/bin/env python3
"""Tests for buffer_occupancy_flag_latency_check.py.

Chip-AGNOSTIC gate: a storage-buffer occupancy flag (empty/full family)
registered from the STALE same-block-advanced pointer settles one cycle
late. FAIL the stale-NBA form; PASS the combinational and next-state forms.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "buffer_occupancy_flag_latency_check.py")


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _proj(tmp_path: Path, rtl_files: dict[str, str],
          waivers: dict | None = None) -> Path:
    proj = tmp_path / "proj"
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    for name, body in rtl_files.items():
        (rtl / name).write_text(body)
    if waivers is not None:
        (proj / "waivers.json").write_text(json.dumps(waivers))
    return proj


# The failing generation: EMPTY/FULL registered from the STALE SP in the
# same posedge block that decrements/increments SP -> one cycle late.
BUGGY_LIFO = """
module LIFObuffer(dataIn, RW, EN, Rst, Clk, EMPTY, FULL, dataOut);
    input [3:0] dataIn;
    input RW, EN, Rst, Clk;
    output reg EMPTY, FULL;
    output reg [3:0] dataOut;
    reg [3:0] stack_mem [0:3];
    integer SP;
    integer i;
    always @(posedge Clk) begin
        if (EN) begin
            if (Rst) begin
                dataOut <= 0;
                for (i=0;i<4;i=i+1) stack_mem[i] <= 0;
                SP <= 4; EMPTY <= 1; FULL <= 0;
            end
            else if (RW == 0 && FULL == 0) begin
                stack_mem[SP-1] <= dataIn;
                SP <= SP - 1;
            end
            else if (RW == 1 && EMPTY == 0) begin
                dataOut <= stack_mem[SP];
                stack_mem[SP] <= 0;
                SP <= SP + 1;
            end
            FULL  <= (SP == 0);
            EMPTY <= (SP == 4);
        end
    end
endmodule
"""

# GOOD form A: combinational flags settle the instant SP settles.
GOOD_COMB = """
module LIFObuffer(dataIn, RW, EN, Rst, Clk, EMPTY, FULL, dataOut);
    input [3:0] dataIn;
    input RW, EN, Rst, Clk;
    output EMPTY, FULL;
    output reg [3:0] dataOut;
    reg [3:0] stack_mem [0:3];
    integer SP;
    integer i;
    always @(posedge Clk) begin
        if (EN) begin
            if (Rst) begin
                dataOut <= 0;
                for (i=0;i<4;i=i+1) stack_mem[i] <= 0;
                SP <= 4;
            end
            else if (RW == 0 && FULL == 0) begin
                stack_mem[SP-1] <= dataIn; SP <= SP - 1;
            end
            else if (RW == 1 && EMPTY == 0) begin
                dataOut <= stack_mem[SP]; stack_mem[SP] <= 0; SP <= SP + 1;
            end
        end
    end
    assign EMPTY = (SP == 4);
    assign FULL  = (SP == 0);
endmodule
"""

# GOOD form B: next-state registered flags (computed from the advanced SP).
GOOD_NEXTSTATE = """
module LIFObuffer(dataIn, RW, EN, Rst, Clk, EMPTY, FULL, dataOut);
    input [3:0] dataIn;
    input RW, EN, Rst, Clk;
    output reg EMPTY, FULL;
    output reg [3:0] dataOut;
    reg [3:0] stack_mem [0:3];
    integer SP;
    integer i;
    always @(posedge Clk) begin
        if (EN) begin
            if (Rst) begin
                SP <= 4; EMPTY <= 1; FULL <= 0;
            end
            else if (RW == 0 && FULL == 0) begin
                stack_mem[SP-1] <= dataIn; SP <= SP - 1;
                FULL  <= ((SP - 1) == 0); EMPTY <= 1'b0;
            end
            else if (RW == 1 && EMPTY == 0) begin
                dataOut <= stack_mem[SP]; stack_mem[SP] <= 0; SP <= SP + 1;
                EMPTY <= ((SP + 1) == 4); FULL <= 1'b0;
            end
        end
    end
endmodule
"""

# Non-buffer design: gate must SKIP (not applicable).
ADDER = """
module adder(input [3:0] a, b, output [4:0] s);
    assign s = a + b;
endmodule
"""

# ANSI multi-output FIFO with the same stale-pointer bug.
BUGGY_FIFO_ANSI = """
module fifo(input clk, input rst, output reg full, output reg empty,
            output reg [7:0] dout);
    reg [3:0] wptr;
    always @(posedge clk) begin
        if (rst) wptr <= 0;
        else wptr <= wptr + 1;
        full  <= (wptr == 15);
        empty <= (wptr == 0);
    end
endmodule
"""


def test_buggy_stale_flag_fails(tmp_path):
    proj = _proj(tmp_path, {"LIFObuffer.v": BUGGY_LIFO})
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "OCCUPANCY_FLAG_STALE_POINTER_LATENCY" in r.stdout
    # both EMPTY and FULL are stale
    assert r.stdout.count("OCCUPANCY_FLAG_STALE_POINTER_LATENCY") >= 2


def test_combinational_flag_passes(tmp_path):
    proj = _proj(tmp_path, {"LIFObuffer.v": GOOD_COMB})
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_next_state_flag_passes(tmp_path):
    proj = _proj(tmp_path, {"LIFObuffer.v": GOOD_NEXTSTATE})
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_non_buffer_skips(tmp_path):
    proj = _proj(tmp_path, {"adder.v": ADDER})
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS_SKIP" in r.stdout


def test_ansi_multi_output_fifo_fails(tmp_path):
    proj = _proj(tmp_path, {"fifo.v": BUGGY_FIFO_ANSI})
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert r.stdout.count("OCCUPANCY_FLAG_STALE_POINTER_LATENCY") >= 2


def test_waiver_downgrades(tmp_path):
    proj = _proj(
        tmp_path, {"LIFObuffer.v": BUGGY_LIFO},
        waivers={"occupancy_flag_latency_intentional":
                 "design intentionally lags empty/full by one cycle per note"},
    )
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS_WITH_WAIVER" in r.stdout


if __name__ == "__main__":
    sys.exit(subprocess.call(
        [sys.executable, "-m", "pytest", "-q", str(Path(__file__))]))
