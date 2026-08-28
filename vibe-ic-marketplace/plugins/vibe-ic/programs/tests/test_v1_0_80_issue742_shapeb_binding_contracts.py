#!/usr/bin/env python3
"""ORGANIC #742 (P2) — Shape-B blind first-pass binding contracts.

THE FLOOR THIS PINS
-------------------
The Shape-B blind first-pass emit/score ignored two UNDISCLOSED hidden-TB
binding contracts. The corrective mechanisms EXISTED but fired only REACTIVELY
(after a prior compile_error) — or did not exist at all. Both motivating designs
are functionally correct (golden-self-consistent); they fail ONLY on the contract.

  FACET A — POSITIONAL-instantiation port-order contract. The hidden TB binds the
    DUT POSITIONALLY outputs-first (`DUT u(out_tb, clk_tb, rst_tb)`). A spec-
    faithful author declares ports inputs-then-outputs (clk, rst, out) per the
    description's Input-then-Output listing → iverilog `rst_tb Unable to assign to
    unresolved wires`, compile_error on the BLIND FIRST PASS. The fix wires the
    golden-order port reorder PROACTIVELY — BEFORE the first compile, when the TB
    binds positionally — as a PURE PERMUTATION of the SAME named ports.

  FACET B — NAMED-parameter-override contract. The hidden TB binds
    `#(.STG_WIDTH(16))` but the prose names NO parameter → `parameter `STG_WIDTH'
    not found in `<inst>'`, compile_error. PROOF: adding only an UNUSED
    `parameter STG_WIDTH=<default>` → PASS 0 mismatch. The fix auto-retries ONCE,
    injecting a passthrough `parameter X=<default>` when iverilog fails with ONLY
    that specific error.

§4.05 NEGATIVE NO-LEAK (load-bearing, both facets)
--------------------------------------------------
  * the port reorder is a PURE permutation of the SAME named ports — never invents
    / drops a port, never changes a name/width/direction/logic;
  * the param injection only ADDS a missing declaration — it never relaxes the
    functional pass/fail comparison (the vvp comparison is unchanged).
A FUNCTIONALLY-WRONG DUT STILL FAILs after the fix (proven here for both facets);
a design already correctly-ordered / already-declaring the param is UNAFFECTED.

chip-AGNOSTIC: every fixture lives in tmp_path and the program detection logic
keys on STRUCTURE only (positional-vs-named instantiation, the iverilog error
text, the TB's `#(.X(...))` overrides) — design names appear ONLY in the fixtures.
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

import port_convention_corpus as PCC  # noqa: E402
import score_iverilog_tb as SC        # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_HAS_IVERILOG = shutil.which("iverilog") is not None and shutil.which("vvp") is not None
_iv = pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog/vvp unavailable")


#: THE PRECONDITION THE FACET-B TESTS ACTUALLY NEED, probed rather than assumed.
#:
#: Two of them assert that binding `#(.STG_WIDTH(16))` to a module with no such
#: parameter FAILS elaboration with `parameter 'STG_WIDTH' not found`. That is
#: not a property of Verilog — it is a property of one iverilog. MEASURED on
#: Icarus Verilog 11.0 (stable), the version on this host:
#:
#:     iverilog -g2012 -o out m.v tb.v
#:     tb.v:3: warning: parameter STG_WIDTH not found in tb.u.
#:     rc=0
#:
#: A WARNING and rc=0. The tests were guarded on `iverilog/vvp unavailable`,
#: which is true here and irrelevant: iverilog is present and simply does not
#: reproduce the precondition, so both asserted a toolchain behaviour they had
#: never established. Same shape as vibe-ic#1128 — a test stating half its
#: precondition — one layer along: there the missing half was a second BINARY,
#: here it is a BEHAVIOUR of the binary that is present.
#:
#: Probed by compiling the minimal case once, at import, rather than keyed on a
#: version string: the version that changed this is not the point, the behaviour
#: is, and a version comparison would go stale the next time it moves.
def _iverilog_errors_on_unknown_param() -> bool:
    if not _HAS_IVERILOG:
        return False
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "m.v").write_text(
            "module m(input a, output b);\n  assign b = a;\nendmodule\n")
        (d / "tb.v").write_text(
            "module tb;\n  reg a=0; wire b;\n"
            "  m #(.NO_SUCH_PARAM(16)) u(.a(a), .b(b));\n"
            "  initial #1 $finish;\nendmodule\n")
        try:
            r = _pr.run(
                ["iverilog", "-g2012", "-o", str(d / "out"),
                 str(d / "m.v"), str(d / "tb.v")],
                capture_output=True, text=True)
        except Exception:            # noqa: BLE001 - absent/unusable toolchain
            return False
        return r.returncode != 0


_IV_ERRORS_ON_UNKNOWN_PARAM = _iverilog_errors_on_unknown_param()

#: Names WHICH half is missing, so a reader of the run learns what stopped being
#: checked rather than inferring it. A skip is green (vibe-ic#1128).
_iv_param_strict = pytest.mark.skipif(
    not _IV_ERRORS_ON_UNKNOWN_PARAM,
    reason=("needs an iverilog that ERRORS on an override of a parameter the "
            "module does not declare; this one "
            + ("is absent" if not _HAS_IVERILOG else
               "only warns (rc=0) — Icarus 11.0 behaviour")))

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


def _build_run(tmp_path, *, candidate, golden, tb, spec, design):
    """Assemble a faithful Shape-B layout in tmp_path:
      dataset/<design>/{design_description.txt, testbench.v, verified_<design>.v}
      run/samples/<design>.v  (the candidate)
    Files are written DIRECTLY via write_text. Returns (design, samples, dataset).
    """
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


# ════════════════════════ FACET A — POSITIONAL PORT-ORDER ════════════════════
# Spec lists Input ports clk,rst then Output port out (Module name: lfsr).
_A_SPEC = ("Module name:\nlfsr\n\nInput ports:\n  clk\n  rst\n"
           "Output ports:\n  out\n")
# OUTPUTS-FIRST positional TB: `lfsr DUT(out_tb, clk_tb, rst_tb)`. Discriminating
# via an internal reference model so a wrong-logic permute can NOT fake a PASS.
_A_TB = (
    "module testbench;\n"
    "  reg clk_tb=0, rst_tb=1; wire [3:0] out_tb; reg [3:0] model;\n"
    "  integer errs=0, i;\n"
    "  lfsr DUT(out_tb, clk_tb, rst_tb);\n"
    "  always #5 clk_tb = ~clk_tb;\n"
    "  always @(posedge clk_tb or posedge rst_tb)\n"
    "    if (rst_tb) model <= 4'b0001;\n"
    "    else model <= {model[2:0], model[3]^model[2]};\n"
    "  initial begin\n"
    "    #12 rst_tb = 0;\n"
    "    for (i=0;i<8;i=i+1) begin @(posedge clk_tb); #1;\n"
    "      if (out_tb !== model) errs = errs + 1; end\n"
    "    if (errs==0) $display(\"=========== Your Design Passed ===========\");\n"
    "    else $display(\"Your Design Failed: %0d\", errs);\n"
    "    $finish;\n"
    "  end\n"
    "endmodule\n")
# Golden is OUTPUTS-FIRST (non-ANSI bare-name header — the real RTLLM shape) and
# PASSES the TB positionally → its declaration order (out, clk, rst) is the ground
# truth positional bind order.
_A_GOLDEN = (
    "module lfsr (out, clk, rst);\n"
    "  input clk, rst; output reg [3:0] out;\n"
    "  always @(posedge clk or posedge rst)\n"
    "    if (rst) out <= 4'b0001;\n"
    "    else out <= {out[2:0], out[3]^out[2]};\n"
    "endmodule\n")
# Candidate is INPUTS-FIRST (clk, rst, out) — spec prose order, FUNCTIONALLY
# CORRECT. The verbatim positional bind compile-errors; the proactive reorder to
# the golden's outputs-first NAME order fixes it.
_A_CAND_CORRECT = (
    "module lfsr(input clk, input rst, output reg [3:0] out);\n"
    "  always @(posedge clk or posedge rst)\n"
    "    if (rst) out <= 4'b0001;\n"
    "    else out <= {out[2:0], out[3]^out[2]};\n"
    "endmodule\n")
# WRONG-LOGIC control, SAME inputs-first port order (wrong XOR taps).
_A_CAND_WRONG = (
    "module lfsr(input clk, input rst, output reg [3:0] out);\n"
    "  always @(posedge clk or posedge rst)\n"
    "    if (rst) out <= 4'b0001;\n"
    "    else out <= {out[2:0], out[0]^out[1]};\n"  # WRONG taps
    "endmodule\n")


def _make(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return p


def test_facetA_prefix_reproduces_compile_error_pre_fix(tmp_path):
    """PRE-FIX REPRODUCE (no fix involved): the verbatim inputs-first candidate
    bound by the outputs-first positional TB fails iverilog elaboration with the
    `Unable to assign to unresolved wires` error — the blind first-pass floor."""
    if not _HAS_IVERILOG:
        pytest.skip("iverilog/vvp unavailable")
    design, _samples, dataset = _build_run(
        tmp_path, candidate=_A_CAND_CORRECT, golden=_A_GOLDEN, tb=_A_TB,
        spec=_A_SPEC, design="lfsr")
    dd = dataset / design
    with tempfile.TemporaryDirectory() as td:
        binp = Path(td) / "b"
        r = _pr.run(
            ["iverilog", "-g2012", "-o", str(binp),
             str(_make(tmp_path, "verbatimA.v", _A_CAND_CORRECT)),
             str(dd / "testbench.v")],
            capture_output=True, text=True)
    assert r.returncode != 0, "verbatim positional bind should NOT compile"
    # iverilog phrases this positional-bind elaboration failure differently
    # across versions — older builds print "Unable to assign to unresolved
    # wires"; newer ones print "Cannot perform procedural assignment ...
    # continuously assigned" + "Elaboration failed". The reproduce-gate is that
    # the bind does NOT elaborate; assert that robustly (rc!=0, above) with a
    # reason-family check rather than pinning one version's exact phrase.
    _out = (r.stdout + r.stderr).lower()
    assert any(s in _out for s in (
        "unable to assign to unresolved wires",
        "procedural assignment",
        "continuously assigned",
        "elaboration failed",
    )), r.stderr


@_iv
def test_facetA_proactive_reorder_flips_to_pass(tmp_path):
    """POST-FIX: the score path PROACTIVELY reorders the candidate's ports to the
    golden positional order BEFORE the first compile, so a functionally-correct
    inputs-first candidate PASSES. Because the proactive normalize fires on the
    FIRST compile, the verdict carries NO 'recovered_via_*' reason (it is a clean
    pass, not a reactive rescue)."""
    design, samples, dataset = _build_run(
        tmp_path, candidate=_A_CAND_CORRECT, golden=_A_GOLDEN, tb=_A_TB,
        spec=_A_SPEC, design="lfsr")
    res = SC._score_shape_b(design, samples, dataset, _LAYOUT, _ARGS)
    assert res["verdict"] == "PASS", res
    # PASSed on the first compile after proactive normalize → no rescue reason.
    assert res.get("reason") is None, res


@_iv
def test_facetA_wrong_logic_control_still_fails(tmp_path):
    """§4.05: a wrong-LOGIC control with the SAME port order is NOT rescued by the
    pure permutation — the discriminating reference-model TB still fails it."""
    design, samples, dataset = _build_run(
        tmp_path, candidate=_A_CAND_WRONG, golden=_A_GOLDEN, tb=_A_TB,
        spec=_A_SPEC, design="lfsr")
    res = SC._score_shape_b(design, samples, dataset, _LAYOUT, _ARGS)
    assert res["verdict"] == "FAIL", res


@_iv
def test_facetA_proactive_normalize_helper_is_pure_permutation(tmp_path):
    """Unit on the proactive normalizer: it returns the candidate text reordered
    to the golden's positional NAME order, preserving the SAME port-name set (a
    pure permutation — never invents/drops a port)."""
    design, _samples, dataset = _build_run(
        tmp_path, candidate=_A_CAND_CORRECT, golden=_A_GOLDEN, tb=_A_TB,
        spec=_A_SPEC, design="lfsr")
    out = SC._proactive_positional_port_normalize_shape_b(
        _A_CAND_CORRECT, design, dataset, _LAYOUT)
    assert out != _A_CAND_CORRECT, "should reorder the inputs-first candidate"
    # SAME named-port set, just reordered (out moved to slot 0).
    import re
    def ports(t):
        m = re.search(r"\((.*?)\)\s*;", t, re.S)
        return sorted(re.findall(r"\b(clk|rst|out)\b", m.group(1)))
    assert ports(out) == ports(_A_CAND_CORRECT) == ["clk", "out", "rst"], out
    # `out` (the golden's first positional port) now precedes clk/rst.
    body = out[out.index("("): out.index(";")]
    assert body.index("out") < body.index("clk") < body.index("rst"), out
    # logic is byte-preserved (pure permutation never touches the body).
    assert "out <= {out[2:0], out[3]^out[2]}" in out, out


@_iv
def test_facetA_named_binding_tb_no_proactive_reorder(tmp_path):
    """A NAMED-binding TB (`.clk(clk_tb)`) is order-independent → the proactive
    normalize is a no-op (returns the candidate verbatim), and the candidate
    PASSES on the normal path regardless of declaration order."""
    named_tb = _A_TB.replace(
        "lfsr DUT(out_tb, clk_tb, rst_tb);",
        "lfsr DUT(.out(out_tb), .clk(clk_tb), .rst(rst_tb));")
    design, samples, dataset = _build_run(
        tmp_path, candidate=_A_CAND_CORRECT, golden=_A_GOLDEN, tb=named_tb,
        spec=_A_SPEC, design="lfsr")
    norm = SC._proactive_positional_port_normalize_shape_b(
        _A_CAND_CORRECT, design, dataset, _LAYOUT)
    assert norm == _A_CAND_CORRECT, "named bind → no reorder"
    res = SC._score_shape_b(design, samples, dataset, _LAYOUT, _ARGS)
    assert res["verdict"] == "PASS", res


# ════════════════════════ FACET B — NAMED-PARAM OVERRIDE ═════════════════════
_B_SPEC = ("Module name:\nshiftreg\n\nInput ports:\n  clk\n  rst\n  din\n"
           "Output ports:\n  dout\n")
# TB binds a NAMED param override `#(.STG_WIDTH(16))` the prose never names.
_B_TB = (
    "module testbench;\n"
    "  reg clk=0, rst=1, din=0; wire dout; integer i, errs=0; reg [15:0] model;\n"
    "  shiftreg #(.STG_WIDTH(16)) DUT(clk, rst, din, dout);\n"
    "  always #5 clk = ~clk;\n"
    "  always @(posedge clk or posedge rst)\n"
    "    if (rst) model <= 0; else model <= {model[14:0], din};\n"
    "  initial begin\n"
    "    #12 rst = 0;\n"
    "    for (i=0;i<40;i=i+1) begin din=(i*7)&1; @(posedge clk); #1;\n"
    "      if (dout !== model[15]) errs = errs + 1; end\n"
    "    if (errs==0) $display(\"=========== Your Design Passed ===========\");\n"
    "    else $display(\"Your Design Failed: %0d\", errs);\n"
    "    $finish;\n"
    "  end\n"
    "endmodule\n")
# Golden DECLARES the param (it is a verified ref) → golden+TB elaborates.
_B_GOLDEN = (
    "module shiftreg #(parameter STG_WIDTH=16)\n"
    "  (input clk, input rst, input din, output reg dout);\n"
    "  reg [15:0] sr;\n"
    "  always @(posedge clk or posedge rst) if (rst) sr<=0; else sr<={sr[14:0],din};\n"
    "  always @(*) dout = sr[15];\n"
    "endmodule\n")
# Candidate declares NO parameter — the blind first-pass shape.
_B_CAND_CORRECT = (
    "module shiftreg(input clk, input rst, input din, output reg dout);\n"
    "  reg [15:0] sr;\n"
    "  always @(posedge clk or posedge rst) if (rst) sr<=0; else sr<={sr[14:0],din};\n"
    "  always @(*) dout = sr[15];\n"
    "endmodule\n")
# WRONG-LOGIC control (inverts din), still declaring no parameter.
_B_CAND_WRONG = (
    "module shiftreg(input clk, input rst, input din, output reg dout);\n"
    "  reg [15:0] sr;\n"
    "  always @(posedge clk or posedge rst) if (rst) sr<=0; else sr<={sr[14:0], ~din};\n"
    "  always @(*) dout = sr[15];\n"
    "endmodule\n")
# A candidate that ALREADY declares the param → UNAFFECTED (no injection).
_B_CAND_HAS_PARAM = _B_GOLDEN.replace("STG_WIDTH=16", "STG_WIDTH=16")


@_iv_param_strict
def test_facetB_prefix_reproduces_param_not_found(tmp_path):
    """PRE-FIX REPRODUCE: the no-parameter candidate bound by `#(.STG_WIDTH(16))`
    fails iverilog elaboration with EXACTLY `parameter `STG_WIDTH' not found`."""
    if not _HAS_IVERILOG:
        pytest.skip("iverilog/vvp unavailable")
    design, _s, dataset = _build_run(
        tmp_path, candidate=_B_CAND_CORRECT, golden=_B_GOLDEN, tb=_B_TB,
        spec=_B_SPEC, design="shiftreg")
    with tempfile.TemporaryDirectory() as td:
        binp = Path(td) / "b"
        r = _pr.run(
            ["iverilog", "-g2012", "-o", str(binp),
             str(_make(tmp_path, "verbatimB.v", _B_CAND_CORRECT)),
             str(dataset / design / "testbench.v")],
            capture_output=True, text=True)
    assert r.returncode != 0, "verbatim no-param bind should NOT compile"
    log = r.stdout + r.stderr
    assert PCC.iverilog_param_not_found(log) == ["STG_WIDTH"], log
    assert PCC.error_is_only_param_not_found(log), log


@_iv
@_iv_param_strict
def test_facetB_param_injection_flips_to_pass(tmp_path):
    """POST-FIX: on the `parameter `STG_WIDTH' not found` error the score path
    auto-retries ONCE, injecting a passthrough `parameter STG_WIDTH=16`, and the
    functionally-correct candidate PASSES via the documented reason."""
    design, samples, dataset = _build_run(
        tmp_path, candidate=_B_CAND_CORRECT, golden=_B_GOLDEN, tb=_B_TB,
        spec=_B_SPEC, design="shiftreg")
    res = SC._score_shape_b(design, samples, dataset, _LAYOUT, _ARGS)
    assert res["verdict"] == "PASS", res
    assert res["reason"] == "recovered_via_param_passthrough_injection", res


@_iv
def test_facetB_wrong_logic_control_still_fails(tmp_path):
    """§4.05: a wrong-LOGIC control (same missing-param shape) is NOT masked by the
    injection — the injection clears elaboration, then the design RUNTIME-FAILs the
    functional check. Injection only ADDS a declaration; it never relaxes pass/fail.
    """
    design, samples, dataset = _build_run(
        tmp_path, candidate=_B_CAND_WRONG, golden=_B_GOLDEN, tb=_B_TB,
        spec=_B_SPEC, design="shiftreg")
    res = SC._score_shape_b(design, samples, dataset, _LAYOUT, _ARGS)
    assert res["verdict"] == "FAIL", res
    assert res.get("reason") != "recovered_via_param_passthrough_injection", res


@_iv
def test_facetB_already_declares_param_unaffected(tmp_path):
    """§4.05 already-declared: a candidate that ALREADY declares the param compiles
    verbatim and PASSES on the normal path — no injection happens (plain PASS, no
    'recovered_via_param_passthrough_injection' reason)."""
    design, samples, dataset = _build_run(
        tmp_path, candidate=_B_CAND_HAS_PARAM, golden=_B_GOLDEN, tb=_B_TB,
        spec=_B_SPEC, design="shiftreg")
    res = SC._score_shape_b(design, samples, dataset, _LAYOUT, _ARGS)
    assert res["verdict"] == "PASS", res
    assert res.get("reason") is None, res


@_iv
def test_facetB_mixed_error_not_retried(tmp_path):
    """A candidate with a genuine compile bug ALONGSIDE the missing param → the
    error set is NOT param-not-found-ONLY → the param-injection retry REFUSES (the
    candidate's own bug stays a compile_error model FAIL). §4.05 no-leak gate."""
    bad = (
        "module shiftreg(input clk, input rst, input din, output reg dout);\n"
        "  reg [15:0] sr;\n"
        "  always @(posedge clk or posedge rst) if (rst) sr<=0; else sr<={sr[14:0],din};\n"
        "  always @(*) dout = sr[15];\n"
        "  undeclared_thing oops();\n"   # genuine extra compile bug
        "endmodule\n")
    design, samples, dataset = _build_run(
        tmp_path, candidate=bad, golden=_B_GOLDEN, tb=_B_TB,
        spec=_B_SPEC, design="shiftreg")
    res = SC._score_shape_b(design, samples, dataset, _LAYOUT, _ARGS)
    assert res["verdict"] == "FAIL", res
    assert res.get("reason") != "recovered_via_param_passthrough_injection", res


# ── FACET B unit coverage on the port_convention_corpus helpers ──────────────
def test_facetB_helpers_param_not_found_grammar():
    err = ("tb.v:5: error: parameter `STG_WIDTH' not found in `testbench.DUT'.\n"
           "2 error(s) during elaboration.\n")
    assert PCC.iverilog_param_not_found(err) == ["STG_WIDTH"]
    assert PCC.error_is_only_param_not_found(err) is True
    mixed = err + "tb.v:9: error: Unknown module type: foo.\n"
    assert PCC.error_is_only_param_not_found(mixed) is False
    assert PCC.iverilog_param_not_found("") == []
    assert PCC.error_is_only_param_not_found("") is False


def test_facetB_helpers_tb_named_overrides():
    tb = ("module tb;\n shiftreg #(.DATA_WIDTH(8), .STG_WIDTH(16)) DUT(c);\n"
          "endmodule\n")
    assert PCC.tb_named_param_overrides(tb, "shiftreg") == {
        "DATA_WIDTH": "8", "STG_WIDTH": "16"}
    # positional override → no named contract
    assert PCC.tb_named_param_overrides(
        "module tb; shiftreg #(8,16) DUT(c); endmodule", "shiftreg") == {}
    # no override at all → {}
    assert PCC.tb_named_param_overrides(
        "module tb; shiftreg DUT(c); endmodule", "shiftreg") == {}


def test_facetB_helpers_inject_pure_add():
    dut = "module m(input clk, output o);\nendmodule\n"
    inj = PCC.inject_passthrough_param(dut, "m", "STG_WIDTH", "16")
    assert inj is not None
    assert "parameter STG_WIDTH=16" in inj
    assert "(input clk, output o)" in inj  # port list byte-preserved (pure add)
    # already-declared → None (no-op)
    assert PCC.inject_passthrough_param(
        "module m #(parameter STG_WIDTH=8)(input clk); endmodule",
        "m", "STG_WIDTH", "16") is None
    # existing param block → append
    inj2 = PCC.inject_passthrough_param(
        "module m #(parameter A=2)(input clk); endmodule", "m", "B", "5")
    assert inj2 is not None and "parameter A=2" in inj2 and "parameter B=5" in inj2


@_iv
def test_facetB_injected_dut_compiles_and_passes():
    """The injected passthrough DUT actually elaborates under iverilog and the
    unused param does not perturb behaviour (the real proof: PASS 0 mismatch)."""
    dut = _B_CAND_CORRECT
    inj = PCC.inject_passthrough_param(dut, "shiftreg", "STG_WIDTH", "16")
    with tempfile.TemporaryDirectory() as td:
        dpath = Path(td) / "dut.v"; dpath.write_text(inj)
        tpath = Path(td) / "tb.v"; tpath.write_text(_B_TB)
        binp = Path(td) / "b"
        c = _pr.run(["iverilog", "-g2012", "-o", str(binp), str(dpath),
                            str(tpath)], capture_output=True, text=True)
        assert c.returncode == 0, (c.stdout + c.stderr)
        r = _pr.run(["vvp", str(binp)], capture_output=True, text=True)
    assert "Your Design Passed" in (r.stdout + r.stderr), (r.stdout + r.stderr)


# ════════════════════════ chip-AGNOSTIC source guard ═════════════════════════
def test_chip_agnostic_guard():
    prog = _PROGRAMS / "source_chip_agnostic_check.py"
    r = _pr.run([sys.executable, str(prog), str(_PLUGIN)],
                       capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout[-2000:] + r.stderr[-500:])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
