"""Final A2 sizing must preserve the loop realized by A3 capacitor cards."""
from copy import deepcopy
import json
import re

import pytest

import analog_a2_topology_emit as a2
import analog_a3_netlist_emit as a3


SPEC = {"order": 2., "osr": 512., "enob": 14., "vref": 1., "vdd": 1.2,
        "vindiff": 1., "fclk": 1., "fclk_min": 1., "fclk_max": 1.,
        "ciff": 1., "ntf_hinf": 1.4, "a1": .25, "a2": .25,
        "cs1_ff": 100., "ci1_ff": 400., "cf1_ff": 100.}
MEASURED = {"cap_area_ff_per_um2": 1.5, "cap_perim_ff_per_um": .08,
            "rsheet_ohm_per_sq": 260., "k_prime_n_ua_per_v2": 328.,
            "vth_n_extracted_v": .197}


def emit(tmp_path, sizing=None, values=None, minima=None, maxima=None, library=None):
    spec = {**SPEC, **(values or {})}
    directory = tmp_path / "phase3/analog/neutral"
    directory.mkdir(parents=True)
    (directory / "sizing_inputs.json").write_text(json.dumps(sizing or {}))
    path = directory / "spec.json"
    path.write_text(json.dumps({"specs": [{"name": k, "target": v} for k, v in spec.items()]}))
    ir = a2.build_ir("neutral", "delta_sigma", {}, library or a2.LIBRARY["delta_sigma"],
                     spec, str(path), tmp_path, None, {}, measured_params=MEASURED,
                     role_minima=minima, role_maxima=maxima)
    overrides, _, _, env = a3._resolve_params(ir, spec)
    deck = a3.render_netlist(ir, {"model_lib": "/synthetic/models.lib", "typ_section": "tt",
        "mos_geometry": {}, "role_models": {"nmos": "n", "pmos": "p", "res": "r", "cap": "c"}}, [], overrides)
    geometry = {}
    for line in deck.splitlines():
        if not line.startswith("x"):
            continue
        name = line.split()[0][1:]
        if next(d["role"] for d in ir["devices"] if d["name"] == name) != "cap":
            continue
        geometry[name] = {k: float(re.search(r"\b"+k+r"=([0-9.eE+-]+)", line)[1])
                          for k in ("w", "l")}
        multiplier = re.search(r"\bm=([0-9.eE+-]+)", line)
        geometry[name]["m"] = float(multiplier[1]) if multiplier else 1.
    def capacitance(base):
        return sum(g["m"] * (env["cap_area_ff_per_um2"] * g["w"] * g["l"]
                    + 2 * env.get("cap_perim_ff_per_um", 0.) * (g["w"] + g["l"]))
                   for name, g in geometry.items() if re.sub(r"_u\d+$", "", name) == base)
    return ir, geometry, capacitance


@pytest.mark.parametrize("name,width", [("ci1", 5.), ("cs1", 6.), ("cf1", 7.),
                                        ("ci2", 8.), ("cff0", 4.), ("cff1", 5.), ("cff2", 6.)])
def test_selected_coefficient_width_preserves_rendered_ratios(tmp_path, name, width):
    ir, geometry, cap = emit(tmp_path, {"device_parameters": {name: {"w": width}}})
    assert geometry[name]["w"] == width
    assert cap("cs1") == pytest.approx(100., rel=1e-5)
    assert cap("ci1") == pytest.approx(400., rel=1e-5)
    for i, gain in enumerate(ir["loop_declaration"]["a"], 1):
        assert cap(f"cs{i}") / cap(f"ci{i}") == pytest.approx(abs(gain), rel=1e-5)
    loop = ir["loop_declaration"]
    assert cap("cf1") / cap("ci1") == pytest.approx(abs(loop["b"][0]), rel=1e-5)
    for i, gain in enumerate(loop["c"], 1):
        assert cap(f"cff{i}") / cap("cff0") == pytest.approx(abs(gain / loop["c0"]), rel=1e-5)


def test_explicit_width_survives_pdk_unit_array(tmp_path):
    ir, geometry, cap = emit(tmp_path, {"device_parameters": {"ci1": {"w": 5.}}},
                            maxima={"cap": {"max_length_um": 30.}})
    units = [g for name, g in geometry.items() if name.startswith("ci1_u")]
    assert len(units) > 1
    assert all(g["w"] == 5. and g["l"] <= 30. for g in units)
    assert cap("ci1") == pytest.approx(400., rel=1e-5)
    assert cap("cs1") / cap("ci1") == pytest.approx(ir["loop_declaration"]["a"][0], rel=1e-5)


def test_incompatible_selected_width_is_named_instead_of_resized(tmp_path):
    with pytest.raises(a2.SizingInputsInvalid, match="SC_LOOP_COEFFICIENT_GEOMETRY_INVALID: ci1"):
        emit(tmp_path, {"device_parameters": {"ci1": {"w": 100.}}},
             minima={"cap": {"min_length_um": 5.}},
             maxima={"cap": {"max_length_um": 100.}})


def test_independent_compensation_and_mos_geometry_stays_selected(tmp_path):
    ir, geometry, _ = emit(tmp_path, {"device_parameters": {"cc1": {"w": 5.},
                                                           "mn_smp1": {"w": 3.}}})
    assert geometry["cc1"]["w"] == 5.
    assert next(d for d in ir["devices"] if d["name"] == "mn_smp1")["w"] == 3.


def test_coefficient_multiplicity_preserves_total_capacitance(tmp_path):
    library = deepcopy(a2.LIBRARY["delta_sigma"])
    next(d for d in library["stage"][0]["devices"] if d["name"] == "ci{i}")["m"] = 1.
    _, geometry, cap = emit(tmp_path, {"device_parameters": {"ci1": {"w": 5., "m": 2.}}},
                            library=library)
    assert geometry["ci1"]["w"] == 5. and geometry["ci1"]["m"] == 2.
    assert cap("ci1") == pytest.approx(400., rel=1e-5)


def test_shared_dac_widths_keep_both_feedback_contributions(tmp_path):
    ir, geometry, cap = emit(tmp_path, {"device_parameters": {"cs1": {"w": 5.}, "ci1": {"w": 8.},
                                                           "cf1": {"w": 6.}}},
                            {"shared_input_dac": 1., "designed_coefficients": 1.,
                             "a1": .25, "a2": .25, "b1": .5, "b2": 0.,
                             "c1": 1., "c2": 2., "c0": 1.})
    assert [geometry[n]["w"] for n in ("cs1", "ci1", "cf1")] == [5., 8., 6.]
    assert (cap("cs1") + cap("cf1")) / cap("ci1") == pytest.approx(ir["loop_declaration"]["b"][0], rel=1e-5)
