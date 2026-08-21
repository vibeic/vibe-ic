#!/usr/bin/env python3
"""vibe-ic — an inferred latch written as `if` (vibe-ic#563).

`rule_case_coverage` answers "is every path assigning this signal?" for the
`case` form, carefully: it excludes clocked blocks (#770 r4), proves
exhaustiveness before warning (#764), resolves symbolic localparams (#770 r2).
None of it had an `if` counterpart, so the same defect in the more common
spelling passed silently.

The FALSE-POSITIVE tests below are the load-bearing half. A latch rule that
reddens a corpus gets deleted rather than obeyed, which is the #492 bar this had
to clear: measured over 331 synthesisable corpus files, 0 findings.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import rtl_hygiene_lint as L  # noqa: E402


def _findings(src: str):
    return [f for f in L.rule_if_no_else_latch(src, "t.v")
            if f.rule == "if-no-else-latch"]


# ---------------------------------------------------------------------------
# THE DEFECT — three spellings that were silent at v1.8.61
# ---------------------------------------------------------------------------

_STAR = """module m(input en, input [7:0] d, output reg [7:0] q);
always @(*) begin if (en) q = d; end
endmodule"""

_COMB = """module m(input en, input [7:0] d, output reg [7:0] q);
always_comb begin if (en) q = d; end
endmodule"""

_EXPLICIT = """module m(input en, input [7:0] d, output reg [7:0] q);
always @(en or d) begin if (en) q = d; end
endmodule"""


@pytest.mark.parametrize("src,label", [(_STAR, "always @(*)"),
                                       (_COMB, "always_comb"),
                                       (_EXPLICIT, "explicit sens list")])
def test_a_combinational_if_without_else_infers_a_latch(src, label):
    """`q` holds its value when `en` is low: combinational feedback in a design
    that will be timed as if it were not."""
    fs = _findings(src)
    assert len(fs) == 1, f"{label}: {fs}"
    assert fs[0].symbol == "q"


def test_the_message_names_both_remediations():
    """A finding a reader cannot act on gets waived. Both fixes are legitimate,
    so both are stated."""
    msg = _findings(_STAR)[0].message
    assert "else" in msg and "default" in msg


# ---------------------------------------------------------------------------
# NOT a latch — every one of these must stay silent
# ---------------------------------------------------------------------------

def test_a_clocked_if_is_an_enabled_flop_not_a_latch():
    """The register HOLDS on the untaken arm; that is the canonical enabled-flop
    idiom, not a latch. Reuses the #770 r4 clocked-span exclusion."""
    assert _findings("""module m(input clk, input en, input [7:0] d, output reg [7:0] q);
always @(posedge clk) begin if (en) q <= d; end
endmodule""") == []


def test_always_ff_is_also_clocked():
    """`_clocked_always_spans` must match the `_ff` flavour — the trailing
    underscore is a word character, so a `\\balways\\b` pattern misses it."""
    assert _findings("""module m(input clk, input en, input [7:0] d, output reg [7:0] q);
always_ff @(posedge clk) begin if (en) q <= d; end
endmodule""") == []


def test_both_arms_assigning_is_latch_free():
    """The question is the assigned SET, not the presence of an `else`."""
    assert _findings("""module m(input en, input [7:0] d, output reg [7:0] q);
always @(*) begin if (en) q = d; else q = 8'h00; end
endmodule""") == []


def test_an_unconditional_default_before_the_if_is_latch_free():
    """The pre-assignment holds on the untaken path — the same latch-free
    fallthrough `_case_body_defaulted` models for `case`."""
    assert _findings("""module m(input en, input [7:0] d, output reg [7:0] q);
always @(*) begin q = 8'h00; if (en) q = d; end
endmodule""") == []


def test_the_reset_idiom_is_not_flagged():
    assert _findings("""module m(input clk, input rst_n, input [7:0] d, output reg [7:0] q);
always @(posedge clk or negedge rst_n) begin
  if (!rst_n) q <= 8'h00; else q <= d;
end
endmodule""") == []


# ---------------------------------------------------------------------------
# the function/task exclusion — MEASURED, not anticipated
# ---------------------------------------------------------------------------

_CRC_FUNC = """module m;
  localparam [15:0] CRC_POLY = 16'h1021;
  function [15:0] crc16_step;
    input [15:0] crc;
    input        data_bit;
    reg          fb;
    begin
      fb = crc[15] ^ data_bit;
      crc16_step = {crc[14:0], 1'b0};
      if (fb) crc16_step = crc16_step ^ CRC_POLY;
    end
  endfunction
endmodule"""


def test_a_function_local_cannot_infer_a_latch():
    """BOTH findings over 331 synthesisable corpus files were this shape, and
    both were false. A function's locals are re-evaluated per call, so a variable
    assigned on one path holds nothing between calls. The unconditional-default
    suppression missed it because it searches back to the nearest `always`, and
    inside a function there is none. Taken verbatim from the corpus file that
    produced the finding (hdlc_core.v:150)."""
    assert _findings(_CRC_FUNC) == []


def test_a_task_body_is_excluded_the_same_way():
    assert _findings("""module m;
  reg [7:0] acc;
  task step; input en; input [7:0] d;
    begin
      acc = 8'h00;
      if (en) acc = d;
    end
  endtask
endmodule""") == []


def test_the_exclusion_does_not_swallow_code_after_endfunction():
    """A span that over-reaches to the end of the module would silence every
    real latch in any file that also declares a function — the same
    over-extension #770 r4 had to fix for clocked blocks."""
    fs = _findings(_CRC_FUNC.replace("endmodule", """
  always @(*) begin if (en2) q2 = d2; end
endmodule"""))
    assert len(fs) == 1 and fs[0].symbol == "q2", fs


# ---------------------------------------------------------------------------
# conservative where the `case` rule is conservative
# ---------------------------------------------------------------------------

def test_a_subscripted_lhs_is_not_claimed_to_be_covered():
    """A base-name assigned set cannot prove a sliced write is fully covered,
    so `_lhs_has_subscript` suppresses exactly as it does for `case`."""
    assert _findings("""module m(input en, input [7:0] d, output reg [7:0] q);
always @(*) begin if (en) q[3:0] = d[3:0]; end
endmodule""") == []


def test_the_rule_is_registered_in_the_run():
    """A rule nothing calls finds nothing — the shape this whole session keeps
    meeting."""
    import inspect
    assert "rule_if_no_else_latch" in inspect.getsource(L.lint_file)



# ---------------------------------------------------------------------------
# generate — selects which hardware EXISTS, so it cannot infer a latch.
# Two entry signals, and NEITHER subsumes the other (both measured on real ICs).
# ---------------------------------------------------------------------------

def test_a_named_generate_arm_is_not_a_latch():
    """SERV's form. No `generate` keyword appears anywhere in the file, so a
    keyword-only test would miss it — 11 of 18 findings on the tapeout ICs."""
    assert _findings("""module m #(parameter W = 2) (input en, input [7:0] d, output reg [7:0] q);
  generate
  if (W == 2) begin : gen_w_2
     reg [1:0] lsb;
  end else if (W == 4) begin : gen_lsb_w_4
     reg [1:0] lsb;
     reg [W-2:0] data_tail;
  end
  endgenerate
endmodule""") == []


def test_an_unlabelled_arm_inside_an_explicit_generate_is_not_a_latch():
    """`servile_mux.v:62`. The arm has no `: label`, so the named-block signal
    misses it and the explicit `generate` region is what identifies it."""
    assert _findings("""module m #(parameter [0:0] sim = 1'b0) (input clk);
  generate
     if (sim) begin
        integer f = 0;
        reg [1023:0] signature_file;
     end
  endgenerate
endmodule""") == []


def test_a_real_latch_inside_a_generate_is_STILL_reported():
    """THE over-exclusion guard. Excluding the whole generate REGION was tried
    first: it cleared every corpus false positive AND kept all four positive
    fixtures green, so it looked correct. This fixture is what caught it — an
    `always @(*)` inside a generate block infers a real latch, and a region-wide
    exclusion swallows it. Same over-extension #770 r4 had to fix for clocked
    blocks."""
    fs = _findings("""module m #(parameter W = 4) (input en, input [7:0] d, output reg [7:0] q);
generate
  if (W == 4) begin : g
    always @(*) begin if (en) q = d; end
  end
endgenerate
endmodule""")
    assert len(fs) == 1 and fs[0].symbol == "q", fs


# ---------------------------------------------------------------------------
# initial — runs once at time 0; models power-up, not held state
# ---------------------------------------------------------------------------

def test_an_initial_block_cannot_infer_a_latch():
    """`serv_ctrl.v:101` — a reset-strategy default written as
    `initial if (RESET_STRATEGY == "NONE") o_ibus_adr = RESET_PC;`."""
    assert _findings("""module m #(parameter RESET_STRATEGY = "MINI") (output reg [31:0] o_adr);
  initial if (RESET_STRATEGY == "NONE") o_adr = 32'h80000000;
endmodule""") == []


def test_code_after_an_initial_statement_is_still_analysed():
    """The `initial` span must cover its own statement and stop. Over-reach here
    would silence every latch in any file with an `initial`."""
    fs = _findings("""module m (input en, input [7:0] d, output reg [7:0] q);
  initial q = 8'h00;
  always @(*) begin if (en) q = d; end
endmodule""")
    assert len(fs) == 1, fs


# ---------------------------------------------------------------------------
# a default before a chain of conditional updates is latch-free
# ---------------------------------------------------------------------------

def test_a_default_followed_by_conditional_updates_is_latch_free():
    """Ibex's bit-manipulation unit (chip_top_sv2v.v:566-616): `rev_result =
    operand_a_i;` then five `if (zbp_shift_amt[n]) rev_result = ...`. The first
    implementation bailed out whenever the prefix held ANY `if`, so one block
    produced 14 false findings."""
    src = """module m(input [4:0] amt, input [31:0] a, output reg [31:0] r, output reg [31:0] s);
always @(*) begin
  r = a;
  s = a;
  if (amt[0]) r = r ^ 32'h5555_5555;
  if (amt[1]) s = s ^ 32'h3333_3333;
end
endmodule"""
    # MUTATION-CHECKED: `s` is first conditionally assigned by an `if` that has
    # ANOTHER `if` before it, so the old prefix test ("bail out if the prefix
    # holds any if/case") reports it and the new one does not. The earlier
    # fixture used a single signal, where the first `if` has no `if` before it —
    # both implementations suppressed it and the mutation survived.
    assert _findings(src) == []


def test_a_signal_the_default_does_NOT_cover_is_still_reported():
    """The suppression is per-signal. A block that defaults `r` and conditionally
    assigns `s` still latches `s`."""
    fs = _findings("""module m(input [4:0] amt, input [31:0] a, output reg [31:0] r, output reg [31:0] s);
always @(*) begin
  r = a;
  if (amt[0]) r = r ^ 32'h5555_5555;
  if (amt[1]) s = a;
end
endmodule""")
    assert len(fs) == 1 and fs[0].symbol == "s", fs


# ---------------------------------------------------------------------------
# an integrated clock gater IS a latch, and flagging it waives the whole rule
# ---------------------------------------------------------------------------

_ICG = """module prim_clock_gating(input clk_i, input en_i, input test_en_i, output clk_o);
  reg en_latch;
  always @* begin
    if (!clk_i) begin
      en_latch = en_i | test_en_i;
    end
  end
  assign clk_o = en_latch & clk_i;
endmodule"""


def test_a_clock_gating_cell_is_not_reported():
    """Ibex ships three copies of this. The rule is RIGHT — that is a latch — but
    it is the cell's entire purpose, and a rule that fires on every clock gater
    gets waived wholesale, taking the real findings with it."""
    assert _findings(_ICG) == []


def test_the_clock_gater_is_recognised_WITHOUT_reading_its_name():
    """Matching the `_latch` suffix would be exactly the text-proxy defect
    vibe-ic#561 catalogues, and a hand-written gater called `zzz` would slip
    through it."""
    assert _findings(_ICG.replace("en_latch", "zzz")) == []


def test_a_latch_gated_on_a_clock_but_NOT_gating_it_is_still_reported():
    """The load-bearing half of the clock-gater test: an ordinary latch never
    feeds an AND with its own enable condition. Without this, any `if (!clk)`
    latch would be silently excused."""
    fs = _findings("""module m(input clk_i, input [7:0] d, output reg [7:0] q, output o);
always @* begin if (!clk_i) q = d; end
assign o = q | clk_i;
endmodule""")
    assert len(fs) == 1 and fs[0].symbol == "q", fs

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
