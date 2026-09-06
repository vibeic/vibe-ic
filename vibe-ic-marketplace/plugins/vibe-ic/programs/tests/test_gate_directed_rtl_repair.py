"""Tests for gate_directed_rtl_repair.py — the loop that ACTS on a blocking
gate's own verdict instead of shipping nothing.

The load-bearing test here is NOT "the repair works". It is
`test_candidate_that_still_fails_is_discarded`: the whole design rests on the
claim that acceptance comes from an INDEPENDENT MEASURING oracle, so a candidate
that applies cleanly and COMPILES but still does not reproduce the spec's
disclosed trace must be thrown away. If that test ever goes green for the wrong
reason, the loop is free to ship broken RTL under a green gate — strictly worse
than the honest rejection it replaced.

The statement-scanner tests pin the corpus-sweep defect: a first cut used a
regex for `<=` and read the COMPARISON in `if (cnt <= 5)` as an assignment,
corrupting 24 of 6265 corpus RTL files.
"""
import shutil
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import gate_directed_rtl_repair as G  # noqa: E402

_HAS_IVERILOG = shutil.which("iverilog") is not None

SPEC = ("Implement a pulse detector. data_in is a 1-bit input. data_out is 1 "
        "the cycle the pulse completes. For example, if data_in is 01010, the "
        "data_out is 00101.")
SPEC_CLOCKED = (
    SPEC + " Inside an always block, sensitive to the positive edge of clk, "
    "implement pulse detection and output generation. Set data_out to 1 in "
    "the end cycle of the pulse."
)

# Registered (Moore) output — reproduces the right sequence one cycle late.
RTL_MOORE = """
module pulse_detect(input clk, input rst_n, input data_in, output reg data_out);
  localparam IDLE=2'd0, GOT1=2'd1;
  reg [1:0] state;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) begin state<=IDLE; data_out<=1'b0; end
    else case(state)
      IDLE: begin state <= data_in ? GOT1 : IDLE; data_out<=1'b0; end
      GOT1: begin state <= data_in ? GOT1 : IDLE; data_out <= ~data_in; end
      default: begin state<=IDLE; data_out<=1'b0; end
    endcase
endmodule
"""

# Correct same-cycle form — the loop must not touch it.
RTL_MEALY = """
module pulse_detect(input clk, input rst_n, input data_in, output data_out);
  localparam IDLE=2'd0, GOT1=2'd1;
  reg [1:0] state;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) state<=IDLE;
    else case(state)
      IDLE: state <= data_in ? GOT1 : IDLE;
      GOT1: state <= data_in ? GOT1 : IDLE;
      default: state <= IDLE;
    endcase
  assign data_out = (state==GOT1) & ~data_in;
endmodule
"""

# Output lags by THREE cycles: the transform applies and the result COMPILES,
# but removing one cycle still leaves it two cycles late.
RTL_TOO_LATE = """
module pulse_detect(input clk, input rst_n, input data_in, output reg data_out);
  reg d1, d2;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) begin d1<=1'b0; d2<=1'b0; data_out<=1'b0; end
    else begin d1 <= data_in; d2 <= d1; data_out <= d2; end
endmodule
"""

RTL_REGISTERED_ALWAYS_ZERO = """
module pulse_detect(input clk, input rst_n, input data_in, output reg data_out);
  always @(posedge clk or negedge rst_n)
    if (!rst_n) data_out <= 1'b0;
    else data_out <= 1'b0;
endmodule
"""

RTL_FALLING_EDGE_WITH_CONSTANT_HISTORY_RESET = """
module pulse_detect(input clk, input rst_n, input data_in, output data_out);
  reg prev;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) prev <= 1'b0;
    else prev <= data_in;
  assign data_out = prev & ~data_in;
endmodule
"""


# ── the statement scanner (no iverilog needed) ──────────────────────────────
def test_comparison_le_is_not_an_assignment():
    """`if (cnt <= 5)` must not be read as an assignment to cnt — the corpus
    sweep defect that corrupted 24 files."""
    src = "always @(posedge clk) if (cnt <= 5) q <= 1'b1;"
    masked = G._blank_noncode(src)
    names = [a[2] for a in G._stmt_assignments(masked, 0, len(masked))]
    assert "cnt" not in names
    assert "q" in names


def test_indexed_target_is_excluded():
    src = "always @(posedge clk) begin mem[i] <= d; q <= e; end"
    masked = G._blank_noncode(src)
    assert [a[2] for a in G._assignments_to(masked, 0, len(masked), "q")] == []\
        or G._assignments_to(masked, 0, len(masked), "mem") == []


def test_comment_text_is_not_parsed_as_code():
    src = "always @(posedge clk) begin // q <= 1'b0;\n  r <= 1'b1; end"
    masked = G._blank_noncode(src)
    names = [a[2] for a in G._stmt_assignments(masked, 0, len(masked))]
    assert names == ["r"]
    assert len(masked) == len(src)          # offsets stay aligned


# ── transform preconditions (no iverilog needed) ────────────────────────────
def test_transform_declines_when_output_is_continuously_assigned():
    assert G.deregister_output(RTL_MEALY, "data_out") is None


def test_transform_declines_on_a_named_block():
    """A named block is a scope name; duplicating it breaks elaboration."""
    rtl = ("module m(input clk, output reg q);\n"
           "  always @(posedge clk) begin : wr\n    q <= 1'b1;\n  end\n"
           "endmodule\n")
    assert G.deregister_output(rtl, "q") is None


def test_transform_preserves_case_structure():
    out = G.deregister_output(RTL_MOORE, "data_out")
    assert out is not None
    # the clocked block keeps the state transitions and loses the output
    clocked = out.split("always @(*)")[0]
    assert "state <= data_in ? GOT1 : IDLE" in clocked
    assert "data_out" not in clocked.split("output reg data_out")[-1]
    # the combinational copy carries the output and drops the state writes
    comb = out.split("always @(*)")[1]
    assert "data_out  = ~data_in" in comb or "data_out = ~data_in" in comb
    assert "state <=" not in comb


# ── the loop, end to end (needs iverilog: the oracle simulates) ─────────────
@pytest.mark.skipif(not _HAS_IVERILOG, reason="oracle needs iverilog")
def test_moore_output_is_repaired_and_reverified():
    res = G.repair(RTL_MOORE, SPEC)
    assert res["verdict"] == "REPAIRED"
    assert res["defect"] == "output-cycle-alignment"
    assert res["transform"] == "deregister_output"
    # the repaired text must itself pass the oracle that raised the finding
    import worked_example_sequence_oracle_check as W
    assert W.analyze(res["rtl"], SPEC)["verdict"] == "PASS"


@pytest.mark.skipif(not _HAS_IVERILOG, reason="oracle needs iverilog")
def test_correct_design_is_left_alone():
    res = G.repair(RTL_MEALY, SPEC)
    assert res["verdict"] == "NOT_APPLICABLE"
    assert res["rtl"] is None


@pytest.mark.skipif(not _HAS_IVERILOG, reason="oracle needs iverilog")
def test_clocked_registered_output_is_repaired_not_deferred():
    """It used to DEFER here: the oracle SKIPped because the spec's prose said the
    output is assigned inside the clocked block, so the one-cycle-late RTL was
    shipped unrepaired. The oracle now reads its verdict at the example's own
    alignment, so the same defect reaches the same transform as the non-clocked
    spelling of the same spec."""
    res = G.repair(RTL_MOORE, SPEC_CLOCKED)
    assert res["verdict"] == "REPAIRED", res
    assert res["defect"] == "output-cycle-alignment"
    assert res["transform"] == "deregister_output"
    import worked_example_sequence_oracle_check as W
    assert W.analyze(res["rtl"], SPEC_CLOCKED)["verdict"] == "PASS"


@pytest.mark.skipif(not _HAS_IVERILOG, reason="oracle needs iverilog")
def test_phase_ambiguity_does_not_mask_independent_history_escalation():
    res = G.repair(RTL_FALLING_EDGE_WITH_CONSTANT_HISTORY_RESET, SPEC_CLOCKED)
    assert res["verdict"] == "ESCALATE", res
    assert res["defect"] == "edge-history-reset-to-constant"
    assert res["evidence"]["gate"] == "edge_history_reset_phantom_check"


@pytest.mark.skipif(not _HAS_IVERILOG, reason="oracle needs iverilog")
def test_mismatch_that_is_not_a_one_cycle_shift_is_not_misrouted_as_alignment_repair():
    res = G.repair(RTL_REGISTERED_ALWAYS_ZERO, SPEC_CLOCKED)
    assert res["verdict"] == "NO_REPAIR", res
    assert res["defect"] == "worked-example-mismatch-not-a-cycle-shift"
    assert res["evidence"]["one_cycle_late"] is False
    assert res["attempts"] == []
    assert "would be a guess" in res["reason"]


@pytest.mark.skipif(not _HAS_IVERILOG, reason="oracle needs iverilog")
def test_candidate_that_still_fails_is_discarded():
    """THE load-bearing test. The transform applies and the result compiles,
    but the trace is still wrong — so the oracle must refuse it and the loop
    must return no RTL. Acceptance comes from the MEASUREMENT, never from the
    transform having succeeded syntactically."""
    res = G.repair(RTL_TOO_LATE, SPEC)
    assert res["verdict"] == "NO_REPAIR"
    assert res["rtl"] is None
    assert res["attempts"][0]["oracle_verdict"] == "BLOCK"


@pytest.mark.skipif(not _HAS_IVERILOG, reason="oracle needs iverilog")
def test_a_skip_is_not_mistaken_for_acceptance():
    """If a candidate makes the oracle INAPPLICABLE (e.g. it no longer
    elaborates) the verdict is SKIP, which must never be read as a pass."""
    res = G.repair(RTL_MOORE, SPEC)
    assert res["verdict"] == "REPAIRED"
    # sanity: the acceptance branch keys on PASS explicitly, not on "not BLOCK"
    src = (Path(G.__file__).read_text())
    assert 'after.get("verdict") == "PASS"' in src


# ── the class that is deliberately NOT repaired ─────────────────────────────
def test_phase_form_is_escalated_with_a_stated_reason():
    """A purely STRUCTURAL gate has no independent oracle to accept a repair,
    so the loop must route it out rather than satisfy the pattern."""
    rtl = """
module divider(input clk, input rst, output clk_div);
  reg clk_div1, clk_div2; reg [3:0] c1, c2;
  always @(posedge clk) if(!rst) begin c1<=0; clk_div1<=1'b0; end
    else if (c1 == 4'd2) begin c1<=0; clk_div1 <= ~clk_div1; end else c1<=c1+1;
  always @(negedge clk) if(!rst) begin c2<=0; clk_div2<=1'b0; end
    else if (c2 == 4'd2) begin c2<=0; clk_div2 <= ~clk_div2; end else c2<=c2+1;
  assign clk_div = clk_div1 | clk_div2;
endmodule
"""
    res = G.repair(rtl, "A clock divider with no worked example in its prose.")
    assert res["verdict"] == "ESCALATE"
    assert res["defect"] == "clock-divider-phase-form"
    assert "why_not_bucket_a" in res and len(res["why_not_bucket_a"]) > 80
    assert "escalate_to" in res


def test_not_repairable_registry_states_a_reason_for_every_entry():
    for name, info in G.NOT_REPAIRABLE.items():
        assert info.get("why_not_bucket_a"), name
        assert info.get("escalate_to"), name
        assert info.get("gate"), name


def test_module_is_chip_agnostic():
    """No design name, no benchmark literal, no expected value in the logic."""
    src = Path(G.__file__).read_text()
    code = "\n".join(l for l in src.splitlines()
                     if not l.strip().startswith("#"))
    for tok in ("rtllm", "cvdp", "verilogeval", "freq_div", "signal_generator",
                "ring_counter"):
        assert tok not in code.lower(), tok
