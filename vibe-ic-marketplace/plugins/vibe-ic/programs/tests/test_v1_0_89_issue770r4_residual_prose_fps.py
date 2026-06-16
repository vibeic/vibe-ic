"""ORGANIC #770 round-4 — the last 2 of the 50-FP corpus.

r3 (v1.0.88) cleared enum_set but its handshake-loop-drive and comma-localparam
forms did NOT clear the two real cases (the root cause was deeper than the form
r3 targeted):

  1. spec_coverage handshake — a ready/valid DUT port driven to BOTH values by
     FLAT sequential statements (`m_tready=1; ... m_tready=0; ... m_tready=1;`),
     not only inside a loop, exercises the backpressure handshake. (The r3
     "≥2 distinct RHS drives" path already credits a flat toggle — this test
     pins it on the verbatim axis_joiner_0001 TB shape.)
  2. rtl_hygiene case-no-default — a `case` inside a CLOCKED (sequential) always
     block CANNOT infer a latch (the state register HOLDS its value on an
     unlisted selector code — the canonical registered-FSM idiom), so the
     case-no-default WARN is downgraded to ADVISORY. Latch risk is COMBINATIONAL
     only (binary_search_tree_sorting_0001).

§4.05 NO-LEAK: a handshake the TB NEVER drives still GAPs/BLOCKs; a partial case
in a COMBINATIONAL `always @(*)` with no default STILL hard-WARNs (real latch).
"""
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import spec_coverage_check as SC  # noqa: E402
import rtl_hygiene_lint as RH  # noqa: E402

_SPEC_COV = _PROGRAMS / "spec_coverage_check.py"
_HYGIENE = _PROGRAMS / "rtl_hygiene_lint.py"

_AJ_SPEC = ("# AXIS joiner\nThe joiner uses a standard valid/ready handshake "
            "with backpressure on the master stream.\n")
_AJ_RTL = ("module axis_joiner(input clk, input s_tvalid, output s_tready, "
           "output reg m_tvalid, input m_tready, output [7:0] m_tdata);\n"
           "endmodule\n")


def _speccov(tmp_path, spec, tb, rtl):
    (tmp_path / "s.md").write_text(spec)
    (tmp_path / "tb.sv").write_text(tb)
    (tmp_path / "r.sv").write_text(rtl)
    return subprocess.run(
        [sys.executable, str(_SPEC_COV), "--spec", str(tmp_path / "s.md"),
         "--rtl", str(tmp_path / "r.sv"), "--tb", str(tmp_path / "tb.sv"),
         "--strict"], capture_output=True, text=True)


def _hygiene(tmp_path, rtl, severity="WARN"):
    (tmp_path / "d.sv").write_text(rtl)
    import json
    jp = tmp_path / "out.json"
    proc = subprocess.run(
        [sys.executable, str(_HYGIENE), "--severity", severity,
         "--json", str(jp), str(tmp_path / "d.sv")],
        capture_output=True, text=True)
    findings = json.loads(jp.read_text()) if jp.exists() else []
    return proc, findings


# ── FP1: flat (non-loop) ready/valid toggle ──────────────────────────────────
def test_770r4_fp_flat_handshake_toggle_covered(tmp_path):
    tb = ("module tb; reg clk=0; reg s_tvalid; reg m_tready;\n"
          "axis_joiner u(.clk(clk), .s_tvalid(s_tvalid), .s_tready(), "
          ".m_tvalid(), .m_tready(m_tready), .m_tdata());\n"
          "always #5 clk=~clk;\n"
          "initial begin s_tvalid=1; m_tready=1;\n"
          "  repeat(9)@(posedge clk); @(negedge clk); m_tready=0;"
          " repeat(2)@(posedge clk); @(negedge clk); m_tready=1;\n"
          "  #20; $finish; end endmodule\n")
    r = _speccov(tmp_path, _AJ_SPEC, tb, _AJ_RTL)
    assert r.returncode == 0, r.stdout


def test_770r4_noleak_handshake_never_driven_still_blocks(tmp_path):
    tb = ("module tb; reg clk=0; reg s_tvalid; reg m_tready;\n"
          "axis_joiner u(.clk(clk), .s_tvalid(s_tvalid), .s_tready(), "
          ".m_tvalid(), .m_tready(m_tready), .m_tdata());\n"
          "initial begin s_tvalid=1; m_tready=1; #20; $finish; end endmodule\n")
    r = _speccov(tmp_path, _AJ_SPEC, tb, _AJ_RTL)
    assert r.returncode == 1, r.stdout


# ── FP2: sequential (clocked) case-no-default → advisory ─────────────────────
_BST_SEQ = (
    "module bst(input clk, input reset, input [1:0] sel, output reg [3:0] o);\n"
    " localparam IDLE=2'd0, LOAD=2'd1, RUN=2'd2;\n"
    " reg [1:0] top_state;\n"
    " always @(posedge clk or posedge reset) begin\n"
    "   if (reset) top_state <= IDLE;\n"
    "   else case (top_state)\n"
    "     IDLE: top_state <= LOAD; LOAD: top_state <= RUN; RUN: top_state <= IDLE;\n"
    "   endcase\n"
    " end\nendmodule\n")


def test_770r4_fp_clocked_case_no_default_advisory(tmp_path):
    proc, findings = _hygiene(tmp_path, _BST_SEQ, severity="WARN")
    # at --severity WARN the advisory (INFO) case finding is filtered out → no
    # case-no-default hard-block; rc not driven to 1 by it.
    case_hits = [f for f in findings if f["rule"] == "case-no-default"]
    assert all(f.get("block_eligible", True) is False for f in case_hits), findings
    # and it IS reported at INFO severity (advisory, not silently dropped).
    proc2, findings2 = _hygiene(tmp_path, _BST_SEQ, severity="INFO")
    adv = [f for f in findings2 if f["rule"] == "case-no-default"]
    assert adv and all(f["block_eligible"] is False for f in adv), findings2


def test_770r4_noleak_combinational_case_no_default_still_warns(tmp_path):
    rtl = ("module m(input [1:0] sel, output reg [3:0] o);\n"
           " always @(*) begin case (sel)\n"
           "   2'd0: o=0; 2'd1: o=1; 2'd2: o=2;\n"
           " endcase end\nendmodule\n")
    proc, findings = _hygiene(tmp_path, rtl, severity="WARN")
    hits = [f for f in findings if f["rule"] == "case-no-default"]
    assert hits and all(f.get("block_eligible", True) for f in hits), findings
    assert proc.returncode == 1


def test_770r4_clocked_always_spans_helper():
    spans = RH._clocked_always_spans(_BST_SEQ)
    assert spans  # the posedge-clk block is detected as clocked
    # a purely combinational module yields no clocked spans.
    assert RH._clocked_always_spans(
        "module m(input a, output reg o); always @(*) o=a; endmodule") == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


# ── r4 Step-2.7 remediation: span must not overshoot into a following block ──
def test_770r4_review_comb_case_after_clocked_block_still_warns(tmp_path):
    """r4 Step-2.7 §4.05: a COMBINATIONAL no-default case that textually FOLLOWS
    a clocked always block must STILL hard-WARN — the clocked span must end at
    the block's own `end`, not extend over the following case (the over-inclusive
    `_block_body_after` span was a reproduced HIGH leak)."""
    rtl = ("module m(input clk, input [1:0] sel, output reg o);\n"
           " always @(posedge clk) begin o <= 1'b0; end\n"
           " always @(*) begin case (sel)\n"
           "   2'd0: o = 1'b1; 2'd1: o = 1'b0;\n"
           " endcase end\nendmodule\n")
    proc, findings = _hygiene(tmp_path, rtl, severity="WARN")
    hits = [f for f in findings if f["rule"] == "case-no-default"]
    assert hits and all(f.get("block_eligible", True) for f in hits), findings
    assert proc.returncode == 1


def test_770r4_review_clocked_span_ends_at_matching_end():
    """The clocked span ends at the block's matching `end`, so a bare case
    statement after it is NOT inside the span."""
    src = ("module m(input clk, input [1:0] sel, output reg o);\n"
           " always @(posedge clk) begin o <= 1'b0; end\n"
           " case (sel) 2'd0: o=1; 2'd1: o=0; endcase\n"
           "endmodule\n")
    spans = RH._clocked_always_spans(src)
    case_off = src.index("case (sel)")
    assert not any(s <= case_off < e for s, e in spans), (spans, case_off)
