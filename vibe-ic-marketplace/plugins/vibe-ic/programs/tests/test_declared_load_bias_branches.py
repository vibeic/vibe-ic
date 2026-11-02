"""Declared SC loads must control real, separately biased OTA branches."""
from copy import deepcopy
import json
import math
import re

import pytest

import analog_a2_topology_emit as a2
import analog_a3_netlist_emit as a3


MEASURED = {"cap_area_ff_per_um2": 1.5, "cap_perim_ff_per_um": .04,
            "rsheet_ohm_per_sq": 260., "k_prime_n_ua_per_v2": 328.,
            "vth_n_extracted_v": .197}
PDK = {"model_lib": "/synthetic/models.lib", "typ_section": "tt",
       "mos_geometry": {}, "role_models": {"nmos": "n", "pmos": "p", "res": "r", "cap": "c"}}


def _inputs(order):
    return {"reference": {"resistor_length_um": 900., "current_a": 1.6e-6},
            "stages": {str(i): {"input_parasitic_ff": 60. / i,
                                 "output_load_ff": 90. / i,
                                 "supply_current_a": 50e-6}
                       for i in range(1, order + 1)},
            "common_mode": {"load_ff": 300., "supply_current_a": 20e-6},
            "fixed_current_a": 100e-6, "channel_current_budget_a": 1e-3,
            "citation": "Neutral declared-load sizing regression"}


def _emit(tmp_path, family="CIFF", order=3, values=None, bias=None, margin=None):
    spec = {"order": float(order), "osr": 128., "enob": 12., "vref": 1.,
            "vdd": 1.2, "vindiff": 1., "fclk": 1., "fclk_min": 1., "fclk_max": 1.}
    if family != "legacy_CIFB":
        spec.update(ciff=float(family == "CIFF"), designed_coefficients=1.,
                    feedback_delay=0., c0=1. if family == "CIFF" else 0., k0=0.)
        for i in range(1, order + 1):
            cs = 120. / i
            feedback = .375 if i == 1 else 0. if family == "CIFF" else .25
            spec.update({f"a{i}": .25, f"b{i}": feedback, f"c{i}": 1.,
                         f"cs{i}_ff": cs, f"ci{i}_ff": 4 * cs})
            if feedback:
                spec[f"cf{i}_ff"] = 4 * cs * feedback
    spec.update(values or {})
    directory = tmp_path / "phase3/analog/neutral"
    directory.mkdir(parents=True)
    sizing = {"device_parameters": {"mn_tail1": {"w": 12., "l": 1.}}}
    if margin is not None:
        sizing["knobs"] = {"slew_design_margin": margin}
    (directory / "sizing_inputs.json").write_text(json.dumps(sizing))
    (directory / "bias_network_inputs.json").write_text(json.dumps(_inputs(order) if bias is None else bias))
    path = directory / "spec.json"
    path.write_text(json.dumps({"specs": [{"name": k, "target": v} for k, v in spec.items()]}))
    ir = a2.build_ir("neutral", "delta_sigma", {}, a2.LIBRARY["delta_sigma"],
                     spec, str(path), tmp_path, None, {}, measured_params=MEASURED)
    overrides, _, _, env = a3._resolve_params(ir, spec)
    deck = a3.render_netlist(ir, PDK, [], overrides)
    cards = {line.split()[0][1:]: line for line in deck.splitlines() if line.startswith("x")}
    devices = {d["name"]: d for d in ir["devices"]}
    def cap(base):
        total = 0.
        for name, line in cards.items():
            if re.sub(r"_u\d+$", "", name) != base:
                continue
            w, length = (float(re.search(r"\b" + k + r"=([0-9.eE+-]+)", line)[1]) for k in ("w", "l"))
            total += MEASURED["cap_area_ff_per_um2"] * w * length + 2 * MEASURED["cap_perim_ff_per_um"] * (w + length)
        return total
    return ir, cards, devices, env, cap


def _stages(ir):
    return {row["stage"]: row for row in ir["ota_bias_network"]["stage_table"]
            if isinstance(row["stage"], int)}


@pytest.mark.parametrize("family,order", [(family, order) for family in ("CIFF", "CIFB")
                                        for order in (1, 2, 3)] + [("legacy_CIFB", 1), ("legacy_CIFB", 2)])
def test_declared_sc_geometry_and_feedback_set_each_stage_load(tmp_path, family, order):
    ir, cards, _, env, cap = _emit(tmp_path, family, order)
    assert float(re.search(r"\bl=([0-9.eE+-]+)", cards["r_ib"])[1]) == pytest.approx(900.)
    rows = _stages(ir)
    assert sorted(rows) == list(range(1, order + 1))
    for i, row in rows.items():
        cs, cf, ci = cap(f"cs{i}"), cap(f"cf{i}"), cap(f"ci{i}")
        assert [row["Cs_ff"], row["Cf_ff"], row["Ci_ff"]] == pytest.approx([cs, cf, ci], rel=1e-5)
        cp, cl = 60. / i, 90. / i
        beta = ci / (ci + cs + cf + cp)
        load = cl + ci * (cs + cf + cp) / (ci + cs + cf + cp)
        assert row["beta"] == pytest.approx(beta, rel=1e-5)
        assert row["load_ff"] == pytest.approx(load, rel=1e-5)
        available = env["settle_periods_available"] / (env["fclk"] * env["hz_per_mhz"])
        slew = load * 1e-15 * env["vref"] * 2 / available
        settle = load * 1e-15 * env["integrator_input_overdrive_v"] * (env["enob"] + 1) * math.log(2) / (beta * available)
        assert row["I_slew_a"] == pytest.approx(slew, rel=1e-5)
        assert row["I_settle_a"] == pytest.approx(settle, rel=1e-5)
        assert row["I_target_a"] == pytest.approx(max(slew, settle), rel=1e-5)


def test_each_ota_has_its_own_physical_ratioed_branch(tmp_path):
    ir, _, devices, _, _ = _emit(tmp_path)
    gates = [devices[f"mn_tail{i}"]["nets"][1] for i in (1, 2, 3)]
    assert len(set(gates)) == 3
    assert gates[0] == "nbias"
    assert devices["mn_bias"]["nets"][:2] == ["nbias", "nbias"]
    for i, row in _stages(ir).items():
        assert row["gate"] == gates[i - 1]
        assert devices[f"mn_tail{i}"]["w"] == (12. if i == 1 else 8.)
        assert devices[f"mn_tail{i}"]["l"] == 1.
        for name in row["devices"]:
            assert devices[name]["nets"][1] == row["gate"]
    assert all(devices[f"mn_o{i}"]["nets"][1] == gates[i - 1] for i in (1, 2, 3))
    assert any(d["role"] == "nmos" and d["nets"][1] == "nbias"
               and d["name"] not in {"mn_bias", "mn_tail1", "mn_o1"}
               for d in devices.values())


def test_fixed_declared_caps_do_not_use_the_noise_osr_load(tmp_path):
    first = _emit(tmp_path / "short", values={"osr": 64.})
    second = _emit(tmp_path / "long", values={"osr": 256.})
    assert first[1]["r_ib"] == second[1]["r_ib"]
    for i in (1, 2, 3):
        a, b = _stages(first[0])[i], _stages(second[0])[i]
        for key in ("Cs_ff", "Cf_ff", "Ci_ff", "beta", "load_ff", "I_slew_a", "I_settle_a", "I_target_a"):
            assert a[key] == pytest.approx(b[key])


def test_resolution_changes_settling_requirement_without_resizing_declared_load(tmp_path):
    first = _emit(tmp_path / "lower", values={"enob": 12.})
    second = _emit(tmp_path / "higher", values={"enob": 14.})
    assert first[1]["r_ib"] == second[1]["r_ib"]
    for i in (1, 2, 3):
        a, b = _stages(first[0])[i], _stages(second[0])[i]
        assert a["load_ff"] == pytest.approx(b["load_ff"])
        assert a["I_slew_a"] == pytest.approx(b["I_slew_a"])
        assert b["I_settle_a"] / a["I_settle_a"] == pytest.approx(15. / 13.)


def test_reference_anchor_and_ota1_geometry_survive_other_stage_load_change(tmp_path):
    first = _emit(tmp_path / "original")
    second = _emit(tmp_path / "heavier", values={"a2": .125, "ci2_ff": 480.})
    for name in ("r_ib", "mn_bias", "mn_tail1", "mn_in1", "mn_ref1"):
        assert first[1][name] == second[1][name]
    assert _stages(second[0])[2]["I_target_a"] != pytest.approx(_stages(first[0])[2]["I_target_a"])


def test_default_margin_two_matches_explicit_two_and_keeps_slew_meaning(tmp_path):
    default = _emit(tmp_path / "default")
    explicit = _emit(tmp_path / "two", margin=2.)
    higher = _emit(tmp_path / "four", margin=4.)
    assert default[1] == explicit[1]
    for i in (1, 2, 3):
        row = _stages(default[0])[i]
        changed = _stages(higher[0])[i]
        assert changed["I_slew_a"] == pytest.approx(2 * row["I_slew_a"])
        assert changed["I_settle_a"] == pytest.approx(row["I_settle_a"])
        assert changed["I_target_a"] == pytest.approx(max(changed["I_slew_a"], changed["I_settle_a"]))


def test_shared_single_bias_gate_cannot_hide_different_stage_needs(tmp_path):
    ir, _, _, _, _ = _emit(tmp_path)
    changed = deepcopy(ir)
    for device in changed["devices"]:
        if device["name"] in ("mn_tail2", "mn_o2", "mn_tail3", "mn_o3"):
            device["nets"][1] = "nbias"
    issues = a3._validate_ir(changed, PDK)
    assert any("OTA_BIAS" in issue for issue in issues), issues


def test_channel_budget_includes_mirror_translators_and_reports_tradeoff(tmp_path):
    inputs = _inputs(3)
    ir, _, _, _, _ = _emit(tmp_path / "room", bias=inputs)
    network = ir["ota_bias_network"]
    budget = network["budget"]
    translator_current = sum(2 * row["reference_current_a"]
                             for row in network["stage_table"] if row["gate"] != "nbias")
    assert budget["estimated_current_a"] >= inputs["fixed_current_a"] + translator_current
    tight = deepcopy(inputs)
    tight["channel_current_budget_a"] = 1e-9
    limited, _, _, _, _ = _emit(tmp_path / "tight", bias=tight)
    limited_budget = limited["ota_bias_network"]["budget"]
    assert limited_budget["status"] == "EXCEEDED"
    assert limited_budget["tradeoff_curve"]
    assert [r["I_target_a"] for r in _stages(limited).values()] == pytest.approx(
        [r["I_target_a"] for r in _stages(ir).values()])


def test_undeclared_channel_budget_cannot_be_reported_as_pass(tmp_path):
    inputs = _inputs(2)
    inputs.pop("channel_current_budget_a")
    ir, _, _, _, _ = _emit(tmp_path, order=2, bias=inputs)
    assert ir["ota_bias_network"]["budget"]["status"] == "UNDECIDED"
