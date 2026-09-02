"""ROUND-3 (subservient x gf180mcuD, 2026-09-02): a post-route repair that
SWAPS two symmetric inputs of one cell must not fail post-layout LEC.

MEASURED on the control arm's own artefacts: the post-route real-SPEF repair
swapped A1/A2 of one OAI21 (RSZ SwapPinsMove; also upsized _1 -> _2). The
flattened functional recipe names every cell pin `<inst>.<pin>`, `equiv_make`
pairs those by NAME, so `<inst>.A1_gold` was asked to equal `<inst>.A1_gate`
— now different nets. Result: 1925 points, 2 UNPROVEN, LEC_POST_UNPROVEN, the
sign-off emit FAILED, on a netlist whose every output and register was proven.
With those two mis-paired points removed from the match set the SAME netlists
prove 1923/1923 in 4.3 s (vs 152 s).

The classifier below grants that removal only on evidence read from the
artefacts (instance on both sides, INPUT pin, same pin sets, input nets a
permutation, output nets unchanged, the pin actually moved, and the cell's
Liberty function symmetric under the permutation by truth table).

FALSIFICATION (two-tree): `parse_unproven_points`,
`classify_pin_permutation_points` and the `blacklist=` argument do not exist
on the pre-fix tree (AttributeError / TypeError). The negative cases here are
the CONTROLS: every one must be REJECTED, on this tree, with the named reason.

chip-AGNOSTIC: synthetic cells (`nc_oai21_1`, `nc_oai21_2`, `nc_mux2`,
`nc_dff`) and nets; no PDK, library or design name.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lec_post_layout_check as L  # noqa: E402


_LIB = """
library (neutral) {
  cell (nc_oai21_1) {
    area : 1.0;
    pin(A1) { direction : input; }
    pin(A2) { direction : input; }
    pin(B)  { direction : input; }
    pin(ZN) { direction : output; function : "(((!A1)&(!A2))|(!B))"; }
  }
  cell (nc_oai21_2) {
    area : 2.0;
    pin(A1) { direction : input; }
    pin(A2) { direction : input; }
    pin(B)  { direction : input; }
    pin(ZN) { direction : output; function : "(((!A1)&(!A2))|(!B))"; }
  }
  cell (nc_mux2) {
    pin(I0) { direction : input; }
    pin(I1) { direction : input; }
    pin(S)  { direction : input; }
    pin(Z)  { direction : output; function : "((!S)&I0)|(S&I1)"; }
  }
  cell (nc_dff) {
    ff (IQ, IQN) { next_state : "D"; clocked_on : "CLK"; }
    pin(D)   { direction : input; }
    pin(CLK) { direction : input; clock : true; }
    pin(Q)   { direction : output; function : "IQ"; }
  }
}
"""

_GOLD = r"""
module top(a, b, c, s, clk, y);
  input a, b, c, s, clk; output y;
  wire n1, n2;
  nc_oai21_1 \u.g1  (
    .A1(a),
    .A2(b),
    .B(c),
    .ZN(n1)
  );
  nc_mux2 \u.m1  ( .I0(a), .I1(b), .S(s), .Z(n2) );
  nc_dff \u.f1  ( .D(n2), .CLK(clk), .Q(y) );
endmodule
"""


def _gate(g1_a1="b", g1_a2="a", g1_b="c", g1_cell="nc_oai21_2",
          m1_i0="a", m1_i1="b", m1_s="s", f1_d="n2", f1_clk="clk", zn="n1"):
    return f"""
module top (a, b, c, s, clk, y);
 input a; input b; input c; input s; input clk; output y;
 wire n1; wire n2;
 {g1_cell} \\u.g1  (.A1({g1_a1}),
    .A2({g1_a2}),
    .B({g1_b}),
    .ZN({zn}));
 nc_mux2 \\u.m1  (.I0({m1_i0}),
    .I1({m1_i1}),
    .S({m1_s}),
    .Z(n2));
 nc_dff \\u.f1  (.D({f1_d}),
    .CLK({f1_clk}),
    .Q(y));
endmodule
"""


_LOG = r"""
  Trying to prove $equiv for \u.g1.A1: failed.
  Trying to prove $equiv for \u.g1.A2: failed.
Proved 0 previously unproven $equiv cells.

7. Executing EQUIV_STATUS pass.
Found 12 $equiv cells in equiv:
  Of those cells 10 are proven and 2 are unproven.
  Unproven $equiv $auto$equiv_make.cc:295:find_same_wires$9213: \u.g1.A2_gold \u.g1.A2_gate
  Unproven $equiv $auto$equiv_make.cc:295:find_same_wires$9212: \u.g1.A1_gold \u.g1.A1_gate
Found a total of 2 unproven $equiv cells.
"""


def test_parse_unproven_points_reads_the_final_status_list():
    assert L.parse_unproven_points(_LOG) == ["u.g1.A2", "u.g1.A1"]
    assert L.parse_unproven_points("") == []
    # a mismatched pair is not one of equiv_make's same-name points
    assert L.parse_unproven_points(
        "  Unproven $equiv x: \\p_gold \\q_gate\n") == []


def test_symmetric_swap_with_upsize_is_accepted():
    r = L.classify_pin_permutation_points(
        ["u.g1.A2", "u.g1.A1"], _GOLD, _gate(), _LIB)
    assert not r["rejected"], r["rejected"]
    assert [a["point"] for a in r["accepted"]] == ["u.g1.A2", "u.g1.A1"]
    a = r["accepted"][0]
    assert a["gold_cell"] == "nc_oai21_1" and a["gate_cell"] == "nc_oai21_2"
    assert a["gold_input_nets"] == {"A1": "a", "A2": "b", "B": "c"}
    assert a["gate_input_nets"] == {"A1": "b", "A2": "a", "B": "c"}


def _only_rejected(names, gate, reason_fragment):
    r = L.classify_pin_permutation_points(names, _GOLD, gate, _LIB)
    assert not r["accepted"], r["accepted"]
    assert len(r["rejected"]) == len(names)
    for x in r["rejected"]:
        assert reason_fragment in x["reason"], x["reason"]


def test_control_asymmetric_permutation_is_rejected():
    """A1 <-> B of an OAI21 is NOT a symmetry: (!A1&!A2)|!B != (!B&!A2)|!A1."""
    _only_rejected(["u.g1.A1"], _gate(g1_a1="c", g1_a2="b", g1_b="a"),
                   "DIFFERENT function")


def test_control_mux_select_swap_is_rejected():
    _only_rejected(["u.m1.S"], _gate(m1_i0="s", m1_s="a"), "DIFFERENT function")


def test_control_rewire_to_a_foreign_net_is_rejected():
    _only_rejected(["u.g1.A1"], _gate(g1_a1="s", g1_a2="b"), "not a permutation")


def test_control_unmoved_pin_is_rejected_even_on_a_swapped_instance():
    """The negative control that found this test missing on the real
    artefacts: B carries the same net on both sides of the A1/A2 swap."""
    _only_rejected(["u.g1.B"], _gate(), "SAME net")


def test_control_output_pin_is_rejected():
    _only_rejected(["u.g1.ZN"], _gate(), "not an INPUT")


def test_control_output_net_change_is_rejected():
    _only_rejected(["u.g1.A1"], _gate(zn="n2"), "output net")


def test_control_register_pin_is_never_blacklisted():
    """D <-> CLK of a flop is a permutation of its input nets; the Liberty
    function `IQ` names a state variable, so the truth table cannot be built
    and the point is rejected."""
    _only_rejected(["u.f1.D"], _gate(f1_d="clk", f1_clk="n2"),
                   "could not be evaluated")


def test_control_non_pin_names_are_rejected():
    r = L.classify_pin_permutation_points(
        ["y", "u.nope.A1"], _GOLD, _gate(), _LIB)
    assert not r["accepted"]
    reasons = [x["reason"] for x in r["rejected"]]
    assert any("not an <instance>.<pin>" in s for s in reasons)
    assert any("absent" in s for s in reasons)


def test_liberty_function_evaluator_precedence():
    f = L._LibertyFn("!A&B|C^D'")
    # ! binds tightest, then ^, then &, then |  ->  ((!A)&B) | (C ^ (!D))
    for A in (0, 1):
        for B in (0, 1):
            for C in (0, 1):
                for D in (0, 1):
                    exp = ((not A) and B) or (bool(C) ^ (not D))
                    assert f({"A": A, "B": B, "C": C, "D": D}) == exp
    assert L._LibertyFn("A B")({"A": 1, "B": 0}) is False      # juxtaposition
    with pytest.raises(KeyError):
        L._LibertyFn("IQ")({})


def test_blacklist_reaches_equiv_make_in_both_recipes():
    for func in (True, False):
        ys = L.build_yosys_equiv_script("g.v", "t.v", "x.lib", "top",
                                        functional_lib=func,
                                        blacklist="/w/bl.txt")
        assert "equiv_make -blacklist /w/bl.txt gold gate equiv" in ys
        plain = L.build_yosys_equiv_script("g.v", "t.v", "x.lib", "top",
                                           functional_lib=func)
        assert "-blacklist" not in plain and "equiv_make gold gate equiv" in plain
