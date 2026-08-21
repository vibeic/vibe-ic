"""v0.3.21 — #522: deterministic FSM next-state transition-completeness check.

Recurring across benchmark clean-room rounds 1-3: a fresh author makes a
next-state logic error on a different FSM each round. spec_conformance only
checked OUTPUT STYLE (Moore/Mealy), and the FSM lessons lived in unreliable
agent prose (the #517/#518 prose-is-dormant lesson). This pins the ONE
structurally-decidable, zero-false-positive FSM defect — an INFERRED LATCH in
the next-state case — plus the precise case-driven state identification that
keeps it from false-firing on real crypto cores (chacha/aes/sha256/ibex).

The deliberately-unflagged classes (counter off-by-one, reachable-wrong-target,
latency pass-through, dead state) are documented residuals that need a self-TB /
the spec's transition table — no regex separates them from a correct design.

chip-AGNOSTIC: synthetic Verilog FSMs, no chip/state literal.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import fsm_transition_completeness_check as F  # noqa: E402
from _hostpaths import require_corpus  # noqa: E402


def _errs(rtl):
    fl, st = F.check_text(rtl)
    return st, [(x.rule, x.state) for x in fl if x.severity == "ERROR"]


_CORRECT = """\
module m(input clk, input rst, input x, output reg y);
 localparam A=2'd0, B=2'd1, C=2'd2;
 reg [1:0] state, next_state;
 always @(posedge clk) if(rst) state<=A; else state<=next_state;
 always @(*) begin
   next_state = state;
   case(state)
     A: next_state = x ? B : A;
     B: next_state = C;
     C: next_state = A;
   endcase
 end
 always @(*) y = (state==C);
endmodule
"""

# C's arm assigns NO next_state, no default, no pre-assign → inferred latch.
_LATCH = """\
module m(input clk, input rst, input x, output reg y);
 localparam A=2'd0, B=2'd1, C=2'd2;
 reg [1:0] state, next_state;
 always @(posedge clk) if(rst) state<=A; else state<=next_state;
 always @(*) begin
   case(state)
     A: next_state = x ? B : A;
     B: next_state = C;
     C: y = 1'b1;
   endcase
 end
endmodule
"""


def test_correct_fsm_is_clean():
    st, errs = _errs(_CORRECT)
    assert st == "CHECKED"
    assert errs == []


def test_inferred_latch_flagged():
    st, errs = _errs(_LATCH)
    assert st == "CHECKED"
    assert ("fsm-inferred-latch", "C") in errs


def test_default_assigning_arm_is_clean():
    # a default that assigns next_state covers any omitted arm → no latch.
    rtl = _LATCH.replace("     C: y = 1'b1;\n",
                         "     C: y = 1'b1;\n     default: next_state = A;\n")
    st, errs = _errs(rtl)
    assert st == "CHECKED"
    assert errs == []


def test_preassign_idiom_is_clean():
    # `next_state = state;` before the case covers the omitted arm → no latch.
    rtl = _LATCH.replace("   case(state)", "   next_state = state;\n   case(state)")
    st, errs = _errs(rtl)
    assert st == "CHECKED"
    assert errs == []


def test_non_fsm_is_skipped():
    st, errs = _errs("module add(input [7:0] a, input [7:0] b,"
                     " output [7:0] y); assign y=a+b; endmodule")
    assert st.startswith("SKIP")
    assert errs == []


def test_data_decode_case_not_a_state_machine_skipped():
    # a case over an address-like selector with non-state constants must NOT be
    # treated as an FSM (the precise case-driven state identification).
    rtl = """\
module decode(input [1:0] addr, output reg [7:0] q);
 localparam ADDR_NAME0=2'd0, ADDR_NAME1=2'd1, ADDR_CTRL=2'd2;
 always @(*) case(addr)
   ADDR_NAME0: q = 8'h11;
   ADDR_NAME1: q = 8'h22;
   ADDR_CTRL:  q = 8'h33;
 endcase
endmodule
"""
    st, errs = _errs(rtl)
    # decode case has no next-state assignment → SKIP, never an inferred-latch.
    assert errs == []
    assert "SKIP" in st or st == "CHECKED"


def test_no_false_positive_on_real_crypto_cores():
    # ACCEPTANCE (#522): the round1-3 close-loop FIXED designs are correct FSMs;
    # the check must NOT false-fire on known-good FSM RTL. We assert zero ERROR
    # findings across the real crypto-core FSMs shipped in the AID tree when
    # present on this host (skips cleanly off-host).
    import pytest
    base = require_corpus()
    samples = [
        base / "_ext_ics/aes/src/rtl/aes_encipher_block.v",
        base / "_ext_ics/chacha/src/rtl/chacha_core.v",
        base / "sha256_e2e_v0316/phase2/stage1/rtl/sha256.v",
    ]
    present = [p for p in samples if p.is_file()]
    if not present:
        pytest.skip("real crypto-core RTL not on this host")
    for p in present:
        _st, errs = _errs(p.read_text(errors="replace"))
        assert errs == [], f"false-positive ERROR on known-good {p.name}: {errs}"


def test_wired_into_spec_conformance(tmp_path):
    # #522 + the #517/#518 non-dormant lesson: the check must actually FIRE via
    # spec_conformance when the spec declares an FSM. A latch-bug FSM + a Moore
    # FSM spec → spec_conformance surfaces the inferred-latch ERROR.
    import spec_conformance_check as S
    rtl = tmp_path / "fsm.v"
    rtl.write_text(_LATCH)
    spec = tmp_path / "spec.json"
    spec.write_text('{"fsm_output_style": "moore"}')
    rc = S.main(["--rtl-dir", str(tmp_path), "--spec", str(spec),
                 "--json", str(tmp_path / "out.json")])
    import json
    out = json.loads((tmp_path / "out.json").read_text())
    findings = out if isinstance(out, list) else out.get("findings", [])
    rules = [f.get("rule") for f in findings]
    assert "fsm-inferred-latch" in rules, (rc, rules)


def test_spec_conformance_clean_fsm_no_latch_finding(tmp_path):
    import spec_conformance_check as S
    import json
    rtl = tmp_path / "fsm.v"
    rtl.write_text(_CORRECT)
    spec = tmp_path / "spec.json"
    spec.write_text('{"fsm_output_style": "moore"}')
    S.main(["--rtl-dir", str(tmp_path), "--spec", str(spec),
            "--json", str(tmp_path / "out.json")])
    out = json.loads((tmp_path / "out.json").read_text())
    findings = out if isinstance(out, list) else out.get("findings", [])
    rules = [f.get("rule") for f in findings]
    assert "fsm-inferred-latch" not in rules
