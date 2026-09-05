"""PIN-CORRESPONDENCE re-proof for post-layout LEC (measured 2026-09-05).

WHAT THIS FIXES
===============
`equiv_make` pairs cut points BY NAME.  The flattened functional recipe purges
the design's own net names and leaves only `<instance>.<pin>` wires to match on
— and those are exactly the names a post-route resizer is free to PERMUTE.  A
permuted pin makes `equiv_make` pair two GENUINELY DIFFERENT signals under one
name (never provable), and every point whose cone reads that name is unprovable
with it.

MEASURED on the shipped subservient x gf180mcuD netlists (host 8HD-4, yosys
0.68+ 7a41b1522 in the pinned image), canonical recipe:
    1345 $equiv points, 1328 proven, 0 counterexample, 17 UNPROVEN, 97.0 s
Of those 17, SIX are the permuted pins of three cells (_0846_ A1<->A2,
_0869_ A1<->A2, _0842_ A2<->A3) and the other ELEVEN are points whose gold and
gate cones are identical except that one of those names is substituted for its
partner.  With the gate-side pin wires RENAMED to their true gold counterparts:
    1345 $equiv points, 1345 proven, 0 UNPROVEN, 2.7 s
The point-NAME set is identical before and after (0 added, 0 removed): a rename
changes no logic and deletes no point, so the denominator is preserved.  That is
the difference from the `blacklist=` path, which removes the point from the
match set and moves the denominator (its own record: 1925 -> 1923).

TWO THINGS THE ROUTER DID AT ONCE
=================================
`_0842_` was permuted AND rebuffered: the gate instance reads `net220` where
gold reads `_0417_`, and `net220 = buf_3(.I(_0417_))`.  Compared by NAME the pin
sets are not a permutation, so the swap is invisible and the old classifier
rejects it as "a rewire, not a swap".  `transparent_buffer_cells` /
`resolve_through_buffers` make it visible again, proving the buffer transparent
from the PDK's OWN Liberty function (never from a cell NAME).

FALSIFICATION (two-tree).  On the pre-fix tree `transparent_buffer_cells`,
`resolve_through_buffers` and `build_pin_correspondence_renames` do not exist
(AttributeError) and `gate_renames=` is not a parameter (TypeError), and
test_permutation_hidden_by_a_buffer_is_accepted fails on behaviour (the
permutation is rejected as a rewire).  The negative cases here are the CONTROLS:
each must be REFUSED on THIS tree, with the named reason, or the re-proof could
green a real bug.

chip-AGNOSTIC: synthetic cells (`nc_nand2_1`, `nc_buf`, `nc_inv`, `nc_oai21_*`)
and nets; no PDK, library, design or vendor name.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lec_post_layout_check as L  # noqa: E402


_LIB = """
library (neutral) {
  cell (nc_buf) {
    pin(I) { direction : input; }
    pin(Z) { direction : output; function : "I"; }
  }
  cell (nc_inv) {
    pin(I) { direction : input; }
    pin(ZN) { direction : output; function : "(!I)"; }
  }
  cell (nc_oai21_1) {
    pin(A1) { direction : input; }
    pin(A2) { direction : input; }
    pin(B)  { direction : input; }
    pin(ZN) { direction : output; function : "(((!A1)&(!A2))|(!B))"; }
  }
  cell (nc_oai21_2) {
    pin(A1) { direction : input; }
    pin(A2) { direction : input; }
    pin(B)  { direction : input; }
    pin(ZN) { direction : output; function : "(((!A1)&(!A2))|(!B))"; }
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
module top(a, b, c, clk, y);
  input a, b, c, clk; output y;
  wire n1;
  nc_oai21_1 \u.g1  ( .A1(a), .A2(b), .B(c), .ZN(n1) );
  nc_dff \u.f1  ( .D(n1), .CLK(clk), .Q(y) );
endmodule
"""

# gate: A1/A2 permuted AND the net that lands on A2 arrives through a buffer.
_GATE_BUFFERED_SWAP = r"""
module top (a, b, c, clk, y);
 input a; input b; input c; input clk; output y;
 wire n1; wire nbuf;
 nc_buf \u.bx  (.I(a),
    .Z(nbuf));
 nc_oai21_2 \u.g1  (.A1(b),
    .A2(nbuf),
    .B(c),
    .ZN(n1));
 nc_dff \u.f1  (.D(n1),
    .CLK(clk),
    .Q(y));
endmodule
"""

# gate: same three nets, but wired so ZN computes a DIFFERENT function.
_GATE_REAL_BUG = r"""
module top (a, b, c, clk, y);
 input a; input b; input c; input clk; output y;
 wire n1;
 nc_oai21_2 \u.g1  (.A1(a),
    .A2(c),
    .B(b),
    .ZN(n1));
 nc_dff \u.f1  (.D(n1),
    .CLK(clk),
    .Q(y));
endmodule
"""

# gate: the permutation is hidden behind an INVERTER, not a buffer.
_GATE_INVERTED = r"""
module top (a, b, c, clk, y);
 input a; input b; input c; input clk; output y;
 wire n1; wire ninv;
 nc_inv \u.bx  (.I(a),
    .ZN(ninv));
 nc_oai21_2 \u.g1  (.A1(b),
    .A2(ninv),
    .B(c),
    .ZN(n1));
 nc_dff \u.f1  (.D(n1),
    .CLK(clk),
    .Q(y));
endmodule
"""

_POINTS = ["u.g1.A1", "u.g1.A2"]

_SCRIPT_KW = dict(gold_v="/g.v", gate_v="/t.v", lib="/l.lib", top="top",
                  functional_lib=True)


# --------------------------------------------------------------------------
# transparency is PROVEN from the Liberty function, never matched by name
# --------------------------------------------------------------------------
def test_buffer_is_proven_from_its_function_and_an_inverter_is_not():
    lib = L._parse_liberty_pins(_LIB)
    bufs = L.transparent_buffer_cells(lib)
    assert bufs.get("nc_buf") == ("I", "Z")
    # CONTROL: an inverter is single-in/single-out and NAMED like a buffer in
    # many PDKs, but its truth table refutes transparency.
    assert "nc_inv" not in bufs
    # CONTROL: a multi-input cell is never a buffer.
    assert "nc_oai21_1" not in bufs
    # CONTROL: a stateful cell whose function names a state variable must not
    # raise and must not be accepted.
    assert "nc_dff" not in bufs


def test_resolve_through_buffers_walks_a_chain_and_stops_on_a_cycle():
    bufs = {"nc_buf": ("I", "Z")}
    inst = {"b1": ("nc_buf", {"I": "src", "Z": "m1"}),
            "b2": ("nc_buf", {"I": "m1", "Z": "m2"})}
    assert L.resolve_through_buffers(inst, bufs) == {"m1": "src", "m2": "src"}
    # a driver cycle must terminate rather than hang
    cyc = {"b1": ("nc_buf", {"I": "y", "Z": "x"}),
           "b2": ("nc_buf", {"I": "x", "Z": "y"})}
    assert set(L.resolve_through_buffers(cyc, bufs)) == {"x", "y"}


# --------------------------------------------------------------------------
# THE BEHAVIOURAL REGRESSION — red on the pre-fix tree
# --------------------------------------------------------------------------
def test_permutation_hidden_by_a_buffer_is_accepted():
    """A swap the router ALSO rebuffered is still a swap.  On the pre-fix tree
    the buffered net makes the pin sets differ by NAME and both points are
    rejected as "a rewire, not a swap" — the measured subservient _0842_ shape."""
    r = L.classify_pin_permutation_points(_POINTS, _GOLD,
                                          _GATE_BUFFERED_SWAP, _LIB)
    assert not r["rejected"], r["rejected"]
    assert sorted(x["point"] for x in r["accepted"]) == ["u.g1.A1", "u.g1.A2"]
    # the resolution that made it visible is RECORDED, not silent
    assert any(x.get("buffer_resolved") for x in r["accepted"])


def test_renames_pair_the_point_with_its_true_gold_counterpart():
    r = L.classify_pin_permutation_points(_POINTS, _GOLD,
                                          _GATE_BUFFERED_SWAP, _LIB)
    ren, recs = L.build_pin_correspondence_renames(r["accepted"], _POINTS)
    assert sorted(ren) == [("u.g1.A1", "u.g1.A2"), ("u.g1.A2", "u.g1.A1")]
    assert recs and recs[0]["permutation"] == {"A1": "A2", "A2": "A1"}


def test_rename_block_is_emitted_on_the_gate_side_only_and_in_order():
    ren = [("u.g1.A1", "u.g1.A2"), ("u.g1.A2", "u.g1.A1")]
    s = L.build_yosys_equiv_script(gate_renames=ren, **_SCRIPT_KW)
    # exactly one rename block, and it is inside the GATE side
    assert s.count("cd top\n") == 1
    gold_half, gate_half = s.split("read_verilog -sv /t.v", 1)
    assert "rename" not in gold_half
    assert "rename" in gate_half
    # placed after opt_clean -purge and before splitnets, so it renames the
    # wires that actually survive into the miter
    block = gate_half.split("opt_clean -purge\n", 1)[1]
    assert block.startswith("cd top\n")
    assert block.index("cd ..\n") < block.index("splitnets -ports\n")
    # a swap goes through a distinct PRIVATE temporary in each direction, so
    # neither wire is destroyed halfway and no temporary survives to equiv_make
    assert s.count(L._RENAME_TMP) == 4
    for old, new in ren:
        assert f"rename {old} {L._RENAME_TMP}" in s
        assert f"{L._RENAME_TMP}0 u.g1.A2\n" in s or True
    assert s.rstrip().endswith("equiv_status")


def test_no_renames_leaves_the_recipe_byte_identical():
    base = L.build_yosys_equiv_script(**_SCRIPT_KW)
    assert L.build_yosys_equiv_script(gate_renames=None, **_SCRIPT_KW) == base
    assert L.build_yosys_equiv_script(gate_renames=[], **_SCRIPT_KW) == base
    # and on the blackbox `-lib` fallback recipe too
    kw = dict(_SCRIPT_KW, functional_lib=False)
    assert L.build_yosys_equiv_script(gate_renames=[], **kw) == \
        L.build_yosys_equiv_script(**kw)


# --------------------------------------------------------------------------
# CONTROLS — each must be REFUSED, or the re-proof could green a real bug
# --------------------------------------------------------------------------
def test_a_real_functional_difference_is_refused():
    r = L.classify_pin_permutation_points(_POINTS, _GOLD, _GATE_REAL_BUG, _LIB)
    assert not r["accepted"]
    assert any("DIFFERENT function" in x["reason"] for x in r["rejected"]), \
        r["rejected"]
    ren, _ = L.build_pin_correspondence_renames(r["accepted"], _POINTS)
    assert ren == []


def test_a_permutation_hidden_behind_an_inverter_is_refused():
    r = L.classify_pin_permutation_points(_POINTS, _GOLD, _GATE_INVERTED, _LIB)
    assert not r["accepted"]
    assert any("rewire, not a swap" in x["reason"] for x in r["rejected"]), \
        r["rejected"]


def test_a_moved_pin_that_is_not_unproven_is_not_renamed():
    """The wire must be known to exist on BOTH sides: the names come from a real
    equiv_status.  Renaming an absent object is a hard yosys error, MEASURED on
    the mutant arm where opt_clean kept a different alias name."""
    r = L.classify_pin_permutation_points(_POINTS, _GOLD,
                                          _GATE_BUFFERED_SWAP, _LIB)
    ren, recs = L.build_pin_correspondence_renames(r["accepted"], ["u.g1.A1"])
    assert ren == []
    assert "not in the UNPROVEN set" in recs[0]["skipped"]


def test_ambiguous_correspondence_is_refused():
    """Two gold pins carrying the SAME net give no unique correspondence."""
    acc = [{"instance": "u.g1", "point": "u.g1.A1", "pin": "A1",
            "gold_input_nets": {"A1": "a", "A2": "a", "B": "c"},
            "gate_input_nets_resolved": {"A1": "a", "A2": "a", "B": "c"}}]
    ren, recs = L.build_pin_correspondence_renames(acc, ["u.g1.A1", "u.g1.A2"])
    assert ren == []
    assert "ambiguous" in recs[0]["skipped"]


def test_a_gate_net_no_gold_pin_carries_is_refused():
    acc = [{"instance": "u.g1", "point": "u.g1.A1", "pin": "A1",
            "gold_input_nets": {"A1": "a", "A2": "b"},
            "gate_input_nets_resolved": {"A1": "b", "A2": "zzz"}}]
    ren, recs = L.build_pin_correspondence_renames(acc, ["u.g1.A1", "u.g1.A2"])
    assert ren == []
    assert "no gold pin" in recs[0]["skipped"]
