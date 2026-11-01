"""Compensation sizing propagates its declared load into the independent bias."""
import json
import math

import pytest

import analog_a2_topology_emit as a2
import analog_a3_netlist_emit as a3

SPEC = {"order": 2., "vdd": 1.2, "vdd_min": 1.2, "osr": 256.,
        "enob": 14., "enob_min": 14., "vref": 1., "fclk": 1.,
        "fclk_min": 1., "fclk_max": 1., "vindiff": 1.}


def emit(project, sizing=None, spec=None):
    block = project / "phase3/analog/loop"
    block.mkdir(parents=True, exist_ok=True)
    if sizing is not None:
        (block / "sizing_inputs.json").write_text(json.dumps(sizing))
    family, params = a2.pdk_device_params("ihp-sg13g2")
    measured, provenance = a2.pdk_measured_params("ihp-sg13g2", project)
    return a2.build_ir("loop", "delta_sigma", {}, a2.LIBRARY["delta_sigma"],
        spec or SPEC, None, project, family, params,
        measured_params=measured, measured_provenance=provenance)


def dimensions(ir):
    values, _, _, _ = a3._resolve_params(ir, SPEC)
    return {d["name"]: {**{p: d[p] for p in ("w", "l") if p in d},
                        **values.get(d["name"], {})} for d in ir["devices"]}


def capacitance(dim):
    return 1.5 * dim["w"] * dim["l"] + .08 * (dim["w"] + dim["l"])


def test_normal_scale_changes_only_two_miller_capacitances(tmp_path):
    base = emit(tmp_path / "base")
    candidate = emit(tmp_path / "candidate", {"knobs": {"ota_compensation_scale": 1.5}})
    before, after = dimensions(base), dimensions(candidate)
    assert base["ports"] == candidate["ports"]
    base_devices = {d["name"]: d for d in base["devices"]}
    candidate_devices = {d["name"]: d for d in candidate["devices"]}
    assert base_devices.keys() == candidate_devices.keys()
    for name in base_devices:
        if name != "ota_bias_2_sink":
            assert base_devices[name] == candidate_devices[name]
    sink_before, sink_after = (devices["ota_bias_2_sink"]
                               for devices in (base_devices, candidate_devices))
    assert {k: v for k, v in sink_before.items() if k != "w"} == {
        k: v for k, v in sink_after.items() if k != "w"}
    assert base["loop_swing"] == candidate["loop_swing"]
    changed = {name for name in before if before[name] != after[name]}
    assert changed == {"cc1", "cc2", "ota_bias_2_sink"}
    for name in ("cc1", "cc2"):
        assert capacitance(after[name]) / capacitance(before[name]) == pytest.approx(1.5)
    rows_before, rows_after = ({r["stage"]: r for r in ir["ota_bias_network"]["stage_table"]}
                               for ir in (base, candidate))
    for stage in (1, 2):
        cap = "cc" + str(stage)
        assert rows_after[stage]["output_load_ff"] - rows_before[stage]["output_load_ff"] == pytest.approx(
            capacitance(after[cap]) - capacitance(before[cap]))
    master = candidate_devices["mn_bias"]
    ratio = (sink_after["w"] / sink_after["l"]) / (master["w"] / master["l"])
    assert ratio == pytest.approx(rows_after[2]["mirror_ratio"])
    assert rows_after[2]["mirror_reference_current_a"] == pytest.approx(
        rows_after[2]["reference_current_a"])
    assert candidate["knob_sources"]["ota_compensation_scale"] == "explicit_design_sizing"


def test_absent_and_unit_scale_keep_normal_geometry_identical(tmp_path):
    a = emit(tmp_path / "absent")
    b = emit(tmp_path / "explicit", {"knobs": {"ota_compensation_scale": 1.}})
    assert dimensions(a) == dimensions(b)
    for index in [1, 2]:
        caps = dimensions(a)
        assert capacitance(caps[f"cc{index}"]) / capacitance(caps[f"ci{index}"]) == pytest.approx(.3)


@pytest.mark.parametrize("value", [0, -1, True, "1.5", math.inf, math.nan])
def test_invalid_scale_refuses_before_normal_ir(tmp_path, value):
    with pytest.raises(a2.SizingInputsInvalid, match="finite positive"):
        emit(tmp_path, {"knobs": {"ota_compensation_scale": value}})


def test_direct_compensation_length_override_stays_refused(tmp_path):
    with pytest.raises(a2.SizingInputsInvalid, match="expression-owned"):
        emit(tmp_path, {"device_parameters": {"cc1": {"l": 12}}})


def test_bound_source_knob_cannot_be_overridden_by_sizing(tmp_path):
    spec = {**SPEC, "ota_compensation_scale": 1.}
    with pytest.raises(a2.SizingInputsInvalid, match="bound by the source specification"):
        emit(tmp_path, {"knobs": {"ota_compensation_scale": 1.5}}, spec)
