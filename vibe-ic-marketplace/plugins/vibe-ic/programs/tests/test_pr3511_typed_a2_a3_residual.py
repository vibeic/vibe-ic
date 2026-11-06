"""Public A2 -> A3 controls for the remaining typed PR3511 geometry seam."""
import copy
import hashlib
import json
import math
import shutil

import pytest

import _plugin_tree  # noqa: F401
import analog_a2_topology_emit as a2
import analog_a3_netlist_emit as a3
from _hostpaths import require_repo


SPEC = {"order": 2.0, "osr": 512.0, "enob": 14.0, "vref": 1.0,
        "vdd": 1.2, "vindiff": 1.0, "fclk": 1.0, "fclk_max": 1.0}
MEASURED = {"cap_area_ff_per_um2": 1.5, "cap_perim_ff_per_um": 0.04,
            "rsheet_ohm_per_sq": 260.0, "k_prime_n_ua_per_v2": 328.0,
            "vth_n_extracted_v": 0.197}


def _context(tmp_path):
    models = tmp_path / "models.lib"
    models.write_text(
        "* Valid range for model: L = (0.1 - 5)um\n"
        "* W = (0.2 - 10)um\n"
        ".lib typ\n"
        ".subckt neutral_n d g s b w=1u l=1u ng=1\n"
        "Ncore d g s b native_n w=w l=l nf='ng'\n"
        ".ends neutral_n\n"
        ".subckt neutral_p d g s b w=1u l=1u ng=1\n"
        "Ncore d g s b native_p w=w l=l nf='ng'\n"
        ".ends neutral_p\n"
        ".subckt neutral_r p n b w=1u l=1u\n.ends neutral_r\n"
        ".subckt neutral_c p n w=1u l=1u\n.ends neutral_c\n"
        ".endl typ\n")
    return {
        "status": "OK", "family": "neutral", "registry_family": "neutral",
        "model_lib": str(models), "typ_section": "typ",
        "role_models": {"nmos": "neutral_n", "pmos": "neutral_p",
                        "res": "neutral_r", "cap": "neutral_c"},
        "device_terminals": {"nmos": 4, "pmos": 4, "res": 3, "cap": 2},
        "geometry_units": {role: "metric"
                           for role in ("nmos", "pmos", "res", "cap")},
        "unresolved_roles": [],
    }


def _sizing(enabled=True):
    return {
        "knobs": {"ota_input_drain_cascodes": enabled},
        "device_parameters": {
            **{name: {"w": 18, "ng": 2}
               for name in ("mn_in1", "mn_ref1", "mn_in2", "mn_ref2")},
            **{name: {"w": 24, "l": 0.5, "ng": 3}
               for name in ("mn_cas_in1", "mn_cas_ref1",
                            "mn_cas_in2", "mn_cas_ref2")},
            "r_cas_top": {"w": 0.8, "l": 120},
            "r_cas_bottom": {"w": 0.8, "l": 40},
        },
    }


def _write_inputs(project, sizing):
    bdir = project / "phase3/analog/converter"
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / "sizing_inputs.json").write_text(json.dumps(sizing))
    (bdir / "spec.json").write_text(json.dumps({
        "specs": [{"name": name, "target": value}
                  for name, value in SPEC.items()]}))
    return bdir


def _build(project, sizing):
    _write_inputs(project, sizing)
    return a2.build_ir(
        "converter", "delta_sigma", {"name": "converter"},
        a2.LIBRARY["delta_sigma"], SPEC, None, project, None, {},
        measured_params=MEASURED)


def _matched_build(project, sizing, lib=None, **limits):
    _write_inputs(project, sizing)
    ir = a2.build_ir("converter", "delta_sigma", {}, lib or a2.LIBRARY["delta_sigma"],
                     SPEC, None, project, None, {}, measured_params=MEASURED, **limits)
    path = project / "phase3/analog/converter/topology.json"
    path.write_text(json.dumps(ir))
    return ir


def _matched_history(project, ir, changed=None):
    audit = ir["matched_gain_length"]
    path = project / "phase3/analog/converter/topology.json"
    return {"iterations": [{"iter": 0, "changes": "prospective typed input",
        "changed_params": changed or audit["independent_parameters"],
        "normal_topology": {"project": str(project), "block": "converter",
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
        "expanded_device_delta": audit["expanded_devices"]}]}


def test_matched_length_default_keeps_full_normal_ir_and_rendered_source(tmp_path):
    declared = a2.LIBRARY["delta_sigma"]
    old = copy.deepcopy(declared)
    for group in a2._stage_groups(old):
        group.pop("matched_gain_length", None)
    current = _matched_build(tmp_path / "same", {})
    legacy = _matched_build(tmp_path / "same", {}, old)
    for ir in [current, legacy]:
        ir.pop("_provenance")
    assert current == legacy
    ctx = _context(tmp_path)
    assert a3.render_netlist(current, ctx, [], a3._resolve_params(current, SPEC)[0]) == a3.render_netlist(
        legacy, ctx, [], a3._resolve_params(legacy, SPEC)[0])


def test_one_matched_length_has_exact_normal_deltas_and_history_binding(tmp_path):
    base = _matched_build(tmp_path / "base", {})
    project = tmp_path / "matched"
    ir = _matched_build(project, {"matched_gain_length_um": 1.5})
    expected = {f"{n}{i}" for i in (1, 2) for n in (
        "mn_in", "mn_ref", "mp_ld1_", "mp_ld2_", "mp_o", "mn_o")}
    derived = {"ota_bias_2_sink", "ota_bias_common_mode_sink"}
    before = {d["name"]: d for d in base["devices"]}
    after = {d["name"]: d for d in ir["devices"]}
    assert {n for n in before if before[n] != after[n]} == expected | derived
    expected_widths = {}
    for topology in (base, ir):
        devices = {d["name"]: d for d in topology["devices"]}
        network = topology["ota_bias_network"]
        reference = devices[network["reference"]["device"]]
        aspect = lambda d: d["w"] * d.get("m", 1) / d["l"]
        for row in network["stage_table"]:
            if row["stage"] not in (2, "common_mode"):
                continue
            tail_ratio, output_ratio = (aspect(devices[n]) / aspect(reference)
                                        for n in row["devices"])
            assert row["tail_ratio"] == pytest.approx(tail_ratio)
            assert row["output_ratio"] == pytest.approx(output_ratio)
            target = max(row["I_settle_a"] / tail_ratio,
                         row["I_slew_a"] / output_ratio)
            ratio = target / network["reference"]["current_a"]
            name = f"ota_bias_{row['stage']}_sink"
            sink = devices[name]
            assert row["reference_current_a"] == pytest.approx(target)
            assert row["mirror_ratio"] == pytest.approx(ratio)
            assert aspect(sink) / aspect(reference) == pytest.approx(ratio)
            if topology is ir:
                expected_widths[name] = ratio * aspect(reference) * sink["l"] / sink.get("m", 1)
    for name in before:
        want = dict(before[name])
        if name in expected:
            want["l"] = max(1.5, want["l"])
        elif name in derived:
            want["w"] = pytest.approx(expected_widths[name])
        assert after[name] == want
    assert ir["ports"] == base["ports"]
    assert ir["device_param_exprs"] == base["device_param_exprs"]
    assert not a3._validate_ir(ir, _context(tmp_path), project)
    assert len(ir["matched_gain_length"]["expanded_devices"]) == 12


def test_matched_length_uses_retained_in_repo_spec_through_normal_consumer(tmp_path):
    source = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
        "fixtures", "stage_analog_on_pass_review", "accept_adc_conv", "phase3", "analog",
        "delta_sigma", "spec.json")
    block = tmp_path / "phase3/analog/converter"
    block.mkdir(parents=True)
    shutil.copy2(source, block / "spec.json")
    (block / "sizing_inputs.json").write_text(json.dumps({"matched_gain_length_um": 1.5}))
    values, _ = a2.bound_spec_values(tmp_path, "converter")
    ir = a2.build_ir("converter", "delta_sigma", {}, a2.LIBRARY["delta_sigma"],
        values, None, tmp_path, None, {}, measured_params=MEASURED)
    assert not a3._validate_ir(ir, _context(tmp_path), tmp_path)
    assert len(ir["matched_gain_length"]["expanded_devices"]) == 6 * int(values["order"])


@pytest.mark.parametrize("value", [True, False, 0, -1, "1.5", math.nan, math.inf,
                                    {"length": 1.5, "w": 20}, [1.5]])
def test_matched_length_malformed_value_refused(tmp_path, value):
    with pytest.raises(a2.SizingInputsInvalid, match="finite positive"):
        _matched_build(tmp_path, {"matched_gain_length_um": value})


@pytest.mark.parametrize("value", [0.1, 6.0])
def test_matched_length_selected_pdk_limits_refuse_before_ir(tmp_path, value):
    with pytest.raises(a2.SizingInputsInvalid, match="PDK"):
        _matched_build(tmp_path, {"matched_gain_length_um": value},
            role_minima={r: {"min_length_um": 0.15} for r in ("nmos", "pmos")},
            role_maxima={r: {"max_length_um": 5.0} for r in ("nmos", "pmos")})


@pytest.mark.parametrize("parameter", ["l", "w"])
def test_matched_length_direct_controlled_device_override_refuses(tmp_path, parameter):
    with pytest.raises(a2.SizingInputsInvalid, match="conflicts with matched"):
        _matched_build(tmp_path, {"matched_gain_length_um": 1.5,
            "device_parameters": {"mn_in1": {parameter: 2}}})


@pytest.mark.parametrize("problem", ["unknown", "expression"])
def test_matched_length_invalid_source_owned_target_refuses(tmp_path, problem):
    lib = copy.deepcopy(a2.LIBRARY["delta_sigma"])
    if problem == "unknown":
        lib["stage"][0]["matched_gain_length"]["targets"].append("nonexistent{i}")
    else:
        lib["stage"][0].setdefault("param_exprs", []).append(
            {"device": "mn_in{i}", "param": "l", "expr": "1"})
    with pytest.raises(a2.SizingInputsInvalid, match="target|expression-owned"):
        _matched_build(tmp_path, {"matched_gain_length_um": 1.5}, lib)


def test_matched_length_missing_real_cascode_bias_still_refuses(tmp_path):
    with pytest.raises(a2.SizingInputsInvalid, match="physical|real bias resistor"):
        _matched_build(tmp_path, {"matched_gain_length_um": 1.5,
            "knobs": {"ota_input_drain_cascodes": True}})


def test_matched_length_includes_added_cascodes_but_full_arm_still_exceeds_cap(tmp_path):
    sizing = {"matched_gain_length_um": 1.5,
        "knobs": {"ota_input_drain_cascodes": True},
        "device_parameters": {"r_cas_top": {"w": 0.8, "l": 120},
                              "r_cas_bottom": {"w": 0.8, "l": 40}}}
    ir = _matched_build(tmp_path, sizing)
    assert not a3._validate_ir(ir, _context(tmp_path), tmp_path)
    rows = ir["matched_gain_length"]["expanded_devices"]
    assert len(rows) == 16
    assert all(row["after"]["l"] == 1.5 for row in rows)
    complete = _matched_history(tmp_path, ir)
    assert len(complete["iterations"][0]["changed_params"]) == 6
    disguised = _matched_history(tmp_path, ir,
                                ["matched_gain_length_um", "knobs.ota_input_drain_cascodes"])


def test_matched_length_tampered_expansion_refused_by_actual_a3(tmp_path):
    ir = _matched_build(tmp_path, {"matched_gain_length_um": 1.5})
    next(d for d in ir["devices"] if d["name"] == "mn_in1")["l"] = 2
    assert any("inconsistent matched" in p for p in a3._validate_ir(ir, _context(tmp_path), tmp_path))


def test_matched_length_retains_original_longer_dimensions(tmp_path):
    ir = _matched_build(tmp_path, {"matched_gain_length_um": 0.75})
    rows = {r["device"]: r for r in ir["matched_gain_length"]["expanded_devices"]}
    assert rows["mn_o1"]["after"]["l"] == 1.0
    assert rows["mn_in1"]["after"]["l"] == 0.75


def test_history_requires_current_exact_expansion_and_all_typed_inputs(tmp_path):
    ir = _matched_build(tmp_path, {"matched_gain_length_um": 1.5})
    valid = _matched_history(tmp_path, ir)
    del valid["iterations"][0]["expanded_device_delta"]
    disguised = _matched_history(tmp_path, ir, ["two arbitrary grouped strings"])
    path = tmp_path / "phase3/analog/converter/sizing_inputs.json"
    path.write_text(json.dumps({"matched_gain_length_um": 1.5,
                               "device_parameters": {"mn_tail1": {"w": 9}}}))
    assert a2.matched_gain_length_problems(ir, tmp_path)




def test_public_a2_to_a3_emits_typed_cascode_graph_and_source_bound_fingers(
        tmp_path):
    """Portable parent control: uses public A2/A3 APIs, not new helpers."""
    context = _context(tmp_path)
    try:
        ir = _build(tmp_path, _sizing())
        problems = a3._validate_ir(ir, context, tmp_path)
        text = a3.render_netlist(
            ir, context, [], a3._resolve_params(ir, SPEC)[0],
            deck_dir=tmp_path / "phase3/analog/converter")
        actual = {
            "status": "EMITTED" if not problems else "REFUSED",
            "problems": problems,
            "cascode": next(d for d in ir["devices"]
                            if d["name"] == "mn_cas_in1"),
            "has_bias_top": "xr_cas_top vdd ncas_bias vss neutral_r" in text,
            "has_native_fingers": (
                "xmn_cas_in1 nd1_1 ncas_bias ncas_mid_in1 vss neutral_n "
                "w=24u l=0.5u ng=3") in text,
        }
    except Exception as exc:  # parent records an actual value, not collection failure
        actual = {"status": type(exc).__name__, "detail": str(exc)}
    assert actual["status"] == "EMITTED", actual
    assert actual["cascode"]["nets"] == [
        "nd1_1", "ncas_bias", "ncas_mid_in1", "vss"]
    assert actual["has_bias_top"] is True
    assert actual["has_native_fingers"] is True


def test_selected_model_source_derives_fingers_without_a_design_literal(tmp_path):
    """Portable parent control for the existing A3 render consumer."""
    context = _context(tmp_path)
    ir = {"block": "neutral", "block_type": "ota", "topology": "stage",
          "ports": ["out", "in", "vss"],
          "devices": [{"name": "signal_device", "role": "nmos",
                       "nets": ["out", "in", "vss", "vss"],
                       "w": 16.0, "l": 1.0}]}
    text = a3.render_netlist(ir, context, [], {})
    assert "xsignal_device out in vss vss neutral_n w=16u l=1u ng=2" in text


def test_a3_refuses_stale_cascode_finger_count_from_current_sizing(tmp_path):
    """A model-legal carried count must still match current ordinary sizing."""
    context = _context(tmp_path)
    sizing = _sizing()
    ir = _build(tmp_path, sizing)
    cascode = next(device for device in ir["devices"]
                   if device["name"] == "mn_cas_in1")
    assert cascode["ng"] == 3

    # 24/4 = 6um remains inside the selected model's 0.2..10um per-finger
    # range.  Only its provenance is stale: current sizing still requests 3.
    cascode["ng"] = 4
    problems = a3._validate_ir(ir, context, tmp_path)
    assert problems == [
        "INPUT_DRAIN_CASCODE_INVALID: mn_cas_in1.ng: actual MOS sizing "
        "disagrees with ordinary sizing"
    ]


@pytest.mark.parametrize("mutation", [
    "partial", "wrong_cascode_gate", "wrong_original_drain",
    "wrong_resistor_end", "wrong_resistor_size", "stale_record",
    "disabled_record", "source_enable_mismatch",
])
def test_a3_refuses_invalid_actual_cascode_electrical_graph(tmp_path, mutation):
    context = _context(tmp_path)
    sizing = _sizing()
    ir = _build(tmp_path, sizing)
    devices = {device["name"]: device for device in ir["devices"]}
    if mutation == "partial":
        ir["devices"].remove(devices["mn_cas_in1"])
    elif mutation == "wrong_cascode_gate":
        devices["mn_cas_in1"]["nets"][1] = "vcm"
    elif mutation == "wrong_original_drain":
        devices["mn_in1"]["nets"][0] = "nd1_1"
    elif mutation == "wrong_resistor_end":
        devices["r_cas_bottom"]["nets"][1] = "vss"
    elif mutation == "wrong_resistor_size":
        devices["r_cas_top"]["w"] = 0.9
    elif mutation == "stale_record":
        ir["input_drain_cascodes"]["branches"][0]["original_drain"] = "vss"
    elif mutation == "disabled_record":
        ir["knobs"]["ota_input_drain_cascodes"] = False
        sizing["knobs"]["ota_input_drain_cascodes"] = False
    else:
        sizing["knobs"]["ota_input_drain_cascodes"] = False
    _write_inputs(tmp_path, sizing)
    problems = a3._validate_ir(ir, context, tmp_path)
    assert any("INPUT_DRAIN_CASCODE_INVALID" in problem
               for problem in problems), problems


def test_disabled_option_preserves_legacy_device_graph(tmp_path):
    disabled = {"knobs": {"ota_input_drain_cascodes": False},
                "device_parameters": {}}
    new = _build(tmp_path / "disabled", disabled)
    old_library = copy.deepcopy(a2.LIBRARY["delta_sigma"])
    old_library.pop("input_drain_cascodes")
    old_library["spec_knobs"] = [k for k in old_library["spec_knobs"]
                                 if k["name"] != "ota_input_drain_cascodes"]
    for group in old_library["stage"]:
        group.pop("input_drain_cascodes", None)
    old_project = tmp_path / "legacy"
    _write_inputs(old_project, {"knobs": {}, "device_parameters": {}})
    old = a2.build_ir("converter", "delta_sigma", {"name": "converter"},
                      old_library, SPEC, None, old_project, None, {},
                      measured_params=MEASURED)
    assert new["devices"] == old["devices"]
    assert new["internal_nets"] == old["internal_nets"]
    assert "input_drain_cascodes" not in new
