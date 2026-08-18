"""v1.3.93 — unit tests for the commercial-PDK sign-off bridge helpers that
made spm's antenna repair + post-layout LEC run chip-AGNOSTICALLY:

  * _discover_antenna_diode_from_lef — find the `CLASS CORE ANTENNACELL` diode.
  * _synthesize_physical_cell_stubs  — blackbox stubs for LEF-only fillers.
  * _module_port_names / _is_supply_name / _gate_only_supply_ports — strip the
    PDN-added VDD/VSS gate ports the synth gold lacks (else equiv_make aborts).

All synthetic, chip-AGNOSTIC fixtures (generic `widget` top, generic cells).
"""
import importlib
from pathlib import Path

mod = importlib.import_module("phase3_one_shot_runner")


# --- antenna-diode discovery ----------------------------------------------
_LEF_WITH_DIODE = """\
MACRO NAND2D1
  CLASS CORE ;
  SIZE 2.64 BY 5.04 ;
END NAND2D1
MACRO ANTENNA
  CLASS CORE ANTENNACELL ;
  SIZE 1.32 BY 5.04 ;
  PIN DIODE
    DIRECTION INPUT ; USE SIGNAL ;
  END DIODE
END ANTENNA
MACRO FILL1
  CLASS CORE SPACER ;
  SIZE 0.66 BY 5.04 ;
END FILL1
"""
_LEF_NO_DIODE = """\
MACRO NAND2D1
  CLASS CORE ;
  SIZE 2.64 BY 5.04 ;
END NAND2D1
"""


def test_discover_antenna_diode_found(tmp_path):
    lef = tmp_path / "cells.lef"
    lef.write_text(_LEF_WITH_DIODE)
    assert mod._discover_antenna_diode_from_lef([str(lef)]) == "ANTENNA"


def test_discover_antenna_diode_absent(tmp_path):
    lef = tmp_path / "cells.lef"
    lef.write_text(_LEF_NO_DIODE)
    assert mod._discover_antenna_diode_from_lef([str(lef)]) is None


def test_discover_antenna_diode_scans_multiple_lefs(tmp_path):
    a = tmp_path / "a.lef"; a.write_text(_LEF_NO_DIODE)
    b = tmp_path / "b.lef"; b.write_text(_LEF_WITH_DIODE)
    assert mod._discover_antenna_diode_from_lef([None, str(a), str(b)]) == "ANTENNA"


# --- physical-cell blackbox stub synthesis --------------------------------
_STUB_LEF = """\
MACRO NAND2D1
  CLASS CORE ;
  SIZE 2.64 BY 5.04 ;
END NAND2D1
MACRO FILL1
  CLASS CORE SPACER ;
  SIZE 0.66 BY 5.04 ;
  PIN VDD
    DIRECTION INOUT ; USE POWER ;
  END VDD
  PIN VSS
    DIRECTION INOUT ; USE GROUND ;
  END VSS
END FILL1
"""
# gate netlist instantiates NAND2D1 (in Liberty) + FILL1 (LEF-only) + FILL9 (no LEF)
_GATE_V = """\
module widget (a, b, y);
  input a, b;
  output y;
  NAND2D1 _1_ ( .A(a), .B(b), .Y(y) );
  FILL1 FILLER_0 ();
  FILL9 FILLER_1 ();
endmodule
"""
_LIBERTY = 'library(x){ cell (NAND2D1) { area:1; } cell(DFFHQD1){area:2;} }'


def _mk_pdk(tmp_path):
    lef = tmp_path / "cells.lef"; lef.write_text(_STUB_LEF)
    lib = tmp_path / "x.lib"; lib.write_text(_LIBERTY)
    return mod.PdkConfig(
        name="custom:x", liberty=str(lib), tech_lef=str(lef), cell_lef=str(lef),
        cell_gds=None, site="unit", drc_deck=None)


def test_synthesize_stubs_only_lef_only_undefined(tmp_path):
    pdk = _mk_pdk(tmp_path)
    gate = tmp_path / "gate.v"; gate.write_text(_GATE_V)
    out = tmp_path / "out"
    c = mod._synthesize_physical_cell_stubs(pdk, "widget", gate, "no-container", out)
    assert c is not None
    text = (out / "physical_cell_stubs.v").read_text()
    # FILL1 is LEF-only + undefined in Liberty -> stubbed WITH its LEF pins
    assert "module FILL1 (VDD, VSS);" in text
    assert "inout VDD;" in text and "inout VSS;" in text
    # NAND2D1 IS in Liberty -> NOT stubbed
    assert "module NAND2D1" not in text
    # FILL9 has no LEF macro -> NOT stubbed (a truly-unknown cell is a real
    # error we must not paper over with an empty module)
    assert "module FILL9" not in text
    # every stub is a blackbox
    assert "(* blackbox *)" in text


def test_synthesize_stubs_none_when_all_defined(tmp_path):
    pdk = _mk_pdk(tmp_path)
    gate = tmp_path / "gate.v"
    gate.write_text("module widget(a,y); input a; output y;\n"
                    "  NAND2D1 _1_ (.A(a), .B(a), .Y(y));\nendmodule\n")
    out = tmp_path / "out"
    assert mod._synthesize_physical_cell_stubs(pdk, "widget", gate,
                                               "no-container", out) is None


# --- supply-port detection + gate-only strip ------------------------------
def test_module_port_names():
    v = "module widget (clk, d, q, VDD, VSS);\n  input clk, d;\nendmodule\n"
    assert mod._module_port_names(v, "widget") == ["clk", "d", "q", "VDD", "VSS"]


def test_is_supply_name():
    for s in ("VDD", "VSS", "vdd", "VPWR", "VGND", "GND", "VCC", "AVDD", "DVSS"):
        assert mod._is_supply_name(s), s
    for ns in ("clk", "data", "y", "addr", "reset_n", "q"):
        assert not mod._is_supply_name(ns), ns


def test_gate_only_supply_ports(tmp_path):
    gate = tmp_path / "gate.v"
    gate.write_text("module widget (clk, d, q, VDD, VSS);\nendmodule\n")
    gold = tmp_path / "gold.v"
    gold.write_text("module widget (clk, d, q);\nendmodule\n")
    # VDD/VSS are on gate, absent from gold, and supply-named -> stripped
    assert mod._gate_only_supply_ports(gate, gold, "widget") == ["VDD", "VSS"]


def test_gate_only_supply_ports_never_strips_functional(tmp_path):
    # a NON-supply port present on gate but absent from gold is a REAL mismatch:
    # it must NOT be returned (must surface as an equivalence defect).
    gate = tmp_path / "gate.v"
    gate.write_text("module widget (clk, d, q, scan_en, VDD, VSS);\nendmodule\n")
    gold = tmp_path / "gold.v"
    gold.write_text("module widget (clk, d, q);\nendmodule\n")
    got = mod._gate_only_supply_ports(gate, gold, "widget")
    assert got == ["VDD", "VSS"]        # supplies stripped
    assert "scan_en" not in got          # functional port NOT stripped
