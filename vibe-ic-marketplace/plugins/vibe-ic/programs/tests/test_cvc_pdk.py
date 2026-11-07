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
    cdl.write_text(".subckt interface N P\nXinner P N physical_link\n.ends\n")
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
