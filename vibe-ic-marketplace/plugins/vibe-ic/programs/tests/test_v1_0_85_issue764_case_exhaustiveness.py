#!/usr/bin/env python3
"""ORGANIC #764 — rule_case_coverage must NOT fire case-no-default on a case
that PROVABLY enumerates its full selector range.

ROOT CAUSE (reproduced on shipped 1.0.84): `rule_case_coverage` emitted WARN
`case-no-default` purely on the textual absence of `default:`, with NO
exhaustiveness analysis. So a fully-enumerated case (e.g. a 2-bit selector with
all four sized literals 2'b00/01/10/11) false-positived — the WARN even fired on
the benchmark's own golden/reference module (yosys confirms no latch is
inferred), and rc=1 hard-BLOCKed the submission.

FIX (chip-AGNOSTIC, purely structural): add `_sized_literal_value`,
`_resolve_selector_width`, `_case_is_exhaustive`. Before emitting the WARN,
suppress ONLY when (a) the selector width resolves from a concrete numeric
`[hi:lo]` declaration to N bits and (b) EVERY case label is a clean sized
numeric literal whose distinct values exactly cover {0..2^N-1}. Otherwise the
WARN stays (conservative-by-design).

§4.05 NO-LEAK: a partial case (some 2^N values un-enumerated) and a symbolic
localparam FSM case (labels are identifiers, value not resolvable) must STILL
fire WARN case-no-default after the fix.

chip-AGNOSTIC: no chip / vendor / SKU literal (enforced by
programs/source_chip_agnostic_check.py).
"""
from __future__ import annotations

import json
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

# NEW-PATH: fully-enumerated 2-bit case, all four sized labels, NO default.
EXHAUSTIVE_2BIT = (
    "module image_rotate(\n"
    "    input  wire [1:0] rotation_angle,\n"
    "    input  wire [7:0] din,\n"
    "    output reg  [7:0] dout\n"
    ");\n"
    "    always @(*) begin\n"
    "        case (rotation_angle)\n"
    "            2'b00: dout = din;\n"
    "            2'b01: dout = {din[3:0], din[7:4]};\n"
    "            2'b10: dout = ~din;\n"
    "            2'b11: dout = din ^ 8'hFF;\n"
    "        endcase\n"
    "    end\n"
    "endmodule\n"
)

# NEW-PATH variant: fully-enumerated via decimal labels.
EXHAUSTIVE_2BIT_DEC = (
    "module dec(input wire [1:0] s, output reg [3:0] o);\n"
    "    always @(*) begin\n"
    "        case (s)\n"
    "            2'd0: o = 4'd1;\n"
    "            2'd1: o = 4'd2;\n"
    "            2'd2: o = 4'd3;\n"
    "            2'd3: o = 4'd4;\n"
    "        endcase\n"
    "    end\n"
    "endmodule\n"
)

# §4.05 NO-LEAK #1: only 2 of 4 sized-literal labels — PARTIAL, must STILL fire.
PARTIAL_2BIT = (
    "module partial(input wire [1:0] sel, input wire [7:0] din, output reg [7:0] dout);\n"
    "    always @(*) begin\n"
    "        case (sel)\n"
    "            2'b00: dout = din;\n"
    "            2'b01: dout = ~din;\n"
    "        endcase\n"
    "    end\n"
    "endmodule\n"
)

# §4.05 NO-LEAK #2: symbolic localparam FSM, 3 of 4 values — must STILL fire
# (bails on the bare identifier label, value not deterministically resolvable).
SYMBOLIC_FSM = (
    "module fsm(input wire clk, input wire [1:0] state, output reg [7:0] out);\n"
    "    localparam IDLE = 2'b00, LOAD = 2'b01, DONE = 2'b10;\n"
    "    always @(*) begin\n"
    "        case (state)\n"
    "            IDLE: out = 8'h00;\n"
    "            LOAD: out = 8'h01;\n"
    "            DONE: out = 8'h02;\n"
    "        endcase\n"
    "    end\n"
    "endmodule\n"
)

# §4.05 NO-LEAK #3: parameterized-width selector — width NOT resolvable from a
# concrete numeric range, so even a 4-label-looking case must STILL fire.
PARAM_WIDTH = (
    "module pw #(parameter W=2)(input wire [W-1:0] s, output reg [7:0] o);\n"
    "    always @(*) begin\n"
    "        case (s)\n"
    "            2'b00: o = 8'd0;\n"
    "            2'b01: o = 8'd1;\n"
    "            2'b10: o = 8'd2;\n"
    "            2'b11: o = 8'd3;\n"
    "        endcase\n"
    "    end\n"
    "endmodule\n"
)


# ---------------------------------------------------------------------------
# (a) NEW-PATH — the wrongly-flagged exhaustive case now passes.
# ---------------------------------------------------------------------------
def test_exhaustive_2bit_binary_not_flagged():
    findings = HY.rule_case_coverage(EXHAUSTIVE_2BIT, "x.sv")
    assert not any(f.rule == "case-no-default" for f in findings), (
        "fully-enumerated 2-bit case must NOT fire case-no-default")


def test_exhaustive_2bit_decimal_not_flagged():
    findings = HY.rule_case_coverage(EXHAUSTIVE_2BIT_DEC, "x.sv")
    assert not any(f.rule == "case-no-default" for f in findings)


def test_case_is_exhaustive_helper_true_for_full():
    block = (
        "case (rotation_angle)\n"
        "    2'b00: dout = din;\n"
        "    2'b01: dout = ~din;\n"
        "    2'b10: dout = din;\n"
        "    2'b11: dout = din;\n"
        "endcase"
    )
    assert HY._case_is_exhaustive(EXHAUSTIVE_2BIT, "rotation_angle", block) is True


def test_sized_literal_value_helper():
    assert HY._sized_literal_value("2'b10") == 2
    assert HY._sized_literal_value("8'hFF") == 255
    assert HY._sized_literal_value("4'd9") == 9
    assert HY._sized_literal_value("3'o7") == 7
    # x/z and non-literals -> None (conservative)
    assert HY._sized_literal_value("2'b1x") is None
    assert HY._sized_literal_value("IDLE") is None
    assert HY._sized_literal_value("4'd?") is None


def test_resolve_selector_width_helper():
    assert HY._resolve_selector_width(EXHAUSTIVE_2BIT, "rotation_angle") == 2
    # parameterized width -> None
    assert HY._resolve_selector_width(PARAM_WIDTH, "s") is None
    # expression selector -> None
    assert HY._resolve_selector_width(EXHAUSTIVE_2BIT, "rotation_angle[0]") is None


# ---------------------------------------------------------------------------
# (b) REGRESSION GUARD — prior correct behaviour unchanged.
#     A genuinely-partial sized-literal case still flags.
# ---------------------------------------------------------------------------
def test_partial_2bit_still_flags():
    findings = HY.rule_case_coverage(PARTIAL_2BIT, "x.sv")
    assert any(f.rule == "case-no-default" for f in findings), (
        "partial 2-of-4 case MUST still fire case-no-default")


def test_case_is_exhaustive_helper_false_for_partial():
    block = (
        "case (sel)\n"
        "    2'b00: dout = din;\n"
        "    2'b01: dout = ~din;\n"
        "endcase"
    )
    assert HY._case_is_exhaustive(PARTIAL_2BIT, "sel", block) is False


# ---------------------------------------------------------------------------
# (c) §4.05 NEGATIVE NO-LEAK — boundary-outside genuine defects STILL fire.
# ---------------------------------------------------------------------------
def test_noleak_symbolic_fsm_still_flags():
    """Symbolic localparam labels (3 of 4 values) -> value not resolvable ->
    the WARN must STILL fire (suppression only for sized-literal full cases)."""
    findings = HY.rule_case_coverage(SYMBOLIC_FSM, "x.sv")
    assert any(f.rule == "case-no-default" for f in findings), (
        "symbolic FSM partial case MUST still fire — fix bails on identifiers")
    # And the helper agrees: it returns False on the symbolic case.
    block = (
        "case (state)\n"
        "    IDLE: out = 8'h00;\n"
        "    LOAD: out = 8'h01;\n"
        "    DONE: out = 8'h02;\n"
        "endcase"
    )
    assert HY._case_is_exhaustive(SYMBOLIC_FSM, "state", block) is False


def test_noleak_parameterized_width_still_flags():
    """Width not deterministically resolvable from a concrete numeric range ->
    even a 4-label-looking case must STILL fire (conservative)."""
    findings = HY.rule_case_coverage(PARAM_WIDTH, "x.sv")
    assert any(f.rule == "case-no-default" for f in findings)


# ---------------------------------------------------------------------------
# (d) #478 END-STATE — direct-write a tmp artifact, invoke the real program
#     via subprocess, assert returncode.
# ---------------------------------------------------------------------------
def test_end_state_exhaustive_returncode_zero(tmp_path):
    """The previously-false-positive exhaustive case now yields rc=0 (no
    case-no-default WARN) and an empty findings JSON."""
    sv = tmp_path / "image_rotate_0015.sv"
    sv.write_text(EXHAUSTIVE_2BIT)
    out_json = tmp_path / "findings.json"
    r = subprocess.run(
        [sys.executable, str(PROG), "--json", str(out_json), str(sv)],
        capture_output=True, text=True)
    assert r.returncode == 0, (
        f"exhaustive case must yield rc=0, got {r.returncode}\n{r.stdout}\n{r.stderr}")
    assert "case-no-default" not in r.stdout
    data = json.loads(out_json.read_text())
    assert all(f["rule"] != "case-no-default" for f in data)


def test_end_state_partial_returncode_one(tmp_path):
    """§4.05 boundary-outside: the genuinely-partial case STILL blocks (rc=1,
    case-no-default present)."""
    sv = tmp_path / "partial.sv"
    sv.write_text(PARTIAL_2BIT)
    r = subprocess.run(
        [sys.executable, str(PROG), str(sv)],
        capture_output=True, text=True)
    assert r.returncode == 1, (
        f"partial case must still BLOCK (rc=1), got {r.returncode}\n{r.stdout}")
    assert "case-no-default" in r.stdout


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
