#!/usr/bin/env python3
"""ORGANIC #765 — _block_body_after must bound always-block bodies at the SAME
`always` flavors the block discovery uses (always / always_ff / always_comb /
always_latch), so a register single-driven in a pure modern-SV design is not
mis-attributed to phantom blocks.

ROOT CAUSE (reproduced on shipped 1.0.84): `_block_body_after` (the body-bounding
helper) used `r'\balways\b|\bendmodule\b'`. `\balways\b` CANNOT match
`always_ff`/`always_comb`/`always_latch` because the trailing `_` is a word char
(no `\b` between `always` and `_ff`), whereas the block-discovery regex
`_iter_always_blocks` uses `always(?:_ff|_comb|_latch)?`. On a pure-modern-SV
design the FIRST block body overran to `endmodule`, swallowing EVERY later block,
so `rule_multidriven_register` saw each single-driven register written by many
blocks across many clock domains and false-WARNed (apb_dsp_op 31, async_filo 9 —
verilator -Wall reports 0 MULTIDRIVEN on both).

FIX (chip-AGNOSTIC, one-line): widen the boundary to
`r'\balways(?:_ff|_comb|_latch)?\b|\bendmodule\b'` so body bounding matches the
discovery flavors. Legacy bare-`always` path is byte-identical (the new
alternation degenerates to `\balways\b` when no `_ff/_comb/_latch` suffix is
present).

§4.05 NO-LEAK: a genuine multidriven hazard (same reg reset-cleared in one block
AND written unconditionally in another under the SAME clock; or written in two
blocks under DIFFERENT clocks) must STILL fire after the fix.

chip-AGNOSTIC: pure SV structure parse. No chip / vendor / SKU literal (enforced
by programs/source_chip_agnostic_check.py).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
sys.path.insert(0, str(PROGRAMS))

import rtl_hygiene_lint as HY  # noqa: E402

PROG = PROGRAMS / "rtl_hygiene_lint.py"

# ---------------------------------------------------------------------------
# Fixtures (self-contained — no dependence on the AI_IC_design corpus).
# ---------------------------------------------------------------------------

# NEW-PATH: pure always_ff, two clock domains, each register single-driven.
# On the buggy boundary, block 1's body overran into block 2 and `rreg` (written
# ONLY in block 2) looked driven from 2 blocks across different clocks.
PURE_ALWAYS_FF_CLEAN = (
    "module two_domain(\n"
    "    input  wire        wclk,\n"
    "    input  wire        rclk,\n"
    "    input  wire        rstn,\n"
    "    input  wire [7:0]  wdata,\n"
    "    input  wire [7:0]  rdata,\n"
    "    output reg  [7:0]  wreg,\n"
    "    output reg  [7:0]  rreg\n"
    ");\n"
    "    always_ff @(posedge wclk or negedge rstn) begin\n"
    "        if (!rstn) wreg <= 8'd0;\n"
    "        else       wreg <= wdata;\n"
    "    end\n"
    "    always_ff @(posedge rclk or negedge rstn) begin\n"
    "        if (!rstn) rreg <= 8'd0;\n"
    "        else       rreg <= rdata;\n"
    "    end\n"
    "endmodule\n"
)

# NEW-PATH: three pure always_ff blocks, same clock, each reg single-driven.
PURE_ALWAYS_FF_THREE = (
    "module apb_block(\n"
    "    input  wire        pclk,\n"
    "    input  wire        presetn,\n"
    "    input  wire [31:0] paddr_in,\n"
    "    input  wire [31:0] pwdata_in,\n"
    "    output reg  [31:0] PADDR,\n"
    "    output reg  [31:0] PRDATA,\n"
    "    output reg  [31:0] reg_operand_a\n"
    ");\n"
    "    always_ff @(posedge pclk or negedge presetn) begin\n"
    "        if (!presetn) PADDR <= 32'd0;\n"
    "        else          PADDR <= paddr_in;\n"
    "    end\n"
    "    always_ff @(posedge pclk or negedge presetn) begin\n"
    "        if (!presetn) PRDATA <= 32'd0;\n"
    "        else          PRDATA <= pwdata_in;\n"
    "    end\n"
    "    always_ff @(posedge pclk or negedge presetn) begin\n"
    "        if (!presetn) reg_operand_a <= 32'd0;\n"
    "        else          reg_operand_a <= paddr_in ^ pwdata_in;\n"
    "    end\n"
    "endmodule\n"
)

# §4.05 NO-LEAK #1: genuine same-clock multidriven — reg reset-cleared in one
# always_ff block AND written UNCONDITIONALLY in another under the SAME clock.
# (reg named q_out — `x` is a Verilog value keyword and would be filtered.)
GENUINE_SAME_CLOCK = (
    "module hazard(input wire clk, input wire rst, input wire [7:0] d, output reg [7:0] q_out);\n"
    "    always_ff @(posedge clk) begin\n"
    "        if (rst) q_out <= 8'd0;\n"
    "    end\n"
    "    always_ff @(posedge clk) begin\n"
    "        q_out <= d;\n"
    "    end\n"
    "endmodule\n"
)

# §4.05 NO-LEAK #2: genuine DIFFERENT-clock multidriven on a pure always_ff
# design (overlapping whole-reg write in two clock domains).
GENUINE_DIFF_CLOCK = (
    "module diffclk(input wire aclk, input wire bclk, input wire [7:0] d, output reg [7:0] y);\n"
    "    always_ff @(posedge aclk) begin\n"
    "        y <= d;\n"
    "    end\n"
    "    always_ff @(posedge bclk) begin\n"
    "        y <= d + 8'd1;\n"
    "    end\n"
    "endmodule\n"
)

# REGRESSION: legacy bare-`always` design — single-driven regs, no false WARN.
BARE_ALWAYS_CLEAN = (
    "module clean_bare(input wire clk, input wire rstn, input wire [7:0] a, input wire [7:0] b,\n"
    "                  output reg [7:0] ra, output reg [7:0] rb);\n"
    "    always @(posedge clk or negedge rstn) begin\n"
    "        if (!rstn) ra <= 8'd0; else ra <= a;\n"
    "    end\n"
    "    always @(posedge clk or negedge rstn) begin\n"
    "        if (!rstn) rb <= 8'd0; else rb <= b;\n"
    "    end\n"
    "endmodule\n"
)


def _multidriven(src):
    return [f for f in HY.rule_multidriven_register(src, "x.sv")
            if f.rule == "multidriven-register"]


# ---------------------------------------------------------------------------
# Boundary-helper unit check: _block_body_after now stops at always_ff.
# ---------------------------------------------------------------------------
def test_block_body_after_stops_at_always_ff():
    # body_start is right after the first block's sens-list close-paren.
    bm = next(HY.re.finditer(
        r'\balways(?:_ff|_comb|_latch)?\s*@\s*\(([^)]*)\)', PURE_ALWAYS_FF_CLEAN))
    body = HY._block_body_after(PURE_ALWAYS_FF_CLEAN, bm.end())
    # The first block's body must NOT swallow the second block (no `rreg` /
    # second `always_ff` should appear in block-1's bounded body).
    assert "rreg" not in body, "block-1 body overran into block-2 (rreg leaked)"
    assert "rclk" not in body


# ---------------------------------------------------------------------------
# (a) NEW-PATH — single-driven regs on pure always_ff designs no longer
#     false-WARN multidriven.
# ---------------------------------------------------------------------------
def test_pure_always_ff_two_domain_no_false_multidriven():
    assert _multidriven(PURE_ALWAYS_FF_CLEAN) == [], (
        "single-driven regs on a pure always_ff design must NOT false-WARN")


def test_pure_always_ff_three_block_no_false_multidriven():
    assert _multidriven(PURE_ALWAYS_FF_THREE) == []


# ---------------------------------------------------------------------------
# (b) REGRESSION GUARD — legacy bare-`always` path unchanged.
# ---------------------------------------------------------------------------
def test_bare_always_clean_unchanged():
    assert _multidriven(BARE_ALWAYS_CLEAN) == []


def test_bare_always_genuine_diffclock_still_flags():
    bare = (
        "module diffclk_bare(input wire aclk, input wire bclk, input wire [7:0] d, output reg [7:0] y);\n"
        "    always @(posedge aclk) begin\n"
        "        y <= d;\n"
        "    end\n"
        "    always @(posedge bclk) begin\n"
        "        y <= d + 8'd1;\n"
        "    end\n"
        "endmodule\n"
    )
    assert len(_multidriven(bare)) == 1, "legacy bare-always genuine race must still fire"


# ---------------------------------------------------------------------------
# (c) §4.05 NEGATIVE NO-LEAK — genuine hazards STILL fire on pure always_ff.
# ---------------------------------------------------------------------------
def test_noleak_genuine_same_clock_still_flags():
    finds = _multidriven(GENUINE_SAME_CLOCK)
    assert len(finds) == 1, (
        "genuine same-clock reset-clear + unconditional race MUST still fire")
    assert finds[0].symbol == "q_out"


def test_noleak_genuine_diff_clock_still_flags():
    finds = _multidriven(GENUINE_DIFF_CLOCK)
    assert len(finds) == 1, (
        "genuine different-clock multidriven MUST still fire")
    assert finds[0].symbol == "y"


# ---------------------------------------------------------------------------
# (d) #478 END-STATE — direct-write a tmp artifact, invoke the real program
#     via subprocess, assert returncode.
# ---------------------------------------------------------------------------
def test_end_state_clean_returncode_zero(tmp_path):
    """Pure always_ff single-driven design now yields rc=0 (no multidriven)."""
    sv = tmp_path / "async_filo_0001.sv"
    sv.write_text(PURE_ALWAYS_FF_THREE)
    r = subprocess.run(
        [sys.executable, str(PROG), str(sv)],
        capture_output=True, text=True)
    assert r.returncode == 0, (
        f"clean pure-always_ff design must yield rc=0, got {r.returncode}\n{r.stdout}")
    assert "multidriven-register" not in r.stdout


def test_end_state_genuine_hazard_returncode_one(tmp_path):
    """§4.05 boundary-outside: genuine same-clock multidriven STILL blocks
    (rc=1, multidriven-register present)."""
    sv = tmp_path / "hazard.sv"
    sv.write_text(GENUINE_SAME_CLOCK)
    r = subprocess.run(
        [sys.executable, str(PROG), str(sv)],
        capture_output=True, text=True)
    assert r.returncode == 1, (
        f"genuine multidriven hazard must still BLOCK (rc=1), got {r.returncode}\n{r.stdout}")
    assert "multidriven-register" in r.stdout


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
