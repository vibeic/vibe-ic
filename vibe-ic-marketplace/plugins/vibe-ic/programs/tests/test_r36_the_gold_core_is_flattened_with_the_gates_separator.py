"""r36 (subservient x gf180mcuD as a DIE): the chip-top post-layout LEC names the
gold core the way the routed gate names it.

MEASURED: gold = recorded pad wrapper + synthesised core (hierarchical); gate =
routed flat netlist whose core cells are `u_core/_3306_`. A plain `flatten`
named the gold `u_core._3306_`, `equiv_make` paired only the 23 ports, and 21
stayed UNPROVEN on every die run. Replaying r36's own script with the core's
Liberty cells flattened first and the core instance flattened with `/`: 1822
points, 1778 proven, the remainder permuted commutative pins.

Both directions: the separator and instance are READ from the two netlists
(none guessed, ambiguity -> None); with None the script is byte-identical.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lec_post_layout_check as L  # noqa: E402

WRAPPER = """module chip_top(input i_clk, output o);
  wire o__core;
  gf180mcu_fd_io__bi_24t u_pad_o (.A(o__core), .PAD(o));
  core u_core (.i_clk(i_clk), .o(o__core));
endmodule
"""
GATE_SLASH = "module chip_top(i_clk, o);\n dffq_1 \\u_core/_3306_ (.CLK(i_clk));\nendmodule\n"
GATE_DOT = "module chip_top(i_clk, o);\n dffq_1 \\u_core._3306_ (.CLK(i_clk));\nendmodule\n"






def _ys(**kw):
    return L.build_yosys_equiv_script("gold.v", "gate.v", "lib.lib", "chip_top",
                                      functional_lib=True, **kw)


def test_the_gold_side_flattens_the_core_first_with_that_separator():
    ys = _ys(gold_core_flatten=("core", "u_core", "/"))
    gold, gate = ys.split("design -stash gold", 1)
    assert "flatten core\nflatten -separator / chip_top/u_core\ntribuf -formal\nflatten\n" in gold
    assert "-separator" not in gate


def test_without_it_the_script_is_byte_identical():
    assert _ys() == _ys(gold_core_flatten=None)
    assert "-separator" not in _ys()


# --- the permutation screen reads the gold under the same flattened names ---

GOLD_H = """module core(i_a, i_b, o_y);
  input i_a; input i_b; output o_y;
  wire _1_;
  nand2_1 _2847_ (.A1(i_a), .A2(_1_), .ZN(o_y));
  inv_1 _2848_ (.I(i_b), .ZN(_1_));
endmodule
module chip_top(a, b, y);
  input a; input b; output y;
  wire a__core; wire y__core;
  in_c u_pad_a (.PAD(a), .Y(a__core));
  core u_core (.i_a(a__core), .i_b(b), .o_y(y__core));
endmodule
"""
GATE_F = """module chip_top(a, b, y);
  in_c u_pad_a (.PAD(a), .Y(a__core));
  nand2_1 \\u_core/_2847_  (.A1(\\u_core/_1_ ), .A2(a__core), .ZN(y__core));
  inv_1 \\u_core/_2848_  (.I(b), .ZN(\\u_core/_1_ ));
endmodule
"""
LIB = """library(x) {
 cell(nand2_1) { pin(A1) { direction : input; } pin(A2) { direction : input; }
   pin(ZN) { direction : output; function : "!(A1&A2)"; } }
 cell(inv_1) { pin(I) { direction : input; } pin(ZN) { direction : output; function : "!I"; } }
}
"""
POINTS = ["u_core/_2847_.A1", "u_core/_2847_.A2"]


def test_a_permuted_core_pin_is_paired_with_the_flattened_gold():
    cls = L.classify_pin_permutation_points(POINTS, GOLD_H, GATE_F, LIB,
                                            gold_core_flatten=("core", "u_core", "/"))
    assert len(cls["accepted"]) == 2 and not cls.get("not_applicable")


def test_without_the_view_the_same_points_cannot_be_paired():
    cls = L.classify_pin_permutation_points(POINTS, GOLD_H, GATE_F, LIB)
    assert cls["accepted"] == [] and cls["not_applicable"]["pairable_points"] == 0


def test_a_real_rewire_is_still_rejected_under_the_view():
    rewired = GATE_F.replace(".A1(\\u_core/_1_ )", ".A1(b)")
    assert rewired != GATE_F
    cls = L.classify_pin_permutation_points(POINTS, GOLD_H, rewired, LIB,
                                            gold_core_flatten=("core", "u_core", "/"))
    assert cls["accepted"] == [] and len(cls["rejected"]) == 2
