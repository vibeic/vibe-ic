"""Scan applicability follows the declared core, never missing RTL files."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import io_pad_chip_top_gen as PAD
from _hostpaths import require_repo
from test_io_pad_chip_top_gen import GEN, SPEC, _pdk, _project, _record, _run


def _declare(project, features):
    (project / "input/flow109-manifest.json").write_text(json.dumps({"features": features}))


def _project_without_handoff(tmp_path):
    project = _project(tmp_path)
    switch = project / "phase3/librelane_switch.json"
    switch.parent.mkdir(parents=True)
    switch.write_text(json.dumps({"steps": {"9": "librelane"}}))
    return project


@pytest.mark.parametrize("model_present", [False, True])
def test_declared_analog_core_does_not_require_a_synthesis_handoff(tmp_path, model_present):
    project = _project_without_handoff(tmp_path)
    _declare(project, {"has_analog": True, "has_digital": False})
    if model_present:
        rtl = project / "phase2/stage1/rtl"
        rtl.mkdir(parents=True)
        (rtl / "model.v").write_text("module model; endmodule\n")
    result = PAD._check_scan_interface(project, SPEC["top_ports"])
    assert result["selected_scan_netlist"] is False
    assert "features.has_analog=true, features.has_digital=false" in result["selection"]


@pytest.mark.parametrize("features", [
    {"has_analog": False, "has_digital": True},
    {"has_analog": True, "has_digital": True},
    {"has_analog": True},
    {"has_digital": False},
    {"has_analog": True, "has_digital": "false"},
    None,
], ids=["digital", "mixed", "digital-unknown", "analog-unknown", "untyped", "undeclared"])
def test_non_analog_declarations_still_refuse_missing_handoff(tmp_path, features):
    project = _project_without_handoff(tmp_path)
    if features is not None:
        _declare(project, features)
    with pytest.raises(ValueError, match="LL_SYNTH_HANDOFF_INVALID"):
        PAD._check_scan_interface(project, SPEC["top_ports"])


def test_declared_analog_core_proceeds_through_the_real_pad_producer(tmp_path):
    project = _project_without_handoff(tmp_path)
    _declare(project, {"has_analog": True, "has_digital": False})
    process = _run(GEN, project, _pdk(tmp_path / "pdk"))
    assert process.returncode == 0, process.stdout + process.stderr
    record = _record(project)
    assert record["verdict"] == "WROTE"
    assert record["scan_interface"]["selected_scan_netlist"] is False
    assert (project / record["chip_top_verilog"]).is_file()


def test_digital_core_without_handoff_stops_the_real_pad_producer(tmp_path):
    project = _project_without_handoff(tmp_path)
    _declare(project, {"has_analog": False, "has_digital": True})
    process = _run(GEN, project, _pdk(tmp_path / "pdk"))
    assert process.returncode != 0
    assert "LL_SYNTH_HANDOFF_INVALID" in process.stdout + process.stderr
    assert not (project / "phase3/stage3/pnr/chip_top_io.v").exists()


def test_published_analog_profile_keeps_its_declared_scan_applicability(tmp_path):
    registry = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "flow", "flow109.json")
    profile = next(row for row in json.loads(registry.read_text())["reference_profiles"]
                   if row["name"] == "Analog IC external trim")
    project = _project_without_handoff(tmp_path)
    _declare(project, profile["features"])
    result = PAD._check_scan_interface(project, SPEC["top_ports"])
    assert result["selected_scan_netlist"] is False
