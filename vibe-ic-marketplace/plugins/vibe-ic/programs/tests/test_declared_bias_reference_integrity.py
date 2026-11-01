"""Bias claims must remain bound to physical reference cards and rail currents."""
from copy import deepcopy
import json

import analog_a3_netlist_emit as a3
from test_declared_load_bias_branches import _emit, PDK
import test_analog_folded_first_stage_input as folded


def test_bias_reference_length_expression_cannot_override_its_declaration(tmp_path):
    ir, _, _, _, _ = _emit(tmp_path)
    changed = deepcopy(ir)
    row = next(r for r in changed["device_param_exprs"]
               if r["device"] == "r_ib" and r["param"] == "l")
    row["expr"] = "1.0"
    assert any("OTA_BIAS" in issue for issue in a3._validate_ir(changed, PDK))


def test_folded_supply_budget_counts_all_top_and_bias_rail_branches(tmp_path):
    project = tmp_path / "folded"
    sizing = folded.inputs(project)
    directory = project / "phase3/analog/converter"
    directory.mkdir(parents=True)
    declaration = {"reference": {"resistor_length_um": 900., "current_a": 1.6e-6},
                   "stages": {"1": {"supply_current_a": 50e-6}},
                   "common_mode": {"supply_current_a": 20e-6},
                   "fixed_current_a": 100e-6, "channel_current_budget_a": 1e-3}
    path = directory / "bias_network_inputs.json"
    path.write_text(json.dumps(declaration))
    ir = folded.build(project, sizing)
    row = next(r for r in ir["ota_bias_network"]["stage_table"] if r["stage"] == 2)
    devices = {d["name"]: d for d in ir["devices"]}
    aspect = lambda d: d["w"] / d["l"] * d.get("m", 1)
    sink_ratio = aspect(devices["ota_bias_2_mn_fc_bias_sink"]) / aspect(devices["mn_bias"])
    diode = aspect(devices["ota_bias_2_mp_fc_bias"])
    top = sum(aspect(devices[n]) / diode for n in ("mp_fc_top_in2", "mp_fc_top_ref2"))
    source = aspect(devices["ota_bias_2_mp_fc_bias_source"]) / diode
    rail_current = (sink_ratio * (top + 1 + source) + row["output_ratio"]) * row["mirror_reference_current_a"]
    assert row["supply_current_estimate_a"] >= rail_current * (1 - 1e-12)
    budget = ir["ota_bias_network"]["budget"]
    assert budget["locked_current_a"] >= declaration["fixed_current_a"] + 50e-6
    declaration["channel_current_budget_a"] = budget["estimated_current_a"] * .99
    path.write_text(json.dumps(declaration))
    limited = folded.build(project, sizing)["ota_bias_network"]["budget"]
    assert limited["status"] == "EXCEEDED"
    for point in limited["tradeoff_curve"]:
        assert point["estimated_current_a"] >= limited["locked_current_a"]


def test_changed_clock_spec_requires_regenerating_static_bias_ratios(tmp_path):
    ir, _, _, _, _ = _emit(tmp_path)
    path = tmp_path / "phase3/analog/neutral/spec.json"
    document = json.loads(path.read_text())
    for row in document["specs"]:
        if row["name"] in ("fclk", "fclk_min", "fclk_max"):
            row["target"] = 2.
    path.write_text(json.dumps(document))
    assert any("OTA_BIAS" in issue for issue in a3._validate_ir(ir, PDK, tmp_path))


def test_automatic_reference_uses_exact_existing_geometry_bound(tmp_path):
    ir, cards, _, _, _ = _emit(tmp_path, order=1,
        values={"cs1_ff": 4., "ci1_ff": 16., "cf1_ff": 6.}, bias={})
    assert ir["ota_bias_network"]["reference"]["resistor_length_um"] == 2000.
    assert "l=2000" in cards["r_ib"]


def test_explicit_reference_above_existing_bound_still_refuses(tmp_path):
    import pytest
    import analog_a2_topology_emit as a2
    with pytest.raises(a2.SizingInputsInvalid, match="OTA_BIAS_REFERENCE_NOT_REALISABLE"):
        _emit(tmp_path, bias={"reference": {"resistor_length_um": 2000.000001}})
