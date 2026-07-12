"""test_spice_correlation_check_hp18e80.py — pure-helper unit tests for the
HP18E80 real-ngspice cell-delay ↔ liberty NLDM correlation driver added to
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


# A tiny liberty fragment mirroring the m18e80pm180su_typ.lib STRUCTURE
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
    assert m.run_hp18e80_cell_correlation(tmp_path) is None
