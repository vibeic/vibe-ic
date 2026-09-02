"""Round 15 of the u_hawaii_adc acceptance: the multi-power-domain PDN.

MEASURED on the live tip (v1.15.54): one modulator's core supply is generated
ON CHIP by the LDO macro. The net (`vldo`) is typed POWER before routing —
correctly — and then `pdngen`, told about exactly ONE voltage domain, built
nothing for it:

    FAIL pnr  PG_UNROUTED_SUPPLY: 1 POWER/GROUND net(s) carry real terminals
              and no special-net geometry — pdngen did not build them

Four things closed it, each pinned here:
  1. the supply-net retype runs BEFORE `set_voltage_domain`, not after pdngen;
  2. every POWER net with a terminal that is not the primary becomes a
     `-secondary_power` of the core domain at runtime, with its own strap
     group on every core strap layer, carried to the die boundary;
  3. a hard macro's supply terminals are reached by a PER-PIN STUB (one strap
     of one net across the pin) where the strap-pattern grid refused — every
     dimension from the LEFs, the clearance rule from a measured pdngen drop;
  4. an L21 rail is joined to the PDK's net by VOLTAGE (or by case-insensitive
     name), never emitted verbatim as a phantom net.
And one blind spot: a SPECIAL supply net with terminals and no geometry was
never named by the pre-route cleanup; geometry is the test now, not the flag.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase3_one_shot_runner as mod  # noqa: E402

TECH = """\
MANUFACTURINGGRID 0.005 ;
LAYER M1
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  PITCH 0.42 ;
  WIDTH 0.16 ;
END M1
LAYER M2
  TYPE ROUTING ;
  DIRECTION VERTICAL ;
  PITCH 0.48 ;
  WIDTH 0.20 ;
  SPACINGTABLE
    PARALLELRUNLENGTH 0.00 0.50 1.00
    WIDTH 0.00        0.21    0.21    0.21
    WIDTH 0.39        0.21    0.24    0.24
    WIDTH 10.0        0.21    0.24    0.60 ;
END M2
LAYER M3
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  PITCH 0.42 ;
  WIDTH 0.20 ;
  SPACINGTABLE
    PARALLELRUNLENGTH 0.00 0.50 1.00
    WIDTH 0.00        0.21    0.21    0.21
    WIDTH 0.39        0.21    0.24    0.24
    WIDTH 10.0        0.21    0.24    0.60 ;
END M3
LAYER M4
  TYPE ROUTING ;
  DIRECTION VERTICAL ;
  PITCH 0.48 ;
  WIDTH 0.20 ;
  SPACINGTABLE
    PARALLELRUNLENGTH 0.00 0.50 1.00
    WIDTH 0.00        0.21    0.21    0.21
    WIDTH 0.39        0.21    0.24    0.24
    WIDTH 10.0        0.21    0.24    0.60 ;
END M4
LAYER M5
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  PITCH 0.42 ;
  WIDTH 0.20 ;
  SPACINGTABLE
    PARALLELRUNLENGTH 0.00 0.50 1.00
    WIDTH 0.00        0.21    0.21    0.21
    WIDTH 0.39        0.21    0.24    0.24
    WIDTH 10.0        0.21    0.24    0.60 ;
END M5
LAYER TM1
  TYPE ROUTING ;
  DIRECTION VERTICAL ;
  PITCH 3.28 ;
  WIDTH 1.64 ;
  SPACING 1.64 ;
END TM1
LAYER TM2
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  PITCH 4 ;
  WIDTH 2 ;
  SPACING 2 ;
END TM2
"""

# The measured shape: two 1.2um x 0.7um supply pads on M3, 2.0um apart
# vertically, 0.8um apart horizontally — a strap PATTERN cannot reach them.
MACRO = """\
MACRO ADCBLK
  CLASS BLOCK ;
  ORIGIN 3.800 20.750 ;
  SIZE 271.370 BY 264.010 ;
  PIN vss
    DIRECTION INOUT ;
    USE GROUND ;
    PORT
      LAYER M3 ;
        RECT -2.600 -12.350 -1.400 -11.650 ;
    END
  END vss
  PIN vdd
    DIRECTION INOUT ;
    USE POWER ;
    PORT
      LAYER M3 ;
        RECT -3.400 -10.350 -2.200 -9.650 ;
    END
  END vdd
  PIN vout
    PORT
      LAYER M3 ;
        RECT 57.250 -20.350 58.450 -19.650 ;
    END
  END vout
  OBS
      LAYER M2 ;
        RECT -3.800 -20.750 267.570 242.420 ;
      LAYER M5 ;
        RECT 147.310 140.000 257.910 166.200 ;
  END
END ADCBLK
"""

STRIPES = [{"layer": "TM1", "width": 2.2, "pitch": 75.6, "offset": 13.6},
           {"layer": "TM2", "width": 2.2, "pitch": 75.6, "offset": 13.6}]


# ═══════════════════════════════════════════════════════════════════════════
# 3. the per-pin stub
# ═══════════════════════════════════════════════════════════════════════════
def test_the_pattern_planner_still_refuses_these_pads():
    """The control: the OLD planner's verdict on the measured pads is
    unchanged — the stub is what answers it, not a change to the pattern."""
    out = mod._macro_pdn_grid_outcome([MACRO], TECH, STRIPES, "M1")
    assert out["plan"] is None
    assert out["refusals"][0]["reason"] == "NO_PORT_WIDE_ENOUGH_FOR_ANY_LEGAL_PITCH"


def test_the_stub_planner_reaches_them():
    out = mod._macro_supply_stub_plan([MACRO], TECH, STRIPES)
    assert out["refusals"] == []
    p = out["plan"]["ADCBLK"]
    assert p["pin_layer"] == "M3"
    # horizontal M5 stub, bonding to the vertical TM1 core strap above it
    assert p["stub_layer"] == "M5" and p["stub_dir"] == "HORIZONTAL"
    assert p["partner_layer"] == "TM1"
    assert p["pins"] == ["vdd", "vss"]
    assert p["min_pin_centre_distance"] == 2.0


def test_stub_width_is_bounded_by_the_neighbouring_pin_and_the_spacing():
    """MEASURED: two 1.7um stubs on pins 2.0um apart were generated as ONE —
    pdngen drops a strap inside the earlier strap's spacing bloat, and a gap
    EQUAL to 2 x spacing still intersects. Width is therefore the pin pitch
    less twice the layer spacing less ten manufacturing grids, capped at the
    partner strap's width."""
    p = mod._macro_supply_stub_plan([MACRO], TECH, STRIPES)["plan"]["ADCBLK"]
    assert p["spacing"] == 0.24
    assert p["width"] == pytest.approx(2.0 - 2 * 0.24 - 10 * 0.005)
    assert p["width"] < STRIPES[0]["width"]
    # the vertical candidate (M4) would have had 0.8um between pin centres:
    # 0.8 - 0.48 - 0.05 = 0.27 >= 0.20 — legal but narrower, so M5 wins.
    assert p["pitch"] == pytest.approx(2 * (p["width"] + p["spacing"]))


def test_a_lone_pin_takes_the_partner_strap_width():
    one = MACRO.replace("  PIN vss\n    DIRECTION INOUT ;\n    USE GROUND ;\n"
                        "    PORT\n      LAYER M3 ;\n"
                        "        RECT -2.600 -12.350 -1.400 -11.650 ;\n"
                        "    END\n  END vss\n", "")
    p = mod._macro_supply_stub_plan([one], TECH, STRIPES)["plan"]["ADCBLK"]
    assert p["min_pin_centre_distance"] is None
    assert p["width"] == STRIPES[0]["width"]


def test_a_layer_the_macro_blocks_across_its_footprint_is_never_the_stub():
    blocked = MACRO.replace("      LAYER M5 ;\n        RECT 147.310 140.000 257.910 166.200 ;\n",
                            "      LAYER M5 ;\n        RECT -3.800 -20.750 267.570 243.260 ;\n"
                            "      LAYER M4 ;\n        RECT -3.800 -20.750 267.570 243.260 ;\n")
    out = mod._macro_supply_stub_plan([blocked], TECH, STRIPES)
    assert out["plan"] == {}
    assert out["refusals"][0]["reason"] == "NO_STUB_LAYER"
    assert "ADCBLK" in out["refusals"][0]["masters"]


def test_no_supply_port_means_nothing_to_do_and_nothing_refused():
    sig = MACRO.replace("    USE GROUND ;\n", "").replace("    USE POWER ;\n", "")
    assert mod._macro_supply_stub_plan([sig], TECH, STRIPES) == \
        {"plan": {}, "refusals": []}


def test_each_master_is_planned_against_its_OWN_obstructions():
    """The pattern planner merges every master's OBS into one filter, so one
    blocked macro took the grid away from an unblocked one (pinned in the
    #701 tests as a known limitation). The stub planner reads per master."""
    other = MACRO.replace("ADCBLK", "OTHERBLK").replace(
        "      LAYER M5 ;\n        RECT 147.310 140.000 257.910 166.200 ;\n",
        "      LAYER M5 ;\n        RECT -3.800 -20.750 267.570 243.260 ;\n"
        "      LAYER M4 ;\n        RECT -3.800 -20.750 267.570 243.260 ;\n")
    out = mod._macro_supply_stub_plan([MACRO, other], TECH, STRIPES)
    assert set(out["plan"]) == {"ADCBLK"}
    assert [r["masters"] for r in out["refusals"]] == [["OTHERBLK"]]


def test_the_tcl_reads_pin_offsets_from_the_database_not_the_lef():
    """One plan serves every orientation: the offset of each stub is taken
    from `$iterm getBBox`, which the instance transform has already applied,
    and the grid is grouped by (master, orient, stub set)."""
    plan = mod._macro_supply_stub_plan([MACRO], TECH, STRIPES)["plan"]
    tcl = mod._build_macro_supply_stub_tcl(plan)
    assert "array set _stub_cfg [list {ADCBLK} [list {M5} " in tcl
    assert "$_it getBBox" in tcl and "$_i getOrient" in tcl
    assert "-cells $_m -orient $_o -voltage_domains CORE -grid_over_boundary" in tcl
    assert "-number_of_straps 1 -nets [list $_net] -starts_with $_st" in tcl
    assert "add_pdn_connect -grid $_gname -layers [list $_pl $_sl]" in tcl
    assert "add_pdn_connect -grid $_gname -layers [list $_sl $_ptl]" in tcl
    # the runtime clearance refusal, by name
    assert "reason=STUB_CLEARANCE" in tcl
    assert 'puts "MACRO_SUPPLY_STUBS: $_stub_n stub(s)' in tcl


def test_an_empty_plan_emits_nothing():
    assert mod._build_macro_supply_stub_tcl({}) == ""


def test_a_master_name_no_tcl_key_can_hold_is_refused_by_name():
    plan = {"B{AD}": {"pin_layer": "M3", "stub_layer": "M5", "stub_dir":
                      "HORIZONTAL", "width": 1.0, "spacing": 0.24,
                      "partner_layer": "TM1", "pitch": 2.48}}
    tcl = mod._build_macro_supply_stub_tcl(plan)
    assert "reason=MASTER_NAME_UNQUOTABLE" in tcl
    assert "array set _stub_cfg" not in tcl


def test_the_layer_spacing_reader_takes_the_narrow_regime():
    assert mod._techlef_layer_spacing(TECH, "M5") == 0.24    # not the 0.60 wide row
    assert mod._techlef_layer_spacing(TECH, "TM1") == 1.64
    assert mod._techlef_layer_spacing(TECH, "NOPE") is None
    assert mod._techlef_manufacturing_grid(TECH) == 0.005
    assert mod._techlef_manufacturing_grid("") == 0.005


# ═══════════════════════════════════════════════════════════════════════════
# 1 + 2. the emitted PDN block: order and the secondary domain
# ═══════════════════════════════════════════════════════════════════════════
def _pdk(tmp_path, macro=None):
    d = tmp_path / "pdk"
    d.mkdir(exist_ok=True)
    (d / "tech.lef").write_text(TECH)
    cell = ("MACRO INV\n  CLASS CORE ;\n  SIZE 1 BY 2 ;\n"
            "  PIN VDD\n    USE POWER ;\n    PORT\n      LAYER M1 ;\n"
            "        RECT 0 1.8 1 2.2 ;\n    END\n  END VDD\n"
            "  PIN VSS\n    USE GROUND ;\n    PORT\n      LAYER M1 ;\n"
            "        RECT 0 -0.2 1 0.2 ;\n    END\n  END VSS\nEND INV\n")
    (d / "cells.lef").write_text(cell)
    lefs = []
    if macro:
        (d / "macro.lef").write_text(macro)
        lefs = [str(d / "macro.lef")]
    return mod.PdkConfig(
        name="t", liberty=str(d / "x.lib"), tech_lef=str(d / "tech.lef"),
        cell_lef=str(d / "cells.lef"), cell_gds=None, site="s", drc_deck=None,
        metal_prefix="M", macro_lefs=lefs,
        pdn_straps={"stripes": STRIPES,
                    "connects": [["M1", "TM1"], ["TM1", "TM2"]]})


def test_retype_runs_before_the_domain_is_declared(tmp_path):
    tcl = mod._build_pdn_tcl(_pdk(tmp_path))
    assert tcl.index("PG_NET_RETYPED") < tcl.index("set_voltage_domain")
    assert tcl.index("global_connect\n") < tcl.index("PG_NET_RETYPED")
    assert tcl.index("set_voltage_domain") < tcl.index("  pdngen\n")


def test_the_retype_also_types_the_boundary_pin():
    tcl = mod._pg_net_retype_tcl()
    assert "$_bt setSigType $_st" in tcl


def test_secondary_supplies_are_enumerated_from_the_database(tmp_path):
    tcl = mod._build_pdn_tcl(_pdk(tmp_path))
    assert "set_voltage_domain -name CORE -power VDD -ground VSS {*}$_sec_opt" in tcl
    assert 'if {$_sst eq "POWER" && $_snm ne "VDD"} { lappend _sec_pwr $_snm }' in tcl
    assert "-secondary_power $_sec_pwr" in tcl
    assert "PDN_SECONDARY_GROUND_UNSUPPORTED" in tcl
    # a net with no terminal is not a supply (a phantom is deleted later)
    assert "[llength [$_sn getBTerms]] == 0} { continue }" in tcl


def test_secondary_straps_ride_every_core_strap_layer_to_the_boundary(tmp_path):
    tcl = mod._build_pdn_tcl(_pdk(tmp_path))
    sec = [ln for ln in tcl.splitlines()
           if "add_pdn_stripe" in ln and "$_sec_pwr" in ln]
    assert [re.search(r"-layer (\S+)", ln).group(1) for ln in sec] == ["TM1", "TM2"]
    for ln in sec:
        # ROUND 16 — the group is no longer dropped at a bare half pitch with
        # the strap WIDTH standing in for the spacing rule. It is CENTRED in
        # the window between two primary straps (`offset + width + gap`, both
        # gaps equal and each the largest available) and separated by the
        # LAYER's own minimum spacing, read from the tech LEF. The old shape
        # shipped 7 TM1.b violations on ihp-sg13g2, where TopMetal1 is 2.2 um
        # wide against a `SPACING 1.64` rule; see
        # `test_round16_signoff_frames.py`.
        assert "-offset [expr {13.6 + 2.2 + $_sec_gap}]" in ln
        assert "-spacing 2.2" in ln and "-extend_to_boundary" in ln
        assert "$_sec_gap >= " in tcl
    assert "PDN_SECONDARY_STRAPS_DO_NOT_FIT" in tcl
    # primary straps untouched
    assert "add_pdn_stripe -grid grid -layer TM1 -width 2.2 -pitch 75.6 -offset 13.6\n" in tcl


def test_secondary_straps_come_after_the_primary_and_before_pdngen(tmp_path):
    tcl = mod._build_pdn_tcl(_pdk(tmp_path))
    prim = tcl.index("add_pdn_stripe -grid grid -layer TM2 -width 2.2")
    sec = tcl.index("-nets $_sec_pwr")
    assert prim < sec < tcl.index("  pdngen\n")


def test_the_run_reports_what_it_built_for_each_secondary(tmp_path):
    tcl = mod._build_pdn_tcl(_pdk(tmp_path))
    assert tcl.index("  pdngen\n") < tcl.index("PDN_SECONDARY_SUPPLY:")
    assert "PDN_SECONDARY_NET: $_snm iterms=" in tcl
    assert "macro_terminals=" in tcl
    assert "PDN_SECONDARY_SUPPLY_NONE" in tcl
    assert "MACRO_SUPPLY_PIN_AUDIT: total=" in tcl
    assert "MACRO_SUPPLY_PIN_UNREACHED" in tcl


def test_stubs_are_built_only_where_the_pattern_grid_refused(tmp_path):
    with_macro = mod._build_pdn_tcl(_pdk(tmp_path, MACRO))
    assert "MACRO_SUPPLY_STUBS:" in with_macro
    assert "supply_stubs(ADCBLK:M3->M5@" in with_macro
    assert "MACRO_PDN_GRID_REFUSED" not in with_macro
    assert "macro_grid_REFUSED" not in with_macro
    assert with_macro.index("MACRO_SUPPLY_STUBS") < with_macro.index("  pdngen\n")
    without = mod._build_pdn_tcl(_pdk(tmp_path))
    assert "MACRO_SUPPLY_STUB" not in without
    assert "_stub_cfg" not in without


def test_a_macro_no_stub_can_serve_keeps_its_refusal_and_says_why(tmp_path):
    blocked = MACRO.replace(
        "      LAYER M5 ;\n        RECT 147.310 140.000 257.910 166.200 ;\n",
        "      LAYER M5 ;\n        RECT -3.800 -20.750 267.570 243.260 ;\n"
        "      LAYER M4 ;\n        RECT -3.800 -20.750 267.570 243.260 ;\n"
        "      LAYER TM1 ;\n        RECT -3.800 -20.750 267.570 243.260 ;\n"
        "      LAYER TM2 ;\n        RECT -3.800 -20.750 267.570 243.260 ;\n")
    tcl = mod._build_pdn_tcl(_pdk(tmp_path, blocked))
    assert "MACRO_PDN_GRID_REFUSED: ADCBLK" in tcl
    assert "MACRO_SUPPLY_STUB_REFUSED: master=ADCBLK reason=NO_STUB_LAYER" in tcl
    assert "define_pdn_grid -macro" not in tcl


def test_the_pnr_tcl_is_still_valid_tcl(tmp_path):
    """Balanced braces on the whole block, with and without a macro."""
    for m in (None, MACRO):
        tcl = mod._build_pdn_tcl(_pdk(tmp_path, m))
        assert tcl.count("{") == tcl.count("}"), "unbalanced braces"
        assert tcl.count("[") == tcl.count("]"), "unbalanced brackets"


# ═══════════════════════════════════════════════════════════════════════════
# 4. an L21 rail is joined to the PDK's net by voltage or name, never verbatim
# ═══════════════════════════════════════════════════════════════════════════
L21 = {"fields": {"power_domains": [
    {"name": "CORE", "power_net": "CORE", "voltage_v": 1.2},
    {"name": "IOVDD", "power_net": "IOVDD", "voltage_v": 1.8},
    {"name": "vdd", "power_net": "vdd", "voltage_v": None,
     "derived_by": "l21_macro_supply_rail_synth"},
    {"name": "vss", "power_net": "CORE", "ground_net": "vss",
     "is_power_domain": False, "voltage_v": 0.0},
]}}
DMAP = {("dsm", "vdd"): "CORE", ("reg", "vdd"): "IOVDD",
        ("reg", "vpp"): "vdd", ("dsm", "vss"): "vss"}


def test_the_rail_at_the_library_voltage_is_the_standard_cell_net():
    out, notes = mod._resolve_l21_rail_bindings(L21, DMAP, ["VDD"], ["VSS"], 1.2)
    assert out[("dsm", "vdd")] == "VDD"
    assert any(n.startswith("CORE -> VDD: 1.2 V == liberty nom_voltage") for n in notes)


def test_a_rail_at_another_voltage_stays_a_secondary_net():
    out, notes = mod._resolve_l21_rail_bindings(L21, DMAP, ["VDD"], ["VSS"], 1.2)
    assert out[("reg", "vdd")] == "IOVDD"
    assert any(n.startswith("IOVDD -> IOVDD: kept as its own") for n in notes)


def test_a_rail_named_like_a_pdk_net_joins_it_case_insensitively():
    out, notes = mod._resolve_l21_rail_bindings(L21, DMAP, ["VDD"], ["VSS"], 1.2)
    assert out[("reg", "vpp")] == "VDD"
    assert out[("dsm", "vss")] == "VSS"


def test_two_rails_at_the_library_voltage_resolve_nothing_and_say_so():
    l21 = {"fields": {"power_domains": [
        {"name": "CORE", "voltage_v": 1.2}, {"name": "AVDD", "voltage_v": 1.2}]}}
    out, notes = mod._resolve_l21_rail_bindings(
        l21, {("m", "p"): "CORE"}, ["VDD"], ["VSS"], 1.2)
    assert out[("m", "p")] == "CORE"
    assert any("AMBIGUOUS" in n for n in notes)


def test_no_library_voltage_means_no_voltage_resolution():
    out, _ = mod._resolve_l21_rail_bindings(L21, DMAP, ["VDD"], ["VSS"], None)
    assert out[("dsm", "vdd")] == "CORE"


def test_the_liberty_nominal_voltage_is_read_from_the_pdk(tmp_path):
    lib = tmp_path / "x.lib"
    lib.write_text("library(x) {\n  nom_voltage : 1.2;\n}\n")
    pdk = mod.PdkConfig(name="t", liberty=str(lib), tech_lef="", cell_lef="",
                        cell_gds=None, site="s", drc_deck=None)
    assert mod._pdk_nominal_voltage(pdk) == 1.2


def test_the_binding_emitter_names_a_terminal_the_netlist_kept_elsewhere():
    """`global_connect` never moves a terminal the netlist already connects
    (measured: delta_sigma/vdd stayed on `vldo` under a binding to CORE)."""
    tcl = mod._build_hardmacro_supply_gc_tcl(
        [{"master": "dsm", "pin": "vdd", "use": "POWER", "rail": "VDD"}], [])
    assert "HARDMACRO_SUPPLY_BINDING_VS_NETLIST" in tcl
    assert '[list "dsm" "vdd" "VDD"]' in tcl
    assert tcl.index("global_connect\n") < tcl.index("HARDMACRO_SUPPLY_BINDING_VS_NETLIST")


# ═══════════════════════════════════════════════════════════════════════════
# the blind spot: a SPECIAL supply net with terminals and no geometry
# ═══════════════════════════════════════════════════════════════════════════
def test_cleanup_names_a_special_supply_net_that_carries_no_geometry():
    tcl = mod._pg_net_cleanup_tcl()
    i = tcl.index("elseif")
    seg = tcl[i:]
    assert "getSWires" in seg and "PG_CLEANUP_UNROUTED_SUPPLY" in seg
    assert "if {$_nsb == 0}" in seg
    # the non-special branch is untouched
    assert "![$_net isSpecial]} {" in tcl[:i]
