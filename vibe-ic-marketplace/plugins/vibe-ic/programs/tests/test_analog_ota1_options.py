"""Declared OTA1 options: connectivity, explicit parameters and default bytes."""
from copy import deepcopy
import json

import pytest

import analog_a2_topology_emit as a2
import analog_a3_netlist_emit as a3
from _analog_producer_fixture import A2, A3, run_prog, bdir, read_json
from test_analog_ciff import _project, _emit


def _case(tmp_path, folded=0, chop=0, phase=1, ratio=4):
    p = _project(tmp_path, 2, ota1_folded_cascode=folded, ota1_chopper=chop,
        ota1_chop_ratio=ratio, ota1_chop_sc_phase=phase,
        ota1_chop_nmos_w_um=2., ota1_chop_pmos_w_um=4., ota1_chop_l_um=.5)
    parameters = {}
    if folded:
        lib = a2.LIBRARY["delta_sigma"]
        rows = lib["stage"][0]["folded_first_stage"]["devices"] + lib["folded_first_stage"]["devices"]
        for row in rows:
            # Synthetic geometry inputs exercise parameter binding, not sizing.
            parameters["ota1_"+row["name"].format(i=1)] = {"w": 2., "l": .5}
    elif chop:
        parameters = {name: {"w": .5, "l": 10.} for name in ("r_ota1_ch_top", "r_ota1_ch_bottom")}
    if parameters:
        (bdir(p, "mod_alpha") / "sizing_inputs.json").write_text(json.dumps({"device_parameters": parameters}))
    cp = run_prog(A2, p)
    gap = bdir(p, "mod_alpha") / "topology_gap.json"
    assert cp.returncode == 0, cp.stdout + cp.stderr + (gap.read_text() if gap.exists() else "")
    ir = read_json(bdir(p, "mod_alpha") / "topology.json")
    return p, ir


@pytest.mark.parametrize("folded,chop", [(1, 0), (0, 1), (1, 1)])
def test_selected_ota1_graph_and_parameters_reach_a3(tmp_path, folded, chop):
    p, ir = _case(tmp_path, folded, chop)
    devs = {d["name"]: d for d in ir["devices"]}
    option = ir["ota1_options"]
    assert option["geometry_status"] == "DECLARED_INPUT_ONLY_NOT_SIZED"
    if folded:
        assert "mp_o1" not in devs and "mn_o1" not in devs
        assert devs["ota1_mp_fc_ref1"]["nets"][0] == ir["loop_declaration"]["state_nets"][0]
        assert devs["cc1"]["nets"] == [ir["loop_declaration"]["state_nets"][0], "vcm"]
        assert option["input_polarity"] == "swapped_to_preserve_inverting_summing_node"
        assert all(devs[n]["w"] == 2. and devs[n]["l"] == .5 for n in option["explicit_geometry_devices"])
    else:
        assert "mp_o1" in devs and "mn_o1" in devs
    if chop:
        clock = option["chopper"]
        assert clock["ratio"] == 4 and clock["source_phase"] == "nph1"
        assert devs["ota1_ch_mn_cki1"]["nets"][1] == "nph1"
        assert clock["output_interface"] == "single_ended"
        assert devs["mn_in1"]["nets"][1] == "ota1_ch_g1"
        assert devs["mn_ota1_ch_in1p"]["w"] == 2.
        assert devs["mp_ota1_ch_in1p"]["w"] == 4.
        for n in ("mn_ota1_ch_in1p", "mn_ota1_ch_out1p"):
            assert devs[n]["nets"][1] == clock["positive_phase"]
        for n in ("mn_ota1_ch_in1n", "mn_ota1_ch_out1n"):
            assert devs[n]["nets"][1] == clock["negative_phase"]
        for i, node in enumerate(clock["demodulation_nodes"], 1):
            common_gate = devs[f"ota1_mp_fc_{'in' if i==1 else 'ref'}1"] if folded else devs[f"mn_ota1_ch_cas{i}"]
            assert common_gate["nets"][2] == node
        assert not any("cmfb" in n for n in option["explicit_geometry_devices"])
    cp = run_prog(A3, p)
    gap = bdir(p, "mod_alpha") / "netlist_gap.json"
    assert cp.returncode == 0, cp.stdout + cp.stderr + (gap.read_text() if gap.exists() else "")
    text = (bdir(p, "mod_alpha") / "mod_alpha.sp").read_text()
    for name in devs:
        assert "x"+name+" " in text


def test_explicit_off_matches_the_previous_default_netlist_byte_for_byte(tmp_path):
    p, before = _emit(tmp_path / "default", 2)
    q, after = _case(tmp_path / "off")
    assert "ota1_options" not in before and "ota1_options" not in after
    ctx = {"model_lib": "/foss/pdks/test.lib", "section": "tt", "mos_geometry": {},
           "role_models": {"nmos": "n", "pmos": "p", "res": "r", "cap": "c"}}
    def render(project, ir):
        sv = a3.spec_values(read_json(bdir(project, "mod_alpha") / "spec.json"))
        overrides, _, _, _ = a3._resolve_params(ir, sv)
        return a3.render_netlist(ir, deepcopy(ctx), [], overrides)
    # Fixed provenance is deliberate: source fingerprints/timestamps change
    # on a producer update; the complete A3 circuit deck must remain identical.
    assert render(p, before).encode() == render(q, after).encode()


def test_options_do_not_choose_capacitor_values(tmp_path):
    _, baseline = _emit(tmp_path / "baseline", 2)
    _, selected = _case(tmp_path / "selected", 1, 1)
    cap_names = {d["name"] for d in baseline["devices"] if d["role"] == "cap"}
    def expressions(ir):
        return [e for e in ir["device_param_exprs"] if e["device"] in cap_names]
    assert expressions(baseline) == expressions(selected)


def test_chop_phase_and_ratio_are_declarations(tmp_path):
    _, ir = _case(tmp_path, 0, 1, phase=2, ratio=2)
    assert ir["ota1_options"]["chopper"]["source_phase"] == "nph2"
    assert ir["ota1_options"]["chopper"]["ratio"] == 2


def test_new_folded_geometry_is_required_and_never_synthesized(tmp_path):
    p = _project(tmp_path, 2, ota1_folded_cascode=1)
    assert run_prog(A2, p).returncode == 2
    gap = read_json(bdir(p, "mod_alpha") / "topology_gap.json")
    assert "no geometry is synthesized" in str(gap)
