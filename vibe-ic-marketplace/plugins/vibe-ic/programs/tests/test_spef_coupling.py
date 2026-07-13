"""Unit tests for _spef_coupling — analytical lateral-coupling SPEF augmentation.

Covers the three pure helpers the enhancement rests on:
  1. coupling_cap_pf   — the disclosed parallel-plate formula (numeric + guards)
  2. find_adjacent_pairs — same-layer parallel adjacency + window + overlap
  3. inject_coupling_into_spef — valid IEEE-1481 coupling-cap emission

Plus parse_lef_layers / parse_def_wires on tiny synthetic fixtures and an
end-to-end build_coupling round-trip.  No container / OpenROAD needed.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import _spef_coupling as sc  # noqa: E402

EPS0 = 8.854e-6  # pF/um


# ── 1. analytical formula ─────────────────────────────────────────────────────
def test_coupling_cap_parallel_plate_value():
    # C = eps_r*eps0*T*L/S ; T=0.53, L=10, S=0.23, eps_r=4.0
    got = sc.coupling_cap_pf(0.53, 10.0, 0.23, 4.0)
    exp = 4.0 * EPS0 * 0.53 * 10.0 / 0.23
    assert abs(got - exp) < 1e-12
    # sanity: ~0.8 fF for this geometry
    assert 0.0007 < got < 0.0009  # pF


def test_coupling_cap_scales_inversely_with_spacing():
    near = sc.coupling_cap_pf(0.53, 5.0, 0.25, 4.0)
    far = sc.coupling_cap_pf(0.53, 5.0, 1.0, 4.0)
    assert near > far
    # exactly 4x when spacing 4x smaller
    assert abs(near - 4.0 * far) < 1e-12


def test_coupling_cap_scales_with_overlap_and_thickness():
    base = sc.coupling_cap_pf(0.5, 4.0, 0.3, 4.0)
    assert abs(sc.coupling_cap_pf(0.5, 8.0, 0.3, 4.0) - 2 * base) < 1e-12
    assert abs(sc.coupling_cap_pf(1.0, 4.0, 0.3, 4.0) - 2 * base) < 1e-12


def test_coupling_cap_zero_guards():
    assert sc.coupling_cap_pf(0.5, 5.0, 0.0, 4.0) == 0.0    # S<=0
    assert sc.coupling_cap_pf(0.5, 0.0, 0.3, 4.0) == 0.0    # L<=0
    assert sc.coupling_cap_pf(0.0, 5.0, 0.3, 4.0) == 0.0    # T<=0
    assert sc.coupling_cap_pf(0.5, 5.0, -1.0, 4.0) == 0.0


# ── LEF / DEF parsers ─────────────────────────────────────────────────────────
LEF = """
LAYER MET1
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  WIDTH 0.23 ;
  SPACING 0.23 ;
  THICKNESS 0.53 ;
END MET1
LAYER VIA1
  TYPE CUT ;
END VIA1
LAYER MET2
  TYPE ROUTING ;
  DIRECTION VERTICAL ;
  WIDTH 0.28 ;
  SPACING 0.28 ;
  THICKNESS 0.53 ;
END MET2
"""


def test_parse_lef_layers_only_routing():
    layers = sc.parse_lef_layers(LEF)
    assert set(layers) == {"MET1", "MET2"}  # VIA1 (CUT) excluded
    assert layers["MET1"].width == 0.23
    assert layers["MET1"].thickness == 0.53
    assert layers["MET2"].direction == "VERTICAL"


def _mk_def(nets_body):
    return ("DESIGN t ;\nUNITS DISTANCE MICRONS 1000 ;\n"
            "NETS 2 ;\n" + nets_body + "END NETS\n")


def test_parse_def_wires_horizontal_and_continuation():
    layers = sc.parse_lef_layers(LEF)
    # net a: horizontal MET1 run y=1000, x 0->10000; continuation ( * 5000 )
    body = (
        "    - a ( i1 A ) ( i2 Y )\n"
        "      + ROUTED MET1 ( 0 1000 ) ( 10000 * ) ;\n"
        "    - b ( i3 A ) ( i4 Y )\n"
        "      + ROUTED MET1 ( 0 1230 ) ( 10000 * ) ;\n")
    segs = sc.parse_def_wires(_mk_def(body), layers, 1000)
    assert len(segs) == 2
    s = segs[0]
    assert s.net == "a" and s.layer == "MET1" and s.horizontal
    assert s.xlo == 0 and s.xhi == 10000
    # width 0.23um => half 115 dbu around y=1000
    assert s.ylo == 1000 - 115 and s.yhi == 1000 + 115


# ── 2. adjacency finder ───────────────────────────────────────────────────────
def test_find_adjacent_pairs_two_parallel_wires():
    layers = sc.parse_lef_layers(LEF)
    # two MET1 horizontal wires, centers y=1000 and y=1460, width 0.23um
    # (half=115 dbu).  edge-to-edge gap = (1460-115) - (1000+115) = 1345-1115
    # = 230 dbu = 0.23um.  overlap x 0..10000 = 10um.
    body = (
        "    - a ( i1 A ) ( i2 Y )\n"
        "      + ROUTED MET1 ( 0 1000 ) ( 10000 * ) ;\n"
        "    - b ( i3 A ) ( i4 Y )\n"
        "      + ROUTED MET1 ( 0 1460 ) ( 10000 * ) ;\n")
    segs = sc.parse_def_wires(_mk_def(body), layers, 1000)
    pairs = sc.find_adjacent_pairs(segs, layers, 1000, window_um=2.0, eps_r=4.0)
    assert ("a", "b") in pairs
    # expected C = 4*eps0*0.53*10/0.23
    exp = 4.0 * EPS0 * 0.53 * 10.0 / 0.23
    assert abs(pairs[("a", "b")] - exp) < 1e-9


def test_find_adjacent_pairs_beyond_window_excluded():
    layers = sc.parse_lef_layers(LEF)
    # centers 4000 um apart => way beyond 2um window
    body = (
        "    - a ( i1 A ) ( i2 Y )\n"
        "      + ROUTED MET1 ( 0 1000 ) ( 10000 * ) ;\n"
        "    - b ( i3 A ) ( i4 Y )\n"
        "      + ROUTED MET1 ( 0 4000000 ) ( 10000 * ) ;\n")
    segs = sc.parse_def_wires(_mk_def(body), layers, 1000)
    pairs = sc.find_adjacent_pairs(segs, layers, 1000, window_um=2.0)
    assert pairs == {}


def test_find_adjacent_pairs_no_overlap_excluded():
    layers = sc.parse_lef_layers(LEF)
    # adjacent in y (gap 0.23um) but x spans don't overlap (0..1000 vs 5000..9000)
    body = (
        "    - a ( i1 A ) ( i2 Y )\n"
        "      + ROUTED MET1 ( 0 1000 ) ( 1000 * ) ;\n"
        "    - b ( i3 A ) ( i4 Y )\n"
        "      + ROUTED MET1 ( 5000 1230 ) ( 9000 * ) ;\n")
    segs = sc.parse_def_wires(_mk_def(body), layers, 1000)
    pairs = sc.find_adjacent_pairs(segs, layers, 1000, window_um=2.0)
    assert pairs == {}


def test_find_adjacent_pairs_same_net_excluded():
    layers = sc.parse_lef_layers(LEF)
    body = (
        "    - a ( i1 A ) ( i2 Y )\n"
        "      + ROUTED MET1 ( 0 1000 ) ( 10000 * )\n"
        "      NEW MET1 ( 0 1230 ) ( 10000 * ) ;\n")
    segs = sc.parse_def_wires(_mk_def(body), layers, 1000)
    pairs = sc.find_adjacent_pairs(segs, layers, 1000, window_um=2.0)
    assert pairs == {}  # both segments belong to net a


# ── 3. SPEF injection ─────────────────────────────────────────────────────────
GROUNDED_SPEF = """*SPEF "ieee 1481-1999"
*DESIGN "t"
*VERSION "test"
*DIVIDER /
*DELIMITER :
*BUS_DELIMITER []
*T_UNIT 1 NS
*C_UNIT 1 PF
*R_UNIT 1 OHM
*L_UNIT 1 HENRY

*NAME_MAP
*1 a
*2 b

*D_NET *1 0.0002
*CONN
*I *10:D I *D DFF
*I *11:Y O *D INV
*CAP
1 *10:D 0.0001
2 *11:Y 0.0001
*RES
1 *11:Y *10:D 20.0
*END

*D_NET *2 0.0003
*CONN
*I *12:D I *D DFF
*CAP
1 *12:D 0.0003
*RES
1 *12:D *12:D 5.0
*END
"""


def test_inject_coupling_writes_three_field_entry():
    coupling = {("a", "b"): 0.0005}
    new, n = sc.inject_coupling_into_spef(GROUNDED_SPEF, coupling, eps_r=4.0)
    assert n == 1
    # banner present + honest disclosure
    assert "NOT foundry-calibrated" in new
    assert "no rules.C/.nxtgrd" in new
    # a 3-field coupling entry referencing real nodes on both nets
    assert "*10:D *12:D 0.0005" in new
    # owner header total bumped by the coupling (0.0002 + 0.0005)
    assert "*D_NET *1 0.0007" in new
    # grounded caps preserved
    assert "1 *10:D 0.0001" in new
    assert "2 *11:Y 0.0001" in new


def test_inject_coupling_below_threshold_skipped():
    coupling = {("a", "b"): 1e-9}  # < min_cc_pf default 1e-7
    new, n = sc.inject_coupling_into_spef(GROUNDED_SPEF, coupling)
    assert n == 0


def test_inject_coupling_unknown_net_skipped():
    coupling = {("a", "zzz"): 0.001}  # zzz not in name map
    new, n = sc.inject_coupling_into_spef(GROUNDED_SPEF, coupling)
    assert n == 0


def test_inject_coupling_cap_ids_continue_after_grounded():
    coupling = {("a", "b"): 0.0005}
    new, _ = sc.inject_coupling_into_spef(GROUNDED_SPEF, coupling)
    # net a had grounded ids 1,2 → coupling id must be 3
    assert "3 *10:D *12:D 0.0005" in new


# ── end-to-end ────────────────────────────────────────────────────────────────
def test_build_coupling_end_to_end():
    body = (
        "    - a ( i1 A ) ( i2 Y )\n"
        "      + ROUTED MET1 ( 0 1000 ) ( 10000 * ) ;\n"
        "    - b ( i3 A ) ( i4 Y )\n"
        "      + ROUTED MET1 ( 0 1460 ) ( 10000 * ) ;\n")
    res = sc.build_coupling(_mk_def(body), LEF, GROUNDED_SPEF)
    assert res["n_cc_written"] == 1
    assert res["stats"]["n_net_pairs"] == 1
    assert res["stats"]["max_fF"] > 0
    assert "NOT foundry-calibrated" in res["new_spef"]
    # summarize() note discloses the model
    note = sc.summarize(res["stats"])
    assert "analytical" in note and "NOT foundry-calibrated" in note
