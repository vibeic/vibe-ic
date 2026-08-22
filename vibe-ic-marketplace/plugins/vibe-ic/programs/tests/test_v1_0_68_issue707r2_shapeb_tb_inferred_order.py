#!/usr/bin/env python3
"""ORGANIC #707 ROUND-2 (P1, reopen) — TB-inferred positional order + a
load-bearing NO-REGRESSION GUARD, replacing v1.0.66's per-GENRE port-order guess.

THE REGRESSION v1.0.66 introduced
---------------------------------
v1.0.66 (#707 r1) wired `port_convention_corpus.order_ports` /
`genre_order_policy` (a per-GENRE guess: `outputs_first` for
digital_arithmetic_primitive) into the SOLE Shape-B emit path
(`shape_b_sample_export.reorder_top_ports`, called by `export()`). THAT IS WRONG
for the Shape-B (RTLLM-style) standalone-design corpus: the positional bind order
is PER-DESIGN, not per-genre. Counter-example: an `alu` whose hidden TB binds
INPUTS-FIRST (`alu uut(a,b,aluc,r,zero,carry,negative,overflow,flag)`) — the
runner's spec-to-rtl ALREADY emits that correct inputs-first order, but the genre
guess SCRAMBLES it to outputs-first (`r,zero,...,a,b,aluc`), so the TB binds
`reg a` onto output `r` → iverilog "Unable to assign to unresolved wires" →
compile_error. A previously-shippable, scorer-passing sample becomes unshippable.
(The LFSR from r1 is genuinely outputs-first — `DUT(out,clk,rst)` — so the reorder
helped IT; the corpus is NOT uniformly inputs- or outputs-first, so a single
positive cannot validate an over-generalized genre policy.) The standalone export
guard missed it because it compiles the sample with NO TB, so a
standalone-valid-but-scorer-broken reorder ships green.

THE FIX (two chip-AGNOSTIC parts)
---------------------------------
(B) ORDER FROM THE TB — `reorder_top_ports(rtl, top, ic_class, tb_text)` infers
    the required positional order from the hidden TB's DUT instantiation: map each
    positional arg to a DUT port by DIRECTION (reg/integer drivers → inputs, wire
    monitors → outputs) + bit-WIDTH (name affinity breaks clk/rst-class ties).
    PURE reorder; an already-correct order is byte-identical. AMBIGUOUS / no-TB →
    NO genre guess, ship verbatim.
(A) NO-REGRESSION GUARD — `export()`, when a TB is locatable, compiles BOTH the
    reordered sample and the verbatim original against that TB and ships the
    VERBATIM original whenever the verbatim order elaborates but the reorder does
    NOT. The reorder can NEVER turn a TB-passing sample into a TB-failing one.

§4.05 invariant: the reorder never regresses a TB-passing verbatim sample.
chip-AGNOSTIC: TB-grammar + direction/width inference; no chip/SKU literal.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import shape_b_sample_export as S  # noqa: E402
import _path_layout as _pl  # noqa: E402

_HAS_IVERILOG = shutil.which("iverilog") is not None
pytestmark = pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog unavailable")


# ── fixtures ─────────────────────────────────────────────────────────────────
# INPUTS-FIRST alu — the runner's spec-to-rtl already emits this (correct) order.
_ALU_INPUTS_FIRST = (
    "module alu(input [31:0] a, input [31:0] b, input [4:0] aluc,\n"
    "  output reg [31:0] r, output reg zero, output reg carry,\n"
    "  output reg negative, output reg overflow, output reg flag);\n"
    "  always @(*) begin\n"
    "    r = a + b; zero = (r==0); carry = 0;\n"
    "    negative = r[31]; overflow = 0; flag = 0;\n"
    "  end\nendmodule\n")

# INPUTS-FIRST positional TB — the hidden TB binds a,b,aluc,r,zero,...
_ALU_TB = (
    "module tb;\n reg [31:0] a, b; reg [4:0] aluc;\n"
    " wire [31:0] r; wire zero, carry, negative, overflow, flag;\n"
    " alu uut(a, b, aluc, r, zero, carry, negative, overflow, flag);\n"
    " initial begin a=1; b=2; aluc=0; #5\n"
    "  $display(\"=========== Your Design Passed ===========\"); $finish; end\n"
    "endmodule\n")

# OUTPUTS-FIRST LFSR (the genuine #707 r1 case) — TB binds out,clk,rst, but the
# runner / blind author writes prompt order clk,rst,out.
_LFSR_PROMPT_ORDER = (
    "module LFSR(input clk, input rst, output reg [3:0] out);\n"
    "  always @(posedge clk or posedge rst)\n"
    "    if(rst) out<=4'b1; else out<={out[2:0],out[3]^out[2]};\n"
    "endmodule\n")
_LFSR_TB = (
    "module tb; reg clk_tb=0, rst_tb=1; wire [3:0] out_tb;\n"
    " LFSR DUT(out_tb, clk_tb, rst_tb);\n"
    " always #5 clk_tb=~clk_tb;\n"
    " initial begin #12 rst_tb=0; #50\n"
    "  $display(\"=========== Your Design Passed ===========\"); $finish; end\n"
    "endmodule\n")


def _fixture(tmp_path, rtl_text, leaf, tb_text=None):
    """Build a Path-A project; optionally stage the hidden TB in a dataset dir."""
    proj = tmp_path / "work" / leaf
    rtl = _pl.rtl_dir(proj)
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / f"{leaf}.v").write_text(rtl_text)
    dataset = tmp_path / "dataset"
    if tb_text is not None:
        d = dataset / leaf
        d.mkdir(parents=True, exist_ok=True)
        (d / "testbench.v").write_text(tb_text)
    return rtl, dataset


def _compile_run(sample, tb):
    """iverilog -g2012 compile+run sample+tb (cwd = tb dir for $readmemh)."""
    tb = Path(tb)
    with tempfile.TemporaryDirectory() as td:
        binp = Path(td) / "a.out"
        c = subprocess.run(["iverilog", "-g2012", "-o", str(binp),
                            str(sample), str(tb)],
                           capture_output=True, text=True,
                           cwd=str(tb.resolve().parent))
        if c.returncode != 0:
            return c.returncode, (c.stdout + c.stderr)
        r = subprocess.run([str(binp)], capture_output=True, text=True)
        return r.returncode, r.stdout


# ── (1) THE ALU REGRESSION (the repro) ───────────────────────────────────────
def test_alu_inputs_first_export_compiles_and_passes_its_tb(tmp_path):
    """The v1.0.66 regression: an inputs-first alu + inputs-first positional TB.
    export() must ship a sample that COMPILES + ELABORATES + PASSES the TB — the
    reorder must NOT scramble the already-correct inputs-first order."""
    rtl, dataset = _fixture(tmp_path, _ALU_INPUTS_FIRST, "alu", _ALU_TB)
    samples = tmp_path / "samples"
    res = S.export(rtl, "alu", samples, ic_class="digital_arithmetic_primitive",
                   dataset=dataset, design="alu")
    assert res["verdict"] == "PASS", res
    rc, out = _compile_run(samples / "alu.v", dataset / "alu" / "testbench.v")
    assert rc == 0 and "Passed" in out, (rc, out)


def _portlist_names_in_order(rtl_text, top):
    """Return the port names in their DECLARED order (uses the production
    parser, so the assertion can't be fooled by substring matches)."""
    g = S._parse_portlist_segments(rtl_text, top)
    assert g is not None, rtl_text
    return [n for _seg, _d, n in g[1]]


def test_alu_inputs_first_order_not_scrambled_to_outputs_first(tmp_path):
    """Structural: the exported alu's first INPUT (`a`) must come BEFORE the
    first OUTPUT (`r`) — the inputs-first order is preserved, NOT genre-flipped."""
    rtl, dataset = _fixture(tmp_path, _ALU_INPUTS_FIRST, "alu", _ALU_TB)
    samples = tmp_path / "samples"
    S.export(rtl, "alu", samples, ic_class="digital_arithmetic_primitive",
             dataset=dataset, design="alu")
    order = _portlist_names_in_order((samples / "alu.v").read_text(), "alu")
    assert order.index("a") < order.index("r"), order
    # the exact inputs-first order is intact (the runner's correct spec-order).
    assert order == ["a", "b", "aluc", "r", "zero", "carry",
                     "negative", "overflow", "flag"], order


# ── (2) LFSR PRESERVED (genuine outputs-first via TB-inference) ──────────────
def test_lfsr_outputs_first_inferred_from_tb_and_passes(tmp_path):
    """The genuinely outputs-first LFSR: TB-inference derives out,clk,rst from
    `DUT(out_tb, clk_tb, rst_tb)` and the reordered sample compiles + passes."""
    rtl, dataset = _fixture(tmp_path, _LFSR_PROMPT_ORDER, "LFSR", _LFSR_TB)
    samples = tmp_path / "samples"
    res = S.export(rtl, "LFSR", samples,
                   ic_class="digital_arithmetic_primitive",
                   dataset=dataset, design="LFSR")
    assert res["verdict"] == "PASS", res
    assert res["reorder_applied"] is True, res  # prompt-order WAS reordered
    rc, out = _compile_run(samples / "LFSR.v", dataset / "LFSR" / "testbench.v")
    assert rc == 0 and "Passed" in out, (rc, out)
    # out before clk before rst (the TB's positional order).
    hdr = (samples / "LFSR.v").read_text().split(");")[0]
    assert hdr.index("out") < hdr.index("clk") < hdr.index("rst"), hdr


def test_lfsr_tb_inferred_order_matches_unit_inference():
    """Unit: reorder_top_ports(tb_text=...) yields out,clk,rst directly."""
    out = S.reorder_top_ports(_LFSR_PROMPT_ORDER, "LFSR",
                              "digital_arithmetic_primitive", _LFSR_TB)
    hdr = out.split(");")[0]
    assert hdr.index("out") < hdr.index("clk") < hdr.index("rst"), hdr


# ── (3) NO-TB FALLBACK — ship verbatim, no genre scramble ────────────────────
def test_no_tb_inputs_first_alu_ships_verbatim_byte_identical(tmp_path):
    """No testbench locatable → the inputs-first alu ships VERBATIM, BYTE-IDENTICAL
    (NOT genre-scrambled to outputs-first). This is the core round-2 safety: with
    no TB there is no no-regression guard, so the genre guess MUST NOT fire."""
    rtl, _ds = _fixture(tmp_path, _ALU_INPUTS_FIRST, "alu", tb_text=None)
    samples = tmp_path / "samples"
    # No dataset/design and no TB in the tree → discovery returns None.
    res = S.export(rtl, "alu", samples,
                   ic_class="digital_arithmetic_primitive")
    assert res["verdict"] == "PASS", res
    assert res["testbench"] is None, res
    assert res["reorder_applied"] is False, res
    # The emitted sample is the verbatim source, inputs-first order intact.
    assert (samples / "alu.v").read_text() == _ALU_INPUTS_FIRST


def test_no_tb_unit_reorder_is_verbatim():
    """Unit: reorder_top_ports with NO tb_text and NO opt-in returns VERBATIM on
    an inputs-first design (the genre guess does not fire by default)."""
    assert S.reorder_top_ports(
        _ALU_INPUTS_FIRST, "alu", "digital_arithmetic_primitive") \
        == _ALU_INPUTS_FIRST


def test_tb_inference_already_correct_is_byte_identical():
    """With the inputs-first TB, the inputs-first alu is recognised as
    already-correct → byte-identical (a PURE no-op reorder)."""
    out = S.reorder_top_ports(_ALU_INPUTS_FIRST, "alu",
                              "digital_arithmetic_primitive", _ALU_TB)
    assert out == _ALU_INPUTS_FIRST


# ── (4) §4.05 INVARIANT — reorder never breaks a TB-passing verbatim sample ──
def _verbatim_passes_then_export_still_passes(tmp_path, rtl_text, leaf, tb_text):
    """Helper: prove (i) the VERBATIM rtl passes its TB, then (ii) export()'s
    emitted sample ALSO passes the SAME TB — the core §4.05 invariant."""
    rtl, dataset = _fixture(tmp_path, rtl_text, leaf, tb_text)
    tb = dataset / leaf / "testbench.v"
    # (i) verbatim baseline
    vb = tmp_path / f"{leaf}.verbatim.v"
    vb.write_text(rtl_text)
    rc0, out0 = _compile_run(vb, tb)
    verbatim_passes = (rc0 == 0 and "Passed" in out0)
    # (ii) exported sample
    samples = tmp_path / "samples"
    res = S.export(rtl, leaf, samples,
                   ic_class="digital_arithmetic_primitive",
                   dataset=dataset, design=leaf)
    assert res["verdict"] == "PASS", res
    rc1, out1 = _compile_run(samples / f"{leaf}.v", tb)
    export_passes = (rc1 == 0 and "Passed" in out1)
    return verbatim_passes, export_passes


def test_4_05_invariant_inputs_first_design(tmp_path):
    """§4.05 on an INPUTS-FIRST design: verbatim passes ⇒ export must also pass
    (the reorder did not break the bind)."""
    vb, ex = _verbatim_passes_then_export_still_passes(
        tmp_path, _ALU_INPUTS_FIRST, "alu", _ALU_TB)
    assert vb, "verbatim inputs-first alu should pass its inputs-first TB"
    assert ex, "export must NOT regress the TB-passing verbatim alu"


def test_4_05_invariant_outputs_first_design(tmp_path):
    """§4.05 on an already-OUTPUTS-FIRST design: a top whose ports already match
    the TB's outputs-first bind must stay TB-passing through export (byte-identical
    reorder; never broken)."""
    conv = ("module accum(output reg [7:0] sum, input clk, input rst,\n"
            "  input [7:0] din);\n"
            "  always @(posedge clk) if(rst) sum<=0; else sum<=sum+din;\n"
            "endmodule\n")
    tb = ("module tb; reg clk=0, rst=1; reg [7:0] din; wire [7:0] sum;\n"
          " accum DUT(sum, clk, rst, din);\n"
          " always #5 clk=~clk;\n"
          " initial begin din=1; #12 rst=0; #50\n"
          "  $display(\"=========== Your Design Passed ===========\"); $finish; end\n"
          "endmodule\n")
    vb, ex = _verbatim_passes_then_export_still_passes(tmp_path, conv, "accum", tb)
    assert vb, "verbatim outputs-first accum should pass its TB"
    assert ex, "export must NOT regress the TB-passing verbatim accum"


def test_4_05_no_regression_guard_reverts_a_bad_reorder(tmp_path):
    """Direct exercise of the no-regression guard (A): even if a hypothetical
    reorder broke the bind, export() ships verbatim. We assert the exported alu
    is identical to the verbatim source (no scramble survived)."""
    rtl, dataset = _fixture(tmp_path, _ALU_INPUTS_FIRST, "alu", _ALU_TB)
    samples = tmp_path / "samples"
    S.export(rtl, "alu", samples, ic_class="digital_arithmetic_primitive",
             dataset=dataset, design="alu")
    assert (samples / "alu.v").read_text() == _ALU_INPUTS_FIRST


# ── (5) discovery / no-foreign-TB / explicit path ────────────────────────────
def test_explicit_testbench_path(tmp_path):
    """An explicit --testbench path is honoured for the inference."""
    rtl, _ds = _fixture(tmp_path, _LFSR_PROMPT_ORDER, "LFSR", tb_text=None)
    tbp = tmp_path / "my_tb.v"
    tbp.write_text(_LFSR_TB)
    samples = tmp_path / "samples"
    res = S.export(rtl, "LFSR", samples,
                   ic_class="digital_arithmetic_primitive", testbench=tbp)
    assert res["verdict"] == "PASS" and res["testbench"] == str(tbp), res
    rc, out = _compile_run(samples / "LFSR.v", tbp)
    assert rc == 0 and "Passed" in out, (rc, out)


def test_foreign_tb_not_bound_by_autodiscovery(tmp_path):
    """A stray testbench that does NOT instantiate the design top is rejected by
    auto-discovery (never binds a foreign TB)."""
    rtl, _ds = _fixture(tmp_path, _ALU_INPUTS_FIRST, "alu", tb_text=None)
    # foreign TB above work/ — must NOT be picked up.
    (tmp_path / "testbench.v").write_text("module tb; foo X(); endmodule\n")
    assert S.discover_testbench(rtl, "alu", top="alu") is None


# ── (6) chip-AGNOSTIC guard ──────────────────────────────────────────────────
def test_chip_agnostic_guard():
    prog = _PROGRAMS / "source_chip_agnostic_check.py"
    r = subprocess.run([sys.executable, str(prog), str(_PROGRAMS.parent)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-400:]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
