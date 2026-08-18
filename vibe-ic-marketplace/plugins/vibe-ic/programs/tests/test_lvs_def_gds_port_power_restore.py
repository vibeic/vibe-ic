"""Unit tests for `def_gds_port_power_restore.py`.

Pin the deterministic DEF-parsing half — `parse_pins` (top-level I/O pin
name/layer/coord) and `parse_power_rails` (SPECIALNETS FOLLOWPIN segments
with `*` wildcard-coordinate resolution). These run on a CI host WITHOUT
KLayout's `pya`, so only the pure parsers are exercised here.

The `restore()` pass that injects `pya.Text` labels + `pya.Box` rail
markers is pya-gated; we only assert its disclosed exit-3 fallback, which
fires precisely because `pya` is absent on the CI host.

Chip-AGNOSTIC synthetic DEF fixtures (generic `widget` top, generic nets).
"""
import importlib

import pytest

mod = importlib.import_module("def_gds_port_power_restore")

try:
    import pya  # noqa: F401
    _HAS_PYA = True
except Exception:
    _HAS_PYA = False


# A small, chip-agnostic synthetic routed DEF. Exercises: multi-line PINS
# (clk), single-line PINS (data[0]) with a bus bit, a PINS entry that omits
# LAYER/PLACED (nolayer -> dropped), and a SPECIALNETS FOLLOWPIN power grid
# for VDD (two rail segments, both `*` wildcard forms) + VSS (one segment).
FULL_DEF = """\
VERSION 5.8 ;
DESIGN widget ;
UNITS DISTANCE MICRONS 1000 ;

PINS 3 ;
    - clk + NET clk + DIRECTION INPUT + USE SIGNAL
      + PORT
        + LAYER MET3 ( -400 -150 ) ( 400 150 )
        + PLACED ( 100 200 ) N ;
    - data[0] + NET data[0] + DIRECTION OUTPUT + USE SIGNAL
      + PORT + LAYER MET1 ( 0 0 ) ( 10 10 ) + PLACED ( 300 -400 ) N ;
    - nolayer + NET nolayer + DIRECTION INPUT + USE SIGNAL ;
END PINS

SPECIALNETS 2 ;
    - VDD ( * VPWR )
      + ROUTED MET1 480 + SHAPE FOLLOWPIN ( 100 200 ) ( 900 * )
        NEW MET1 480 + SHAPE FOLLOWPIN ( 100 700 ) ( * 1500 )
      + USE POWER ;
    - VSS ( * VGND )
      + ROUTED MET1 480 + SHAPE FOLLOWPIN ( 100 0 ) ( 900 * )
      + USE GROUND ;
END SPECIALNETS

END DESIGN
"""

# A DEF with no PINS section and no SPECIALNETS section.
NO_SECTIONS_DEF = "VERSION 5.8 ;\nDESIGN empty ;\nNETS 0 ;\nEND NETS\nEND DESIGN\n"

# A SPECIALNET that carries no MET rail segment (a bare PIN alias) -> no rail.
NO_SEG_SPECIALNETS_DEF = (
    "SPECIALNETS 1 ;\n"
    "    - VDD ( PIN VDD )\n"
    "      + USE POWER ;\n"
    "END SPECIALNETS\n"
)


class TestParsePins:
    def test_parses_two_valid_pins(self):
        pins = mod.parse_pins(FULL_DEF)
        assert len(pins) == 2

    def test_order_and_names(self):
        pins = mod.parse_pins(FULL_DEF)
        assert [p[0] for p in pins] == ["clk", "data[0]"]

    def test_layers_captured(self):
        pins = mod.parse_pins(FULL_DEF)
        by_name = {p[0]: p for p in pins}
        assert by_name["clk"][1] == "MET3"
        assert by_name["data[0]"][1] == "MET1"

    def test_coords_are_int_dbu(self):
        pins = mod.parse_pins(FULL_DEF)
        by_name = {p[0]: p for p in pins}
        assert by_name["clk"][2:] == (100, 200)
        # negative coordinate parsed as a signed int
        assert by_name["data[0]"][2:] == (300, -400)

    def test_bus_bit_kept_verbatim(self):
        pins = mod.parse_pins(FULL_DEF)
        assert any(p[0] == "data[0]" for p in pins)

    def test_pin_without_layer_or_placed_is_dropped(self):
        pins = mod.parse_pins(FULL_DEF)
        assert all(p[0] != "nolayer" for p in pins)

    def test_no_pins_section_returns_empty(self):
        assert mod.parse_pins(NO_SECTIONS_DEF) == []

    def test_empty_text(self):
        assert mod.parse_pins("") == []


class TestParsePowerRails:
    def test_both_rails_present(self):
        rails = mod.parse_power_rails(FULL_DEF)
        assert set(rails.keys()) == {"VDD", "VSS"}

    def test_vdd_has_two_segments(self):
        rails = mod.parse_power_rails(FULL_DEF)
        assert len(rails["VDD"]) == 2

    def test_first_vdd_segment_exact_with_width(self):
        # ( 100 200 ) ( 900 * ) : x2=900, y2 wildcard -> resolves to y1=200.
        # v1.3.93 — the 6th tuple element is the metal layer (MET1 here).
        rails = mod.parse_power_rails(FULL_DEF)
        assert rails["VDD"][0] == (100, 200, 900, 200, 480, "MET1")

    def test_y_wildcard_resolves_to_start_y(self):
        rails = mod.parse_power_rails(FULL_DEF)
        x1, y1, x2, y2, w, metal = rails["VDD"][0]
        assert y2 == y1 == 200
        assert metal == "MET1"

    def test_x_wildcard_resolves_to_start_x(self):
        # ( 100 700 ) ( * 1500 ) : x2 wildcard -> resolves to x1=100.
        rails = mod.parse_power_rails(FULL_DEF)
        assert rails["VDD"][1] == (100, 700, 100, 1500, 480, "MET1")
        assert rails["VDD"][1][2] == rails["VDD"][1][0] == 100

    def test_vss_single_segment(self):
        rails = mod.parse_power_rails(FULL_DEF)
        assert rails["VSS"] == [(100, 0, 900, 0, 480, "MET1")]

    def test_no_specialnets_returns_empty(self):
        assert mod.parse_power_rails(NO_SECTIONS_DEF) == {}

    def test_empty_text(self):
        assert mod.parse_power_rails("") == {}

    def test_net_without_rail_segment_omitted(self):
        # A SPECIALNET with no MET FOLLOWPIN segment contributes no rail.
        assert mod.parse_power_rails(NO_SEG_SPECIALNETS_DEF) == {}


class TestModuleConstants:
    def test_rail_marker_layers(self):
        # VDD -> 901, VSS -> 902 (the geometry-marker layers the extractor reads).
        assert mod.RAIL_MARKER["VDD"] == (901, 0)
        assert mod.RAIL_MARKER["VSS"] == (902, 0)

    def test_text_layer(self):
        assert mod.TEXT_LAYER == (100, 0)


@pytest.mark.skipif(_HAS_PYA, reason="exit-3 disclosure only fires when pya is absent")
class TestRestorePyaGate:
    def test_restore_returns_3_when_pya_absent(self):
        # `restore` imports pya FIRST and returns 3 (disclosed) before touching
        # any file, so bogus paths are fine on a host without KLayout.
        rc = mod.restore("no.gds", "no.def", "out.gds")
        assert rc == 3
