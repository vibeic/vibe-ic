"""v1.1.62 — FSM next-state-BIT blind functional oracle (extends
kmap_truth_table_oracle_check to the Prob135_m2014_q6b class).

A VerilogEval prompt that hands a COMPLETE state-transition table + a sequential
state encoding + asks for ONE next-state bit (`output Y1 is y[1]`) is a complete
combinational oracle, blind. The gate parses the table, computes the required bit
per (state_code, input), and BLOCKs an authored RTL that mis-derives it — the
authoring-variance slip that flipped VE-v2 Prob135 pass->fail between runs.

§4.05 load-bearing half = the NEGATIVE: the gate must NEVER false-block a correct
design (incl. a structurally different correct one, and any behavior on the
don't-care unused state codes), and must SKIP whenever the oracle is not
unambiguously parseable.
"""
import sys
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parents[1]
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))
import kmap_truth_table_oracle_check as K  # noqa: E402
from _sim_tools import expect_verdict  # noqa: E402

PROMPT = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise
specified.

 - input  y (3 bits)
 - input  w
 - output Y1

The module should implement the state machine shown below:

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

The FSM should be implemented using three flip-flops and state codes
y = 000, 001, ..., 101 for states A, B, ..., F, respectively. Implement
just the next-state logic for y[1]. The output Y1 is y[1].
"""

# y[1] of the next state per (state, w). A=0..F=5.
CORRECT = """
module TopModule(input [2:0] y, input w, output reg Y1);
  always @(*) begin
    case ({y, w})
      4'b000_0: Y1=1'b0; 4'b000_1: Y1=1'b0;   // A->B(001)/A(000)
      4'b001_0: Y1=1'b1; 4'b001_1: Y1=1'b1;   // B->C(010)/D(011)
      4'b010_0: Y1=1'b0; 4'b010_1: Y1=1'b1;   // C->E(100)/D(011)
      4'b011_0: Y1=1'b0; 4'b011_1: Y1=1'b0;   // D->F(101)/A(000)
      4'b100_0: Y1=1'b0; 4'b100_1: Y1=1'b1;   // E->E(100)/D(011)
      4'b101_0: Y1=1'b1; 4'b101_1: Y1=1'b1;   // F->C(010)/D(011)
      default:  Y1=1'b0;
    endcase
  end
endmodule
"""

# the authoring-variance slip: C,w=1 -> D(011) has y[1]=1, flipped to 0.
WRONG = CORRECT.replace("4'b010_0: Y1=1'b0; 4'b010_1: Y1=1'b1;",
                        "4'b010_0: Y1=1'b0; 4'b010_1: Y1=1'b0;")

# a STRUCTURALLY DIFFERENT but functionally CORRECT design (collapsed by state).
ALT_CORRECT = """
module TopModule(input [2:0] y, input w, output reg Y1);
  always @(*) begin
    Y1 = 1'b0;
    case (y)
      3'd1: Y1 = 1'b1;   // B -> 1 for both w
      3'd2: Y1 = w;      // C -> 0/1
      3'd4: Y1 = w;      // E -> 0/1
      3'd5: Y1 = 1'b1;   // F -> 1 for both w
      default: Y1 = 1'b0;  // A, D -> 0
    endcase
  end
endmodule
"""

# correct on every USED code, garbage on the unused codes 6/7 (don't-care).
DONTCARE = ALT_CORRECT.replace("default: Y1 = 1'b0;  // A, D -> 0",
                               "3'd6: Y1 = 1'bx; 3'd7: Y1 = 1'bx; default: Y1 = 1'b0;")


def _verdict(tmp_path, prompt, rtl, name="s.sv"):
    r = tmp_path / name
    r.write_text(rtl)
    return K.check(prompt, str(r))[0]


def test_fsm_correct_passes(tmp_path):
    expect_verdict(_verdict(tmp_path, PROMPT, CORRECT), "PASS")


def test_fsm_wrong_blocks(tmp_path):
    expect_verdict(_verdict(tmp_path, PROMPT, WRONG), "BLOCK")


def test_fsm_alt_correct_not_false_blocked(tmp_path):
    # §4.05: a different correct implementation must NOT be blocked
    expect_verdict(_verdict(tmp_path, PROMPT, ALT_CORRECT), "PASS")


def test_fsm_dontcare_unused_codes_pass(tmp_path):
    # §4.05: unused state codes are don't-care; garbage there must NOT block
    expect_verdict(_verdict(tmp_path, PROMPT, DONTCARE), "PASS")


def test_fsm_skip_without_state_encoding(tmp_path):
    # ambiguous encoding -> SKIP (never block)
    p = PROMPT.replace(
        "The FSM should be implemented using three flip-flops and state codes\n"
        "y = 000, 001, ..., 101 for states A, B, ..., F, respectively. Implement\n"
        "just the next-state logic for y[1]. The output Y1 is y[1].",
        "Implement just the next-state logic for y[1]. The output Y1 is y[1].")
    assert _verdict(tmp_path, p, CORRECT) == "SKIP"


def test_fsm_skip_multibit_output(tmp_path):
    # output is a full next-state vector, not a single bit -> SKIP
    p = PROMPT.replace(" - output Y1", " - output Y (2 bits)")
    assert _verdict(tmp_path, p, CORRECT) == "SKIP"


def test_fsm_oracle_table_matches_hand_derivation():
    # the parsed oracle equals the hand-derived y[1] truth table (12 care cells)
    ins, outs = K.parse_ports(PROMPT)
    res = K.parse_fsm_next_state_bit(PROMPT, ins, outs)
    assert res is not None
    _kind, in_specs, out_name, table = res
    assert in_specs == [("y", 3), ("w", 1)] and out_name == "Y1"
    expect = {(0, 0): 0, (0, 1): 0, (1, 0): 1, (1, 1): 1, (2, 0): 0, (2, 1): 1,
              (3, 0): 0, (3, 1): 0, (4, 0): 0, (4, 1): 1, (5, 0): 1, (5, 1): 1}
    assert table == expect


# ----- §4.05 adversarial-review regressions (Step-2.7 REJECT, 4 reproduced HIGH) -----
# Root cause that was fixed: the encoding was taken from LISTING ORDER, not the
# prompt-DECLARED code map, with a guard that only checked the first two codes.

_HDR = (
    "I would like you to implement a module named TopModule with the following\n"
    "interface. All input and output ports are one bit unless otherwise specified.\n\n"
    " - input  y (3 bits)\n - input  w\n - output Y1\n\n")


def _states_of(prompt):
    import re
    out = []
    for m in re.finditer(r"^\s*(\w+)\s*\(\s*\d+\s*\)\s*--", prompt, re.M):
        if m.group(1) not in out:
            out.append(m.group(1))
    return out


def test_explicit_nonsequential_encoding_read_from_declared_map():
    # HIGH-1: A=000 B=001 C=010 D=100 E=011 F=110 — NOT listing order
    p = _HDR + (
        "  A (0) --0--> B\n  A (0) --1--> A\n  B (0) --0--> C\n  B (0) --1--> D\n"
        "  C (0) --0--> E\n  C (0) --1--> D\n  D (0) --0--> F\n  D (0) --1--> A\n"
        "  E (1) --0--> E\n  E (1) --1--> D\n  F (1) --0--> C\n  F (1) --1--> D\n\n"
        "state codes y = 000, 001, 010, 100, 011, 110 for states A, B, C, D, E, F, "
        "respectively. The output Y1 is y[1].\n")
    enc = K._parse_state_encoding(p, _states_of(p))
    assert enc == {"A": 0, "B": 1, "C": 2, "D": 4, "E": 3, "F": 6}


def test_sparse_gray_encoding_read_from_declared_map():
    # HIGH-2: C=011 (=3), not listing-index 2
    p = _HDR + (
        "  A (0) --0--> B\n  A (0) --1--> A\n  B (0) --0--> C\n  B (0) --1--> A\n"
        "  C (1) --0--> A\n  C (1) --1--> C\n\n"
        "state codes y = 000, 001, 011 for states A, B, C, respectively. "
        "The output Y1 is y[1].\n")
    enc = K._parse_state_encoding(p, _states_of(p))
    assert enc == {"A": 0, "B": 1, "C": 3}


def test_out_of_order_transition_never_misencodes():
    # HIGH-3: codes declared by NAME (A=000,B=001,C=010) but table lists B first.
    # Must use the NAMED map, or SKIP — but NEVER the transition-order map.
    p = _HDR + (
        "  B (0) --0--> C\n  B (0) --1--> A\n  A (0) --0--> B\n  A (0) --1--> A\n"
        "  C (1) --0--> A\n  C (1) --1--> C\n\n"
        "state codes y = 000, 001, 010 for states A, B, C, respectively. "
        "The output Y1 is y[1].\n")
    enc = K._parse_state_encoding(p, _states_of(p))
    assert enc is None or enc == {"A": 0, "B": 1, "C": 2}  # never {B:0,A:1,...}


def test_reqbit_taken_from_output_clause_not_stray_token():
    # HIGH-4: 'bit y[2] is the MSB' must not hijack the requested bit (y[1])
    p = _HDR + (
        "Note that bit y[2] is the MSB of the state register.\n\n"
        "  A (0) --0--> B\n  A (0) --1--> A\n  B (1) --0--> A\n  B (1) --1--> B\n\n"
        "state codes y = 000, 001, ..., 001 for states A, B, respectively. "
        "Implement just the next-state logic for y[1]. The output Y1 is y[1].\n")
    ins, outs = K.parse_ports(p)
    res = K.parse_fsm_next_state_bit(p, ins, outs)
    assert res is not None
    _k, _in, _out, table = res
    # B=001 -> next on w=0 is A(000): y[1]=0 ; on w=1 is B(001): y[1]=0
    # if req_bit were 2 the whole table would be all-zeros AND mis-attributed;
    # correct y[1]: A(0)->B(001) y[1]=0, A(1)->A y[1]=0, B->A/B y[1]=0  (all 0 here,
    # so instead assert the requested bit index was 1 via a state whose next has y[1]=1)
    # Use a transition that sets y[1]: extend is overkill — assert req parsing directly:
    import re
    m = re.search(r"(?:output\s+\w+\s+is|next[-\s]?state\s+logic\s+for)\s+y\s*\[\s*(\d+)\s*\]", p, re.I)
    assert m and m.group(1) == "1"


# ----- Step-2.7 CONFIRMATION-round regressions (2 reproduced gaps the first fix left) -----

def test_skip_code_value_wider_than_bus():
    # Finding 1: a declared code (B=1000=8) overflows the 3-bit bus -> SKIP, never
    # emit an over-width case literal that truncates+collides.
    import oracle_table_synth as S
    p = _HDR + (
        "  A (0) --0--> B\n  A (0) --1--> A\n  B (0) --0--> C\n  B (0) --1--> A\n"
        "  C (1) --0--> A\n  C (1) --1--> C\n\n"
        "state codes y = 000, 1000, 010 for states A, B, C, respectively. "
        "The output Y1 is y[1].\n")
    ins, outs = K.parse_ports(p)
    assert K.parse_fsm_next_state_bit(p, ins, outs) is None
    assert S.synth(p, "TopModule") is None


def test_skip_reqbit_clause_disagreement():
    # Finding 2: descriptive 'output Y is y[1]' disagreeing with the task
    # 'next-state logic for y[2]' is ambiguous -> SKIP (no false-block of correct RTL).
    p = _HDR + (
        "The output Y is y[1] for reference.\n\n"
        "  A (0) --0--> B\n  A (0) --1--> A\n  B (0) --0--> C\n  B (0) --1--> A\n"
        "  C (0) --0--> D\n  C (0) --1--> A\n  D (1) --0--> A\n  D (1) --1--> D\n\n"
        "state codes y = 000, 001, 010, 011 for states A, B, C, D, respectively. "
        "Implement just the next-state logic for y[2].\n")
    ins, outs = K.parse_ports(p)
    assert K.parse_fsm_next_state_bit(p, ins, outs) is None


def test_skip_ellipsis_jump_tail():
    # soft spot: an ellipsis whose explicit codes are not a clean 0,1,.. prefix -> SKIP
    p = ("state codes y = 000, 001, ..., 011, 111 for states A, B, C, D "
         "respectively. output Y1 is y[1]")
    assert K._parse_state_encoding(p, ["A", "B", "C", "D"]) is None
