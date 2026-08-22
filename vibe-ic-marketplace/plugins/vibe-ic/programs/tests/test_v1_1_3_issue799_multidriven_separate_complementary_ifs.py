"""ORGANIC #799 (cross-ref #788) — rule_continuous_vs_procedural_driver
FALSE-FIRED `multidriven-continuous-procedural` when a net's continuous `assign`
and its procedural `always` write live in TWO SEPARATE single-arm generate-if
blocks whose conditions are structurally COMPLEMENTARY (`if(COND) begin:gen_a`
AND `if(!COND) begin:gen_b`) — NOT an if/else chain. iverilog -g2012 elaborates
exactly ONE arm (rc=0), so it is legitimate RTL.

INCOMPLETENESS, not a regression: #788's `_generate_if_arms` walked the if/ELSE
chain only, discarding each stand-alone one-arm group (`len(arms) >= 2` gate), so
the two drivers read as a same-scope race. FIX: pair stand-alone single-arm ifs
whose conditions are `_conditions_complementary` (`!COND` or `X==K`/`X!=K`).

This is a RELAXATION → §4.05 is load-bearing. DELIBERATELY only `!` (boolean
complement, any width) — bitwise `~COND` is EXCLUDED (a real multidriver). Any
non-complementary pair (`if(A)`/`if(B)`, `if(X==1)`/`if(X==2)`) STILL hard-blocks.

chip-AGNOSTIC: pure SV generate-if grammar; no chip literal.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import rtl_hygiene_lint as H  # noqa: E402

_LINT = PROGRAMS / "rtl_hygiene_lint.py"
_IV = shutil.which("iverilog")


def _ff(qcond):
    return ("always_ff @(posedge clk or negedge rst_n) "
            "if(!rst_n) qi<=1'b0; else qi<=d;")


_POS = """\
module pos #(parameter bit USE_FF=1)(input logic clk,rst_n,d,output logic q);
  logic qi;
  if (USE_FF)  begin : gen_a always_ff @(posedge clk or negedge rst_n) if(!rst_n) qi<=1'b0; else qi<=d; end
  if (!USE_FF) begin : gen_b assign qi = d; end
  assign q = qi;
endmodule
"""
_NEG1_IFELSE = """\
module neg1 #(parameter bit USE=1)(input logic clk,rst_n,d,output logic q);
  logic qi;
  if (USE) begin : gen_ff always_ff @(posedge clk or negedge rst_n) if(!rst_n) qi<=1'b0; else qi<=d; end
  else     begin : gen_comb assign qi = d; end
  assign q = qi;
endmodule
"""
_NEG2_RACE = """\
module neg2(input logic clk,rst_n,d,output logic q);
  logic qi; assign qi = d;
  always_ff @(posedge clk or negedge rst_n) if(!rst_n) qi<=1'b0; else qi<=d;
  assign q = qi;
endmodule
"""
_NEG3_NONCOMP = """\
module neg3 #(parameter bit A=1, parameter bit B=0)(input logic clk,rst_n,d,output logic q);
  logic qi;
  if (A) begin : gen_a always_ff @(posedge clk or negedge rst_n) if(!rst_n) qi<=1'b0; else qi<=d; end
  if (B) begin : gen_b assign qi = d; end
  assign q = qi;
endmodule
"""
_ADV_TILDE = """\
module advt #(parameter int EN=1)(input logic clk,rst_n,d,output logic q);
  logic qi;
  if (EN)  begin : gen_a always_ff @(posedge clk or negedge rst_n) if(!rst_n) qi<=1'b0; else qi<=d; end
  if (~EN) begin : gen_b assign qi = d; end
  assign q = qi;
endmodule
"""
_ADV_EQK = """\
module adveqk #(parameter int M=1)(input logic clk,rst_n,d,output logic q);
  logic qi;
  if (M==1) begin : gen_a always_ff @(posedge clk or negedge rst_n) if(!rst_n) qi<=1'b0; else qi<=d; end
  if (M==2) begin : gen_b assign qi = d; end
  assign q = qi;
endmodule
"""


def _rc(tmp_path, rtl):
    f = tmp_path / "d.sv"
    f.write_text(rtl)
    return subprocess.run(
        [sys.executable, str(_LINT), "--severity", "ERROR", str(f)],
        capture_output=True, text=True).returncode


# ── §4.05 load-bearing set: 1 POSITIVE + 3 NEGATIVE no-leak ─────────────────
def test_799_pos_complementary_standalone_ifs_no_false_fire(tmp_path):
    assert _rc(tmp_path, _POS) == 0


def test_799_neg1_ifelse_chain_unchanged(tmp_path):
    assert _rc(tmp_path, _NEG1_IFELSE) == 0


def test_799_neg2_genuine_same_scope_race_still_blocks(tmp_path):
    assert _rc(tmp_path, _NEG2_RACE) == 1


def test_799_neg3_noncomplementary_ifs_still_block(tmp_path):
    assert _rc(tmp_path, _NEG3_NONCOMP) == 1


# ── Step-2.7 adversarial: the leak-prone vectors must STILL hard-block ───────
def test_799_adv_bitwise_tilde_still_blocks(tmp_path):
    # ~EN is the BIT-complement: for a multi-bit operand both arms elaborate →
    # a GENUINE multidriver. Must NOT be paired as complementary.
    assert _rc(tmp_path, _ADV_TILDE) == 1


def test_799_adv_eq_different_constants_still_blocks(tmp_path):
    # M==1 and M==2 are NOT complementary (both can be false) → stay flagged.
    assert _rc(tmp_path, _ADV_EQK) == 1


# ── helper-level truth table ────────────────────────────────────────────────
@pytest.mark.parametrize("a,b,want", [
    ("USE_FF", "!USE_FF", True),
    ("!USE_FF", "USE_FF", True),
    ("USE", "!(USE)", True),
    ("X==1", "X!=1", True),
    ("X != 1", "X == 1", True),
    ("EN", "~EN", False),            # bitwise — NOT complementary
    ("M==1", "M==2", False),         # different constants
    ("A", "B", False),               # unrelated
    ("X==1", "Y!=1", False),         # different LHS
])
def test_799_conditions_complementary_truth_table(a, b, want):
    assert H._conditions_complementary(a, b) is want, (a, b)


@pytest.mark.skipif(not _IV, reason="iverilog unavailable")
def test_799_pos_genuinely_elaborates_single_arm(tmp_path):
    # prove the POSITIVE is a real false-fire: iverilog elaborates rc=0.
    f = tmp_path / "pos.sv"
    f.write_text(_POS)
    r = subprocess.run([_IV, "-g2012", "-o", str(tmp_path / "o"), str(f)],
                       capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout + r.stderr)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
