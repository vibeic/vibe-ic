#!/usr/bin/env python3
"""ORGANIC #707 ROUND-3 (P1, field-agent reopen) — SCORE-SIDE pure-permutation
port rescue, moving the #707 reorder off the WRONG side of the blindness boundary.

THE ARCHITECTURAL DEFECT r2 left open
-------------------------------------
#707's positional-TB port reorder lived in the EXPORT step
(`programs/shape_b_sample_export.py`). r2 made the exporter INFER the order from
the hidden `testbench.v` — but at blind AUTHORING time the TB is FORBIDDEN, and the
canonical `benchmark/benchmark_dispatch.py` step-3b export invocation passes NO
`--testbench`/`--dataset`, so the inference path NEVER fires in the real flow and
the exporter ships the candidate VERBATIM. The Shape-B (RTLLM-style) corpus binds
positionally PER-DESIGN (an `alu` TB is inputs-first, an `LFSR` TB is
outputs-first), so NO authoring-side policy can satisfy both — r1's outputs-first
guess broke `alu`, r2's verbatim default breaks `LFSR`.

THE FIX (this test pins it) — round-3 HARDENED (Lens-1 leak fix)
---------------------------------------------------------------
The reorder moves SCORE-SIDE — the methodology-sanctioned place to touch the hidden
corpus (the scorer already touches it via `_power_up_fixed` / `_aliased_golden_srcs`
/ `_golden_ref_compiles_with_tb_shape_b`). On a Shape-B `reason=='compile_error'`,
`score_iverilog_tb._score_side_port_permutation_rescue_shape_b` attempts a PURE
PERMUTATION of the candidate's port-declaration list and adopts a PASS only if the
permuted candidate now passes.

THE LENS-1 LEAK an earlier draft had (this test now pins it CLOSED): the target
order was inferred FROM THE TB by direction+width with name-affinity as the ONLY
tie-break. For a non-commutative op with two SAME-WIDTH SAME-DIRECTION operands
(`gt = a > b`), a TB whose driver-net names (`a_tb`/`b_tb`) carry affinity that
CONTRADICTS the positional ground truth let a WRONG-operand candidate (`gt = b > a`)
be bound so the TB pass-marker fired → a wrong submission rescued to PASS.

THE HARDENING: the target order is now the GOLDEN's port-DECLARATION order, matched
by port NAME (NO TB-net-affinity, NO width guessing for ordering). The golden
`verified_<X>.v` compiles AND passes the TB POSITIONALLY, so its declaration order
IS the correct positional bind order (ground truth); a spec-faithful candidate
shares the spec's port NAMES with the golden. The wrong-operand `gt = b > a`
candidate permutes to the golden NAME order (a,b,gt), and its WRONG LOGIC still
RUNTIME-FAILs → NOT rescued.

§4.05 NEGATIVE-NO-LEAK (load-bearing — this RELAXES a guard: compile_error → PASS)
---------------------------------------------------------------------------------
This test proves BOTH halves:
  POSITIVE — an inputs-first functionally-correct LFSR + an outputs-first
    positional TB + an outputs-first golden → permutation re-maps to the golden's
    NAME order, recompiles, FLIPS compile_error → PASS.
  NEGATIVE — a pure permutation must NEVER rescue a wrong submission:
    * LENS-1 LEAK (the one that slipped through): a non-commutative `gt = b > a`
      candidate + a deceptive-affinity TB (driver `a_tb` positionally on the
      golden's `b` slot) → permute to golden NAME order is no-op/RUNTIME-FAILs →
      STAYS FAIL (the spec-faithful `gt = a > b` PASSes).
    * PORT-NAME-MISMATCH — a candidate using different port names than the golden →
      name-set mismatch → REFUSE (stays FAIL).
    * MISSING a port → name-set mismatch → REFUSE → stays compile_error FAIL.
    * EXTRA a port → name-set mismatch → REFUSE → stays FAIL.
    * WRONG-WIDTH port → name set matches but the permuted recompile still errors
      (width incompatible with the TB net) → stays FAIL.
    * WRONG LOGIC but correct ports → permutation compiles but RUNTIME-FAILs (a
      discriminating reference-model TB) → stays FAIL.
    * golden+TB does NOT elaborate (dataset defect) → permutation NOT attempted;
      the #690 dataset_defect annotation path is unchanged.
  REGRESSION — an inputs-first `alu` + inputs-first positional TB still PASSES the
    normal path (the rescue never even runs because the verbatim bind compiles).
  NAMED-BINDING — a `.clk(clk_tb)` TB → no positional arg list → no permutation.

chip-AGNOSTIC: structural Verilog grammar + registry layout only.
"""
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent
_BENCH = _PLUGIN / "benchmark"
for _p in (str(_PROGRAMS), str(_BENCH)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import score_iverilog_tb as SC  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_HAS_IVERILOG = shutil.which("iverilog") is not None
pytestmark = pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog unavailable")

# ── faithful Shape-B (RTLLM-style) fixture ───────────────────────────────────
# The spec lists Input ports clk,rst then Output ports out (Module name: LFSR).
_SPEC = ("Module name:\nLFSR\n\n"
         "Input ports:\n  clk: clock\n  rst: synchronous-style reset\n"
         "Output ports:\n  out: 4-bit LFSR state\n")

# OUTPUTS-FIRST positional TB — instantiates `LFSR DUT(out_tb, clk_tb, rst_tb)`.
# Self-checking via an INTERNAL reference model (taps out[3]^out[2]) so a
# wrong-LOGIC candidate diverges and prints "Your Design Failed" — i.e. the TB is
# DISCRIMINATING (a wrong-logic permute cannot fake a PASS).
_TB_OUTPUTS_FIRST = (
    "module testbench;\n"
    "  reg clk_tb=0, rst_tb=1;\n"
    "  wire [3:0] out_tb;\n"
    "  reg  [3:0] model;\n"
    "  integer errs=0, i;\n"
    "  LFSR DUT(out_tb, clk_tb, rst_tb);\n"
    "  always #5 clk_tb = ~clk_tb;\n"
    "  always @(posedge clk_tb or posedge rst_tb)\n"
    "    if (rst_tb) model <= 4'b0001;\n"
    "    else model <= {model[2:0], model[3]^model[2]};\n"
    "  initial begin\n"
    "    #12 rst_tb = 0;\n"
    "    for (i=0;i<8;i=i+1) begin\n"
    "      @(posedge clk_tb); #1;\n"
    "      if (out_tb !== model) errs = errs + 1;\n"
    "    end\n"
    "    if (errs==0) $display(\"=========== Your Design Passed ===========\");\n"
    "    else $display(\"Your Design Failed: %0d mismatches\", errs);\n"
    "    $finish;\n"
    "  end\n"
    "endmodule\n")

# OUTPUTS-FIRST golden that PASSES the TB above (same reset + taps as `ref`).
_GOLDEN_OUTPUTS_FIRST = (
    "module LFSR(output reg [3:0] out, input clk, input rst);\n"
    "  always @(posedge clk or posedge rst)\n"
    "    if (rst) out <= 4'b0001;\n"
    "    else out <= {out[2:0], out[3]^out[2]};\n"
    "endmodule\n")

# CANDIDATE, INPUTS-FIRST `(clk, rst, out)`, FUNCTIONALLY CORRECT (matches golden
# logic). Positionally the TB binds out_tb(wire)->clk(input) etc → compile_error.
# A pure permutation to outputs-first makes it byte-equivalent to the golden.
_CAND_CORRECT_INPUTS_FIRST = (
    "module LFSR(input clk, input rst, output reg [3:0] out);\n"
    "  always @(posedge clk or posedge rst)\n"
    "    if (rst) out <= 4'b0001;\n"
    "    else out <= {out[2:0], out[3]^out[2]};\n"
    "endmodule\n")

_LAYOUT = {
    "tb_filename": "testbench.v",
    "ref_glob": "verified_*.v",
    "prompt_filename": "design_description.txt",
    "module_name_strategy": "from_description_module_name_line",
}
_ARGS = {
    "pass_regex": "Your Design Passed",
    "fail_regex": "Test failed|Your Design Failed",
    "cwd_design_dir": True,
}


def _build_run(tmp_path, candidate, golden=_GOLDEN_OUTPUTS_FIRST,
               tb=_TB_OUTPUTS_FIRST, spec=_SPEC, design="LFSR"):
    """Assemble a faithful Shape-B layout:
      dataset/<design>/{design_description.txt, testbench.v, verified_<design>.v}
      run/samples/<design>.v  (the candidate)
    Returns (design, samples_dir, dataset_dir)."""
    dataset = tmp_path / "dataset"
    dd = dataset / design
    dd.mkdir(parents=True, exist_ok=True)
    (dd / "design_description.txt").write_text(spec)
    (dd / "testbench.v").write_text(tb)
    (dd / f"verified_{design}.v").write_text(golden)
    samples = tmp_path / "run" / "samples"
    samples.mkdir(parents=True, exist_ok=True)
    (samples / f"{design}.v").write_text(candidate)
    return design, samples, dataset


def _score(tmp_path, candidate, **kw):
    design, samples, dataset = _build_run(tmp_path, candidate, **kw)
    return SC._score_shape_b(design, samples, dataset, _LAYOUT, _ARGS)


# A correct candidate with a positional-TB port-order mismatch is now resolved by
# the ORGANIC #742 FACET A PROACTIVE normalization (the port reorder fires BEFORE
# the first compile), so the verdict is a clean PASS with NO `recovered_via_*`
# reason. The reactive score-side rescue here (#707-r3) remains the BACKSTOP for
# cases the proactive normalize cannot reach, and the §4.05 NEGATIVE no-leak tests
# below still exercise it. So the POSITIVE assertions accept EITHER the proactive
# clean pass (reason absent) OR the reactive rescue reason.
_RESCUE_REASON = "recovered_via_scoreside_port_permutation"


def _passed_via_reorder(res) -> bool:
    return res.get("verdict") == "PASS" and res.get("reason") in (
        None, _RESCUE_REASON)


# ── POSITIVE — the reorder flips compile_error → PASS (proactive or reactive) ─
def test_positive_inputs_first_correct_candidate_rescued_to_pass(tmp_path):
    """An inputs-first functionally-correct LFSR + outputs-first positional TB +
    an outputs-first passing golden: the verbatim positional bind COMPILE-ERRORs,
    a pure permutation to outputs-first makes it PASS — proactively (#742, BEFORE
    the first compile, no reason) or reactively (#707-r3 rescue)."""
    res = _score(tmp_path, _CAND_CORRECT_INPUTS_FIRST)
    assert _passed_via_reorder(res), res


def test_positive_helper_returns_pass_directly(tmp_path):
    """Direct unit on the rescue helper: it returns a PASS dict for the correct
    candidate (the integration point's contract)."""
    design, samples, dataset = _build_run(tmp_path, _CAND_CORRECT_INPUTS_FIRST)
    sample = samples / "LFSR.v"
    out = SC._score_side_port_permutation_rescue_shape_b(
        design, sample, dataset, _LAYOUT, _ARGS)
    assert out is not None and out["verdict"] == "PASS", out


# ── ROUND-4 (field-agent reopen) — NON-ANSI golden (the real RTLLM shape) ────
# The golden order extractor must read a NON-ANSI (Verilog-2001 bare-name) golden
# header `module LFSR (out, clk, rst);` (directions in the body). The ANSI-only
# `_parse_portlist_segments` returned None on it → the round-3 rescue was a NO-OP
# on the real LFSR artifact. The header bare-name parser fixes it.
_GOLDEN_OUTPUTS_FIRST_NONANSI = (
    "module LFSR (out, clk, rst);\n"
    "  input clk, rst;\n"
    "  output reg [3:0] out;\n"
    "  always @(posedge clk or posedge rst)\n"
    "    if (rst) out <= 4'b0001;\n"
    "    else out <= {out[2:0], out[3]^out[2]};\n"
    "endmodule\n")


def test_module_header_port_name_order_nonansi_and_ansi():
    """The header bare-name parser yields the positional name order for BOTH a
    NON-ANSI bare-name header and an ANSI directional header."""
    assert SC._module_header_port_name_order(
        _GOLDEN_OUTPUTS_FIRST_NONANSI, "LFSR") == ["out", "clk", "rst"]
    assert SC._module_header_port_name_order(
        _GOLDEN_OUTPUTS_FIRST, "LFSR") == ["out", "clk", "rst"]
    # a #(...) param header is skipped before the port list:
    assert SC._module_header_port_name_order(
        "module m #(parameter N=4)(out, clk); input clk;\n"
        " output [N-1:0] out; endmodule", "m") == ["out", "clk"]


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog/vvp required")
def test_round4_nonansi_golden_rescue_fires(tmp_path):
    """ROUND-4 (the reopen): with a NON-ANSI golden, the round-3 rescue used to be
    a NO-OP (golden-order=None → bail). The header parser now resolves the order,
    so an inputs-first correct candidate is rescued compile_error → PASS."""
    res = _score(tmp_path, _CAND_CORRECT_INPUTS_FIRST,
                 golden=_GOLDEN_OUTPUTS_FIRST_NONANSI)
    assert _passed_via_reorder(res), res


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog/vvp required")
def test_round4_nonansi_golden_wrong_logic_stays_fail(tmp_path):
    """§4.05 with a NON-ANSI golden: a wrong-logic candidate (correct ports) is
    NOT rescued — the permutation is logic-preserving, so the discriminating TB
    still fails it."""
    wrong = ("module LFSR(input clk, input rst, output reg [3:0] out);\n"
             "  always @(posedge clk) out <= 4'b0;\n"  # wrong taps/logic
             "endmodule\n")
    res = _score(tmp_path, wrong, golden=_GOLDEN_OUTPUTS_FIRST_NONANSI)
    assert res["verdict"] == "FAIL", res


# ── NEGATIVE (load-bearing) — a pure permutation NEVER rescues a wrong design ─
def test_negative_missing_port_stays_compile_error(tmp_path):
    """A candidate MISSING the `rst` port → its port-NAME set {clk,out} ≠ the
    golden's {clk,rst,out} → the rescue REFUSES (not a pure-permutation case) →
    stays compile_error FAIL."""
    cand = ("module LFSR(input clk, output reg [3:0] out);\n"
            "  always @(posedge clk) out <= {out[2:0], out[3]^out[2]};\n"
            "endmodule\n")
    design, samples, dataset = _build_run(tmp_path, cand)
    # name-set mismatch → helper refuses outright.
    assert SC._score_side_port_permutation_rescue_shape_b(
        design, samples / "LFSR.v", dataset, _LAYOUT, _ARGS) is None
    res = SC._score_shape_b(design, samples, dataset, _LAYOUT, _ARGS)
    assert res["verdict"] == "FAIL", res
    assert res.get("reason") != "recovered_via_scoreside_port_permutation", res


def test_negative_extra_port_stays_fail(tmp_path):
    """A candidate with an EXTRA `en` port → its port-NAME set {clk,rst,en,out} ≠
    the golden's {clk,rst,out} → the rescue REFUSES → stays FAIL."""
    cand = ("module LFSR(input clk, input rst, input en, "
            "output reg [3:0] out);\n"
            "  always @(posedge clk or posedge rst)\n"
            "    if (rst) out <= 4'b0001;\n"
            "    else if (en) out <= {out[2:0], out[3]^out[2]};\n"
            "endmodule\n")
    design, samples, dataset = _build_run(tmp_path, cand)
    assert SC._score_side_port_permutation_rescue_shape_b(
        design, samples / "LFSR.v", dataset, _LAYOUT, _ARGS) is None
    res = SC._score_shape_b(design, samples, dataset, _LAYOUT, _ARGS)
    assert res["verdict"] == "FAIL", res
    assert res.get("reason") != "recovered_via_scoreside_port_permutation", res


def test_negative_wrong_width_port_stays_fail(tmp_path):
    """A candidate whose `out` is `[2:0]` (3-bit) vs the golden/TB's 4-bit `out`:
    the port-NAME set matches {clk,rst,out}, so the rescue permutes to the golden
    NAME order — but the permuted recompile still errors / runtime-fails (the 3-bit
    output is incompatible with the 4-bit TB net) → stays FAIL."""
    cand = ("module LFSR(input clk, input rst, output reg [2:0] out);\n"
            "  always @(posedge clk or posedge rst)\n"
            "    if (rst) out <= 3'b001;\n"
            "    else out <= {out[1:0], out[2]^out[1]};\n"
            "endmodule\n")
    res = _score(tmp_path, cand)
    assert res["verdict"] == "FAIL", res
    assert res.get("reason") != "recovered_via_scoreside_port_permutation", res


def test_negative_wrong_logic_correct_ports_stays_fail(tmp_path):
    """A candidate with WRONG LOGIC (XORs the WRONG taps: out[0]^out[1]) but the
    correct inputs-first ports: the pure permutation to outputs-first COMPILES but
    RUNTIME-FAILs the discriminating reference-model TB (no pass marker) → a pure
    permutation CANNOT convert a wrong-logic FAIL to PASS. (load-bearing proof)."""
    cand = ("module LFSR(input clk, input rst, output reg [3:0] out);\n"
            "  always @(posedge clk or posedge rst)\n"
            "    if (rst) out <= 4'b0001;\n"
            "    else out <= {out[2:0], out[0]^out[1]};\n"  # WRONG taps
            "endmodule\n")
    res = _score(tmp_path, cand)
    assert res["verdict"] == "FAIL", res
    assert res.get("reason") != "recovered_via_scoreside_port_permutation", res


def test_negative_wrong_logic_already_correct_order_is_noop(tmp_path):
    """A WRONG-LOGIC candidate whose ports are ALREADY outputs-first (matching the
    TB bind): the permutation is a byte-identical NO-OP → the helper returns None
    (nothing to re-evaluate) → the candidate stays its honest FAIL. A no-op reorder
    can never rescue wrong logic."""
    cand = ("module LFSR(output reg [3:0] out, input clk, input rst);\n"
            "  always @(posedge clk or posedge rst)\n"
            "    if (rst) out <= 4'b0001;\n"
            "    else out <= {out[2:0], out[0]^out[1]};\n"  # WRONG taps
            "endmodule\n")
    design, samples, dataset = _build_run(tmp_path, cand)
    sample = samples / "LFSR.v"
    # The order is already correct → the rescue is a no-op → returns None.
    assert SC._score_side_port_permutation_rescue_shape_b(
        design, sample, dataset, _LAYOUT, _ARGS) is None
    # And end-to-end it stays a FAIL (never rescued).
    res = SC._score_shape_b(design, samples, dataset, _LAYOUT, _ARGS)
    assert res["verdict"] == "FAIL", res
    assert res.get("reason") != "recovered_via_scoreside_port_permutation", res


def test_negative_golden_does_not_elaborate_no_permutation(tmp_path):
    """When the golden+TB does NOT elaborate (a #690 dataset defect — the golden
    is MISSING the `out` port the TB binds), the rescue gate refuses to attempt the
    permutation, and the #690 dataset_defect annotation path is unchanged."""
    # A defective golden that lacks `out` → golden(aliased)+TB fails elaboration.
    defective_golden = ("module LFSR(input clk, input rst);\n"
                        "  reg [3:0] s;\n"
                        "  always @(posedge clk or posedge rst)\n"
                        "    if (rst) s <= 4'b0001; else s <= {s[2:0], s[3]^s[2]};\n"
                        "endmodule\n")
    design, samples, dataset = _build_run(
        tmp_path, _CAND_CORRECT_INPUTS_FIRST, golden=defective_golden)
    sample = samples / "LFSR.v"
    # The gate (golden+TB must elaborate) fails → rescue NOT attempted.
    assert SC._score_side_port_permutation_rescue_shape_b(
        design, sample, dataset, _LAYOUT, _ARGS) is None
    # End-to-end: stays a FAIL and the #690 dataset-defect audit still fires.
    res = SC._score_shape_b(design, samples, dataset, _LAYOUT, _ARGS)
    assert res["verdict"] == "FAIL", res
    assert res.get("reason") != "recovered_via_scoreside_port_permutation", res
    assert res.get("dataset_defect") is True, res
    assert res.get("dataset_defect_reason") == "golden_ref_fails_own_tb_compile", res


# ── LENS-1 LEAK (the §4.05 hole the adversarial review found) ────────────────
# A NON-COMMUTATIVE op `gt = a > b` with two SAME-WIDTH SAME-DIRECTION operands.
# The golden `cmp(a, b, gt)` passes the TB POSITIONALLY → its declaration order is
# the ground truth. The TB carries DECEPTIVE net affinity: it declares `a_tb`/
# `b_tb` and binds POSITIONALLY `cmp DUT(a_tb, b_tb, gt_tb)`. The OLD affinity-based
# inference could bind a WRONG-operand candidate so the marker fired. The HARDENED
# rescue derives the order from the GOLDEN's declaration order matched by NAME, so a
# wrong-operand candidate permutes to (a,b,gt) and its wrong logic still FAILs.
_CMP_GOLDEN = ("module cmp(input [7:0] a, input [7:0] b, output gt);\n"
               "  assign gt = a > b;\n"
               "endmodule\n")
# Deceptive-affinity, same-width-operand, POSITIONAL TB (binds a_tb to slot 0).
_CMP_TB = (
    "module testbench;\n"
    "  reg [7:0] a_tb, b_tb; wire gt_tb; integer errs=0;\n"
    "  cmp DUT(a_tb, b_tb, gt_tb);\n"
    "  initial begin\n"
    "    a_tb=8'd5; b_tb=8'd3; #5; if (gt_tb!==1'b1) errs=errs+1;\n"
    "    a_tb=8'd2; b_tb=8'd9; #5; if (gt_tb!==1'b0) errs=errs+1;\n"
    "    a_tb=8'd7; b_tb=8'd7; #5; if (gt_tb!==1'b0) errs=errs+1;\n"
    "    if (errs==0) $display(\"=========== Your Design Passed ===========\");\n"
    "    else $display(\"Your Design Failed: %0d\", errs);\n"
    "    $finish;\n"
    "  end\n"
    "endmodule\n")
_CMP_SPEC = ("Module name:\ncmp\n\nInput ports:\n  a\n  b\n"
             "Output ports:\n  gt\n")


def _score_cmp(tmp_path, candidate):
    return _score(tmp_path, candidate, golden=_CMP_GOLDEN, tb=_CMP_TB,
                  spec=_CMP_SPEC, design="cmp")


def test_lens1_leak_wrong_operand_output_first_stays_fail(tmp_path):
    """LENS-1 LEAK (load-bearing): a spec-WRONG candidate `gt = b > a`, declared
    OUTPUT-FIRST `(gt, a, b)` so the verbatim positional bind COMPILE-ERRORs (a reg
    driving the output) and the rescue FIRES. The hardened rescue permutes its ports
    to the GOLDEN's NAME order (a, b, gt) — leaving the WRONG `gt = b > a` logic —
    so under the positional TB (`a_tb`→a, `b_tb`→b) it computes `b_tb > a_tb` and
    RUNTIME-FAILs. A same-width operand swap is NEVER silently bound → stays FAIL.
    (The old TB-net-affinity inference rescued this wrong candidate.)"""
    cand = ("module cmp(output gt, input [7:0] a, input [7:0] b);\n"
            "  assign gt = b > a;\n"  # WRONG operand order (spec wants a > b)
            "endmodule\n")
    res = _score_cmp(tmp_path, cand)
    assert res["verdict"] == "FAIL", res
    assert res.get("reason") != "recovered_via_scoreside_port_permutation", res


def test_lens1_spec_faithful_output_first_is_rescued_to_pass(tmp_path):
    """The companion POSITIVE: the SPEC-FAITHFUL `gt = a > b`, declared OUTPUT-FIRST
    `(gt, a, b)` (verbatim compile-errors), IS rescued — permuted to the golden NAME
    order (a, b, gt) it computes `a_tb > b_tb` = correct → PASS. Proves the rescue
    still rescues a genuinely-correct candidate (it's the wrong one that can't be)."""
    cand = ("module cmp(output gt, input [7:0] a, input [7:0] b);\n"
            "  assign gt = a > b;\n"  # CORRECT
            "endmodule\n")
    res = _score_cmp(tmp_path, cand)
    assert _passed_via_reorder(res), res


def test_lens1_wrong_operand_already_golden_order_is_noop(tmp_path):
    """A WRONG-operand `gt = b > a` candidate whose ports are ALREADY in the golden
    NAME order `(a, b, gt)` compiles VERBATIM (no error → rescue never even fires)
    and RUNTIME-FAILs on the normal path. Belt-and-braces: even if the rescue were
    invoked, the golden-name permutation is a byte-identical no-op → returns None."""
    cand = ("module cmp(input [7:0] a, input [7:0] b, output gt);\n"
            "  assign gt = b > a;\n"  # WRONG operand order
            "endmodule\n")
    design, samples, dataset = _build_run(
        tmp_path, cand, golden=_CMP_GOLDEN, tb=_CMP_TB, spec=_CMP_SPEC,
        design="cmp")
    # The golden-name permutation is a no-op (order already matches) → None.
    assert SC._score_side_port_permutation_rescue_shape_b(
        "cmp", samples / "cmp.v", dataset, _LAYOUT, _ARGS) is None
    res = SC._score_shape_b("cmp", samples, dataset, _LAYOUT, _ARGS)
    assert res["verdict"] == "FAIL", res
    assert res.get("reason") != "recovered_via_scoreside_port_permutation", res


def test_negative_port_name_mismatch_refused(tmp_path):
    """A candidate that uses DIFFERENT port names than the golden/spec (here `x`,`y`,
    `z` instead of `a`,`b`,`gt`) → its port-NAME set ≠ the golden's → the rescue
    REFUSES (a candidate that doesn't even use the spec's port names is not a
    pure-permutation case) → stays FAIL, even though the LOGIC is correct."""
    cand = ("module cmp(output z, input [7:0] x, input [7:0] y);\n"
            "  assign z = x > y;\n"  # correct logic, but WRONG port names
            "endmodule\n")
    design, samples, dataset = _build_run(
        tmp_path, cand, golden=_CMP_GOLDEN, tb=_CMP_TB, spec=_CMP_SPEC,
        design="cmp")
    assert SC._score_side_port_permutation_rescue_shape_b(
        "cmp", samples / "cmp.v", dataset, _LAYOUT, _ARGS) is None
    res = SC._score_shape_b("cmp", samples, dataset, _LAYOUT, _ARGS)
    assert res["verdict"] == "FAIL", res
    assert res.get("reason") != "recovered_via_scoreside_port_permutation", res


# ── REGRESSION — an inputs-first design with an inputs-first TB still PASSES ──
def test_regression_inputs_first_alu_passes_normal_path(tmp_path):
    """An inputs-first `alu` + an inputs-first positional TB: the verbatim bind
    COMPILES + PASSES on the normal path, so the rescue never even runs (a
    byte-identical no-op). The score-side change does not regress already-passing
    inputs-first designs."""
    alu = ("module alu(input [31:0] a, input [31:0] b, input [4:0] aluc,\n"
           "  output reg [31:0] r, output reg zero);\n"
           "  always @(*) begin r = a + b; zero = (r==0); end\n"
           "endmodule\n")
    alu_tb = (
        "module testbench;\n"
        "  reg [31:0] a, b; reg [4:0] aluc; wire [31:0] r; wire zero;\n"
        "  alu uut(a, b, aluc, r, zero);\n"
        "  initial begin\n"
        "    a=1; b=2; aluc=0; #5;\n"
        "    if (r===32'd3 && zero===1'b0)\n"
        "      $display(\"=========== Your Design Passed ===========\");\n"
        "    else $display(\"Your Design Failed\");\n"
        "    $finish;\n"
        "  end\n"
        "endmodule\n")
    alu_golden = ("module alu(input [31:0] a, input [31:0] b, input [4:0] aluc,\n"
                  "  output reg [31:0] r, output reg zero);\n"
                  "  always @(*) begin r = a + b; zero = (r==0); end\n"
                  "endmodule\n")
    spec = ("Module name:\nalu\n\nInput ports:\n a\n b\n aluc\n"
            "Output ports:\n r\n zero\n")
    res = _score(tmp_path, alu, golden=alu_golden, tb=alu_tb, spec=spec,
                 design="alu")
    assert res["verdict"] == "PASS", res
    # the NORMAL path passed — NOT the rescue (verbatim bind compiles).
    assert res.get("reason") != "recovered_via_scoreside_port_permutation", res


# ── NAMED-BINDING — no positional list → no permutation attempted ────────────
def test_named_binding_tb_no_permutation(tmp_path):
    """A TB that binds by NAME (`.clk(clk_tb)`): the positional-arg parse finds no
    positional list → no permutation attempted. A correct candidate compiles &
    passes on the normal path regardless of declaration order; the rescue is moot.
    Here we assert the rescue helper itself returns None on a named bind."""
    named_tb = (
        "module testbench;\n"
        "  reg clk_tb=0, rst_tb=1; wire [3:0] out_tb; reg [3:0] model;\n"
        "  integer errs=0, i;\n"
        "  LFSR DUT(.clk(clk_tb), .rst(rst_tb), .out(out_tb));\n"
        "  always #5 clk_tb=~clk_tb;\n"
        "  always @(posedge clk_tb or posedge rst_tb)\n"
        "    if (rst_tb) model<=4'b0001; else model<={model[2:0], model[3]^model[2]};\n"
        "  initial begin\n"
        "    #12 rst_tb=0;\n"
        "    for (i=0;i<8;i=i+1) begin @(posedge clk_tb); #1;\n"
        "      if (out_tb!==model) errs=errs+1; end\n"
        "    if (errs==0) $display(\"=========== Your Design Passed ===========\");\n"
        "    else $display(\"Your Design Failed\");\n"
        "    $finish;\n"
        "  end\n"
        "endmodule\n")
    # Use an inputs-first candidate that would compile_error ONLY under a
    # positional bind; under the NAMED bind it elaborates regardless of order.
    design, samples, dataset = _build_run(
        tmp_path, _CAND_CORRECT_INPUTS_FIRST, tb=named_tb)
    sample = samples / "LFSR.v"
    # The rescue path: a named bind → no positional args → helper returns None.
    assert SC._score_side_port_permutation_rescue_shape_b(
        design, sample, dataset, _LAYOUT, _ARGS) is None
    # End-to-end the candidate PASSES on the NORMAL path (named bind, any order).
    res = SC._score_shape_b(design, samples, dataset, _LAYOUT, _ARGS)
    assert res["verdict"] == "PASS", res
    assert res.get("reason") != "recovered_via_scoreside_port_permutation", res


# ── chip-AGNOSTIC guard ──────────────────────────────────────────────────────
def test_chip_agnostic_guard():
    prog = _PROGRAMS / "source_chip_agnostic_check.py"
    r = _pr.run([sys.executable, str(prog), str(_PLUGIN)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-400:]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
