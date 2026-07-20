"""ORGANIC #810 — single-1-bit-input Moore transition-FUNCTION conformance.

The #522 structural check + #791 one-hot continuous-assign extension both SKIP
the most common FSM shape: a `case (state)`-or-inline Moore machine whose
next-state is a ternary (`next = in ? X : Y`). A fresh author can wire the
RIGHT edge SET but the WRONG per-input mapping — e.g. a state-INDEPENDENT
`state <= in ? B : A` for a spec whose transitions are state-DEPENDENT. Every
structural lint passes, yet the hidden TB mismatches on every cycle exercising
the wrong arm.

MEASURED (VerilogEval iccad2023, open-bench round-17): the human samples for
Prob109_fsm1 (79/228 hidden-TB mismatches) and Prob107_fsm1s (118/230) ship
exactly this state-INDEPENDENT-vs-state-DEPENDENT defect while passing every
gate. The prompt discloses the intended transition table in an arrow grammar
(`B (1) --0--> A`), so with `--spec` the gate CAN evaluate the RTL's next-state
ternary for in in {0,1} per state and compare.

`check_single_input_moore(rtl, spec)` closes the hole, scoped TIGHT (§4.05
NO-FALSE-BLOCK): only a single-1-bit-input FULL Moore arrow table + a
case/inline Moore RTL whose every state's next-state is a resolvable ternary is
CHECKED; two-input / Mealy / arbiter / one-hot-equation prompts SKIP, as does
any RTL arm that is not a clean ternary. Only the NEXT-state mismatch is an
ERROR; the output mismatch is INFO (never blocks).

NO-CHEAT: reads ONLY the prompt (the legitimate spec) + the candidate RTL —
never the hidden TB / _ref.sv. chip-AGNOSTIC: synthetic FSMs + arrow grammar,
no chip/state literal. Where the real on-disk dataset/round-17 artifacts are
present they are asserted directly (content-gated so a LIVE-corpus overwrite
skips rather than false-fails).
"""
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import fsm_transition_completeness_check as F  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402


# A 2-state Moore FSM whose transitions are STATE-DEPENDENT (from A on in=0 go
# to B; from B on in=0 go to A). The arrow grammar discloses the intended table.
_SPEC_2STATE = """\
Consider the follow Moore machine with the diagram described below:

  B (1) --0--> A
  B (1) --1--> B
  A (0) --0--> B
  A (0) --1--> A

Write Verilog implementing this state machine.
"""

# WRONG: state-INDEPENDENT `state <= in ? B : A` — implements (A,0)->A and
# (A,1)->B, contradicting the spec's (A,0)->B / (A,1)->A.
_RTL_WRONG_INLINE = """\
module TopModule(input clk, input in, input areset, output out);
  localparam A = 1'b0, B = 1'b1;
  reg state;
  always @(posedge clk or posedge areset)
    if (areset) state <= B;
    else        state <= in ? B : A;
  assign out = (state == B);
endmodule
"""

# CORRECT: state-DEPENDENT case form matching the spec exactly.
_RTL_CORRECT_CASE = """\
module TopModule(input clk, input in, input areset, output out);
  localparam A = 1'b0, B = 1'b1;
  reg state;
  always @(posedge clk or posedge areset)
    if (areset) state <= B;
    else case (state)
      A: state <= in ? A : B;
      B: state <= in ? B : A;
    endcase
  assign out = (state == B);
endmodule
"""


def _n_err(rtl, spec):
    findings, status = F.check_single_input_moore(rtl, spec)
    return sum(1 for f in findings if f.severity == "ERROR"), status


# --------------------------------------------------------------------------- #
# Core: wrong → FAIL ; correct → PASS.                                        #
# --------------------------------------------------------------------------- #
def test_state_independent_for_state_dependent_table_is_flagged():
    n, status = _n_err(_RTL_WRONG_INLINE, _SPEC_2STATE)
    assert status == "CHECKED-MOORE"
    assert n >= 1
    findings, _ = F.check_single_input_moore(_RTL_WRONG_INLINE, _SPEC_2STATE)
    assert any(f.rule == "fsm-prompt-transition-mismatch" for f in findings)


def test_correct_state_dependent_case_passes():
    n, status = _n_err(_RTL_CORRECT_CASE, _SPEC_2STATE)
    assert status == "CHECKED-MOORE"
    assert n == 0


def test_negated_condition_with_swapped_operands_passes():
    # `!in ? B : A` is logically `in ? A : B`. For state A the spec wants
    # in=0 -> B, in=1 -> A — so `A: state <= !in ? B : A`. Must NOT false-fire.
    rtl = _RTL_CORRECT_CASE.replace(
        "A: state <= in ? A : B;", "A: state <= !in ? B : A;").replace(
        "B: state <= in ? B : A;", "B: state <= !in ? A : B;")
    n, status = _n_err(rtl, _SPEC_2STATE)
    assert status == "CHECKED-MOORE"
    assert n == 0


def test_wrong_but_reachable_target_is_flagged():
    # 6-state binary FSM, single input w. Disclosed (D,w=1)->A; author wrote F.
    spec = """\
  A (0) --0--> B
  A (0) --1--> A
  B (0) --0--> C
  B (0) --1--> D
  C (0) --0--> E
  C (0) --1--> D
  D (0) --0--> F
  D (0) --1--> A
  E (1) --0--> E
  E (1) --1--> D
  F (1) --0--> C
  F (1) --1--> D
"""
    rtl = """\
module TopModule(input clk, input reset, input w, output z);
  localparam A=0,B=1,C=2,D=3,E=4,F=5;
  reg [2:0] state, next;
  always @(*) case(state)
    A: next = w ? A : B;
    B: next = w ? D : C;
    C: next = w ? D : E;
    D: next = w ? F : F;   // BUG: (D,w=1) should be A
    E: next = w ? D : E;
    F: next = w ? D : C;
    default: next = A;
  endcase
  always @(posedge clk) if(reset) state<=A; else state<=next;
  assign z = (state==E)||(state==F);
endmodule
"""
    n, status = _n_err(rtl, spec)
    assert status == "CHECKED-MOORE"
    findings, _ = F.check_single_input_moore(rtl, spec)
    assert any(f.rule == "fsm-prompt-transition-mismatch" and f.state == "D"
               for f in findings)


# --------------------------------------------------------------------------- #
# §4.05 NO-FALSE-BLOCK — out-of-scope shapes must SKIP, not flag.             #
# --------------------------------------------------------------------------- #
def test_two_input_prompt_skips():
    spec = """\
  OFF (out=0) --j=0--> OFF
  OFF (out=0) --j=1--> ON
  ON  (out=1) --k=0--> ON
  ON  (out=1) --k=1--> OFF
"""
    rtl = """\
module TopModule(input clk, input j, input k, input areset, output out);
  localparam OFF=0, ON=1; reg state;
  always @(posedge clk or posedge areset)
    if (areset) state<=OFF;
    else case(state) OFF: state<=j?ON:OFF; ON: state<=k?OFF:ON; endcase
  assign out=(state==ON);
endmodule
"""
    findings, status = F.check_single_input_moore(rtl, spec)
    assert status == "SKIP-prompt-not-single-input-moore"
    assert findings == []


def test_mealy_edge_output_prompt_skips():
    spec = """\
  A --x=0 (z=0)--> A
  A --x=1 (z=1)--> B
  B --x=0 (z=1)--> B
  B --x=1 (z=0)--> B
"""
    rtl = "module TopModule(input clk,input areset,input x,output z); endmodule\n"
    _, status = F.check_single_input_moore(rtl, spec)
    assert status == "SKIP-prompt-not-single-input-moore"


def test_arbiter_multi_input_prompt_skips():
    spec = """\
  A --r1=0,r2=0,r3=0--> A
  A --r1=1--> B
  B (g1=1) --r1=1--> B
  B (g1=1) --r1=0--> A
"""
    rtl = "module TopModule(input clk,input resetn,input [3:1] r,output [3:1] g); endmodule\n"
    _, status = F.check_single_input_moore(rtl, spec)
    assert status == "SKIP-prompt-not-single-input-moore"


def test_comparison_condition_arm_skips_not_flags():
    # `(in==1'b1) ? ...` is not a bare-ident ternary cond — must SKIP, not flag.
    rtl = _RTL_CORRECT_CASE.replace("in ? ", "(in==1'b1) ? ")
    findings, status = F.check_single_input_moore(rtl, _SPEC_2STATE)
    assert status.startswith("SKIP")
    assert findings == []


def test_no_transition_table_prompt_skips():
    _, status = F.check_single_input_moore(
        _RTL_CORRECT_CASE, "A free-text spec with no arrow transition table.\n")
    assert status == "SKIP-prompt-not-single-input-moore"


def test_default_arm_does_not_false_block():
    rtl = _RTL_CORRECT_CASE.replace(
        "    endcase", "      default: state <= A;\n    endcase")
    n, status = _n_err(rtl, _SPEC_2STATE)
    assert status == "CHECKED-MOORE"
    assert n == 0


# --------------------------------------------------------------------------- #
# Real on-disk artifacts (content-gated; SKIP if the corpus path is absent).  #
# --------------------------------------------------------------------------- #
_DATASET = corpus_path("_extbench/verilog-eval/dataset_code-complete-iccad2023")
_R17 = corpus_path("_bench_open_v100_r17")


@pytest.mark.parametrize("prob", ["Prob109_fsm1", "Prob107_fsm1s"])
def test_real_round17_human_wrong_sample_is_flagged(prob):
    rtl_p = _R17 / "verilogeval-human" / "samples" / f"{prob}_sample01.sv"
    spec_p = _DATASET / f"{prob}_prompt.txt"
    if not rtl_p.is_file() or not spec_p.is_file():
        pytest.skip("round-17 / dataset corpus not present")
    n, status = _n_err(rtl_p.read_text(), spec_p.read_text())
    assert status == "CHECKED-MOORE"
    assert n >= 1


@pytest.mark.parametrize("prob", [
    "Prob107_fsm1s", "Prob109_fsm1", "Prob110_fsm2", "Prob111_fsm2s",
    "Prob136_m2014_q6", "Prob138_2012_q2fsm", "Prob088_ece241_2014_q5b",
    "Prob091_2012_q2b", "Prob099_m2014_q6c", "Prob135_m2014_q6b",
    "Prob143_fsm_onehot", "Prob148_2013_q2afsm",
    "Prob150_review2015_fsmonehot"])
def test_real_golden_refs_never_false_block(prob):
    ref_p = _DATASET / f"{prob}_ref.sv"
    spec_p = _DATASET / f"{prob}_prompt.txt"
    if not ref_p.is_file() or not spec_p.is_file():
        pytest.skip("dataset corpus not present")
    n, _ = _n_err(ref_p.read_text(), spec_p.read_text())
    assert n == 0, f"golden ref {prob} false-blocked"


@pytest.mark.parametrize("variant", ["human", "v2"])
@pytest.mark.parametrize("prob", [
    "Prob110_fsm2", "Prob111_fsm2s", "Prob136_m2014_q6", "Prob138_2012_q2fsm",
    "Prob088_ece241_2014_q5b", "Prob091_2012_q2b", "Prob099_m2014_q6c",
    "Prob135_m2014_q6b", "Prob143_fsm_onehot", "Prob148_2013_q2afsm",
    "Prob150_review2015_fsmonehot"])
def test_real_correct_samples_never_false_block(variant, prob):
    rtl_p = _R17 / f"verilogeval-{variant}" / "samples" / f"{prob}_sample01.sv"
    spec_p = _DATASET / f"{prob}_prompt.txt"
    if not rtl_p.is_file() or not spec_p.is_file():
        pytest.skip("round-17 / dataset corpus not present")
    n, _ = _n_err(rtl_p.read_text(), spec_p.read_text())
    assert n == 0, f"correct sample {variant}/{prob} false-blocked"


@pytest.mark.parametrize("variant", ["human", "v2"])
def test_real_v2_prob107_109_correct_not_flagged(variant):
    # v2 Prob107/109 use the state-DEPENDENT case form (correct) for the SAME
    # prompt the human variant gets wrong — proves the gate evaluates the
    # transition FUNCTION, not a structural heuristic.
    for prob in ("Prob107_fsm1s", "Prob109_fsm1"):
        rtl_p = _R17 / "verilogeval-v2" / "samples" / f"{prob}_sample01.sv"
        spec_p = _DATASET / f"{prob}_prompt.txt"
        if not rtl_p.is_file() or not spec_p.is_file():
            pytest.skip("round-17 / dataset corpus not present")
        n, _ = _n_err(rtl_p.read_text(), spec_p.read_text())
        assert n == 0
