import json
import gzip
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from flow_pdn_current import attach, estimated_current, sized_widths


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
    attach(tmp_path, native, tmp_path, native["PDN_CFG"])
    assert native["PDN_CFG"] == str(tmp_path / "custom.tcl")


def test_runtime_cli_reads_native_power_and_reports_a_numeric_floor(tmp_path):
    native = config()
    library, tech = tmp_path / "corner.lib", tmp_path / "technology.lef"
    library.write_text("library (corner) { nom_voltage : 5; }")
    tech.write_text(LEF)
    native.update(LIB={"nom_*": [str(library)]}, TECH_LEFS={"nom_*": str(tech)},
                  DEFAULT_CORNER="nom_corner", VDD_NETS=["supply"], GND_NETS=["ground"])
    path = tmp_path / "native.json"
    path.write_text(json.dumps(native))
    result = tmp_path / "steps/pre_layout_timing/result.json"
    result.parent.mkdir(parents=True)
    result.write_text(json.dumps({"native_metrics": {"power__total__corner:nom_corner": .008965}}))
    program = Path(__file__).resolve().parents[1] / "flow_pdn_current.py"
    process = subprocess.run([sys.executable, program, "--project", tmp_path, "--config", path],
                             capture_output=True, text=True, check=True)
    assert "PDN_VWIDTH 2.68" in process.stdout
    report = json.loads((tmp_path / "work/flow/chip/pdn_sizing.json").read_text())
    assert report["estimated_current_a"] == pytest.approx(.001793)

    step = tmp_path / "native step"
    step.mkdir()
    (step / "config.json").write_text(json.dumps(native))
    environment = step / "_env.tcl"
    environment.write_text("set ::env(PDN_VWIDTH) 1.6\nset ::env(PDN_CORE_RING_VWIDTH) 1.6\n")
    base = tmp_path / "work/flow/pdn_cfg.tcl"
    base.write_text('source $::env(_TCL_ENV_IN)\n'
                    'puts [list actual $::env(PDN_VWIDTH) $::env(PDN_CORE_RING_VWIDTH)]\n')
    native["PDN_CFG"] = str(base)
    attach(tmp_path, native, base.parent, str(base))
    driver = step / "probe.tcl"
    driver.write_text('set ::env(STEP_DIR) [lindex $argv 0]\n'
                      'set ::env(_TCL_ENV_IN) [lindex $argv 1]\n'
                      'namespace eval utl {proc metric_float {args} {}}\n'
                      'source [lindex $argv 2]\n')
    tclsh = shutil.which("tclsh")
    if not tclsh:
        pytest.skip("native Tcl interpreter unavailable")
    for _ in range(2):
        process = subprocess.run([tclsh, driver, step, environment, native["PDN_CFG"]],
                                 capture_output=True, text=True, check=True)
        assert "actual 2.68 2.68" in process.stdout
    assert environment.read_text().startswith("set ::env(PDN_VWIDTH) 1.6\n")
