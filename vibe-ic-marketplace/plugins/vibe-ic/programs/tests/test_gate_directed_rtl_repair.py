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
def test_clocked_registered_output_is_not_deregistered():
    """The public clocked output owns sampling and cannot be rewritten away."""
    res = G.repair(RTL_MOORE, SPEC_CLOCKED)
    assert res["verdict"] == "NOT_APPLICABLE", res
    assert res["rtl"] is None
    assert res["transform"] is None
    import worked_example_sequence_oracle_check as W
    assert W.analyze(RTL_MOORE, SPEC_CLOCKED)["verdict"] == "PASS"


@pytest.mark.skipif(not _HAS_IVERILOG, reason="oracle needs iverilog")
@pytest.mark.parametrize("ambiguous", [False, True])
def test_phase_ambiguity_does_not_mask_independent_history_escalation(ambiguous):
    # An explicit conflicting output clause is genuinely phase-ambiguous;
    # a merely pre-edge/post-edge difference cannot cancel a clocked contract.
    spec = SPEC_CLOCKED + ("\n\nOutput data_out is combinational." if ambiguous else "")
    res = G.repair(RTL_FALLING_EDGE_WITH_CONSTANT_HISTORY_RESET, spec)
    assert res["rtl"] is None and res["transform"] is None
    if ambiguous:
        assert res["verdict"] == "ESCALATE", res
        assert res["defect"] == "edge-history-reset-to-constant"
        assert res["evidence"]["gate"] == "edge_history_reset_phantom_check"
    else:
        assert res["verdict"] == "NO_REPAIR", res
        assert res["evidence"]["one_cycle_late"] is False
        assert "clocked output" in res["reason"] and "register" in res["reason"]
        assert res["evidence"]["gate"] == "worked_example_sequence_oracle_check"


@pytest.mark.skipif(not _HAS_IVERILOG, reason="oracle needs iverilog")
def test_mismatch_that_is_not_a_one_cycle_shift_is_not_misrouted_as_alignment_repair():
    res = G.repair(RTL_REGISTERED_ALWAYS_ZERO, SPEC_CLOCKED)
    assert res["verdict"] == "NO_REPAIR", res
    assert res["defect"] == "worked-example-mismatch-not-a-cycle-shift"
    assert res["evidence"]["one_cycle_late"] is False
    assert res["attempts"] == []
    assert ("clocked output" in res["reason"] and "cannot authorise" in res["reason"]
            and "register" in res["reason"])


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


# ── vibe-ic#2178: the slow-corner wide-arithmetic class is ROUTED ────────────
# `arith_ss_corner_risk_check` ran at Step 2, wrote every row to
# `reports/phase2/gates/arith_ss_corner_risk.json`, and was read by NOTHING —
# while its step-mate `counter_decode_lookahead_phase_check` was routed here.
# MEASURED by lane cz2178 (2026-09-07) on two real authoring outputs of one
# design: 13 HIGH against 0 HIGH, and this module returned NOT_APPLICABLE / rc 0
# on BOTH. These tests drive the router, they do not grep the wiring — that
# distinction is the whole lesson of #2166.

_WIDE_ARITH_RTL = """
module round_dp(input clk, input rst_n,
                input [31:0] a, input [31:0] b, input [31:0] c,
                input [31:0] d, input [31:0] e,
                output reg [31:0] t1);
  always @(posedge clk) begin
    if (!rst_n) t1 <= 32'd0;
    else        t1 <= a + b + c + d + e;
  end
endmodule
"""

# The SAME datapath with the chain reduced. It carries a mitigation marker, so
# the checker is quiet on it — which is what makes this a control and not a
# second copy of the first case.
#
# THE MARKER IS AN IDENTIFIER IN THE CODE, NEVER A COMMENT (vibe-ic#2192).
# This control was first written with `// carry_save: reduced with 3:2
# compressors` and nothing else, which silenced the module on the tree #2178's
# branch was authored against. #2192 landed first and removed exactly that: the
# marker is now matched over the module NAME and the COMMENT-STRIPPED body, so
# the old control would have produced a HIGH row and this pair would have been
# two copies of the same case rather than a control. `wire [31:0] csa_s,
# csa_c;` is the form that still silences after #2192, and the direction that
# issue preserved on purpose.
_REDUCED_RTL = """
module round_dp(input clk, input rst_n,
                input [31:0] a, input [31:0] b, output reg [31:0] t1);
  wire [31:0] csa_s, csa_c;
  always @(posedge clk) begin
    if (!rst_n) t1 <= 32'd0;
    else        t1 <= a + b;
  end
endmodule
"""

# A SECOND control with no marker at all, so "the router said NOT_APPLICABLE"
# is proved once by a module whose rows were WITHHELD and once by a module that
# never produced a row. Without this one, every NOT_APPLICABLE below could be
# resting on the suppression path alone.
_NARROW_RTL = """
module round_dp(input clk, input rst_n,
                input [7:0] a, input [7:0] b, output reg [7:0] t1);
  always @(posedge clk) begin
    if (!rst_n) t1 <= 8'd0;
    else        t1 <= a + b;
  end
endmodule
"""


def test_wide_arithmetic_is_routed_ESCALATE_with_its_count():
    res = G.repair(_WIDE_ARITH_RTL, SPEC)
    assert res["verdict"] == "ESCALATE", res
    assert res["defect"] == "slow-corner-wide-arithmetic"
    ev = res["evidence"]
    assert ev["gate"] == "arith_ss_corner_risk_check"
    # the COUNT reaches the router, not just the fact of a finding
    assert ev["high_findings"] == 1
    assert ev["finding"]["symbol"] == "t1"
    assert ev["finding"]["width"] == 32
    # and the row's own honesty survives the trip: this is a PREDICTION
    assert ev["finding"]["measured"] is False
    assert ev["finding"]["basis"] == "predicted-from-rtl-structure"
    assert res["escalate_to"] and res["why_not_bucket_a"]


def test_the_routing_MOVES_on_this_checker_alone():
    """The direction that makes it a wiring and not a label: with the chain
    reduced, the same module reaches NOT_APPLICABLE — proved on both shapes of
    quiet, a module whose rows a code marker WITHHELD and a module that never
    produced a row at all."""
    assert G.repair(_REDUCED_RTL, SPEC)["verdict"] == "NOT_APPLICABLE"
    assert G.repair(_NARROW_RTL, SPEC)["verdict"] == "NOT_APPLICABLE"


def test_the_control_is_quiet_for_the_reason_it_claims():
    """A control that is quiet for the WRONG reason proves nothing about the
    branch above it. `_REDUCED_RTL` must be quiet because a marker IN CODE
    withheld its rows (vibe-ic#2192) and `_NARROW_RTL` because it has no rows,
    and the same text with the marker demoted to a comment must be LOUD."""
    ass = pytest.importorskip("arith_ss_corner_risk_check")
    withheld = []
    assert ass.analyse_text(_REDUCED_RTL, "<rtl>", suppressed=withheld) == []
    assert len(withheld) == 1 and withheld[0].withheld >= 1

    never = []
    assert [f for f in ass.analyse_text(_NARROW_RTL, "<rtl>", suppressed=never)
            if f.risk == "HIGH"] == []
    assert never == []

    commented = _REDUCED_RTL.replace(
        "  wire [31:0] csa_s, csa_c;\n", "  // carry_save reduced\n")
    assert [f for f in ass.analyse_text(commented) if f.risk == "HIGH"], (
        "a mitigation named only in a comment must not silence the module "
        "(vibe-ic#2192) — if this is empty the control above is quiet for a "
        "reason that no longer exists")


def test_the_class_is_never_a_repair_and_never_a_FAIL():
    """It may not rewrite RTL and it may not refuse a delivery. Every row the
    gate emits is PREDICTED, and a prediction may not buy a refusal (#2063)."""
    res = G.repair(_WIDE_ARITH_RTL, SPEC)
    assert res["rtl"] is None and res["transform"] is None
    assert res["verdict"] != "REPAIRED"


def test_the_register_entry_is_what_the_dispatches_read():
    """`design_one_shot_runner.step_determinism_gates` looks this entry up
    rather than restating the routing, so removing it must break that dispatch
    loudly. Pin the KEY and the two fields both readers use."""
    entry = G.NOT_REPAIRABLE["slow-corner-wide-arithmetic"]
    assert entry["gate"] == "arith_ss_corner_risk_check"
    assert entry["why_not_bucket_a"] and entry["escalate_to"]


def test_removing_the_routing_branch_goes_red(tmp_path):
    """THE MUTATION CONTROL, run against a real copy of the module with the
    branch deleted. Without this, every test above could be passing because
    some OTHER branch happens to answer — the check would not be a check."""
    src = (_PROGRAMS / "gate_directed_rtl_repair.py").read_text()
    marker = "        import arith_ss_corner_risk_check as _ass\n"
    assert src.count(marker) == 1, "the mutation has nothing to remove"
    start = src.index(marker)
    end = src.index("    except Exception:\n        pass\n", start) + len(
        "    except Exception:\n        pass\n")
    mutated = src[:start - len("    try:\n")] + src[end:]
    mod_dir = tmp_path / "progs"
    shutil.copytree(_PROGRAMS, mod_dir, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("tests", "__pycache__"))
    (mod_dir / "gate_directed_rtl_repair.py").write_text(mutated)
    sys.path.insert(0, str(mod_dir))
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_gdr_mutated", mod_dir / "gate_directed_rtl_repair.py")
        mut = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mut)
    finally:
        sys.path.remove(str(mod_dir))
    got = mut.repair(_WIDE_ARITH_RTL, SPEC)["verdict"]
    assert got == "NOT_APPLICABLE", (
        "with the routing branch deleted the router must fall back to "
        f"NOT_APPLICABLE — got {got}. If this is still ESCALATE the tests "
        "above are passing for a reason other than the branch they name.")


# ── the phase-2 dispatch that reads the register above ──────────────────────
# The second consumer. `step_determinism_gates` looks the routing up in
# `NOT_REPAIRABLE` rather than restating it, so deleting the entry breaks this
# dispatch loudly instead of leaving the step printing a route nobody honours.

def _run_determinism(tmp_path, rtl_by_name):
    import design_one_shot_runner as R  # noqa: E402
    proj = tmp_path / "proj"
    rtl_dir = proj / "phase2" / "stage1" / "rtl"
    rtl_dir.mkdir(parents=True)
    for name, text in rtl_by_name.items():
        (rtl_dir / name).write_text(text)
    res = R.step_determinism_gates(proj)
    return res, (getattr(res, "extras", None) or {}).get(
        "arith_ss_corner_risk_advisory")


def test_phase2_dispatch_reports_the_count_and_routes_it(tmp_path):
    res, row = _run_determinism(tmp_path, {"dp.v": _WIDE_ARITH_RTL})
    assert row is not None, "the row must be written"
    assert row["verdict"] == "FINDING"
    assert row["high_findings"] == 1          # THE COUNT, on the row
    assert row["files_scanned"] == 1
    assert row["router_verdict"] == "ESCALATE"
    assert row["gate"] == "arith_ss_corner_risk_check"
    assert row["blocking"] is False
    assert row["findings"][0]["symbol"] == "t1"


def test_phase2_dispatch_writes_the_row_even_when_the_scan_is_clean(tmp_path):
    """A row that appears only on a finding cannot tell `ran and found
    nothing` from `never ran` — which is the exact defect #2178 names."""
    res, row = _run_determinism(tmp_path / "withheld", {"dp.v": _REDUCED_RTL})
    assert row is not None
    assert row["verdict"] == "PASS"
    assert row["high_findings"] == 0
    assert row["router_verdict"] == "NOT_APPLICABLE"
    # and it is not written as a CLEAN one: vibe-ic#2192's rule holds in this
    # row too, so a module a marker silenced is distinguishable from one with
    # no wide adders in it.
    assert row["suppressed_modules"] == 1
    assert row["suppressed"][0]["module"] == "round_dp"
    assert row["suppressed"][0]["withheld"] >= 1

    _res2, clean = _run_determinism(tmp_path / "clean", {"dp.v": _NARROW_RTL})
    assert clean is not None
    assert clean["verdict"] == "PASS" and clean["high_findings"] == 0
    assert clean["suppressed_modules"] == 0 and clean["suppressed"] == []
    assert clean != row


def test_phase2_dispatch_never_moves_the_step_verdict(tmp_path):
    """The advisory may not refuse a delivery, in either direction."""
    hot, _ = _run_determinism(tmp_path / "hot", {"dp.v": _WIDE_ARITH_RTL})
    cold, _ = _run_determinism(tmp_path / "cold", {"dp.v": _REDUCED_RTL})
    assert hot.status == cold.status
