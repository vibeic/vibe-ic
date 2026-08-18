"""PG-rail discovery picked a WELL layer, and the wells were never biased.

`_discover_pg_from_lef` selected the follow-pin rail by TALLEST RECT. That is
wrong for any PDK which also declares WELL-BIAS pins as USE POWER / USE GROUND.

gf180mcu does exactly that. Measured on the shipped
`gf180mcu_fd_sc_mcu7t5v0.lef` (vibeic-eda:0.2.24), cell `inv_1`:

    PIN VDD  USE POWER   LAYER Metal1  RECT 0.000 3.620 2.240 4.220  h=0.60
    PIN VNW  USE POWER   LAYER Nwell   RECT -0.430 1.760 2.670 4.350 h=2.59
    PIN VSS  USE GROUND  LAYER Metal1  RECT 0.000 -0.300 2.240 0.300 h=0.60
    PIN VPW  USE GROUND  LAYER Pwell   RECT -0.430 -0.430 2.670 1.760 h=2.19

The well RECTs are both TALLER than the real rails and span the full cell
width, so they passed the tap-stub guard and won on height. Discovery returned
("VNW", "VPW", "Nwell", 2.59) and the PDN emitted follow-pin stripes on
`Nwell` — a NON-ROUTING layer:

    + ROUTED Nwell ... SHAPE FOLLOWPIN

OpenROAD's detailed router then took SIGNAL 11 (SIGSEGV) in
`drt::io::Parser::updateNetRouting` while reading the design, reproducible in
isolation from post_hold.def.

Fix 1: prefer a PG candidate on a ROUTING-METAL layer, ordering by
(is_metal, height). Degenerates to tallest-RECT when nothing is on metal, so
every PDK that was working keeps its exact previous answer.

Fix 2: having correctly declined to treat VNW/VPW as rails, they still must be
CONNECTED — `_discover_well_bias_pins_from_lef` finds PG pins that live only on
non-routing layers and the PDN ties them to the rails (VNW->VDD, VPW->VSS).
Without that the wells float and the power-aware LVS compare cannot match the
per-instance well nets.

chip-AGNOSTIC: both keyed on the LEF's own USE/LAYER records plus the PDK's own
declared `metal_prefix`. No PDK literal in either code path.
"""
import importlib
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
mod = importlib.import_module("phase3_one_shot_runner")


# Faithful reduction of the real gf180mcu std cell: four PG pins, wells on
# non-routing layers and TALLER than the Metal1 rails.
GF180_LEF = """\
MACRO gf180mcu_fd_sc_mcu7t5v0__inv_1
  CLASS core ;
  SIZE 2.240 BY 3.920 ;
  PIN VDD
    DIRECTION INOUT ;
    USE POWER ;
    PORT
      LAYER Metal1 ;
        RECT 0.000 3.620 2.240 4.220 ;
    END
  END VDD
  PIN VNW
    DIRECTION INOUT ;
    USE POWER ;
    PORT
      LAYER Nwell ;
        RECT -0.430 1.760 2.670 4.350 ;
    END
  END VNW
  PIN VPW
    DIRECTION INOUT ;
    USE GROUND ;
    PORT
      LAYER Pwell ;
        RECT -0.430 -0.430 2.670 1.760 ;
    END
  END VPW
  PIN VSS
    DIRECTION INOUT ;
    USE GROUND ;
    PORT
      LAYER Metal1 ;
        RECT 0.000 -0.300 2.240 0.300 ;
    END
  END VSS
END gf180mcu_fd_sc_mcu7t5v0__inv_1
"""

# A PDK with no well-bias pins at all — the shape sky130/nangate45/asap7 have.
PLAIN_LEF = """\
MACRO plain_inv
  CLASS core ;
  SIZE 2.000 BY 3.000 ;
  PIN VDD
    DIRECTION INOUT ;
    USE POWER ;
    PORT
      LAYER met1 ;
        RECT 0.000 2.700 2.000 3.000 ;
    END
  END VDD
  PIN VSS
    DIRECTION INOUT ;
    USE GROUND ;
    PORT
      LAYER met1 ;
        RECT 0.000 0.000 2.000 0.300 ;
    END
  END VSS
END plain_inv
"""


def _lef(tmp_path, text, name="cells.lef"):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


# ------------------------------------------------ rail discovery ------------

def test_gf180_rail_is_metal_not_the_taller_well(tmp_path):
    """The regression: the taller Nwell pin must NOT win."""
    pg = mod._discover_pg_from_lef(_lef(tmp_path, GF180_LEF), "Metal")
    assert pg is not None
    pwr, gnd, layer, width = pg
    assert (pwr, gnd) == ("VDD", "VSS"), f"picked the well pins: {pg}"
    assert layer == "Metal1", f"follow-pins would land on {layer}"
    assert abs(width - 0.6) < 1e-6


def test_gf180_rail_layer_is_never_a_well_layer(tmp_path):
    """Guards the actual crash condition, independent of pin naming."""
    _pwr, _gnd, layer, _w = mod._discover_pg_from_lef(
        _lef(tmp_path, GF180_LEF), "Metal")
    assert layer.lower() not in ("nwell", "pwell")


def test_layer_name_returned_verbatim_for_case_exact_match(tmp_path):
    """OpenROAD matches the tech-LEF layer name case-exactly."""
    _p, _g, layer, _w = mod._discover_pg_from_lef(
        _lef(tmp_path, GF180_LEF), "metal")   # lowercase prefix still matches
    assert layer == "Metal1"


def test_plain_pdk_unchanged(tmp_path):
    """A PDK with only metal PG pins gets exactly its previous answer."""
    pg = mod._discover_pg_from_lef(_lef(tmp_path, PLAIN_LEF), "met")
    assert pg == ("VDD", "VSS", "met1", 0.3)


def test_default_metal_prefix_is_backward_compatible(tmp_path):
    """Called with ONE argument (the pre-fix signature) it still works."""
    assert mod._discover_pg_from_lef(_lef(tmp_path, PLAIN_LEF)) == (
        "VDD", "VSS", "met1", 0.3)


def test_falls_back_to_tallest_when_nothing_is_on_metal(tmp_path):
    """No routing-metal candidate -> previous tallest-RECT behaviour.

    Ordering by (is_metal, height) degenerates to height when is_metal is
    False for every candidate, so a PDK whose rails our prefix does not
    recognise still resolves instead of returning None.
    """
    pg = mod._discover_pg_from_lef(_lef(tmp_path, GF180_LEF), "ZZZ")
    assert pg is not None
    pwr, gnd, layer, _w = pg
    assert (pwr, gnd, layer) == ("VNW", "VPW", "Nwell")


def test_no_pg_pins_returns_none(tmp_path):
    assert mod._discover_pg_from_lef(
        _lef(tmp_path, "MACRO x\n  CLASS core ;\nEND x\n"), "met") is None


# ------------------------------------------------ well-bias discovery -------

def test_gf180_well_bias_pins_discovered(tmp_path):
    pwr, gnd = mod._discover_well_bias_pins_from_lef(
        _lef(tmp_path, GF180_LEF), "Metal")
    assert pwr == ["VNW"]
    assert gnd == ["VPW"]


def test_plain_pdk_has_no_well_bias_pins(tmp_path):
    """No-op for sky130 / nangate45 / asap7 shaped libraries."""
    assert mod._discover_well_bias_pins_from_lef(
        _lef(tmp_path, PLAIN_LEF), "met") == ([], [])


def test_rail_pin_is_not_mistaken_for_a_well_tie(tmp_path):
    """A pin that also has a routing-metal RECT is a rail, not a body tie.

    The real `filltie` cell declares VDD with BOTH an Nwell RECT and a Metal1
    RECT; re-tying VDD to itself would be wrong.
    """
    lef = """\
MACRO filltie
  CLASS core WELLTAP ;
  SIZE 1.120 BY 3.920 ;
  PIN VDD
    USE POWER ;
    PORT
      LAYER Nwell ;
        RECT -0.430 1.760 1.550 4.350 ;
      LAYER Metal1 ;
        RECT 0.000 3.620 1.120 4.220 ;
    END
  END VDD
END filltie
"""
    pwr, gnd = mod._discover_well_bias_pins_from_lef(_lef(tmp_path, lef),
                                                    "Metal")
    assert pwr == []
    assert gnd == []


# ------------------------------------------------ emitted PDN Tcl -----------

def _stack_tlef(tmp_path, metal_prefix):
    """A minimal 4-layer routing stack under the PDK's own metal prefix, so the
    adaptive PDN can derive upper-metal straps. Generic names/values — this
    stands for any PDK reaching the adaptive path."""
    p = tmp_path / f"{metal_prefix}_stack.tlef"
    p.write_text("".join(
        f"LAYER {metal_prefix}{i}\n  TYPE ROUTING ;\n  DIRECTION {d} ;\n"
        f"  PITCH 0.5 ;\n  WIDTH 0.2 ;\nEND {metal_prefix}{i}\n"
        for i, d in enumerate(
            ["HORIZONTAL", "VERTICAL", "HORIZONTAL", "VERTICAL"], 1)))
    return str(p)


def _pdk(tmp_path, lef_text, metal_prefix, tech_lef=None):
    return mod.PdkConfig(
        name="unit", liberty="/nonexistent/x.lib",
        tech_lef=(tech_lef if tech_lef is not None
                  else _stack_tlef(tmp_path, metal_prefix)),
        cell_lef=_lef(tmp_path, lef_text),
        cell_gds=None, site="SITE", drc_deck=None,
        metal_prefix=metal_prefix, tapcell_master=None)


def test_pdn_tcl_uses_metal_rail_and_ties_the_wells(tmp_path):
    tcl = mod._build_pdn_tcl(_pdk(tmp_path, GF180_LEF, "Metal"))
    # follow-pins on the routing layer, NOT on the well layer
    assert "-layer Metal1" in tcl
    assert "Nwell" not in tcl
    # wells tied to the rails
    assert 'add_global_connection -net VDD -pin_pattern "^VNW$" -power' in tcl
    assert 'add_global_connection -net VSS -pin_pattern "^VPW$" -ground' in tcl
    # the rails themselves are still connected
    assert 'add_global_connection -net VDD -pin_pattern "^VDD$" -power' in tcl


def test_pdn_tcl_for_plain_pdk_emits_no_well_connections(tmp_path):
    """Blast-radius control: a PDK without well pins is byte-unaffected."""
    tcl = mod._build_pdn_tcl(_pdk(tmp_path, PLAIN_LEF, "met"))
    assert "-layer met1" in tcl
    assert tcl.count("add_global_connection") == 2  # VDD + VSS only
    assert "wells(" not in tcl


def test_pdn_tcl_reports_the_well_ties_in_its_marker(tmp_path):
    tcl = mod._build_pdn_tcl(_pdk(tmp_path, GF180_LEF, "Metal"))
    assert "PDN_INSERTED_ADAPTIVE" in tcl
    assert "wells(VNW->VDD,VPW->VSS)" in tcl
