#!/usr/bin/env python3
"""ORGANIC #742 REOPEN round-11 (P2) — the proactive positional-port normalizer
NO-OPed on ANY Shape-B candidate that carried an INLINE port-list comment.

THE HALF-WIRED NO-OP THIS PINS
------------------------------
v1.0.80 shipped `_proactive_positional_port_normalize_shape_b` →
`shape_b_sample_export._apply_order`. The round-10 field-verify passed only
because its LFSR fixture had NO inline port comment. Round-11's real author wrote
the SAME spec-order ports WITH a comment:

    module LFSR (
        input clk,
        input rst, // active high
        output [2:0] out
    );

`_apply_order` builds `block`/`parsed` from the COMMENT-STRIPPED header
(`_module_portlist_block` → `_module_header` calls `_strip_comments` FIRST), then
searched `rtl_text` (which still carries `// active high`) for that stripped
block → `rtl_text.find(block) == -1` → silent fail-safe no-op (FIRED=False). The
normalizer NEVER reordered the ports, so the candidate still compile-errored
against the outputs-first positional hidden TB. ALL 10 preconditions PASSed; only
the rewrite anchoring was wrong.

THE FIX
-------
`_apply_order` now re-anchors onto the RAW (comment-preserving) paren-contents of
the SAME module (`_raw_portlist_block`) when the stripped block is not found
verbatim, splits the RAW block into segments keyed by their comment-stripped port
name, reorders THOSE, and comma-joins them WITHOUT letting a `//` line comment
swallow the comma / next port (`_join_raw_segments`). So the text it splits and
the text it searches are identical, and the inline comment travels with its port.

§4.05 NEGATIVE NO-LEAK (load-bearing)
-------------------------------------
Still a PURE permutation. A WRONG-NAME candidate (port-name set != golden) is NOT
rescued — the name-set mismatch aborts the reorder, so it still compile-errors /
fails. A wrong-LOGIC candidate with the right order still runtime-FAILs the
discriminating reference-model TB. An unclosed block comment makes the join
return None (no-op). chip-AGNOSTIC: every fixture lives in tmp_path and the logic
keys on grammar/structure — the design name appears ONLY in the fixtures.
"""
import re
import shutil
import subprocess
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

import shape_b_sample_export as SB   # noqa: E402
import score_iverilog_tb as SC       # noqa: E402

_HAS_IVERILOG = (shutil.which("iverilog") is not None
                 and shutil.which("vvp") is not None)
_iv = pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog/vvp unavailable")

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

# ── Fixtures: an LFSR whose author wrote spec-order ports WITH an inline comment.
_SPEC = ("Module name:\nlfsr\n\nInput ports:\n  clk\n  rst\n"
         "Output ports:\n  out\n")

# OUTPUTS-FIRST positional hidden TB (`lfsr DUT(out_tb, clk_tb, rst_tb)`), with a
# discriminating internal reference model so a wrong-logic permute can NOT fake a
# PASS. 4-bit ring-tap LFSR seeded 0001.
_TB = (
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

# Golden OUTPUTS-FIRST (the ground-truth positional order out, clk, rst).
_GOLDEN = (
    "module lfsr (out, clk, rst);\n"
    "  input clk, rst; output reg [3:0] out;\n"
    "  always @(posedge clk or posedge rst)\n"
    "    if (rst) out <= 4'b0001;\n"
    "    else out <= {out[2:0], out[3]^out[2]};\n"
    "endmodule\n")

# CANDIDATE — INPUTS-FIRST spec order WITH an inline comment on the rst port: the
# round-11 author shape that NO-OPed the v1.0.80 normalizer. Functionally correct.
_CAND_CORRECT_INLINE = (
    "module lfsr (\n"
    "    input clk,\n"
    "    input rst, // active high\n"
    "    output reg [3:0] out\n"
    ");\n"
    "  always @(posedge clk or posedge rst)\n"
    "    if (rst) out <= 4'b0001;\n"
    "    else out <= {out[2:0], out[3]^out[2]};\n"
    "endmodule\n")

# WRONG-NAME control: declares `reset` (not the golden's `rst`) — a different
# port-name set → the pure-permutation reorder MUST abort (no rescue). Inline
# comment present too, to exercise the raw path on the negative.
_CAND_WRONG_NAME = (
    "module lfsr (\n"
    "    input clk,\n"
    "    input reset, // active high  (WRONG name vs golden rst)\n"
    "    output reg [3:0] out\n"
    ");\n"
    "  always @(posedge clk or posedge reset)\n"
    "    if (reset) out <= 4'b0001;\n"
    "    else out <= {out[2:0], out[3]^out[2]};\n"
    "endmodule\n")

# WRONG-LOGIC control, inputs-first + inline comment, RIGHT names, WRONG taps.
_CAND_WRONG_LOGIC = (
    "module lfsr (\n"
    "    input clk,\n"
    "    input rst, // active high\n"
    "    output reg [3:0] out\n"
    ");\n"
    "  always @(posedge clk or posedge rst)\n"
    "    if (rst) out <= 4'b0001;\n"
    "    else out <= {out[2:0], out[0]^out[1]};\n"  # WRONG taps
    "endmodule\n")


def _build_run(tmp_path, *, candidate, design="lfsr"):
    dataset = tmp_path / "dataset"
    dd = dataset / design
    dd.mkdir(parents=True, exist_ok=True)
    (dd / "design_description.txt").write_text(_SPEC)
    (dd / "testbench.v").write_text(_TB)
    (dd / f"verified_{design}.v").write_text(_GOLDEN)
    samples = tmp_path / "run" / "samples"
    samples.mkdir(parents=True, exist_ok=True)
    (samples / f"{design}.v").write_text(candidate)
    return design, samples, dataset


# ════════════════════════ unit: _apply_order on inline comment ════════════════

def _portnames(seglist):
    return sorted(n for _s, _d, n in seglist)


def test_apply_order_fires_on_inline_comment_was_noop():
    """ROOT CAUSE PIN: with an inline port comment, _apply_order USED to no-op
    (the stripped block was not findable in the comment-bearing rtl_text). It now
    FIRES, reordering to the golden NAME order while keeping the comment attached
    to a port (so the result still compiles)."""
    g = SB._parse_portlist_segments(_CAND_CORRECT_INLINE, "lfsr")
    assert g is not None
    block, segs = g
    assert _portnames(segs) == ["clk", "out", "rst"]
    out = SB._apply_order(_CAND_CORRECT_INLINE, block, segs, ["out", "clk", "rst"])
    assert out != _CAND_CORRECT_INLINE, "FIRED=False — the #742 reopen no-op"
    # `out` (golden slot 0) now precedes clk/rst in the rewritten header.
    hdr = out[out.index("("): out.index(");")]
    assert hdr.index("out") < hdr.index("clk") < hdr.index("rst"), out
    # the inline comment survives (never dropped — it travels with a port).
    assert "// active high" in out, out
    # body byte-preserved (pure permutation touches the header only).
    assert "out <= {out[2:0], out[3]^out[2]}" in out, out


def test_apply_order_reordered_rtl_compiles_against_positional_tb(tmp_path):
    """The reordered RTL (with its inline comment) ELABORATES against the
    outputs-first positional TB — proving the comment did not swallow a port."""
    if not _HAS_IVERILOG:
        pytest.skip("iverilog/vvp unavailable")
    g = SB._parse_portlist_segments(_CAND_CORRECT_INLINE, "lfsr")
    block, segs = g
    out = SB._apply_order(_CAND_CORRECT_INLINE, block, segs, ["out", "clk", "rst"])
    dut = tmp_path / "lfsr.v"
    dut.write_text(out)
    tb = tmp_path / "testbench.v"
    tb.write_text(_TB)
    with tempfile.TemporaryDirectory() as td:
        binp = Path(td) / "b"
        r = subprocess.run(
            ["iverilog", "-g2012", "-o", str(binp), str(dut), str(tb)],
            capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, (r.stdout + r.stderr)
        v = subprocess.run(["vvp", str(binp)], capture_output=True,
                           text=True, timeout=60)
    assert "Your Design Passed" in (v.stdout + v.stderr), (v.stdout + v.stderr)


def test_apply_order_wrong_name_set_aborts():
    """§4.05: a candidate whose port-name set != the golden order is NOT a pure
    permutation → _apply_order returns it UNCHANGED (never invents/renames)."""
    g = SB._parse_portlist_segments(_CAND_WRONG_NAME, "lfsr")
    block, segs = g
    # golden order names {out,clk,rst} but this candidate declares {out,clk,reset}
    out = SB._apply_order(_CAND_WRONG_NAME, block, segs, ["out", "clk", "rst"])
    assert out == _CAND_WRONG_NAME, "wrong-name set must abort (no rescue)"


def test_join_raw_segments_unclosed_block_comment_is_noop():
    """§4.05 robustness: an unclosed /* block comment makes the safe join bail
    (None) so _apply_order no-ops rather than emit corrupt RTL."""
    assert SB._join_raw_segments(["input a /* open", " input b"]) is None
    # a normal trailing line-comment is made safe (comma pushed to a fresh line).
    joined = SB._join_raw_segments(["input rst // active high", " input clk"])
    assert joined is not None
    assert "// active high\n," in joined, joined


# ════════════════════════ end-to-end through the real scorer ══════════════════

@_iv
def test_prefix_inline_comment_reproduces_compile_error(tmp_path):
    """REPRODUCE-現象 (no fix involved): the verbatim inputs-first candidate WITH
    the inline comment, bound by the outputs-first positional TB, fails iverilog
    elaboration — the round-11 floor the v1.0.80 normalizer failed to lift."""
    design, _samples, dataset = _build_run(tmp_path, candidate=_CAND_CORRECT_INLINE)
    dd = dataset / design
    dut = tmp_path / "verbatim.v"
    dut.write_text(_CAND_CORRECT_INLINE)
    with tempfile.TemporaryDirectory() as td:
        binp = Path(td) / "b"
        r = subprocess.run(
            ["iverilog", "-g2012", "-o", str(binp), str(dut),
             str(dd / "testbench.v")],
            capture_output=True, text=True, timeout=60)
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
def test_score_inline_comment_candidate_now_passes(tmp_path):
    """POST-FIX end-state: the score path proactively reorders the inline-comment
    candidate's ports to the golden positional order BEFORE the first compile, so
    the functionally-correct candidate PASSES (FIRED False→True end-state)."""
    design, samples, dataset = _build_run(tmp_path, candidate=_CAND_CORRECT_INLINE)
    # FIRED proof at the normalizer boundary.
    pre = (samples / f"{design}.v").read_text()
    norm = SC._proactive_positional_port_normalize_shape_b(
        pre, design, dataset, _LAYOUT)
    assert norm != pre, "normalizer must FIRE on the inline-comment sample"
    res = SC._score_shape_b(design, samples, dataset, _LAYOUT, _ARGS)
    assert res["verdict"] == "PASS", res
    assert res.get("reason") is None, res  # clean first-compile pass, not a rescue


@_iv
def test_score_wrong_name_candidate_still_fails(tmp_path):
    """§4.05: a WRONG-NAME candidate (declares `reset`, not the golden `rst`) is
    NOT rescued — the reorder aborts on the name-set mismatch and the positional
    TB still cannot bind it → FAIL/compile_error (never a false PASS)."""
    design, samples, dataset = _build_run(tmp_path, candidate=_CAND_WRONG_NAME)
    res = SC._score_shape_b(design, samples, dataset, _LAYOUT, _ARGS)
    assert res["verdict"] != "PASS", res


@_iv
def test_score_wrong_logic_candidate_still_fails(tmp_path):
    """§4.05: a wrong-LOGIC candidate with the right names/order is reordered but
    still runtime-FAILs the discriminating reference-model TB (the permutation
    never decides PASS/FAIL — the same vvp gate runs)."""
    design, samples, dataset = _build_run(tmp_path, candidate=_CAND_WRONG_LOGIC)
    res = SC._score_shape_b(design, samples, dataset, _LAYOUT, _ARGS)
    assert res["verdict"] == "FAIL", res


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
