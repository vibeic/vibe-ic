#!/usr/bin/env python3
"""ORGANIC #843 (CVDP convergence round 18) — `rtl_hygiene_lint`'s
`uninit-registered-output` rule false-positived on a RELATIONAL `<=` COMPARISON.

REPRODUCED FP (shipped plugin v1.1.21, CVDP cvdp_copilot_perceptron_0006):
    `python3 rtl_hygiene_lint.py --strict perceptron_gates.sv` -> rc=1
    [WARN] uninit-registered-output: registered output 'y_in' has no reset and
           no power-up initializer
on a line whose ONLY `<=` touching `y_in` is the RELATIONAL comparison
    else if (y_in >= -threshold && y_in <= threshold)
`y_in` is PURELY COMBINATIONAL — every real write is a blocking `=` inside an
`always_comb`. A combinational output cannot power-up-X-then-be-clocked, so the
rule's premise is inapplicable; flagging it is structurally wrong.

ROOT CAUSE: the registered-output (NBA-LHS) detection regex
    (?<![<>!=])\\b(\\w+)(?:\\[[^\\]]+\\])?\\s*<=
put its negative lookbehind BEFORE the IDENTIFIER, not before the `<=` OPERATOR,
so a relational `<=` comparison whose left operand is an identifier
(`y_in <= threshold`, `if (a <= b)`) was mis-read as a non-blocking ASSIGNMENT
and the identifier wrongly added to the "registered" set.

FIX (ORGANIC #843): keep the proven regex (so the matched-LHS scope is BYTE-
IDENTICAL to the shipped one — §4.05 no-leak: it must NOT start matching
anything new) and ACCEPT a match only when its `<=` token is at PAREN DEPTH 0
(a procedural NBA STATEMENT), rejecting a relational `<=` COMPARISON inside an
`if (...)` / expression `(...)`. Strictly NARROWER than the shipped set:
removes ONLY the relational-comparison false matches, adds nothing.

§4.05 NO-LEAK: a GENUINE reset-less registered output
(`always @(posedge clk) q <= d;` with no reset, no init) writes `q` via a real
statement-level `<=` (paren depth 0), so `q` STILL enters the set and STILL
warns. The negative tests below assert this on the patched gate.

POSITIVE asserts FAIL on shipped v1.1.21 and PASS on patched; NEGATIVE
(no-leak) asserts hold on BOTH (the genuine register must always warn).

chip-AGNOSTIC: pure SV structure parse. No chip / vendor / SKU literal.

Resolves the programs dir via Path(__file__).resolve().parent.parent
(= programs/) with a VIBE_PROGRAMS env override (CI layout: programs/tests/).
This gate is pure-Python lint — no iverilog/vvp needed.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_DEFAULT_PROGRAMS = Path(__file__).resolve().parent.parent
PROGRAMS = Path(os.environ.get("VIBE_PROGRAMS", str(_DEFAULT_PROGRAMS)))
GATE = PROGRAMS / "rtl_hygiene_lint.py"


# ---------------------------------------------------------------------------
# Inline, chip-AGNOSTIC RTL fixtures
# ---------------------------------------------------------------------------

# POSITIVE — the FP shape, minimised: a purely COMBINATIONAL output whose name
# appears on the LHS of a RELATIONAL `<=` comparison inside an `if (...)`. Every
# real write to `yc` is a blocking `=` inside `always @(*)`. Must NOT be flagged.
# (On shipped v1.1.21 this WRONGLY warns -> rc=1; on patched it is silent rc=0.)
POS_COMB_RELATIONAL = (
    "module pos_comb_relational (\n"
    "   input  wire signed [7:0] a,\n"
    "   input  wire signed [7:0] thr,\n"
    "   output reg  signed [7:0] yc\n"
    ");\n"
    "   always @(*) begin\n"
    "      if (a > thr)\n"
    "         yc = 8'd1;\n"
    "      else if (yc >= -thr && yc <= thr)\n"   # yc is LHS of a relational <=
    "         yc = 8'd0;\n"
    "      else\n"
    "         yc = -8'd1;\n"
    "   end\n"
    "endmodule\n"
)

# NEGATIVE / §4.05 no-leak (a) — a GENUINE reset-less registered output: a real
# NBA in a clocked block, no reset, no power-up initializer. MUST STILL warn.
NEG_GENUINE_UNINIT = (
    "module neg_genuine_uninit (\n"
    "   input  wire       clk,\n"
    "   input  wire [7:0] d,\n"
    "   output reg  [7:0] q\n"
    ");\n"
    "   always @(posedge clk)\n"
    "      q <= d;\n"
    "endmodule\n"
)

# NEGATIVE / §4.05 no-leak (b) — a registered output with a REAL NBA in a clocked
# block AND the comparison-form of the SAME name elsewhere. The genuine NBA on
# `qr` MUST still be flagged; the relational `qr <= thr` comparison must NOT
# suppress it (and must not, by itself, register a comb signal).
NEG_MIXED_NBA_AND_COMPARE = (
    "module neg_mixed_nba_and_compare (\n"
    "   input  wire       clk,\n"
    "   input  wire [7:0] d,\n"
    "   input  wire [7:0] thr,\n"
    "   output reg  [7:0] qr,\n"
    "   output reg        flag\n"
    ");\n"
    "   always @(posedge clk)\n"
    "      qr <= d;\n"                 # genuine reset-less NBA -> must WARN
    "   always @(*) begin\n"
    "      if (qr <= thr)\n"           # relational comparison, NOT an NBA
    "         flag = 1'b1;\n"
    "      else\n"
    "         flag = 1'b0;\n"
    "   end\n"
    "endmodule\n"
)

# NEGATIVE / §4.05 no-leak (c) — an UNRELATED real defect (incomplete
# sensitivity list, rule 6) must STILL fire on the patched gate, proving the fix
# did not broadly weaken the lint.
NEG_OTHER_RULE_DEFECT = (
    "module neg_other_rule_defect (\n"
    "   input  wire a,\n"
    "   input  wire clock,\n"
    "   output reg  p\n"
    ");\n"
    "   always @(a)\n"
    "      if (clock) p <= a;\n"
    "endmodule\n"
)


def _run_gate(tmp_path: Path, name: str, rtl: str):
    """Run rtl_hygiene_lint.py --strict on `rtl`; return (returncode, output)."""
    f = tmp_path / f"{name}.sv"
    f.write_text(rtl)
    proc = subprocess.run(
        [sys.executable, str(GATE), "--strict", str(f)],
        capture_output=True, text=True, cwd=str(PROGRAMS),
    )
    return proc.returncode, (proc.stdout + proc.stderr)


def test_gate_exists():
    assert GATE.is_file(), f"rtl_hygiene_lint.py not found at {GATE}"


# ---------------------------------------------------------------------------
# POSITIVE — the FP must be gone (FAILS on shipped v1.1.21, PASSES on patched)
# ---------------------------------------------------------------------------

def test_positive_relational_compare_combinational_output_not_flagged(tmp_path):
    """A combinational output that is the LHS of a relational `<=` comparison
    must NOT be reported as an uninit-registered-output. rc must be 0 and the
    finding must be absent. This is the assertion that fails on shipped v1.1.21
    (which WRONGLY warns) and passes on the patched gate."""
    rc, out = _run_gate(tmp_path, "pos_comb_relational", POS_COMB_RELATIONAL)
    assert "uninit-registered-output" not in out, (
        "relational `<=` comparison on a combinational output was mis-flagged "
        f"as a registered output:\n{out}")
    assert "yc" not in out or "uninit-registered-output" not in out
    assert rc == 0, f"expected rc=0 (no blocking finding), got rc={rc}\n{out}"


def test_positive_real_perceptron_fp_fixture(tmp_path):
    """The exact CVDP round-18 perceptron shape (combinational `y_in` whose only
    `<=` is a relational comparison) collapsed to a minimal generic module —
    must be clean."""
    rtl = (
        "module perceptron_like (\n"
        "   input  logic signed [3:0] x1,\n"
        "   input  logic signed [3:0] threshold,\n"
        "   output logic signed [3:0] y_in,\n"
        "   output logic signed [3:0] y\n"
        ");\n"
        "   always_comb begin\n"
        "      y_in = x1 + threshold;\n"
        "      if (y_in > threshold)\n"
        "         y = 4'd1;\n"
        "      else if (y_in >= -threshold && y_in <= threshold)\n"
        "         y = 4'd0;\n"
        "      else\n"
        "         y = -4'd1;\n"
        "   end\n"
        "endmodule\n"
    )
    rc, out = _run_gate(tmp_path, "perceptron_like", rtl)
    assert "uninit-registered-output" not in out, out
    assert rc == 0, f"expected rc=0, got rc={rc}\n{out}"


# ---------------------------------------------------------------------------
# §4.05 NO-LEAK NEGATIVES — these must hold on BOTH shipped and patched
# (the fix is strictly narrower; a genuine register MUST still warn)
# ---------------------------------------------------------------------------

def test_no_leak_genuine_uninit_registered_output_still_warns(tmp_path):
    """A GENUINE reset-less registered output (`always @(posedge clk) q <= d;`
    with no reset, no init) MUST still be flagged uninit-registered-output and
    block (rc=1). This is the load-bearing §4.05 assertion: if the fix were too
    wide it would silence this real defect."""
    rc, out = _run_gate(tmp_path, "neg_genuine_uninit", NEG_GENUINE_UNINIT)
    assert "uninit-registered-output" in out, (
        "the fix LEAKED — a genuine reset-less registered output is no longer "
        f"flagged:\n{out}")
    assert "'q'" in out, out
    assert rc == 1, f"genuine uninit register must block (rc=1), got rc={rc}\n{out}"


def test_no_leak_mixed_real_nba_still_warns_despite_comparison(tmp_path):
    """A registered output with a REAL NBA in a clocked block is STILL flagged
    even when the comparison-form of the same name appears elsewhere — the
    relational `<=` neither suppresses the genuine finding nor masks it."""
    rc, out = _run_gate(tmp_path, "neg_mixed", NEG_MIXED_NBA_AND_COMPARE)
    assert "uninit-registered-output" in out, out
    assert "'qr'" in out, (
        f"the genuine NBA register 'qr' must still be flagged:\n{out}")
    assert rc == 1, f"expected rc=1, got rc={rc}\n{out}"


def test_no_leak_other_rule_still_fires(tmp_path):
    """An unrelated real defect (incomplete sensitivity list) must STILL fire on
    the patched gate — the fix did not broadly weaken the lint."""
    rc, out = _run_gate(tmp_path, "neg_other_rule", NEG_OTHER_RULE_DEFECT)
    assert "incomplete-sensitivity-list" in out, (
        f"an unrelated lint rule stopped firing:\n{out}")
    assert rc == 1, f"expected rc=1, got rc={rc}\n{out}"


# --- §4.05 round-2 (Step-2.7): the paren-depth gate must be measured over a
# STRUCTURAL view — a stray paren in a COMMENT or STRING must not push a genuine
# reset-less registered output to apparent depth>0 and silence it. ---
_NEG_COMMENT_PAREN = (
    "// see weight( table\n"
    "module dut(input clk, input d, output reg q);\n"
    "  always @(posedge clk) q <= d;\n"
    "endmodule\n")
_NEG_TRAILING_COMMENT_PAREN = (
    "module dut(input clk, input d, output reg q);\n"
    "  always @(posedge clk) begin\n"
    "    q <= d;  // note: weight( unbalanced paren in comment\n"
    "  end\n"
    "endmodule\n")


def test_no_leak_unbalanced_paren_in_comment_still_warns(tmp_path):
    """An unbalanced '(' in a PRECEDING comment must not corrupt the paren-depth
    count and silence a genuine reset-less registered output (Step-2.7 HIGH)."""
    rc, out = _run_gate(tmp_path, "neg_comment_paren", _NEG_COMMENT_PAREN)
    assert "uninit-registered-output" in out, (
        "LEAK: a comment paren hid a genuine reset-less registered output:\n" + out)
    assert "'q'" in out, out
    assert rc == 1, out


def test_no_leak_unbalanced_paren_in_trailing_comment_still_warns(tmp_path):
    rc, out = _run_gate(tmp_path, "neg_trailing_comment_paren",
                        _NEG_TRAILING_COMMENT_PAREN)
    assert "uninit-registered-output" in out, out
    assert "'q'" in out, out
    assert rc == 1, out


# --- §4.05 round-3 (Step-2.7): a comment-token (/*, //) INSIDE a STRING literal
# must be inert — the single-pass masker must not truncate real code after it. ---
_NEG_STR_BLOCK_TOKEN = (
    'module m(input clk, input d, output reg q);\n'
    '  wire [63:0] s = "/* (";\n'
    '  always @(posedge clk) q <= d;\n'
    'endmodule\n')
_NEG_STR_LINE_TOKEN = (
    'module m(input clk, input d, output reg q);\n'
    '  wire [63:0] s = "// (";\n'
    '  always @(posedge clk) q <= d;\n'
    'endmodule\n')


def test_no_leak_comment_token_inside_string_still_warns(tmp_path):
    """A `/* (` inside a STRING literal must not be treated as a block comment
    and truncate the source — the genuine reset-less output still warns."""
    rc, out = _run_gate(tmp_path, "neg_str_block_token", _NEG_STR_BLOCK_TOKEN)
    assert "uninit-registered-output" in out and "'q'" in out, out
    assert rc == 1, out


def test_no_leak_line_comment_token_inside_string_still_warns(tmp_path):
    rc, out = _run_gate(tmp_path, "neg_str_line_token", _NEG_STR_LINE_TOKEN)
    assert "uninit-registered-output" in out and "'q'" in out, out
    assert rc == 1, out


# --- §4.05 round-3 (Step-2.7): a depth-0 relational `<=` in a continuous-assign
# / blocking RHS (`assign le = sum <= b`) is NOT an NBA — statement-boundary. ---
_POS_DEPTH0_ASSIGN = (
    "module m(input [7:0] b, output [7:0] sum, output le);\n"
    "  assign sum = b + 1;\n"
    "  assign le  = sum <= b;\n"
    "endmodule\n")
_POS_DEPTH0_BLOCKING = (
    "module m(input [7:0] yc, input [7:0] thr, output reg flag);\n"
    "  always @* flag = yc <= thr;\n"
    "endmodule\n")
_NEG_CASE_ITEM_NBA = (
    "module m(input clk, input [1:0] s, input d, output reg q);\n"
    "  always @(posedge clk) case (s)\n"
    "    2'd0: q <= d;\n"
    "    default: q <= 1'b0;\n"
    "  endcase\n"
    "endmodule\n")


def test_positive_depth0_relational_in_assign_not_flagged(tmp_path):
    rc, out = _run_gate(tmp_path, "pos_depth0_assign", _POS_DEPTH0_ASSIGN)
    assert "uninit-registered-output" not in out, (
        "a depth-0 relational `<=` in a continuous assign is a comparison, not "
        f"an NBA — `sum`/`le` are combinational:\n{out}")


def test_positive_depth0_relational_blocking_not_flagged(tmp_path):
    rc, out = _run_gate(tmp_path, "pos_depth0_blocking", _POS_DEPTH0_BLOCKING)
    assert "uninit-registered-output" not in out, out


def test_no_leak_case_item_nba_still_warns(tmp_path):
    """A genuine NBA whose LHS follows a `case`-label `:` must STILL register —
    the statement-boundary check must not reject `:`-preceded NBAs."""
    rc, out = _run_gate(tmp_path, "neg_case_item", _NEG_CASE_ITEM_NBA)
    assert "uninit-registered-output" in out and "'q'" in out, out
    assert rc == 1, out
