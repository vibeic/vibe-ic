"""test_spice_correlation_check_commercial_pdk.py — pure-helper unit tests for the
commercial-PDK real-ngspice cell-delay ↔ liberty NLDM correlation driver added to
spice_correlation_check.py.

These tests exercise ONLY the deterministic, side-effect-free helpers
(liberty parse, NLDM bilinear interpolation, extracted-subckt model rename,
slew→PULSE mapping, deck build, .meas parse, correlation math). The real
ngspice invocation + container orchestration are NOT tested here (they need
the vibeic-eda container + the NDA PDK); the end-to-end run is verified out of
band on the spm run dir.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))
import spice_correlation_check as m  # noqa: E402


# A tiny liberty fragment mirroring the commercial-PDK typ liberty STRUCTURE
# (units + thresholds + one 2x2 NLDM cell). No NDA content — invented numbers.
_LIB = """
library (toy) {
    time_unit : "1ns";
    voltage_unit : "1V";
    slew_lower_threshold_pct_fall : 30.000000;
    slew_upper_threshold_pct_fall : 70.000000;
    slew_lower_threshold_pct_rise : 30.000000;
    slew_upper_threshold_pct_rise : 70.000000;
    input_threshold_pct_fall : 50.000000;
    output_threshold_pct_fall : 50.000000;
    slew_derate_from_library : 0.500000;
    nom_voltage : 1.800000;
    nom_temperature : 25.000000;
    cell (INVD1) {
        pin (A) { direction : input; }
        pin (Y) {
            function : "(!A)";
            direction : output;
            timing () {
                related_pin : "A";
                cell_rise (delay_template_2x2) {
                    index_1("0.1, 0.4");
                    index_2("0.021, 0.084");
                    values("0.10, 0.20", \\
                      "0.30, 0.40");
                }
                cell_fall (delay_template_2x2) {
                    index_1("0.1, 0.4");
                    index_2("0.021, 0.084");
                    values("0.05, 0.15", \\
                      "0.25, 0.35");
                }
            }
        }
    }
}
"""

_CELLS_SPICE = """.GLOBAL VDD VSS
.SUBCKT INVD1 VSS VDD A Y
M$1 Y A VSS VSS nmos L=0.18U W=0.6U
M$2 Y A VDD VDD pmos L=0.18U W=0.9U
.ENDS
.SUBCKT OTHER VSS VDD A Y
M$1 Y A VSS VSS nmos L=0.18U W=0.42U
.ENDS
"""


def test_parse_liberty_header():
    h = m.parse_liberty_header(_LIB)
    assert h["time_unit_ns"] == 1.0
    assert h["slew_lower_fall"] == 30.0 and h["slew_upper_fall"] == 70.0
    assert h["slew_derate"] == 0.5
    assert h["output_threshold_fall"] == 50.0
    assert h["nom_voltage"] == 1.8 and h["nom_temperature"] == 25.0


def test_extract_cell_block_and_pins():
    block = m.extract_cell_block(_LIB, "INVD1")
    assert block is not None and "cell_rise" in block and "cell_fall" in block
    ins, outs = m.liberty_pins(block)
    assert ins == ["A"] and outs == ["Y"]


def test_parse_nldm_table():
    block = m.extract_cell_block(_LIB, "INVD1")
    cf = m.parse_nldm_table(block, "cell_fall")
    assert cf["index_1"] == [0.1, 0.4]
    assert cf["index_2"] == [0.021, 0.084]
    assert cf["values"] == [[0.05, 0.15], [0.25, 0.35]]
    cr = m.parse_nldm_table(block, "cell_rise")
    assert cr["values"][1][1] == 0.40


def test_bilinear_grid_and_interior():
    idx1, idx2 = [0.1, 0.4], [0.021, 0.084]
    vals = [[0.05, 0.15], [0.25, 0.35]]
    # exact grid corners
    assert m.bilinear(idx1, idx2, vals, 0.1, 0.021) == 0.05
    assert m.bilinear(idx1, idx2, vals, 0.4, 0.084) == 0.35
    # interior midpoint = mean of the four corners
    mid = m.bilinear(idx1, idx2, vals, 0.25, 0.0525)
    assert abs(mid - (0.05 + 0.15 + 0.25 + 0.35) / 4) < 1e-9
    # clamp beyond the grid (does not extrapolate past the edge)
    assert m.bilinear(idx1, idx2, vals, 0.05, 0.021) == 0.05
    assert m.bilinear(idx1, idx2, vals, 1.0, 0.084) == 0.35


def test_extract_subckt_model_rename():
    res = m.extract_subckt(_CELLS_SPICE, "INVD1")
    assert res is not None
    pins, body = res
    assert pins == ["VSS", "VDD", "A", "Y"]
    # generic LVS device names must be renamed to the bridge BSIM model names
    assert "nch_tn" in body and "pch_tn" in body
    assert "nmos" not in body and "pmos" not in body
    # W/L and instance names are preserved verbatim
    assert "L=0.18U W=0.6U" in body and "M$1" in body
    assert m.extract_subckt(_CELLS_SPICE, "NOPE") is None


def test_map_pin_to_node():
    assert m._map_pin_to_node("A", "A", "Y") == "a"
    assert m._map_pin_to_node("Y", "A", "Y") == "y"
    assert m._map_pin_to_node("VSS", "A", "Y") == "0"
    assert m._map_pin_to_node("VDD", "A", "Y") == "vdd"


def test_pulse_tr_for_slew():
    # 30-70% thresholds, derate 0.5 → tr_full = slew * 0.5 / 0.4 = 1.25 * slew
    assert abs(m.pulse_tr_for_slew(0.4, 30.0, 70.0, 0.5) - 0.5) < 1e-12
    assert abs(m.pulse_tr_for_slew(0.1, 30.0, 70.0, 0.5) - 0.125) < 1e-12
    # no derate, 10-90% → tr = slew / 0.8
    assert abs(m.pulse_tr_for_slew(0.8, 10.0, 90.0, 1.0) - 1.0) < 1e-12


def test_build_cell_delay_deck():
    res = m.extract_subckt(_CELLS_SPICE, "INVD1")
    pins, body = res
    deck = m.build_cell_delay_deck(
        "/abs/shim.lib", "ttt_lv", "INVD1", body, pins,
        "A", "Y", 1.8, 0.5, 0.0385, 25.0, 0.9)
    assert ".lib '/abs/shim.lib' ttt_lv" in deck
    assert ".temp 25" in deck
    # instance node order maps VSS VDD A Y -> 0 vdd a y
    assert "xdut 0 vdd a y INVD1" in deck
    assert "cload y 0 38.5f" in deck
    assert "pulse(0 1.8 2n 0.5n 0.5n" in deck
    # both delay arcs measured at the 50% (0.9 V) threshold
    assert "TRIG v(a) VAL='0.9' RISE=1 TARG v(y) VAL='0.9' FALL=1" in deck
    assert "TRIG v(a) VAL='0.9' FALL=1 TARG v(y) VAL='0.9' RISE=1" in deck


def test_parse_meas_delays():
    txt = (
        "some banner\n"
        "tphl                =  2.81255e-11 targ=  1.04e-09 trig=  1.01e-09\n"
        "tplh                =  4.76630e-11 targ=  6.09e-09 trig=  6.04e-09\n"
    )
    d = m.parse_meas_delays(txt)
    assert abs(d["tphl"] - 2.81255e-11) < 1e-16
    assert abs(d["tplh"] - 4.76630e-11) < 1e-16
    assert m.parse_meas_delays("no meas here") == {}


def test_correlation_pct():
    # 28.13 ps SPICE vs 33.55 ps liberty → about -16%
    p = m.correlation_pct(28.13e-12, 0.03355)
    assert p is not None and -17.0 < p < -15.0
    # exact match → 0%
    assert abs(m.correlation_pct(0.2e-9, 0.2)) < 1e-9
    # guard: non-positive liberty → None
    assert m.correlation_pct(1e-9, 0.0) is None


def test_finders_and_driver_skip_gracefully(tmp_path):
    # No PDK shim present → driver honestly skips (returns None), never raises.
    assert m._find_bridge_shim(tmp_path) is None
    assert m.run_commercial_pdk_cell_correlation(tmp_path) is None
    # The full-PATH driver skips the same way with no inputs present.
    assert m.run_commercial_pdk_path_correlation(tmp_path) is None
    # The TOP-N path driver skips the same way with no inputs present.
    assert m.run_commercial_pdk_topN_path_correlation(tmp_path) is None


# ══════════════════════════════════════════════════════════════════════════
#  Full-PATH correlation pure-helper tests (deck stitch + STA/netlist/SPEF
#  parse + correlation math). Real ngspice + NDA PDK verified out of band.
# ══════════════════════════════════════════════════════════════════════════

# A synthetic post-route report_checks max-delay path: primary-input x[31]
# through two ANDs into a capture flop's D pin (mirrors the spm crit path).
_STA_RPT = """Startpoint: x[31] (input port clocked by clk)
Endpoint: _455_ (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type: max

  Delay    Time   Description
---------------------------------------------------------
   0.00    0.00   clock clk (rise edge)
   2.00    2.00 v input external delay
   0.00    2.00 v x[31] (in)
   0.26    2.26 v _365_/Y (AND3D1)
   0.17    2.43 v _373_/Y (AND2D1)
   0.00    2.43 v _455_/D (DFFHQD1)
           2.43   data arrival time
"""

# A degenerate flop→output path (no stitchable combinational stage → score 0).
_STA_RPT_FLOP = """Startpoint: _392_ (rising edge-triggered flip-flop clocked by clk)
Endpoint: p (output port clocked by clk)

  Delay    Time   Description
---------------------------------------------------------
   0.21    0.21 ^ _392_/CK (DFFHQD1)
   0.22    0.44 ^ _392_/Q (DFFHQD1)
   0.00    0.44 ^ p (out)
"""

_NETLIST = """module spm (clk, rst, x, p);
 input clk, rst;
 AND3D1 _365_ (.A(y),
    .C(c[31]),
    .B(x[31]),
    .Y(_180_));
 AND2D1 _373_ (.A(_064_),
    .B(_180_),
    .Y(_055_));
 DFFHQD1 _455_ (.D(_055_),
    .CK(clk),
    .Q(c[31]));
endmodule
"""

_SPEF = """*SPEF "IEEE 1481-1998"
*T_UNIT 1 NS
*C_UNIT 1 PF
*NAME_MAP
*94 _055_
*219 _180_
*D_NET *219 0.000445744
*D_NET *94 0.000135308
"""

_CELLS_PATH = """.SUBCKT AND3D1 VSS VDD C B A Y
M$1 n$9 A n$1 n$1 nmos L=0.18U W=0.38U
M$2 n$8 B n$9 n$9 nmos L=0.18U W=0.38U
M$3 n$8 C VSS VSS nmos L=0.18U W=0.38U
M$4 Y n$1 VSS VSS nmos L=0.18U W=0.56U
M$5 VDD C n$1 n$1 pmos L=0.18U W=0.36U
M$6 VDD B n$1 n$1 pmos L=0.18U W=0.255U
M$7 n$1 A VDD VDD pmos L=0.18U W=0.36U
M$8 Y n$1 VDD VDD pmos L=0.18U W=0.9U
.ENDS
.SUBCKT AND2D1 VSS VDD B A Y
M$1 n$7 A n$1 n$1 nmos L=0.18U W=0.32U
M$2 n$7 B VSS VSS nmos L=0.18U W=0.32U
M$3 Y n$1 VSS VSS nmos L=0.18U W=0.6U
M$4 VDD B n$1 n$1 pmos L=0.18U W=0.36U
M$5 Y n$1 VDD VDD pmos L=0.18U W=0.902U
M$6 VDD A n$1 n$1 pmos L=0.18U W=0.36U
.ENDS
.SUBCKT DFFHQD1 VSS VDD Q CK D
M$1 Q n$8 VSS VSS nmos L=0.18U W=0.445U
.ENDS
"""

_LIB_DFF = """
library (toy) { time_unit : "1ns";
    cell (DFFHQD1) {
        pin (D) { direction : input; capacitance : 0.002200; }
        pin (CK) { direction : input; capacitance : 0.003210; }
        pin (Q) { direction : output; }
    }
}
"""


def test_normalize_mos_bulk():
    body = (".SUBCKT AND2D1 VSS VDD B A Y\n"
            "M$1 n$7 A n$1 n$1 nch_tn L=0.18U W=0.32U\n"
            "M$5 Y n$1 VDD VDD pch_tn L=0.18U W=0.9U\n.ENDS")
    out = m.normalize_mos_bulk(body, "VSS", "VDD")
    # nmos bulk (4th node) rebound to VSS; W/L + other nodes preserved
    assert "M$1 n$7 A n$1 VSS nch_tn L=0.18U W=0.32U" in out
    # pmos bulk already VDD stays VDD
    assert "M$5 Y n$1 VDD VDD pch_tn" in out
    # header/footer untouched
    assert ".SUBCKT AND2D1 VSS VDD B A Y" in out and ".ENDS" in out


def test_cell_family_classifiers():
    assert m.is_sequential_cell("DFFHQD1") and not m.is_sequential_cell("AND2D1")
    assert m.cell_inverts("INVD1") and m.cell_inverts("NAND2D1")
    assert not m.cell_inverts("AND2D1") and not m.cell_inverts("XOR2D1")
    assert m.tie_value_for_cell("AND2D1") == "vdd"
    assert m.tie_value_for_cell("NAND2D1") == "vdd"
    assert m.tie_value_for_cell("NOR2D1") == "0"
    assert m.tie_value_for_cell("OR2D1") == "0"
    assert m.tie_value_for_cell("XNOR2D1") == "0"


def test_parse_sta_path():
    p = m.parse_sta_path(_STA_RPT)
    assert p["startpoint"] == "x[31]" and p["endpoint"] == "_455_"
    assert p["start_time_ns"] == 2.00 and p["end_time_ns"] == 2.43
    assert abs(p["path_delay_ns"] - 0.43) < 1e-9
    assert p["endpoint_transition"] == "fall"
    # the "input external delay" row (no `(CELL)`) is not captured
    cells = [r["cell"] for r in p["rows"]]
    assert cells == ["in", "AND3D1", "AND2D1", "DFFHQD1"]


def test_sta_path_stitch_score():
    names = {"AND3D1", "AND2D1", "DFFHQD1", "INVD1"}
    assert m.sta_path_stitch_score(_STA_RPT, names) == 2      # two ANDs
    assert m.sta_path_stitch_score(_STA_RPT_FLOP, names) == 0  # flop→port only


def test_parse_verilog_instances():
    im = m.parse_verilog_instances(_NETLIST)
    assert im["_365_"]["cell"] == "AND3D1"
    assert im["_365_"]["conns"]["B"] == "x[31]"
    assert im["_365_"]["conns"]["Y"] == "_180_"
    assert im["_373_"]["conns"]["B"] == "_180_"
    assert im["_455_"]["conns"]["D"] == "_055_"


def test_parse_spef_caps():
    caps = m.parse_spef_caps(_SPEF)
    assert abs(caps["_180_"] - 0.000445744) < 1e-12
    assert abs(caps["_055_"] - 0.000135308) < 1e-12
    # unit / section keywords must NOT be picked up as nets
    assert "T_UNIT" not in caps and "NAME_MAP" not in caps


def test_liberty_pin_cap():
    block = m.extract_cell_block(_LIB_DFF, "DFFHQD1")
    assert abs(m.liberty_pin_cap(block, "D") - 0.002200) < 1e-9
    assert abs(m.liberty_pin_cap(block, "CK") - 0.003210) < 1e-9
    assert m.liberty_pin_cap(block, "NOPE") is None


def test_resolve_path_stages_faithful_toggle_pins():
    p = m.parse_sta_path(_STA_RPT)
    im = m.parse_verilog_instances(_NETLIST)
    caps = m.parse_spef_caps(_SPEF)
    names = {"AND3D1", "AND2D1", "DFFHQD1"}
    r = m.resolve_path_stages(p, im, caps, names, _LIB_DFF)
    assert r["covered"] == 2 and r["total_comb"] == 2
    s0, s1 = r["stages"]
    # stage 0 toggling pin = the AND3D1 pin on the startpoint net x[31] → B
    assert s0["inst"] == "_365_" and s0["toggle_pin"] == "B"
    assert s0["out_net"] == "_180_"
    assert abs(s0["wire_cap_pf"] - 0.000445744) < 1e-12
    # stage 1 toggling pin = the AND2D1 pin on stage-0's out net _180_ → B
    assert s1["inst"] == "_373_" and s1["toggle_pin"] == "B"
    assert s1["out_net"] == "_055_"
    # endpoint load = last-net wire cap + DFF D-pin cap (0.1353fF + 2.2fF)
    assert abs(r["endpoint_load_pf"] - (0.000135308 + 0.002200)) < 1e-9


def test_build_path_deck_stitch_structure():
    subckts = {
        "AND3D1": m.extract_subckt(_CELLS_PATH, "AND3D1"),
        "AND2D1": m.extract_subckt(_CELLS_PATH, "AND2D1"),
    }
    stages = [
        {"inst": "_365_", "cell": "AND3D1", "toggle_pin": "B", "out_pin": "Y",
         "out_net": "_180_", "wire_cap_pf": 0.000445744},
        {"inst": "_373_", "cell": "AND2D1", "toggle_pin": "B", "out_pin": "Y",
         "out_net": "_055_", "wire_cap_pf": 0.000135308},
    ]
    deck = m.build_path_deck("/abs/shim.lib", "ttt_lv", stages, subckts,
                             1.8, 0.5, 25.0, 0.9,
                             endpoint_load_pf=0.000135308 + 0.002200)
    assert ".lib '/abs/shim.lib' ttt_lv" in deck
    # stage-0 output is intermediate node n0; stage-1 output is pout
    # AND3D1 pins VSS VDD C B A Y ; toggle B→a(in), tie A,C→vdd, out Y→n0
    assert "0 vdd vdd a vdd n0 AND3D1" in deck
    # AND2D1 pins VSS VDD B A Y ; toggle B→n0, tie A→vdd, out Y→pout
    assert "0 vdd n0 vdd pout AND2D1" in deck
    # bulk normalised inside the emitted subckts (no source-tied bulk artefact)
    assert "M$1 n$9 A n$1 VSS nch_tn" in deck
    # each net carries a cap; final node carries the endpoint receiver cap too
    assert "cpout pout 0" in deck
    # non-inverting chain → output-fall reached by a falling input edge
    assert "TRIG v(a) VAL='0.9' FALL=1 TARG v(pout) VAL='0.9' FALL=1" in deck
    assert "TRIG v(a) VAL='0.9' RISE=1 TARG v(pout) VAL='0.9' RISE=1" in deck


def test_build_path_deck_inverting_parity():
    # A single inverting stage flips the input edge needed for an output fall.
    subckts = {"INVD1": (["VSS", "VDD", "A", "Y"],
                         ".SUBCKT INVD1 VSS VDD A Y\n"
                         "M$1 Y A VSS VSS nch_tn L=0.18U W=0.6U\n.ENDS")}
    stages = [{"inst": "_1_", "cell": "INVD1", "toggle_pin": "A",
               "out_pin": "Y", "out_net": "n", "wire_cap_pf": 0.0}]
    deck = m.build_path_deck("/s.lib", "ttt_lv", stages, subckts,
                             1.8, 0.5, 25.0, 0.9, endpoint_load_pf=0.001)
    # odd inversion parity → output FALL needs a RISING input edge
    assert "TRIG v(a) VAL='0.9' RISE=1 TARG v(pout) VAL='0.9' FALL=1" in deck


def test_parse_path_meas():
    txt = ("banner\n"
           "tpd_fall            =  3.91272e-10 targ=  1.5e-08 trig=  1.4e-08\n"
           "tpd_rise            =  2.28738e-10 targ=  2.4e-09 trig=  2.2e-09\n"
           "vpout_max           =  1.84339e+00 at=  1.5e-08\n"
           "vpout_min           = -3.21948e-02 at=  2.4e-09\n")
    d = m.parse_path_meas(txt)
    assert abs(d["tpd_fall"] - 3.91272e-10) < 1e-16
    assert abs(d["tpd_rise"] - 2.28738e-10) < 1e-16
    assert abs(d["vpout_max"] - 1.84339) < 1e-6
    assert abs(d["vpout_min"] - (-0.0321948)) < 1e-9


def test_path_correlation_pct_reuses_cell_math():
    # SPICE 0.391 ns vs STA 0.43 ns → ~ -9 %
    p = m.correlation_pct(0.391323e-9, 0.43)
    assert p is not None and -9.5 < p < -8.5


# ══════════════════════════════════════════════════════════════════════════
#  TOP-N path correlation pure-helper tests (multi-path parse + dedup +
#  aggregate math + skip-reason handling + OpenSTA tcl build). Real ngspice +
#  OpenSTA verified out of band on the spm run dir.
# ══════════════════════════════════════════════════════════════════════════

# A 3-path report_checks transcript: two distinct endpoints (_455_, _404_) and
# a DUPLICATE of _404_ (OpenSTA emits repeat paths to the same endpoint).
_STA_MULTI = """Startpoint: x[31] (input port clocked by clk)
Endpoint: _455_ (rising edge-triggered flip-flop clocked by clk)

  Delay    Time   Description
---------------------------------------------------------
   0.00    2.00 v x[31] (in)
   0.25    2.25 v _365_/Y (AND3D1)
   0.16    2.41 v _373_/Y (AND2D1)
   0.00    2.41 v _455_/D (DFFHQD1)
           2.41   data arrival time
          10.00 ^ _455_/CK (DFFHQD1)

Startpoint: y (input port clocked by clk)
Endpoint: _404_ (rising edge-triggered flip-flop clocked by clk)

  Delay    Time   Description
---------------------------------------------------------
   0.00    2.00 ^ y (in)
   0.06    2.06 v _262_/Y (NAND2D1)
   0.19    2.25 ^ _265_/Y (XOR3D2)
   0.05    2.30 v _266_/Y (NOR2D1)
   0.00    2.30 v _404_/D (DFFHQD1)
           2.30   data arrival time

Startpoint: y (input port clocked by clk)
Endpoint: _404_ (rising edge-triggered flip-flop clocked by clk)

  Delay    Time   Description
---------------------------------------------------------
   0.00    2.00 ^ y (in)
   0.06    2.06 v _262_/Y (NAND2D1)
   0.19    2.25 ^ _265_/Y (XOR3D2)
   0.05    2.30 v _266_/Y (NOR2D1)
   0.00    2.30 v _404_/D (DFFHQD1)
           2.30   data arrival time
"""


def test_split_sta_path_blocks():
    blocks = m.split_sta_path_blocks(_STA_MULTI)
    assert len(blocks) == 3
    assert blocks[0].startswith("Startpoint: x[31]")
    assert m.split_sta_path_blocks("no startpoint here") == []


def test_parse_sta_paths_multi_dedups_distinct_endpoints():
    paths = m.parse_sta_paths_multi(_STA_MULTI, max_paths=5)
    # the duplicate y→_404_ collapses to ONE distinct-endpoint path
    assert [(p["startpoint"], p["endpoint"]) for p in paths] == [
        ("x[31]", "_455_"), ("y", "_404_")]
    assert abs(paths[0]["path_delay_ns"] - 0.41) < 1e-9   # 2.41-2.00
    assert abs(paths[1]["path_delay_ns"] - 0.30) < 1e-9   # 2.30-2.00
    # max_paths caps the count
    assert len(m.parse_sta_paths_multi(_STA_MULTI, max_paths=1)) == 1
    # no-dedup keeps the repeat
    assert len(m.parse_sta_paths_multi(_STA_MULTI, max_paths=5,
                                       dedup=False)) == 3


def test_aggregate_path_correlations_mixed():
    per = [
        {"verdict": "CORRELATED", "pct_error": -4.6},
        {"verdict": "MISMATCH", "pct_error": 14.0},
        {"verdict": "SKIP", "skip_reason": "endpoint_did_not_swing"},
        {"verdict": "SKIP", "skip_reason": "no_stitchable_combinational_stage"},
    ]
    agg = m.aggregate_path_correlations(per)
    assert agg["n_paths"] == 4 and agg["n_correlated"] == 2
    assert agg["n_skipped"] == 2
    assert agg["worst_abs_pct_error"] == 14.0
    assert abs(agg["mean_abs_pct_error"] - 9.3) < 1e-9   # (4.6+14.0)/2
    assert agg["verdict"] == "MISMATCH"
    assert agg["skip_reasons"] == {"endpoint_did_not_swing": 1,
                                   "no_stitchable_combinational_stage": 1}


def test_aggregate_path_correlations_verdict_ladder():
    # any CRITICAL dominates
    agg = m.aggregate_path_correlations([
        {"verdict": "CRITICAL_MISMATCH", "pct_error": -30.0},
        {"verdict": "CORRELATED", "pct_error": 2.0}])
    assert agg["verdict"] == "CRITICAL_MISMATCH"
    assert agg["worst_abs_pct_error"] == 30.0
    # all correlated within tol → CORRELATED
    agg2 = m.aggregate_path_correlations([
        {"verdict": "CORRELATED", "pct_error": 1.0},
        {"verdict": "CORRELATED", "pct_error": -3.0}])
    assert agg2["verdict"] == "CORRELATED"


def test_aggregate_path_correlations_none_correlated():
    agg = m.aggregate_path_correlations([
        {"verdict": "SKIP", "skip_reason": "endpoint_did_not_swing"}])
    assert agg["verdict"] == "NO_PATH_CORRELATED"
    assert agg["worst_abs_pct_error"] is None
    assert agg["mean_abs_pct_error"] is None
    assert agg["n_correlated"] == 0 and agg["n_skipped"] == 1


def test_build_topN_sta_tcl():
    tcl = m.build_topN_sta_tcl("/l.lib", "/n.v", "spm", "/c.sdc", "/s.spef", 5)
    assert "read_liberty /l.lib" in tcl
    assert "read_verilog /n.v" in tcl and "link_design spm" in tcl
    assert "read_sdc /c.sdc" in tcl and "read_spef /s.spef" in tcl
    assert ("report_checks -path_delay max -group_count 5 "
            "-endpoint_count 1 -format full") in tcl
    assert tcl.rstrip().endswith("exit")
    # sdc/spef omitted when absent
    tcl2 = m.build_topN_sta_tcl("/l.lib", "/n.v", "spm", None, None, 3)
    assert "read_sdc" not in tcl2 and "read_spef" not in tcl2
    assert "-group_count 3 " in tcl2


def test_top_module_name():
    assert m._top_module_name("module spm (clk,\n  input x);") == "spm"
    assert m._top_module_name("// no module\nwire a;") is None


def test_stitch_skip_no_combinational_stage():
    # A flop→port path has 0 stitchable combinational stages → honest SKIP with
    # a reason, and the ngspice/shim path is never touched (dummy paths safe).
    p = m.parse_sta_path(_STA_RPT_FLOP)
    im = m.parse_verilog_instances(_NETLIST)
    caps = m.parse_spef_caps(_SPEF)
    hdr = m.parse_liberty_header(_LIB)
    res = m._stitch_sim_correlate_path(
        p, im, caps, {"DFFHQD1"}, _CELLS_PATH, _LIB_DFF, hdr,
        Path("/nonexistent/shim.lib"), "vibeic-eda", "ttt_lv", 0.4, 12,
        Path("/nonexistent/hspice"), Path("/tmp"), "t")
    assert res["verdict"] == "SKIP"
    assert res["skip_reason"] == "no_stitchable_combinational_stage"
    assert res["endpoint"] == "p" and "pct_error" not in res
