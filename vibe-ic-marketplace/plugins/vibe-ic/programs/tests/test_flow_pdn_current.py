import json
import gzip
from pathlib import Path

import pytest

from flow_pdn_current import coherent_geometry, current_settings, estimated_current, needs_estimate, sized_widths


LEF = """MANUFACTURINGGRID 0.005 ;
LAYER upper_vertical
 TYPE ROUTING ;
 WIDTH 0.28 ;
 THICKNESS 0.54 ;
 DCCURRENTDENSITY AVERAGE 0.67 ;
END upper_vertical
LAYER upper_horizontal
 TYPE ROUTING ;
 WIDTH 0.44 ;
 THICKNESS 0.9 ;
 DCCURRENTDENSITY AVERAGE 1.5 ;
END upper_horizontal
"""


def config():
    return {"PDN_VERTICAL_LAYER": "upper_vertical", "PDN_HORIZONTAL_LAYER": "upper_horizontal",
            "PDN_VWIDTH": 1.6, "PDN_HWIDTH": 1.6,
            "PDN_CORE_RING_VWIDTH": 1.6, "PDN_CORE_RING_HWIDTH": 1.6}


@pytest.mark.parametrize("current, expected", [(0.001793, 2.68), (0.001440, 2.15), (0.001167815, 1.75)])
def test_current_floor_uses_native_per_width_units_and_legal_centered_grid(current, expected):
    widths = sized_widths(config(), current, LEF)
    assert widths["PDN_VWIDTH"] == expected
    assert widths["PDN_CORE_RING_VWIDTH"] == expected
    assert widths["PDN_CORE_RING_HWIDTH"] >= widths["PDN_HWIDTH"]


def test_wider_strap_setting_also_widens_ring_without_an_estimate():
    native = config()
    native["PDN_VWIDTH"] = 3.2
    assert sized_widths(native, None, LEF)["PDN_CORE_RING_VWIDTH"] == 3.2


def test_missing_native_grid_does_not_invent_a_width():
    assert sized_widths(config(), 0.01, LEF.replace("MANUFACTURINGGRID 0.005 ;", "")) == {}


@pytest.mark.parametrize("compressed", [False, True])
def test_current_is_maximum_matched_corner_power_over_voltage(tmp_path, compressed):
    libs = {}
    for name, voltage in (("slow", 4.5), ("fast", 5.5)):
        path = tmp_path / (name + (".lib.gz" if compressed else ".lib"))
        with (gzip.open if compressed else open)(path, "wt") as stream:
            stream.write(f"library ({name}) {{ nom_voltage : {voltage}; }}")
        libs[name + "*"] = [str(path)]
    native = {"LIB": libs, "VDD_NETS": ["supply"], "GND_NETS": ["ground"]}
    current, samples = estimated_current(native, {"power__total__corner:slow": .009,
                                                  "power__total__corner:fast": .0099})
    assert current == pytest.approx(.002)
    assert len(samples) == 2
    native["LIB"]["slow*"] += native["LIB"]["fast*"]
    assert estimated_current(native, {"power__total__corner:slow": .009})[0] is None


def test_custom_pdn_script_keeps_its_control(tmp_path):
    native = {"PDN_CFG": str(tmp_path / "custom.tcl")}
    assert current_settings(tmp_path, native) == {}


@pytest.mark.parametrize("current, vertical, horizontal, voffset, hoffset", [
    (.001793, 2.68, 1.6, 7.34, 7.),
    (.006871, 10.26, 4.59, 11.13, 8.495),
])
@pytest.mark.parametrize("default_supplies", [False, True])
def test_native_geometry_is_resolved_before_floorplan(tmp_path, current, vertical, horizontal, voffset, hoffset, default_supplies):
    pytest.importorskip("odb")
    native = config()
    library, tech = tmp_path / "corner.lib", tmp_path / "technology.lef"
    library.write_text("library (corner) { nom_voltage : 5; }")
    text = "VERSION 5.8 ;\nUNITS\n DATABASE MICRONS 2000 ;\nEND UNITS\n" + LEF
    text = text.replace(" TYPE ROUTING ;", " TYPE ROUTING ;\n DIRECTION VERTICAL ;\n PITCH 1 ;\n SPACING 0.28 ;")
    text = text.replace(" WIDTH 0.28 ;", " WIDTH 0.28 ;\n SPACING 0.30 RANGE 10.005 999 ;")
    tech.write_text(text + "\nEND LIBRARY\n")
    native.update(PDK="technology", LIB={"nom_*": [str(library)]}, TECH_LEFS={"nom_*": str(tech)},
                  DEFAULT_CORNER="nom_corner", VDD_NETS=["supply"], GND_NETS=["ground"],
                  PDN_CFG=str(tmp_path / "work/flow/pdn_cfg.tcl"), PDN_CORE_RING=True,
                  PDN_VPITCH=4, PDN_HPITCH=4, PDN_VSPACING=1.7, PDN_HSPACING=1.7,
                  PDN_VOFFSET=6.8, PDN_HOFFSET=7, PDN_CORE_RING_VSPACING=1.7, PDN_CORE_RING_HSPACING=1.7)
    power = tmp_path / "steps/pre_layout_timing/result.json"
    power.parent.mkdir(parents=True)
    power.write_text(json.dumps({"native_metrics": {"power__total__corner:nom_corner": current * 5}}))
    if default_supplies:
        native.update(VDD_NETS=None, GND_NETS=None, VDD_PIN="supply", GND_PIN="ground", PDN_CFG=None)
    values = current_settings(tmp_path, native)
    assert values["PDN_VWIDTH"] == vertical
    assert values["PDN_CORE_RING_VWIDTH"] == vertical
    assert values["PDN_HWIDTH"] == horizontal
    assert values["PDN_VOFFSET"] == voffset
    assert values["PDN_HOFFSET"] == hoffset
    assert values["PDN_VPITCH"] >= 2 * (vertical + values["PDN_VSPACING"]) - 1e-12
    assert values["PDN_HPITCH"] >= 2 * (horizontal + values["PDN_HSPACING"]) - 1e-12
    assert not (tmp_path / "work/flow/chip/pdn_current.tcl").exists()


def test_estimate_window_covers_physical_deliveries_before_geometry():
    from flow_engine import TABLE
    table = json.loads(TABLE.read_text())
    route = {"delivery_target": "shippable_gds", "entry_step": "requirements_and_delivery_route",
             "verify_through": "compliance_and_final_adoption"}
    assert needs_estimate(route, None, table)
    assert needs_estimate(route, "synthesis", table)
    assert not needs_estimate(route, "die_floorplan_and_macros", table)
    assert needs_estimate({**route, "delivery_target": "ip_hardmacro"}, None, table)
    assert not needs_estimate({**route, "verify_through": "pre_layout_timing"}, None, table)


def test_native_parallel_run_length_rules_and_explicit_geometry(tmp_path):
    odb = pytest.importorskip("odb")
    text = "VERSION 5.8 ;\nUNITS\n DATABASE MICRONS 2000 ;\nEND UNITS\nMANUFACTURINGGRID 0.005 ;\n"
    for layer, direction in (("vertical", "VERTICAL"), ("horizontal", "HORIZONTAL")):
        text += f"""LAYER {layer}
 TYPE ROUTING ;
 DIRECTION {direction} ;
 PITCH 1 ;
 WIDTH 0.28 ;
 SPACINGTABLE PARALLELRUNLENGTH 0 10 100
 WIDTH 0 0.28 0.5 2.0
 WIDTH 10 0.3 1.0 3.0 ;
END {layer}
"""
    path = tmp_path / "rules.lef"
    path.write_text(text + "END LIBRARY\n")
    database = odb.dbDatabase.create()
    try:
        odb.read_lef(database, str(path))
        native = config()
        native.update(PDN_VERTICAL_LAYER="vertical", PDN_HORIZONTAL_LAYER="horizontal",
            VDD_NETS=["power"], GND_NETS=["ground"], PDN_CORE_RING=True,
            PDN_VSPACING=1.7, PDN_HSPACING=1.7, PDN_VPITCH=153.6, PDN_HPITCH=153.6,
            PDN_VOFFSET=7, PDN_HOFFSET=7, PDN_CORE_RING_VSPACING=1.7, PDN_CORE_RING_HSPACING=1.7)
        widths = {key: 10.26 for key in ("PDN_VWIDTH", "PDN_HWIDTH", "PDN_CORE_RING_VWIDTH", "PDN_CORE_RING_HWIDTH")}
        values = coherent_geometry(native, widths, database.getTech(), 200)
        assert values["PDN_VSPACING"] == 3
        assert values["PDN_CORE_RING_VSPACING"] == 3
        with pytest.raises(ValueError, match="Declared PDN_VSPACING"):
            coherent_geometry(native, widths, database.getTech(), 200, {"PDN_VSPACING"})
        native["PDN_VSPACING"] = 3.0015
        with pytest.raises(ValueError, match="manufacturing grid"):
            coherent_geometry(native, widths, database.getTech(), 200, {"PDN_VSPACING"})
        native["PDN_VSPACING"] = 3
        values = coherent_geometry(native, widths, database.getTech(), 200, {"PDN_VSPACING", "PDN_VOFFSET"})
        assert values["PDN_VOFFSET"] == 7
    finally:
        odb.dbDatabase.destroy(database)
