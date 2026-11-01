"""Positive state scaling changes capacitor ratios, not the ideal bit decisions."""
import copy
import json

import pytest

import analog_a2_topology_emit as a2
import analog_a3_netlist_emit as a3
import analog_incremental_resolution as resolution
import test_analog_miller_nulling_input as miller
from test_q6_a2_cap_split_and_swing_model import emitted, run_prog, A2, PDK


KNOB = "second_integrator_state_scale"


def test_absent_input_preserves_existing_ir_and_rendered_source(tmp_path):
    lib = copy.deepcopy(a2.LIBRARY["delta_sigma"])
    lib["spec_knobs"] = [row for row in lib["spec_knobs"] if row["name"] != KNOB]
    sizing = miller.inputs(tmp_path)
    old = miller.build(tmp_path, sizing, lib, repo_spec=True)
    new = miller.build(tmp_path, sizing, repo_spec=True)
    for ir in (old, new):
        ir.pop("_provenance")
    assert old == new
    context = miller.folded._context(tmp_path)
    assert a3.render_netlist(old, context, [], a3._resolve_params(old, miller.folded.SPEC)[0]) == \
        a3.render_netlist(new, context, [], a3._resolve_params(new, miller.folded.SPEC)[0])


def test_normal_input_scales_only_second_state_and_its_integrating_capacitor(emitted):
    root, directory, old, spec = emitted
    (directory / "sizing_inputs.json").write_text(json.dumps({"knobs": {KNOB: .5}}))
    result = run_prog(A2, root, "--pdk", PDK)
    assert result.returncode == 0, result.stderr
    new = json.loads((directory / "topology.json").read_text())
    before = old["loop_swing"]["coefficients_scaled"]
    after = new["loop_swing"]["coefficients_scaled"]
    assert after["b1"] == before["b1"]
    assert after["a"][0] == before["a"][0]
    assert after["a"][1] == .5 * before["a"][1]
    assert after["c"][1] == .5 * before["c"][1]
    assert after["a"][1] / after["c"][1] == before["a"][1] / before["c"][1]
    assert new["loop_swing"]["bitstream_identical"]
    assert new["loop_swing"]["peaks_after"][0] == pytest.approx(old["loop_swing"]["peaks_after"][0])
    assert new["loop_swing"]["peaks_after"][1] == pytest.approx(.5 * old["loop_swing"]["peaks_after"][1])
    before_params = a3._resolve_params(old, a3.spec_values(spec))[0]
    after_params = a3._resolve_params(new, a3.spec_values(spec))[0]
    for cap in ("cs1", "ci1", "cf1", "cs2", "cf2"):
        assert after_params[cap] == pytest.approx(before_params[cap])
    measured = new["pdk_measured_params"]
    def capacitance(ir, parameters):
        device = next(d for d in ir["devices"] if d["name"] == "ci2")
        w, l = [parameters["ci2"].get(key, device[key]) for key in ("w", "l")]
        return measured["cap_area_ff_per_um2"] * w * l + 2 * measured["cap_perim_ff_per_um"] * (w + l)
    assert capacitance(new, after_params) == pytest.approx(2 * capacitance(old, before_params))
    assert new["stage_expansion"]["coefficients"] == old["stage_expansion"]["coefficients"]
    for value in (-.72, 0, .72):
        stimulus = resolution._dc(value)
        assert resolution.run_loop(512, before["b1"], before["a"], before["c"], 1, stimulus)["bits"] == \
            resolution.run_loop(512, after["b1"], after["a"], after["c"], 1, stimulus)["bits"]


@pytest.mark.parametrize("bad", [0, -1, True, "0.5", None, float("inf")])
def test_invalid_scale_is_refused_by_normal_input(tmp_path, bad):
    sizing = miller.inputs(tmp_path)
    sizing["knobs"][KNOB] = bad
    with pytest.raises(a2.SizingInputsInvalid, match="finite positive"):
        miller.build(tmp_path, sizing, repo_spec=True)
