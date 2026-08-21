#!/usr/bin/env python3
"""Tests for rtl_hygiene_lint.py Rule 17 (width-expand / width-trunc value-
identical cast + auto-`--fix`) and Rule 18 (unused clock-input port).

Both rules are CORPUS-CLEAN additions (zero false-positives on the
run_clean_v1252 drafts). These tests pin:
  * a PASS case (clean RTL, no finding) for each rule;
  * the real defect each rule guards (it fires);
  * a VALUE-IDENTICAL `--fix` assertion for Rule 17 (the inserted size cast must
    not change behaviour — verified by parsing the patched RHS and, when
    iverilog is available, by simulating original vs patched on the same
    stimulus).
"""
from __future__ import annotations
import re
import shutil
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "rtl_hygiene_lint.py"


def _run(args, **kw):
    return subprocess.run([sys.executable, str(PROG)] + args,
                          capture_output=True, text=True, **kw)


# ---------------------------------------------------------------------------
# Rule 17a — WIDTHEXPAND accumulator (narrower operand into a wider accumulator)
# ---------------------------------------------------------------------------
_EXPAND_DEFECT = """module acc12 (input clk, input rst_n, input [7:0] din,
                              output reg [11:0] acc);
  always @(posedge clk)
    if (!rst_n) acc <= 12'd0;
    else        acc <= acc + din;
endmodule
"""

# Same-width accumulator: NO implicit extension -> must stay silent.
_EXPAND_CLEAN = """module acc8 (input clk, input rst_n, input [7:0] din,
                             output reg [7:0] acc);
  always @(posedge clk)
    if (!rst_n) acc <= 8'd0;
    else        acc <= acc + din;
endmodule
"""


def test_rule17_expand_fires_on_defect(tmp_path):
    f = tmp_path / "acc12.sv"
    f.write_text(_EXPAND_DEFECT)
    r = _run(["--severity", "INFO", str(f)])
    assert "width-expand" in r.stdout
    assert "12'(din)" in r.stdout  # the value-identical cast it would insert


def test_rule17_expand_clean_no_finding(tmp_path):
    f = tmp_path / "acc8.sv"
    f.write_text(_EXPAND_CLEAN)
    r = _run(["--severity", "INFO", str(f)])
    assert "width-expand" not in r.stdout


def test_rule17_expand_fix_is_value_identical(tmp_path):
    f = tmp_path / "acc12.sv"
    f.write_text(_EXPAND_DEFECT)
    fr = _run(["--fix", str(f)])
    assert fr.returncode == 0
    patched = f.read_text()
    # The addend is now explicitly cast to the accumulator width; behaviour
    # (a pure zero-extend) is unchanged.
    assert re.search(r"acc\s*<=\s*acc\s*\+\s*12'\(din\)\s*;", patched)
    # idempotent: a second --fix inserts nothing more.
    fr2 = _run(["--fix", str(f)])
    assert "inserted 0 value-identical width cast(s)" in fr2.stdout


# ---------------------------------------------------------------------------
# Rule 17b — WIDTHTRUNC arithmetic (mult/mod result into a narrower reg)
# ---------------------------------------------------------------------------
_TRUNC_DEFECT = """module mul (input clk, input [15:0] a, input [15:0] b,
                            output reg [7:0] p);
  initial p = 0;
  always @(posedge clk) p <= a * b;
endmodule
"""

# Same-width operands: verilator generates max(Wa,Wb)==8 bits -> no truncation.
_TRUNC_CLEAN = """module mul8 (input clk, input [7:0] a, input [7:0] b,
                             output reg [7:0] p);
  initial p = 0;
  always @(posedge clk) p <= a * b;
endmodule
"""


def test_rule17_trunc_fires_on_defect(tmp_path):
    f = tmp_path / "mul.sv"
    f.write_text(_TRUNC_DEFECT)
    r = _run(["--severity", "INFO", str(f)])
    assert "width-trunc-arith" in r.stdout
    assert "8'(a * b)" in r.stdout


def test_rule17_trunc_clean_no_finding(tmp_path):
    f = tmp_path / "mul8.sv"
    f.write_text(_TRUNC_CLEAN)
    r = _run(["--severity", "INFO", str(f)])
    assert "width-trunc-arith" not in r.stdout


def test_rule17_trunc_fix_is_value_identical(tmp_path):
    f = tmp_path / "mul.sv"
    f.write_text(_TRUNC_DEFECT)
    _run(["--fix", str(f)])
    patched = f.read_text()
    assert re.search(r"p\s*<=\s*8'\(a \* b\)\s*;", patched)


def test_rule17_fix_simulates_identically(tmp_path):
    """Strong value-identity proof: drive the original and the --fixed module
    with identical random stimulus and assert bit-for-bit equality every cycle.
    Skipped when iverilog is unavailable."""
    iv = shutil.which("iverilog")
    vvp = shutil.which("vvp")
    if not iv or not vvp:
        import pytest
        pytest.skip("iverilog/vvp not available")
    orig = tmp_path / "orig.sv"
    orig.write_text(_TRUNC_DEFECT.replace("module mul ", "module orig "))
    fixed = tmp_path / "fixed.sv"
    fixed.write_text(_TRUNC_DEFECT.replace("module mul ", "module fixed "))
    _run(["--fix", str(fixed)])
    tb = tmp_path / "tb.sv"
    tb.write_text(
        "module tb;\n"
        "  reg clk=0; reg [15:0] a,b; wire [7:0] p,pf; integer i,fails=0;\n"
        "  orig  u0(.clk(clk),.a(a),.b(b),.p(p));\n"
        "  fixed u1(.clk(clk),.a(a),.b(b),.p(pf));\n"
        "  always #5 clk=~clk;\n"
        "  initial begin\n"
        "    for(i=0;i<2000;i=i+1) begin a=$random;b=$random;@(posedge clk);#1;\n"
        "      if(p!==pf) fails=fails+1; end\n"
        "    if(fails==0) $display(\"EQUIV_PASS\"); else $display(\"EQUIV_FAIL\");\n"
        "    $finish; end\n"
        "endmodule\n")
    vvp_out = tmp_path / "s.vvp"
    c = subprocess.run([iv, "-g2012", "-o", str(vvp_out), str(orig),
                        str(fixed), str(tb)], capture_output=True, text=True)
    assert c.returncode == 0, c.stderr
    s = subprocess.run([vvp, str(vvp_out)], capture_output=True, text=True)
    assert "EQUIV_PASS" in s.stdout and "EQUIV_FAIL" not in s.stdout


# ---------------------------------------------------------------------------
# Rule 18 — unused clock-input port (single-clock module with sequential logic)
# ---------------------------------------------------------------------------
# Genuine wiring bug: the lone declared clock `clk` is never referenced; the
# flip-flops are clocked by a data signal (`enable`) instead.
_CLK_DEFECT = """module wrong_clk (input clk, input enable, input rst_n,
                                 input [7:0] d, output reg [7:0] q);
  always @(posedge enable or negedge rst_n)
    if (!rst_n) q <= 8'd0; else q <= d;
endmodule
"""

# Correct: the clock drives the flops.
_CLK_CLEAN = """module good_clk (input clk, input rst_n, input [7:0] d,
                                output reg [7:0] q);
  always @(posedge clk or negedge rst_n)
    if (!rst_n) q <= 8'd0; else q <= d;
endmodule
"""

# Purely combinational single-clock module: clk legitimately unused -> silent.
_CLK_COMB = """module comb (input clk, input [7:0] a, input [7:0] b,
                            output [7:0] y);
  assign y = a ^ b;
endmodule
"""

# Multi-clock CDC block: a secondary clock legitimately unused -> silent.
_CLK_MULTI = """module cdc (input clk_src, input clk_dst, input [7:0] d,
                           output reg [7:0] q);
  always @(posedge clk_dst) q <= d;
endmodule
"""


def test_rule18_fires_on_wiring_bug(tmp_path):
    f = tmp_path / "wrong_clk.sv"
    f.write_text(_CLK_DEFECT)
    r = _run(["--severity", "INFO", str(f)])
    assert "unused-clock-input" in r.stdout
    assert "`clk`" in r.stdout


def test_rule18_clean_clock_used(tmp_path):
    f = tmp_path / "good_clk.sv"
    f.write_text(_CLK_CLEAN)
    r = _run(["--severity", "INFO", str(f)])
    assert "unused-clock-input" not in r.stdout


def test_rule18_combinational_module_silent(tmp_path):
    f = tmp_path / "comb.sv"
    f.write_text(_CLK_COMB)
    r = _run(["--severity", "INFO", str(f)])
    assert "unused-clock-input" not in r.stdout


def test_rule18_multiclock_cdc_silent(tmp_path):
    f = tmp_path / "cdc.sv"
    f.write_text(_CLK_MULTI)
    r = _run(["--severity", "INFO", str(f)])
    assert "unused-clock-input" not in r.stdout


def test_rule18_is_advisory_nonblocking(tmp_path):
    """The unused-clock finding is advisory (non-blocking): at --severity ERROR
    it must not trip rc=1 on its own."""
    f = tmp_path / "wrong_clk.sv"
    f.write_text(_CLK_DEFECT)
    r = _run(["--severity", "ERROR", str(f)])
    assert r.returncode == 0


# ---------------------------------------------------------------------------
# Rule 17b extension — parenthesised mult/mod RHS (`r <= (a % m);`)
# ---------------------------------------------------------------------------
def test_rule17_paren_mod_fires_and_fixes(tmp_path):
    f = tmp_path / "pmod.sv"
    f.write_text(
        "module pmod (input clk, input [15:0] a, input [15:0] m,\n"
        "             output reg [7:0] r);\n"
        "  initial r = 0;\n"
        "  always @(posedge clk) r <= (a % m);\n"
        "endmodule\n")
    r = _run(["--severity", "INFO", str(f)])
    assert "width-trunc-arith" in r.stdout
    _run(["--fix", str(f)])
    assert re.search(r"r\s*<=\s*\(?8'\(a % m\)", f.read_text())


# ---------------------------------------------------------------------------
# Rule 19 — bitwise-NOT width-expand
# ---------------------------------------------------------------------------
_NOT_DEFECT = """module m (input [7:0] x8, input [3:0] y4, input clk, output reg eq,
                          output reg [7:0] o8);
  always @(posedge clk) begin
    eq <= (x8 == ~y4);
    o8 <= ~y4;
  end
endmodule
"""

# Same-width complement: no expansion -> silent.
_NOT_CLEAN = """module m (input [7:0] x8, input [7:0] z8, input clk, output reg eq);
  always @(posedge clk) eq <= (x8 == ~z8);
endmodule
"""


def test_rule19_not_width_fires(tmp_path):
    f = tmp_path / "notd.sv"
    f.write_text(_NOT_DEFECT)
    r = _run(["--severity", "INFO", str(f)])
    assert "bitwise-not-width" in r.stdout
    assert r.stdout.count("bitwise-not-width") >= 2  # comparison + assignment


def test_rule19_not_width_clean(tmp_path):
    f = tmp_path / "notc.sv"
    f.write_text(_NOT_CLEAN)
    r = _run(["--severity", "INFO", str(f)])
    assert "bitwise-not-width" not in r.stdout


# ---------------------------------------------------------------------------
# Rule 21 — enum-ternary base-type assigned to a narrower target
# ---------------------------------------------------------------------------
_ENUM_DEFECT = """typedef enum logic [3:0] { IDLE, RUN, STOP } st_t;
module m (input c, input clk, output reg [1:0] sel);
  always @(posedge clk) sel <= c ? RUN : STOP;
endmodule
"""

_ENUM_CLEAN = """typedef enum logic [3:0] { IDLE, RUN, STOP } st_t;
module m (input c, input clk, output reg [3:0] sel);
  always @(posedge clk) sel <= c ? RUN : STOP;
endmodule
"""


def test_rule21_enum_ternary_fires(tmp_path):
    f = tmp_path / "ed.sv"
    f.write_text(_ENUM_DEFECT)
    r = _run(["--severity", "INFO", str(f)])
    assert "enum-ternary-width" in r.stdout


def test_rule21_enum_ternary_clean(tmp_path):
    f = tmp_path / "ec.sv"
    f.write_text(_ENUM_CLEAN)
    r = _run(["--severity", "INFO", str(f)])
    assert "enum-ternary-width" not in r.stdout


# ---------------------------------------------------------------------------
# Rule 22 — mixed blocking / non-blocking to the SAME reg in a clocked block
# ---------------------------------------------------------------------------
# Genuine mix: `q` reset with `<=` then computed with `=` in one posedge block.
_MIX_DEFECT = """module m (input clk, input rst, input [7:0] d, output reg [7:0] q);
  always @(posedge clk) begin
    if (rst) q <= 8'd0;
    else begin
      q = d;
      q = q + 8'd1;
    end
  end
endmodule
"""

# Legit blocking-temp idiom (DIFFERENT names) -> silent.
_MIX_CLEAN_TEMP = """module m (input clk, input [7:0] a, input [7:0] b,
                              output reg [7:0] q);
  reg [7:0] tmp;
  always @(posedge clk) begin
    tmp = a & b;
    q <= tmp | 8'h01;
  end
endmodule
"""

# Genvar / comparison `<=` in a loop bound must NOT be mistaken for an NBA write.
_MIX_CLEAN_LOOPBOUND = """module m (input clk, output reg [7:0] acc);
  integer gl;
  always @(posedge clk) begin
    acc = 8'd0;
    for (gl = 1; gl <= 8; gl = gl + 1) acc = acc + gl[7:0];
  end
endmodule
"""


def test_rule22_mixed_fires(tmp_path):
    f = tmp_path / "mixd.sv"
    f.write_text(_MIX_DEFECT)
    r = _run(["--severity", "INFO", str(f)])
    assert "mixed-blocking-nonblocking" in r.stdout
    assert "`q`" in r.stdout


def test_rule22_blocking_temp_idiom_silent(tmp_path):
    f = tmp_path / "mixt.sv"
    f.write_text(_MIX_CLEAN_TEMP)
    r = _run(["--severity", "INFO", str(f)])
    assert "mixed-blocking-nonblocking" not in r.stdout


def test_rule22_loopbound_comparison_silent(tmp_path):
    """`gl <= 8` is a loop bound (comparison), not an NBA write — must not be
    mistaken for a mixed blocking/non-blocking assignment to `gl`."""
    f = tmp_path / "mixl.sv"
    f.write_text(_MIX_CLEAN_LOOPBOUND)
    r = _run(["--severity", "INFO", str(f)])
    assert "mixed-blocking-nonblocking" not in r.stdout
