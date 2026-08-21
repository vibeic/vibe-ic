#!/usr/bin/env python3
"""Tests for rtl_hygiene_lint.py Rule 22 — `narrow-bitwise-not-wider-context`.

A unary bitwise NOT `~OP`, a binary XNOR `A ~^ B` / `A ^~ B`, or a `<<` / `>>>`
shift whose operand self-width N is NARROWER than the M-bit assignment context
inverts/shifts the upper M-N pad bits (e.g. `~4'hC` in an 8-bit lvalue = 8'hF3,
not 8'h03). The rule is an ADVISORY (non-block-eligible) WARN with NO auto-fix —
a blanket widening cast would corrupt a legitimate full-width inversion.

These tests pin:
  * the canonical sub-word-invert bug FIRES (`~narrow`, `~(a~^b)`, binary XNOR,
    ternary arm, `<<`);
  * legitimate code stays SILENT (full-width `~`, reduction ops, plain `&|^`,
    a `~a & b` masked invert, concat-padded `{4'b0, ~a}`, a same-width XNOR);
  * the finding is WARN-severity, advisory (block_eligible == False), and so is
    visible at `--severity WARN` without tripping rc=1 (additive);
  * the real corpus defect (cvdp_copilot_secure_ALU_0001) fires twice and its
    concat-padded fix is silent.
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "rtl_hygiene_lint.py"
sys.path.insert(0, str(PROG.parent))
import rtl_hygiene_lint as L  # noqa: E402

RULE = "narrow-bitwise-not-wider-context"


def _findings(src: str):
    return L.rule_narrow_bitwise_not_wider_context(L.strip_comments(src), "t.sv")


def _run(args):
    return subprocess.run([sys.executable, str(PROG)] + args,
                          capture_output=True, text=True)


def _wrap(body: str) -> str:
    return ("module m(input clk, input s);\n"
            "  reg [7:0] o; wire [3:0] a, b; wire [7:0] wa, wb;\n"
            "  always @(posedge clk) begin\n    " + body + "\n  end\n"
            "endmodule\n")


# --------------------------------------------------------------------------- #
# FIRES — genuine sub-word invert/shift in a wider lvalue context
# --------------------------------------------------------------------------- #
def test_fires_bare_not_narrow():
    fs = _findings(_wrap("o <= ~a;"))
    assert len(fs) == 1 and fs[0].rule == RULE and fs[0].symbol == "o"


def test_fires_not_of_inner_xnor():
    # ~(a~^b) — outer NOT over a 4-bit XNOR result widened to 8.
    fs = _findings(_wrap("o <= ~(a ~^ b);"))
    assert len(fs) == 1 and fs[0].rule == RULE


def test_fires_binary_xnor_both_forms():
    assert len(_findings(_wrap("o <= a ~^ b;"))) == 1
    assert len(_findings(_wrap("o <= a ^~ b;"))) == 1


def test_fires_left_shift():
    fs = _findings(_wrap("o <= a << 2;"))
    assert len(fs) == 1 and "shift" in fs[0].message


def test_fires_ternary_arm():
    # the ~a arm inherits the 8-bit context; the b arm is fine.
    fs = _findings(_wrap("o <= s ? ~a : b;"))
    assert len(fs) == 1 and fs[0].rule == RULE


def test_fires_continuous_assign():
    src = ("module m(); reg [7:0] o; wire [3:0] a; assign o = ~a; endmodule\n")
    assert len(_findings(src)) == 1


# --------------------------------------------------------------------------- #
# SILENT — legitimate code must NOT fire
# --------------------------------------------------------------------------- #
def test_silent_full_width_not():
    # full-width complement (N == M) is legitimate — never flag.
    assert _findings(_wrap("o <= ~wa;")) == []


def test_silent_reduction_ops():
    # ~&a / ~|a / ~^a are 1-bit reductions, not sub-word inversions.
    for body in ("o <= ~&a;", "o <= ~|a;", "o <= ~^a;",
                 "o <= &a;", "o <= |a;", "o <= ^a;"):
        assert _findings(_wrap(body)) == [], body


def test_silent_plain_bitwise_and_or_xor():
    # &/|/^ over a zero-extended operand keep pad bits 0 — not dangerous.
    for body in ("o <= a & b;", "o <= a | b;", "o <= a ^ b;"):
        assert _findings(_wrap(body)) == [], body


def test_silent_masked_invert():
    # ~a & b — a trailing AND can mask the inverted pad bits; conservative skip.
    assert _findings(_wrap("o <= ~a & b;")) == []


def test_silent_concat_padded():
    # operand already sized to M via {4'b0, ~a} — the fix shape itself.
    assert _findings(_wrap("o <= {4'b0000, ~a};")) == []
    assert _findings(_wrap("o <= {4'b0000, ~(a ^ b)};")) == []


def test_silent_same_width_xnor():
    assert _findings(_wrap("o <= wa ~^ wb;")) == []


def test_silent_logical_right_shift():
    # >> (logical) shifts in 0s at the top — safe; only <</>>> are flagged.
    assert _findings(_wrap("o <= a >> 2;")) == []


def test_silent_comparison_not_assignment():
    # a relational <= inside an if-condition must never read as an assignment.
    src = _wrap("if (a <= b) o <= ~wa; else o <= wa;")
    # the only ~ here is full-width (~wa) -> no finding.
    assert _findings(src) == []


# --------------------------------------------------------------------------- #
# Severity / advisory / additive contract
# --------------------------------------------------------------------------- #
def test_finding_is_advisory_warn():
    f = _findings(_wrap("o <= ~a;"))[0]
    assert f.severity == "WARN"
    assert f.block_eligible is False  # advisory -> never trips rc=1


def test_visible_at_severity_warn_but_rc_zero(tmp_path):
    # A CLEAN module whose ONLY finding is this advisory rule (no undriven wires,
    # reset-covered output) — so rc reflects this rule alone.
    f = tmp_path / "bug.sv"
    f.write_text("module m(input clk, input rst_n, input [3:0] a,\n"
                 "         output reg [7:0] o);\n"
                 "  always @(posedge clk)\n"
                 "    if (!rst_n) o <= 8'b0;\n"
                 "    else        o <= ~a;\n"
                 "endmodule\n")
    r = _run(["--severity", "WARN", str(f)])
    assert RULE in r.stdout
    assert "[ADVISORY" in r.stdout
    assert r.returncode == 0  # additive: advisory WARN does not hard-block


# --------------------------------------------------------------------------- #
# Real corpus defect (confirmed true-positive; the fix_draft concat-pads it)
# --------------------------------------------------------------------------- #
_SECURE_ALU_BUGGY = """module alu_seq (
    input i_clk, input i_rst_b,
    input [3:0] i_operand_a, input [3:0] i_operand_b,
    input [2:0] i_opcode, input [7:0] i_key_in,
    output reg [7:0] o_result
);
    always @(posedge i_clk or negedge i_rst_b) begin
        if (!i_rst_b) o_result <= 8'b0;
        else case (i_opcode)
            3'b101: o_result <= ~i_operand_a;
            3'b111: o_result <= ~(i_operand_a ^ i_operand_b);
            default: o_result <= 8'b0;
        endcase
    end
endmodule
"""

_SECURE_ALU_FIXED = (_SECURE_ALU_BUGGY
                     .replace("~i_operand_a;", "{4'b0000, ~i_operand_a};")
                     .replace("~(i_operand_a ^ i_operand_b);",
                              "{4'b0000, ~(i_operand_a ^ i_operand_b)};"))


def test_corpus_secure_alu_buggy_fires_twice():
    fs = _findings(_SECURE_ALU_BUGGY)
    assert len(fs) == 2
    assert all(f.rule == RULE and f.symbol == "o_result" for f in fs)


def test_corpus_secure_alu_fixed_is_silent():
    assert _findings(_SECURE_ALU_FIXED) == []


if __name__ == "__main__":
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-q"]))
