"""Unit tests for `lvs_def_port_seed.py` (Route B — DEF-pin port seed).

Pin the deterministic shape of the DEF PINS parser and the netgen
port-seed / .subckt-injection emitters. Chip-agnostic synthetic DEF
fixture (no HDLC-specific names hardcoded into the program under test).
"""
import importlib

import pytest

mod = importlib.import_module("lvs_def_port_seed")


# A small, chip-agnostic synthetic DEF. Exercises: multi-line PINS entries,
# bus bits (data[0]/data[1]), INPUT/OUTPUT/INOUT, a NET name that differs from
# the pin name, and a pin that omits DIRECTION.
SYNTH_DEF = """\
VERSION 5.8 ;
DESIGN widget ;
UNITS DISTANCE MICRONS 1000 ;

PINS 5 ;
    - clk + NET clk + DIRECTION INPUT + USE SIGNAL
      + PORT
        + LAYER met3 ( -400 -150 ) ( 400 150 )
        + PLACED ( 248850 117300 ) N ;
    - rst_n + NET sys_reset + DIRECTION INPUT + USE SIGNAL
      + PORT
        + LAYER met3 ( -400 -150 ) ( 400 150 )
        + PLACED ( 248850 143140 ) N ;
    - data[0] + NET data[0] + DIRECTION OUTPUT + USE SIGNAL
      + PORT + LAYER met3 ( -400 -150 ) ( 400 150 ) + PLACED ( 1 2 ) N ;
    - data[1] + NET data[1] + DIRECTION OUTPUT + USE SIGNAL
      + PORT + LAYER met3 ( -400 -150 ) ( 400 150 ) + PLACED ( 3 4 ) N ;
    - bidir + NET bidir + DIRECTION INOUT + USE SIGNAL
      + PORT + LAYER met4 ( 0 0 ) ( 10 10 ) + PLACED ( 5 6 ) N ;
END PINS

NETS 0 ;
END NETS
END DESIGN
"""

# A DEF whose PINS entry omits the DIRECTION token (legal, rare).
NODIR_DEF = """\
PINS 1 ;
    - solo + NET solo + USE SIGNAL
      + PORT + LAYER met3 ( 0 0 ) ( 1 1 ) + PLACED ( 0 0 ) N ;
END PINS
"""

NO_PINS_DEF = "VERSION 5.8 ;\nDESIGN empty ;\nNETS 0 ;\nEND NETS\nEND DESIGN\n"


class TestParseDefPins:
    def test_parses_all_five(self):
        pins = mod.parse_def_pins(SYNTH_DEF)
        assert len(pins) == 5

    def test_order_preserved(self):
        pins = mod.parse_def_pins(SYNTH_DEF)
        assert [p.name for p in pins] == ["clk", "rst_n", "data[0]", "data[1]", "bidir"]

    def test_net_differs_from_name(self):
        pins = mod.parse_def_pins(SYNTH_DEF)
        rst = next(p for p in pins if p.name == "rst_n")
        assert rst.net == "sys_reset"

    def test_direction_uppercased(self):
        pins = mod.parse_def_pins(SYNTH_DEF)
        assert next(p for p in pins if p.name == "clk").direction == "INPUT"
        assert next(p for p in pins if p.name == "bidir").direction == "INOUT"

    def test_bus_bits_kept_verbatim(self):
        pins = mod.parse_def_pins(SYNTH_DEF)
        assert any(p.name == "data[0]" for p in pins)
        assert any(p.name == "data[1]" for p in pins)

    def test_missing_direction_defaults_empty(self):
        pins = mod.parse_def_pins(NODIR_DEF)
        assert len(pins) == 1
        assert pins[0].direction == ""
        assert pins[0].net == "solo"

    def test_no_pins_section_returns_empty(self):
        assert mod.parse_def_pins(NO_PINS_DEF) == []

    def test_empty_text(self):
        assert mod.parse_def_pins("") == []

    def test_single_line_entries_robust(self):
        # All on one line per entry should still parse.
        d = ("PINS 2 ;\n"
             "- a + NET a + DIRECTION INPUT ;\n"
             "- b + NET b + DIRECTION OUTPUT ;\n"
             "END PINS\n")
        pins = mod.parse_def_pins(d)
        assert [p.name for p in pins] == ["a", "b"]


class TestOrderedPortList:
    def test_names_in_order(self):
        pins = mod.parse_def_pins(SYNTH_DEF)
        assert mod.build_ordered_port_list(pins) == [
            "clk", "rst_n", "data[0]", "data[1]", "bidir"]

    def test_dedupe_preserves_first(self):
        from lvs_def_port_seed import DefPin
        pins = [DefPin("x", "x", "INPUT"), DefPin("x", "x", "INPUT"),
                DefPin("y", "y", "OUTPUT")]
        assert mod.build_ordered_port_list(pins) == ["x", "y"]


class TestSubcktLine:
    def test_verbatim_keeps_brackets(self):
        pins = mod.parse_def_pins(SYNTH_DEF)
        line = mod.build_subckt_line("widget", pins)
        assert line.startswith(".subckt widget ")
        assert "data[0]" in line

    def test_spice_safe_maps_brackets_to_dots(self):
        pins = mod.parse_def_pins(SYNTH_DEF)
        line = mod.build_subckt_line_spice_safe("widget", pins)
        assert "data.0" in line
        assert "data[0]" not in line

    def test_empty_pins_emits_portless_line(self):
        line = mod.build_subckt_line("widget", [])
        assert line == ".subckt widget"


class TestNetgenSeedTcl:
    def test_lists_all_ports(self):
        pins = mod.parse_def_pins(SYNTH_DEF)
        tcl = mod.build_netgen_seed_tcl("widget", pins)
        # spice-safe by default -> brackets become dots
        for tok in ("clk", "rst_n", "data.0", "data.1", "bidir"):
            assert tok in tcl

    def test_equate_pins_per_port(self):
        pins = mod.parse_def_pins(SYNTH_DEF)
        tcl = mod.build_netgen_seed_tcl("widget", pins)
        directive_lines = [l for l in tcl.splitlines()
                           if l.startswith("equate pins ")]
        assert len(directive_lines) == 5

    def test_no_spice_safe_keeps_brackets(self):
        pins = mod.parse_def_pins(SYNTH_DEF)
        tcl = mod.build_netgen_seed_tcl("widget", pins, spice_safe=False)
        assert "data[0]" in tcl

    def test_empty_pins_emits_skipped(self):
        tcl = mod.build_netgen_seed_tcl("widget", [])
        assert "LVS_PORT_SEED_SKIPPED" in tcl

    def test_generated_by_provenance(self):
        tcl = mod.build_netgen_seed_tcl("widget", mod.parse_def_pins(SYNTH_DEF))
        assert "lvs_def_port_seed.py" in tcl


class TestInjectPortsIntoSubckt:
    PORTLESS = ".subckt widget\nX0 a b sky130_fd_sc_hd__inv\n.ends\n"

    def test_rewrites_portless_line(self):
        pins = mod.parse_def_pins(SYNTH_DEF)
        out = mod.inject_ports_into_subckt(self.PORTLESS, "widget", pins)
        assert ".subckt widget clk rst_n data.0 data.1 bidir" in out

    def test_idempotent_when_ports_present(self):
        already = ".subckt widget clk rst_n\nX0 a b inv\n.ends\n"
        pins = mod.parse_def_pins(SYNTH_DEF)
        out = mod.inject_ports_into_subckt(already, "widget", pins)
        # Should NOT clobber the existing port list.
        assert out == already

    def test_top_absent_returns_unchanged(self):
        pins = mod.parse_def_pins(SYNTH_DEF)
        other = ".subckt something_else\n.ends\n"
        assert mod.inject_ports_into_subckt(other, "widget", pins) == other

    def test_no_spice_safe_injects_brackets(self):
        pins = mod.parse_def_pins(SYNTH_DEF)
        out = mod.inject_ports_into_subckt(self.PORTLESS, "widget", pins,
                                           spice_safe=False)
        assert "data[0]" in out

    def test_chip_agnostic_arbitrary_top_name(self):
        pins = mod.parse_def_pins(SYNTH_DEF)
        src = ".subckt my_weird_TOP_42\n.ends\n"
        out = mod.inject_ports_into_subckt(src, "my_weird_TOP_42", pins)
        assert ".subckt my_weird_TOP_42 clk" in out


class TestNoHdlcHardcoding:
    def test_program_source_has_no_hdlc_literal(self):
        import inspect
        src = inspect.getsource(mod)
        # The program logic must not key off the HDLC name (comments/docstring
        # may mention the pilot, but no code literal 'hdlc_core' string).
        # Strip the module docstring before checking code.
        code = src.split('"""', 2)[-1] if src.count('"""') >= 2 else src
        assert "hdlc_core" not in code.replace("RESULT_e2e_pilot.md", "")
