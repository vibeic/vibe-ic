"""ORGANIC #791 — continuous-assign one-hot FSM dropped self-loop ships PASS.

Round-15 VerilogEval Prob150_review2015_fsmonehot: a one-hot FSM authored as
CONTINUOUS ASSIGNs (no `case`). The spec EXPLICITLY discloses the self-loop
`Count (counting=1) --done_counting=0--> Count`, but the emitted sample dropped
that self-loop in-edge (`assign Count_next = state[7];` only — the B3->Count
predecessor edge, missing `| state[Count]&~done_counting`) → hidden-TB
mismatches on every cycle exercising the dropped self-loop.

PREMISE: the case-driven `check_text` SKIPs (-no-state-declarations) on a
continuous-assign one-hot FSM, so the functionally-wrong design shipped
hard_gates_pass=true. `check_onehot_continuous_assign(rtl, spec)` closes that
hole by parsing the spec's disclosed arrow-form transition table + one-hot
encoding and the RTL's `assign <Dst>_next = ...` one-hot equations, flagging a
disclosed in-edge (incl self-loop) absent from the destination's next-state OR.

§4.05 NO-FALSE-FIRE: a CORRECT one-hot FSM (all disclosed in-edges present) must
NOT be flagged; a design with NO disclosed transition table stays SKIP; a header
row / bare-prose arrow must not pollute the edge set.

chip-AGNOSTIC: synthetic Verilog FSMs, no chip/state literal. Where a real
on-disk defect artifact is present it is asserted directly (content-gated so a
LIVE-corpus overwrite skips rather than false-fails — Step-2.7 rule 2).
"""
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import fsm_transition_completeness_check as F  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402


# A canonical VerilogEval-style one-hot spec: arrow-form transition table + a
# one-hot encoding tuple. The Count state has a disclosed SELF-LOOP.
_SPEC = """\
The module should implement the following Moore state machine.

state   (output)      --input--> next state
-------------------------------------------
  S     ()            --d=0--> S
  S     ()            --d=1--> S1
  B3    (shift_ena=1) --(always go to next cycle)--> Count
  Count (counting=1)  --done_counting=0--> Count
  Count (counting=1)  --done_counting=1--> Wait
  Wait  (done=1)      --ack=0--> Wait
  Wait  (done=1)      --ack=1--> S

Derive next-state logic equations by inspection assuming the following one-hot
encoding is used: (S, S1, S11, S110, B0, B1, B2, B3, Count, Wait)
= (10'b0000000001, 10'b0000000010, ... , 10'b1000000000)
"""

# numeric-index one-hot RTL with the Count self-loop DROPPED (the round-15 bug).
_BUGGY_NUMERIC = """\
module TopModule (input d, input done_counting, input ack, input [9:0] state,
    output S_next, output S1_next, output B3_next, output Count_next,
    output Wait_next, output done, output counting, output shift_ena);
    assign S_next     = (state[0] & ~d) | (state[9] & ack);
    assign S1_next    = (state[0] & d);
    assign B3_next    = state[6];
    assign Count_next = state[7];                       // DROPPED self-loop
    assign Wait_next  = (state[8] & done_counting) | (state[9] & ~ack);
    assign shift_ena = state[7];
    assign counting  = state[8];
    assign done      = state[9];
endmodule
"""

# same design but with the self-loop RESTORED (correct, numeric index form).
_CORRECT_NUMERIC = _BUGGY_NUMERIC.replace(
    "assign Count_next = state[7];                       // DROPPED self-loop",
    "assign Count_next = state[7] | (state[8] & ~done_counting);")

# correct design using NAMED one-hot indices via parameters (state[Count]).
_CORRECT_NAMED = """\
module TopModule (input d, input done_counting, input ack, input [9:0] state,
    output S_next, output S1_next, output B3_next, output Count_next,
    output Wait_next, output done, output counting, output shift_ena);
    parameter S=0, S1=1, S11=2, S110=3, B0=4, B1=5, B2=6, B3=7, Count=8, Wait=9;
    assign S_next     = state[S]&~d | state[Wait]&ack;
    assign S1_next    = state[S]&d;
    assign B3_next    = state[B2];
    assign Count_next = state[B3] | state[Count]&~done_counting;  // self-loop present
    assign Wait_next  = state[Count]&done_counting | state[Wait]&~ack;
    assign shift_ena = state[B3];
    assign counting  = state[Count];
    assign done      = state[Wait];
endmodule
"""


def _oh(rtl, spec):
    fl, st = F.check_onehot_continuous_assign(rtl, spec)
    return st, [(x.rule, x.state) for x in fl if x.severity == "ERROR"]


# ---- POSITIVE: the defect must be flagged ----------------------------------
def test_dropped_self_loop_numeric_is_flagged():
    st, errs = _oh(_BUGGY_NUMERIC, _SPEC)
    assert st == "CHECKED-ONEHOT"
    assert ("fsm-onehot-missing-transition", "Count") in errs


def test_dropped_non_self_loop_in_edge_is_flagged():
    # drop the Wait--ack=1-->S in-edge from S_next (general in-edge, not a loop).
    buggy = _CORRECT_NUMERIC.replace(
        "assign S_next     = (state[0] & ~d) | (state[9] & ack);",
        "assign S_next     = (state[0] & ~d);")
    st, errs = _oh(buggy, _SPEC)
    assert st == "CHECKED-ONEHOT"
    assert ("fsm-onehot-missing-transition", "S") in errs


# ---- §4.05 NEGATIVE: a correct FSM must NOT be flagged ----------------------
def test_correct_numeric_onehot_not_flagged():
    st, errs = _oh(_CORRECT_NUMERIC, _SPEC)
    assert st == "CHECKED-ONEHOT"
    assert errs == []


def test_correct_named_index_onehot_not_flagged():
    st, errs = _oh(_CORRECT_NAMED, _SPEC)
    assert st == "CHECKED-ONEHOT"
    assert errs == []


# ---- §4.05 NEGATIVE: no disclosed table / non-FSM must stay SKIP -----------
def test_no_transition_table_stays_skip():
    spec = ("Implement an 8-bit adder. Inputs a, b; output sum. The pipeline "
            "goes stage1 --> stage2 --> stage3 for processing.")
    rtl = ("module TopModule(input [7:0] a, input [7:0] b, output [7:0] sum);"
           " assign sum = a + b; endmodule")
    st, errs = _oh(rtl, spec)
    assert st.startswith("SKIP")
    assert errs == []


# ── §4.05 Step-2.7 — the state-vector name is DERIVED, not hard-coded `state` ─
@pytest.mark.parametrize("vec", ["state_q", "cur_state", "q", "cs", "state_reg"])
def test_791_noleak_correct_fsm_nonstate_vector_not_flagged(vec):
    # a CORRECT one-hot FSM whose current-state register is NOT named `state`
    # must not be falsely flagged (the hard-coded `state[...]` false-fire).
    rtl = (f"module fsm(input clk, input in,\n"
           f"  output A_next, output B_next);\n"
           f"  reg [1:0] {vec};\n"
           f"  assign A_next = ({vec}[0] & ~in) | ({vec}[1] & ~in);\n"
           f"  assign B_next = ({vec}[0] &  in) | ({vec}[1] &  in);\n"
           f"endmodule\n")
    spec = ("One-hot encoding (A, B) = (2'b01, 2'b10)\n"
            "A () --in=0--> A\nA () --in=1--> B\n"
            "B () --in=0--> A\nB () --in=1--> B\n")
    st, errs = _oh(rtl, spec)
    assert errs == [], (vec, st, errs)


def test_791_derived_state_vector_picks_dominant_base():
    # `cur_state` is read in every next-state eq; a data bus `cfg` in one — the
    # dominant base is the state vector.
    vecs = F._state_vector_names([
        "cur_state[0] & ~in | cfg[2]", "cur_state[0] & in", "cur_state[1]"])
    assert vecs == {"cur_state"}


def test_791_no_state_vector_skips():
    # next-state equations that index NO vector at all → cannot judge → SKIP.
    _, st = F.check_onehot_continuous_assign(
        "module m(output A_next); assign A_next = 1'b0; endmodule",
        "A () --x--> A\nB () --x--> B\n")
    assert st.startswith("SKIP")


def test_bare_prose_arrow_does_not_create_edges():
    # A bare prose `A --> B` (no `--cond--` segment) must NOT be parsed as a
    # transition row — else it could pollute the edge set and false-fire.
    spec = ("Signals flow input --> register --> output across the datapath. "
            "data --> result is combinational.")
    assert F.parse_transition_table(spec) == []


def test_table_but_no_onehot_assign_stays_skip():
    # disclosed table but the RTL is a case-style FSM (no continuous one-hot
    # _next assign) — the one-hot path must SKIP, not guess.
    rtl = ("module TopModule(input clk, input d, output reg [9:0] state);\n"
           "  always @(posedge clk) case (state) default: state <= state;"
           " endcase\nendmodule")
    st, errs = _oh(rtl, _SPEC)
    assert st.startswith("SKIP")
    assert errs == []


def test_empty_spec_stays_skip():
    st, errs = _oh(_BUGGY_NUMERIC, "")
    assert st == "SKIP-no-spec"
    assert errs == []


# ---- back-compat: case-driven check_text is unchanged (no spec needed) ------
def test_check_text_still_skips_continuous_assign_onehot():
    fl, st = F.check_text(_BUGGY_NUMERIC)
    assert st == "SKIP-no-state-declarations"
    assert fl == []


# ---- spec_conformance_check wires the rule (emit-surface integration) -------
def test_spec_conformance_emits_rule_for_buggy_onehot(tmp_path):
    import importlib
    import spec_conformance_check as S
    importlib.reload(S)
    rtl_dir = tmp_path / "rtl"
    rtl_dir.mkdir()
    (rtl_dir / "TopModule.sv").write_text(_BUGGY_NUMERIC)
    spec_f = tmp_path / "prompt.txt"
    spec_f.write_text(_SPEC)
    out_json = tmp_path / "conf.json"
    rc = S.main(["--rtl-dir", str(rtl_dir), "--spec", str(spec_f),
                 "--top", "TopModule", "--json", str(out_json)])
    import json
    findings = json.loads(out_json.read_text())
    rules = {x["rule"] for x in findings}
    assert "fsm-onehot-missing-transition" in rules
    assert rc == 1  # ERROR finding → non-zero exit


def test_spec_conformance_clean_for_correct_onehot(tmp_path):
    import importlib
    import spec_conformance_check as S
    importlib.reload(S)
    rtl_dir = tmp_path / "rtl"
    rtl_dir.mkdir()
    (rtl_dir / "TopModule.sv").write_text(_CORRECT_NAMED)
    spec_f = tmp_path / "prompt.txt"
    spec_f.write_text(_SPEC)
    out_json = tmp_path / "conf.json"
    S.main(["--rtl-dir", str(rtl_dir), "--spec", str(spec_f),
            "--top", "TopModule", "--json", str(out_json)])
    import json
    findings = json.loads(out_json.read_text())
    rules = {x["rule"] for x in findings}
    assert "fsm-onehot-missing-transition" not in rules


# ---- gates_atomic allow-lists the rule as emit-blocking ---------------------
def test_gates_atomic_blocks_on_rule():
    # The rule must be a member of the emit-blocking conformance set that
    # gates_atomic actually consults. This used to slice the set out of
    # gates_atomic's source between "_BLOCKING_CONFORMANCE_RULES" and the next
    # "}"; that literal was a hand-kept duplicate and was deleted in v1.11.70
    # when it drifted from the canonical set. Read the set instead of the file.
    import spec_conformance_check as _scc
    assert "fsm-onehot-missing-transition" in _scc.EMIT_BLOCKING_CONFORMANCE_RULES, \
        sorted(_scc.EMIT_BLOCKING_CONFORMANCE_RULES)


# ---- DEFECT ARTIFACT: the real on-disk sample, content-gated (Step-2.7 r2) --
_REAL_SAMPLE = corpus_path("_bench_open_v100_r15/verilogeval-v2/samples/"
                           "Prob150_review2015_fsmonehot_sample01.sv")
_REAL_PROMPT = corpus_path("_extbench/verilog-eval/dataset_spec-to-rtl/"
                           "Prob150_review2015_fsmonehot_prompt.txt")


@pytest.mark.skipif(
    not (_REAL_SAMPLE.is_file() and _REAL_PROMPT.is_file()),
    reason="real defect artifact / prompt absent on this host; set $VIBEIC_CORPUS_ROOT to the external benchmark corpus")
def test_real_prob150_sample_flags_dropped_count_selfloop():
    sample = _REAL_SAMPLE.read_text(errors="replace")
    # content-gate: only assert the defect when the dropped-self-loop shape is
    # actually present (the LIVE corpus may be re-authored between runs).
    if "assign Count_next = state[7];" not in sample:
        pytest.skip("live corpus re-authored — dropped-self-loop shape gone")
    prompt = _REAL_PROMPT.read_text(errors="replace")
    st, errs = _oh(sample, prompt)
    assert st == "CHECKED-ONEHOT"
    assert ("fsm-onehot-missing-transition", "Count") in errs


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
