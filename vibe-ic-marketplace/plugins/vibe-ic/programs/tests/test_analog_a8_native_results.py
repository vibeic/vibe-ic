"""Native OP and physical PG data remain usable without identity records."""
from pathlib import Path
import json
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analog_a8_hardmacro_emit as emit
import analog_a8_hardmacro_gen_check as check
import _analog_a_check_common as common


@pytest.fixture
def measured(tmp_path):
    block = tmp_path / "phase3/analog/cell"
    block.mkdir(parents=True)
    extracted = block / "extracted.sp"
    extracted.write_text(".subckt cell vp vn out\nR1 vp out 1meg\nR2 out vn 1meg\n.ends cell\n")
    deck = block / "native.sp"
    deck.write_text("Native passive OP\nVsup vp 0 1.2\nR1 vp out 1meg\nR2 out 0 1meg\n.control\nop\nlet pwr = -v(vp)*i(Vsup)\nprint pwr\n.endc\n.end\n")
    log = block / "native.log"
    binary = shutil.which("ngspice")
    assert binary, "the EDA test environment must provide native ngspice"
    result = subprocess.run([binary, "-b", "-o", str(log), str(deck)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    rec = {"block": "cell", "status": "MEASURED", "metric": "cell_leakage_power",
           "measurement_basis": "delivered_a3_testbench_op",
           "source_netlist": str(extracted.relative_to(tmp_path)),
           "native_log": str(log.relative_to(tmp_path))}
    (block / emit._A8_MEASUREMENT).write_text(json.dumps(rec))
    return tmp_path, block, {"ports": ["vp", "vn", "out"], "devices": [{"role": "res"}]}


def load(measured):
    project, block, topology = measured
    return emit.load_native_measurement(project, "cell", block / "cell.gds", topology)


def test_native_op_supplies_liberty_power_without_passports(measured):
    rec, why = load(measured)
    assert rec is not None, why
    assert rec["value"] == pytest.approx(7.2e-7)
    assert rec["liberty_value"] == pytest.approx(0.72)
    text = emit.interface_liberty("cell", ["vp", "vn"], ["out"], rec)
    assert "cell_leakage_power : 0.72" in text
    assert "timing ()" not in text


def test_native_value_wins_over_old_scalar_and_identity_metadata(measured):
    _, block, _ = measured
    path = block / emit._A8_MEASUREMENT
    rec = json.loads(path.read_text())
    rec.update(value=999, unit="W", schema="old", provenance="old", image_digest="changed",
               native_log_sha256="wrong", source_netlist_sha256="wrong", native_binary={"sha256": "wrong"})
    path.write_text(json.dumps(rec))
    current, why = load(measured)
    assert current is not None, why
    assert current["value"] == pytest.approx(7.2e-7)


@pytest.mark.parametrize("log,expected", [("pwr = -1\n", False), ("pwr = 0\n", True),
    ("pwr = 1e-6\n;;RESIDUAL_FAIL\n", False), ("no native power\n", False)])
def test_native_power_and_operating_point_boundaries(measured, log, expected):
    _, block, _ = measured
    (block / "native.log").write_text(log)
    result, _ = load(measured)
    assert (result is not None) is expected


def test_active_devices_cannot_claim_zero_power(measured):
    _, block, topology = measured
    topology["devices"] = [{"role": "nmos"}]
    (block / "native.log").write_text("pwr = 0\n")
    result, why = load(measured)
    assert result is None and "zero requires passive" in why


def test_missing_native_log_remains_unmeasured(measured):
    _, block, _ = measured
    (block / "native.log").unlink()
    result, why = load(measured)
    assert result is None and "native_log" in why


def test_real_executable_selection_requires_no_hash():
    binary = shutil.which("ngspice")
    selected, why = emit._selected_native_binary("", binary)
    assert selected == {"path": binary, "selection": "explicit"}, why
    missing, _ = emit._selected_native_binary("", "/missing/native-ngspice")
    assert missing is None


def test_native_model_availability_and_sections(tmp_path):
    model = tmp_path / "model.lib"
    model.write_text(".lib tt\n.model basic NMOS LEVEL=1\n.endl tt\n")
    result = emit._bound_models("", [f".lib {model} tt"], tmp_path)
    assert result == [{"path": str(model), "section": "tt"}]
    assert emit._validated_model_bindings(result) == result
    model.write_text(".lib tt\n.model basic NMOS LEVEL=1 VTO=0.8\n.endl tt\n")
    assert emit._bound_models("", [f".lib {model} tt"], tmp_path) == result
    with pytest.raises(ValueError, match="UNRESOLVED"):
        emit._bound_models("", [f".lib {tmp_path / 'missing.lib'} tt"], tmp_path)


def test_native_pg_parser_reads_current_selected_lef_without_identity(tmp_path):
    block = tmp_path / "phase3/analog/cell"
    block.mkdir(parents=True)
    source = tmp_path / "native.lef"
    source.write_text("""MACRO stdcell
SIZE 2.0 BY 3.0 ;
PIN VPWR
 USE POWER ;
 PORT
 LAYER met1 ;
 RECT 0 2.5 2 3 ;
 END
END VPWR
PIN VGND
 USE GROUND ;
 PORT
 LAYER met1 ;
 RECT 0 0 2 0.5 ;
 END
END VGND
END stdcell
""")
    (block / "layout_provenance.json").write_text(json.dumps({"pins_basis": {"core_pg": {
        "result": "MEASURED", "source": str(source), "metal_prefix": "met", "source_sha256": "old"}}}))
    followpin, why = check._normal_core_followpin(tmp_path, "cell", ["met1", "met2"])
    assert followpin == "met1", why
    followpin, why = check._normal_core_followpin(tmp_path, "cell", ["met2"])
    assert followpin is None and "absent from the tech LEF" in why


@pytest.mark.parametrize("content,expected", [("structure_and_geometry", common.CONTENT_DESIGN_BOUND),
                                             ("structure_only", common.CONTENT_STRUCTURE_ONLY)])
def test_native_power_keeps_design_scope_without_four_view_manifest(measured, content, expected):
    _, block, topology = measured
    (block / "topology.json").write_text(json.dumps(topology))
    (block / "netlist_provenance.json").write_text(json.dumps({"_provenance": {"design_content": content}}))
    assert common.hardmacro_content(block).klass == expected


def test_delivered_dc_deck_runs_native_ngspice_with_original_supply(tmp_path):
    block = tmp_path / "phase3/analog/cell"
    block.mkdir(parents=True)
    topology = {"ports": ["vp", "vn", "out"], "rails": {"vdd": "vp", "vss": "vn"}}
    model = block / "passive.lib"
    model.write_text(".lib tt\n* passive devices use native resistor cards\n.endl tt\n")
    netlist = ".subckt cell vp vn out\nR1 vp vn 1meg\nR2 out vn 1meg\n.ends cell\n"
    (block / "cell.sp").write_text(f".lib {model} tt\n" + netlist)
    extracted = block / "extracted.sp"
    extracted.write_text(netlist)
    (block / "tb_cell.sp").write_text("* Native delivered supply\n.include cell.sp\nVMAIN vp vn 2.3\nVZERO vn 0 0\nXDUT vp vn out cell\nRLOAD out vn 7k\n.end\n")
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"instances": [{"block": "cell", "ports": [
        {"name": "vp", "type": "power", "direction": "input"},
        {"name": "vn", "type": "ground", "direction": "inout"},
        {"name": "out", "type": "analog", "direction": "output"}]}]}))
    deck, detail = emit._delivered_measurement_deck(tmp_path, "cell", extracted, topology["ports"], "cell", topology)
    assert "VMAIN vp vn 2.3" in deck and "RLOAD out vn 7k" in deck
    assert not any("sha256" in field for field in detail)
    path, log = block / "op.sp", block / "op.log"
    path.write_text(deck)
    native = subprocess.run([shutil.which("ngspice"), "-b", "-o", str(log), str(path)], cwd=block, capture_output=True, text=True)
    assert native.returncode == 0, log.read_text()
    (block / emit._A8_MEASUREMENT).write_text(json.dumps({"block": "cell", "status": "MEASURED", "metric": "cell_leakage_power",
        "measurement_basis": "delivered_a3_testbench_op", "source_netlist": str(extracted), "native_log": str(log)}))
    measurement, why = emit.load_native_measurement(tmp_path, "cell", block / "cell.gds", topology)
    assert measurement is not None, why
    assert measurement["value"] == pytest.approx(2.3 ** 2 / 1e6)


def test_actual_spec_interface_mismatch_cannot_describe_design_scope(measured):
    _, block, topology = measured
    (block / "topology.json").write_text(json.dumps(topology))
    (block / "netlist_provenance.json").write_text(json.dumps({"_provenance": {"design_content": "structure_and_geometry"}}))
    (block / "spec.json").write_text(json.dumps({"block": "cell", "interface": {"pins": [{"name": "different"}]}}))
    result, why = load(measured)
    assert result is not None, why
    assert common.hardmacro_content(block).klass == common.CONTENT_UNDISCLOSED
