from pathlib import Path
import json
import os
import shutil
from types import SimpleNamespace
import pytest

from _cvc_pdk import normalize_cdl, power_setup


def primitive(pdk, name, text):
    path = pdk / "libs.ref/devices/spice" / (name + ".spice")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_cvc_primitive_calls_keep_pdk_model_and_explicit_dimensions(tmp_path):
    primitive(tmp_path, "hv", ".subckt hv d g s b\n.param l=1 w=2\nM0 d g s b real_model l={l} w={w}\n.model real_model nmos\n.ends\n")
    text, models = normalize_cdl(".subckt top d g s b\nX0 d g s b hv w=8 l=.5\n.ends\n", tmp_path,
                                 "MN hv Vth=.7 Vgs=5.5 Vds=11\n")
    assert "MX0 d g s b hv w=8 l=.5" in text
    assert models == "MN hv Vth=.7 Vgs=5.5 Vds=11\n"


def test_missing_dimensions_come_from_that_pdks_primitive_defaults(tmp_path):
    primitive(tmp_path, "poly", ".subckt poly p n w=.33 l=1.2\nR0 p n poly w={w} l={l}\n.ends\n")
    text, models = normalize_cdl(".subckt top p n\nR0 p n poly\nX0 p n poly w=.7\n.ends\n", tmp_path,
                                 "R poly R=l/w*48\n")
    assert "R0 p n poly l=1.2 w=.33" in text
    assert "RX0 p n poly w=.7 l=1.2" in text
    assert models == "R poly R=l/w*48\n"


def test_native_spice_alias_preserves_the_complete_pdk_cvc_profile(tmp_path):
    primitive(tmp_path, "sram_device", ".subckt sram_device d g s b\n.param l=.15 w=.36\nX0 d g s b core_model l={l} w={w}\n.ends\n")
    text, models = normalize_cdl(".subckt top d g s b\nX0 d g s b sram_device\n.ends\n", tmp_path,
                                 "MN core_model Vth=.45 Vgs=1.8 Vds=1.8\n")
    assert "MX0 d g s b sram_device l=.15 w=.36" in text
    assert "MN sram_device Vth=.45 Vgs=1.8 Vds=1.8\n" in models


def test_missing_cvc_properties_are_never_replaced_with_a_type_only_model(tmp_path):
    primitive(tmp_path, "unknown", ".subckt unknown d g s b\n.param l=.15 w=.36\nM0 d g s b physical l={l} w={w}\n.model physical.0 nmos\n.ends\n")
    text, models = normalize_cdl(".subckt top d g s b\nX0 d g s b unknown\n.ends\n", tmp_path, "")
    assert "X0 d g s b unknown" in text
    assert models == ""


def test_scaled_wrapper_is_not_treated_as_a_passthrough_alias(tmp_path):
    primitive(tmp_path, "scaled", ".subckt scaled d g s b\n.param l=.15 w=.36\nX0 d g s b core_model l={l*2} w={w}\n.ends\n")
    text, models = normalize_cdl(".subckt top d g s b\nX0 d g s b scaled\n.ends\n", tmp_path,
                                 "MN core_model Vth=.45 Vgs=1.8 Vds=1.8\n")
    assert "X0 d g s b scaled" in text
    assert models == "MN core_model Vth=.45 Vgs=1.8 Vds=1.8\n"


def test_real_hierarchical_cells_are_not_lowered_as_primitive_calls(tmp_path):
    text = ".subckt top d g s b\nX0 d g s b hv w=8 l=.5\n.ends\n.subckt hv d g s b\nM0 d g s b physical l=.5 w=8\n.ends\n"
    result, _ = normalize_cdl(text, tmp_path, "MN hv Vth=.7\nMN physical Vth=.7\n")
    assert "X0 d g s b hv w=8 l=.5" in result


def test_calibre_model_tags_use_the_native_profile_without_changing_properties(tmp_path):
    text = ".subckt top p n\nr0 p n $SUB=bulk $[POLY] $W=8e-7 $L=3.57e-5\nc0 p n $[moscap]\nr1 p n $[unknown]\n.ends\n"
    models = "R poly R=l/w*350\nC moscap Vds=6\n"
    result, actual_models = normalize_cdl(text, tmp_path, models)
    assert "R0 p n poly $W=8e-7 $L=3.57e-5 $SUB=bulk" in result
    assert "C0 p n moscap" in result
    assert "R1 p n $[unknown]" in result
    assert actual_models == models


def test_power_uses_active_liberty_voltages_for_all_declared_rails(tmp_path):
    library = tmp_path / "cells.lib"
    library.write_text('library(cells) {\nnom_voltage : 1.8;\nvoltage_map(VDDIO, 3.3);\nvoltage_map(VSSIO, 0);\n}\n')
    result = power_setup("VPWR power 1.8\nVGND power 0.0\n#define std_input min@VGND max@VPWR\nA input std_input\nVDDIO input std_input\n",
                         {"LIB": {"typ*": [str(library)]}, "DEFAULT_CORNER": "typical",
                          "VDD_NETS": ["VPWR", "VDDIO"], "GND_NETS": ["VGND", "VSSIO"]})
    assert "VPWR power 1.8\n" in result
    assert "VDDIO power 3.3\n" in result
    assert "VSSIO power 0.0\n" in result
    assert "A input std_input" in result
    assert "VDDIO input std_input" not in result


@pytest.mark.parametrize("corner,core,io", [("typ", 1.8, 3.3), ("fast", 1.95, 5.5), ("slow", 1.6, 3.0)])
def test_corner_operating_views_own_supply_voltages_not_uncharacterized_labels(tmp_path, corner, core, io):
    libraries = {}
    for name, voltage, io_voltage in (("typ", 1.8, 3.3), ("fast", 1.95, 5.5), ("slow", 1.6, 3.0)):
        path = tmp_path / (name + ".lib")
        path.write_text(f'library({name}) {{\nnom_voltage : {voltage};\n'
                        f'voltage_map(VCORE, {voltage});\nvoltage_map(VIO, {io_voltage});\nvoltage_map(GND, 0);\n}}\n')
        libraries[name + "*"] = [str(path)]
    labels = tmp_path / "supply_links.lib"
    labels.write_text('library(links) {\nvoltage_map(VCORE, 1.95);\nvoltage_map(VIO, 5.5);\n}\n')
    config = {"DEFAULT_CORNER": corner, "LIB": libraries, "PAD_LIBS": {"*": [str(labels)]},
              "VDD_NETS": ["VCORE", "VIO"], "GND_NETS": ["GND"]}
    result = power_setup("A input std_input\n", config)
    assert f"VCORE power {core}\n" in result
    assert f"VIO power {io}\n" in result
    assert "GND power 0.0\n" in result


def test_conflicting_characterized_views_still_refuse(tmp_path):
    paths = []
    for name, voltage in (("one", 1.8), ("two", 1.95)):
        path = tmp_path / (name + ".lib")
        path.write_text(f'library({name}) {{\nnom_voltage : {voltage};\nvoltage_map(VCORE, {voltage});\n}}\n')
        paths.append(str(path))
    with pytest.raises(ValueError, match="Conflicting active PDK Liberty voltages for VCORE"):
        power_setup("", {"LIB": paths, "VDD_NETS": ["VCORE"], "GND_NETS": ["GND"]})


def test_uncharacterized_label_does_not_invent_an_unresolved_supply(tmp_path):
    core = tmp_path / "core.lib"
    core.write_text('library(core) {\nnom_voltage : 1.8;\nvoltage_map(VCORE, 1.8);\nvoltage_map(GND, 0);\n}\n')
    labels = tmp_path / "supply_links.lib"
    labels.write_text('library(links) {\nvoltage_map(VIO, 5.5);\n}\n')
    with pytest.raises(ValueError, match="No PDK Liberty voltage or CVC power declaration for VIO"):
        power_setup("", {"LIB": [str(core)], "PAD_LIBS": [str(labels)],
                         "VDD_NETS": ["VCORE", "VIO"], "GND_NETS": ["GND"]})


def pad_domain_fixture(tmp_path, *, supply_voltage=3.3):
    liberty = tmp_path / "pad.lib"
    liberty.write_text(f'''library(pads) {{
nom_voltage : 1.8;
voltage_map(CORE, 1.8);
voltage_map(IO, {supply_voltage});
voltage_map(RETURN, 0);
cell (supply_pad) {{
  pg_pin (P) {{
    pg_type : primary_power;
    voltage_name : IO;
  }}
  pg_pin (G) {{
    pg_type : primary_ground;
    voltage_name : RETURN;
  }}
  pg_pin (SLEEP) {{
    pg_type : internal_power;
    voltage_name : IO;
  }}
  pin (BOND) {{
    is_pad : true;
    direction : inout;
    related_power_pin : P;
    related_ground_pin : G;
  }}
}}
}}''')
    lef = tmp_path / "pad.lef"
    lef.write_text('''MACRO supply_pad
 CLASS PAD POWER ;
 PIN BOND
  DIRECTION INOUT ;
  USE POWER ;
 END BOND
 PIN P
  DIRECTION INOUT ;
  USE POWER ;
 END P
 PIN G
  DIRECTION INOUT ;
  USE GROUND ;
 END G
END supply_pad
''')
    # The native model's own resistor proves which supply the bond feeds.
    cdl = (".subckt package bond A CORE RETURN\nXpad ring_g bond sleeping ring_p supply_pad\n.ends\n"
           ".subckt supply_pad G BOND SLEEP P\nXbase BOND G P base\n.ends\n"
           ".subckt base PAD RETURN SUPPLY\nRfeed PAD SUPPLY .1\n.ends\n")
    config = {"DESIGN_NAME": "package", "PAD_LEFS": [str(lef)], "LIB": [str(liberty)],
              "VDD_NETS": ["CORE"], "GND_NETS": ["RETURN"]}
    return config, cdl


def test_primary_pad_domains_and_external_bond_use_the_native_operating_view(tmp_path):
    config, cdl = pad_domain_fixture(tmp_path)
    result = power_setup("CORE power 1.8\nRETURN power 0\nA input std_input\n", config, cdl)
    assert "bond power 3.3\n" in result
    assert "/ring_p power 3.3\n" in result
    assert "/ring_g power 0.0\n" in result
    assert "sleeping power" not in result
    assert "A input std_input" in result
    assert "A power" not in result


def test_an_internal_signal_connected_to_a_supply_bond_is_not_an_external_source(tmp_path):
    config, cdl = pad_domain_fixture(tmp_path)
    cdl = cdl.replace(".subckt package bond A CORE RETURN", ".subckt package A CORE RETURN")
    result = power_setup("CORE power 1.8\nRETURN power 0\n", config, cdl)
    assert "bond power" not in result
    assert "ring_p power 3.3" in result  # Native primary supply, not an inferred signal.


def test_unknown_bond_to_rail_connection_is_not_guessed_from_related_power_pin(tmp_path):
    config, cdl = pad_domain_fixture(tmp_path)
    cdl = cdl.replace("Rfeed PAD SUPPLY .1", "Dclamp PAD SUPPLY diode")
    with pytest.raises(ValueError, match="No unique PDK Liberty voltage for supply bond"):
        power_setup("CORE power 1.8\nRETURN power 0\n", config, cdl)


def test_a_physical_net_binding_incompatible_pad_domains_is_not_overwritten(tmp_path):
    config, cdl = pad_domain_fixture(tmp_path)
    cdl = cdl.replace("ring_g bond sleeping ring_p", "shorted bond sleeping shorted")
    with pytest.raises(ValueError, match="Conflicting active PDK Liberty voltages for /shorted"):
        power_setup("CORE power 1.8\nRETURN power 0\n", config, cdl)


def test_pad_primary_supply_cannot_override_the_configured_core_voltage(tmp_path):
    config, cdl = pad_domain_fixture(tmp_path)
    cdl = cdl.replace("sleeping ring_p", "sleeping CORE")
    with pytest.raises(ValueError, match="Conflicting active PDK Liberty voltages for CORE"):
        power_setup("CORE power 1.8\nRETURN power 0\n", config, cdl)


def test_ip_power_recipe_is_unchanged_without_pad_views(tmp_path):
    config, _ = pad_domain_fixture(tmp_path)
    del config["PAD_LEFS"]
    power = "CORE power 1.8\nRETURN power 0\n#define std_input min@RETURN max@CORE\nA input std_input\n"
    result = power_setup(power, config, ".subckt package A CORE RETURN\n.ends\n")
    assert result == "RETURN power 0.0\nCORE power 1.8\n#define std_input min@RETURN max@CORE\nA input std_input\n"


def test_a_configured_supply_bond_does_not_need_a_second_pg_description(tmp_path):
    config, cdl = pad_domain_fixture(tmp_path)
    Path(config["LIB"][0]).write_text('''library(pads) {
nom_voltage : 1.8;
cell (supply_pad) {
  pin (BOND) {
    is_pad : true;
    direction : inout;
  }
}
}''')
    cdl = cdl.replace(".subckt package bond A CORE RETURN", ".subckt package A CORE RETURN")
    cdl = cdl.replace("ring_g bond sleeping ring_p", "ring_g CORE sleeping ring_p")
    result = power_setup("CORE power 1.8\nRETURN power 0\n", config, cdl)
    assert result == "RETURN power 0\nCORE power 1.8\n"


@pytest.mark.parametrize("direction", ["input", "output", None])
def test_inout_pad_input_levels_need_the_selected_logical_input_direction(tmp_path, direction):
    config, cdl = pad_domain_fixture(tmp_path)
    liberty = Path(config["LIB"][0])
    text = liberty.read_text().replace("cell (supply_pad)", "cell (signal_pad)")
    liberty.write_text(liberty.read_text() + "\n" + text)
    lef = Path(config["PAD_LEFS"][0])
    lef.write_text(lef.read_text() + "\n" + lef.read_text().replace("supply_pad", "signal_pad")
                   .replace("CLASS PAD POWER", "CLASS PAD INPUT").replace("USE POWER", "USE SIGNAL"))
    cdl = cdl.replace(".subckt package bond A CORE RETURN",
                      ".subckt package bond A CORE RETURN\nXinput ring_g A sleeping ring_p signal_pad")
    cdl += ".subckt signal_pad G BOND SLEEP P\n.ends\n"
    config["DESIGN_DIR"] = str(tmp_path)
    prepared = tmp_path / "work/flow/chip/preparation.json"
    prepared.parent.mkdir(parents=True)
    prepared.write_text(json.dumps({"pads": {"input": {
        "port": "A", "master": "signal_pad", "terminal": "BOND", "direction": direction}}}))
    result = power_setup("CORE power 1.8\nRETURN power 0\n", config, cdl)
    assert ("A input min@0.0 max@3.3\n" in result) == (direction == "input")
    explicit = power_setup("CORE power 1.8\nRETURN power 0\nA input min@0 max@1.2\n", config, cdl)
    assert "A input min@0 max@1.2\n" in explicit
    assert "A input min@0.0 max@3.3\n" not in explicit


@pytest.mark.parametrize("conducting", [False, True])
def test_native_cvc_binds_internal_primary_domains_and_keeps_a_real_short(tmp_path, conducting):
    pytest.importorskip("librelane")
    from librelane.state import DesignFormat
    from flow_ic_checks import ElectricalRules

    pdk_root = Path(os.environ.get("PDK_ROOT", "/nonexistent"))
    pdk = pdk_root / "sky130A"
    if not pdk.is_dir() or not shutil.which("cvc_rv"):
        pytest.skip("native PDK and CVC required")
    config, cdl = pad_domain_fixture(tmp_path)
    gate = "ring/rail" if conducting else "RETURN"
    cdl = cdl.replace("ring_p", "ring/rail")
    cdl = cdl.replace("Rfeed PAD SUPPLY .1", "Rfeed PAD SUPPLY sky130_fd_pr__res_generic_m5 w=10 l=.1")
    cdl = cdl.replace("Xpad ring_g", "Xpad RETURN")
    cdl = cdl.replace(".subckt package bond A CORE RETURN",
                      ".subckt package bond A CORE RETURN\n"
                      f"Mshort ring/rail {gate} RETURN RETURN sky130_fd_pr__nfet_g5v0d10v5 w=1 l=.5")
    source = tmp_path / "source.spice"
    source.write_text(cdl)
    netlist = tmp_path / "source.v"
    netlist.write_text("module package(bond, A, CORE, RETURN);\ninput CORE;\ninput RETURN;\ninout bond;\ninput A;\nendmodule\n")
    config.update(PDK_ROOT=str(pdk_root), PDK="sky130A", STD_CELL_LIBRARY="sky130_fd_sc_hd")
    step = SimpleNamespace(step_dir=str(tmp_path), config=config)
    _, metrics = ElectricalRules.run(step, {DesignFormat.SPICE: str(source), DesignFormat.NETLIST: str(netlist)})
    report = json.loads((tmp_path / "cvc.json").read_text())
    assert report["completed"] and report["counts"]["Model errors"] == 0, report
    assert (metrics["cvc_electrical_errors"] > 0) == conducting, report
    assert "/ring/rail power 3.3" in (tmp_path / "top.power").read_text()
    assert "could not expand signal" not in (tmp_path / "report.rpt").read_text()


@pytest.mark.parametrize("conducting", [False, True])
@pytest.mark.parametrize("missing_cell", [False, True])
def test_native_pdk_io_cell_and_default_resistor_complete_cvc_without_losing_a_leak(
        tmp_path, conducting, missing_cell):
    pytest.importorskip("librelane")
    from librelane.state import DesignFormat
    from _pad_ring import parse_spice_subckts
    from flow_ic_checks import ElectricalRules

    pdk_root = Path(os.environ.get("PDK_ROOT", "/nonexistent"))
    pdk = pdk_root / "sky130A"
    io = pdk / "libs.ref/sky130_fd_io/spice/sky130_fd_io.spice"
    if not io.is_file() or not shutil.which("cvc_rv"):
        pytest.skip("native SKY130 PDK and CVC are required")
    cell = "sky130_fd_io__amx_inv1"
    ports, body = parse_spice_subckts(io.read_text(), preserve_parameters=True)[cell]
    pad_cdl = pdk / "libs.ref/sky130_fd_io/cdl/sky130_ef_io.cdl"
    filler = "sky130_ef_io__com_bus_slice_5um"
    filler_ports, filler_body = parse_spice_subckts(pad_cdl.read_text())[filler]
    assert filler_body == []  # The native PDK describes a passive bus slice.
    gate = "VPWR" if conducting else "VGND"
    source = tmp_path / "source.spice"
    source.write_text(".subckt neutral VPWR VGND A Z\n"
                      f"Xi A Z VPWR VGND {cell}\n"
                      "Rdefault VPWR passive sky130_fd_pr__res_generic_po\n"
                      f"Xsram passive {gate} VGND VGND sky130_fd_pr__special_nfet_01v8 w=.36 l=.15\n"
                      + "Xfill " + " ".join("VGND" for _ in filler_ports) + f" {filler}\n"
                      + "Xduplicate " + " ".join("VGND" for _ in filler_ports) + f" {filler}\n"
                      + ("Xmissing VPWR VGND neutral_absent_cell\n" if missing_cell else "")
                      + ".ends\n.subckt " + cell + " " + " ".join(ports) + "\n" +
                      "\n".join(" ".join(row) for row in body) + "\n.ends\n")
    netlist = tmp_path / "source.v"
    netlist.write_text("module neutral (VPWR, VGND, A, Z);\ninput VPWR;\ninput VGND;\ninput A;\noutput Z;\nendmodule\n")
    step = SimpleNamespace(step_dir=str(tmp_path), config={"PDK_ROOT": str(pdk_root), "PDK": "sky130A",
        "STD_CELL_LIBRARY": "sky130_fd_sc_hd", "VDD_NETS": ["VPWR"], "GND_NETS": ["VGND"], "DESIGN_NAME": "neutral"})
    libraries = list((pdk / "libs.ref/sky130_fd_sc_hd/lib").glob("*tt_025C_1v80.lib*"))
    assert len(libraries) == 1
    step.config.update(LIB={"*": list(map(str, libraries))}, DEFAULT_CORNER="tt")
    io_libs = pdk / "libs.ref/sky130_fd_io/lib"
    step.config["PAD_LIBS"] = {"*": [str(next(io_libs.glob("sky130_ef_io__vccd_lvc_clamped_pad_tt_025C_1v80*.lib"))),
                                   str(io_libs / "slices_stubs.lib")]}
    step.config["PAD_CDLS"] = [str(pad_cdl)]
    _, metrics = ElectricalRules.run(step, {DesignFormat.SPICE: str(source), DesignFormat.NETLIST: str(netlist)})
    result = json.loads((tmp_path / "cvc.json").read_text())
    if missing_cell:
        assert not result["completed"] and result["result"] == "INCOMPLETE"
        assert "cvc_electrical_errors" not in metrics
        assert "neutral_absent_cell" in (tmp_path / "command_3.log").read_text()
        return
    assert result["completed"] and result["devices"] == 4
    assert result["counts"]["Model errors"] == 0
    assembled = (tmp_path / "design.cdl").read_text().casefold()
    assert assembled.count(".subckt " + filler) == 1
    assert (tmp_path / "models").read_text().startswith((pdk / "libs.tech/librelane/cvc/models").read_text())
    if conducting:
        assert result["result"] == "FAIL" and result["counts"]["Leaks"] == 1
        assert metrics["cvc_electrical_errors"] >= 1
    else:
        assert result["result"] == "PASS" and metrics["cvc_electrical_errors"] == 0


@pytest.mark.parametrize("distinct_unused", [False, True])
def test_native_cvc_resolves_transitive_companion_spice_from_selected_cdl(tmp_path, distinct_unused):
    pytest.importorskip("librelane")
    from librelane.state import DesignFormat
    from flow_ic_checks import ElectricalRules

    pdk_root = Path(os.environ.get("PDK_ROOT", "/nonexistent"))
    if not (pdk_root / "sky130A").is_dir() or not shutil.which("cvc_rv"):
        pytest.skip("native PDK and CVC required")
    cdl = tmp_path / "library/cdl/interface.cdl"
    cdl.parent.mkdir(parents=True)
    cdl.write_text(".subckt interface N P\nxinner P N physical_link\n.ends\n")
    spice = tmp_path / "library/spice/implementation.spice"
    spice.parent.mkdir()
    spice.write_text(".subckt physical_link P N\nR0 P P sky130_fd_pr__res_generic_po l=1 w=1\n.ends\n")
    source = tmp_path / "source.spice"
    unused = "unmodeled" if distinct_unused else "VPWR"
    source.write_text("* Black-box entry subcircuit for interface abstract view\n"
                      ".subckt interface P PAD_ONLY N\n.ends\n"
                      ".subckt neutral VPWR VGND\n"
                      f"X0 VPWR {unused} VGND interface\nX1 VPWR {unused} VGND interface\n.ends\n"
                      )
    netlist = tmp_path / "source.v"
    netlist.write_text("module neutral(input VPWR, input VGND); endmodule\n")
    step = SimpleNamespace(step_dir=str(tmp_path), config={"PDK_ROOT": str(pdk_root), "PDK": "sky130A",
        "STD_CELL_LIBRARY": "sky130_fd_sc_hd", "VDD_NETS": ["VPWR"], "GND_NETS": ["VGND"],
        "DESIGN_NAME": "neutral", "EXTRA_CDLS": [str(cdl)]})
    _, metrics = ElectricalRules.run(step, {DesignFormat.SPICE: str(source), DesignFormat.NETLIST: str(netlist)})
    result = json.loads((tmp_path / "cvc.json").read_text())
    if distinct_unused:
        assert not result["completed"] and "cvc_electrical_errors" not in metrics
        assert "port count mismatch" in (tmp_path / "command_3.log").read_text()
        return
    assert result["completed"] and result["devices"] == 2
    assert result["counts"]["Model errors"] == 0
    assert metrics["cvc_electrical_errors"] == result["counts"]["Total"]
    assembled = (tmp_path / "design.cdl").read_text().casefold()
    assert assembled.count(".subckt interface ") == 1
    assert assembled.count(".subckt physical_link ") == 1
    assert "x0 vgnd vpwr interface" in assembled


@pytest.mark.parametrize("pad_voltage", [1.8, 3.3])
def test_internal_core_supplies_share_the_native_cvc_domain_declaration(tmp_path, pad_voltage):
    config, cdl = pad_domain_fixture(tmp_path, supply_voltage=pad_voltage)
    cdl = cdl.replace(".subckt package bond A CORE RETURN", ".subckt package bond A")
    cdl = cdl.replace("Xpad ring_g bond sleeping ring_p", "Xpad RETURN bond sleeping CORE")
    if pad_voltage != 1.8:
        with pytest.raises(ValueError, match="Conflicting active PDK Liberty voltages for /CORE"):
            power_setup("CORE power 1.8\nRETURN power 0\n", config, cdl)
    else:
        result = power_setup("CORE power 1.8\nRETURN power 0\n", config, cdl)
        assert result.splitlines().count("/CORE power 1.8") == 1
        assert result.splitlines().count("/RETURN power 0.0") == 1
        assert not any(line.startswith(("CORE power ", "RETURN power ")) for line in result.splitlines())
