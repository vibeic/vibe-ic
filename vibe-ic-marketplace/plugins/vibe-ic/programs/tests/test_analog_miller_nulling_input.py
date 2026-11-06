"""Physical coupled Miller source controls; no native performance is inferred."""
import copy
import json
import math
import shutil

import pytest

import analog_a2_topology_emit as a2
import analog_a3_netlist_emit as a3
import test_analog_folded_first_stage_input as folded
import test_analog_folded_reference_diode as diode
from test_pr3511_typed_a2_a3_residual import _write_inputs
from _hostpaths import require_repo

CAP = "ota_miller_capacitance_ff"
LENGTH = "ota_miller_nulling_length_um"


def inputs(project, variant="parent"):
    sizing = diode.inputs(project) if variant == "diode" else folded.inputs(project)
    sizing["knobs"].update({CAP: 3900.0, LENGTH: 3.8})
    return sizing


def build(project, sizing, lib=None, repo_spec=False):
    _write_inputs(project, sizing)
    if repo_spec:
        source = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
            "fixtures", "stage_analog_on_pass_review", "accept_adc_conv", "phase3", "analog",
            "delta_sigma", "spec.json")
        shutil.copy2(source, project / "phase3/analog/converter/spec.json")
    values, path = a2.bound_spec_values(project, "converter")
    fam, params = a2.pdk_device_params("ihp-sg13g2")
    measured, provenance = a2.pdk_measured_params(fam, project)
    _, minima = a2._minima.layout_minima(fam)
    _, maxima = a2._minima.layout_maxima(fam)
    ir = a2.build_ir("converter", "delta_sigma", {}, lib or a2.LIBRARY["delta_sigma"],
        values, path, project, fam, params, minima, a2._minima.minima_source(fam),
        measured, provenance, maxima, a2._minima.maxima_source(fam))
    (project / "phase3/analog/converter/topology.json").write_text(json.dumps(ir))
    return ir


def cap_total(ir, base):
    params, _, _, _ = a3._resolve_params(ir, folded.SPEC)
    measured = ir["pdk_measured_params"]
    total = 0.0
    for d in ir["devices"]:
        if d["role"] == "cap" and (d["name"] == base or d["name"].startswith(base + "_u")):
            w, l = [params.get(d["name"], {}).get(p, d[p]) for p in ("w", "l")]
            total += measured["cap_area_ff_per_um2"] * w * l + 2 * measured["cap_perim_ff_per_um"] * (w + l)
    return total


@pytest.mark.parametrize("stage", [1, 2])
def test_existing_constructor_observes_total_coupled_capacitance(tmp_path, stage):
    sizing = inputs(tmp_path)
    # Let the old constructor reach its physical values rather than fail
    # only on the absent option. It still keeps the original small Cc.
    lib = copy.deepcopy(a2.LIBRARY["delta_sigma"])
    for key in (CAP, LENGTH):
        if not any(row["name"] == key for row in lib["spec_knobs"]):
            lib["spec_knobs"].append({"name": key, "expr": key, "default": None, "optional": True})
    ir = build(tmp_path, sizing, lib)
    assert cap_total(ir, "cc" + str(stage)) == pytest.approx(3900.0)


@pytest.mark.parametrize("variant", ["parent", "diode"])
def test_normal_physical_series_graph_and_lvs_readback(tmp_path, variant):
    ir = build(tmp_path, inputs(tmp_path, variant))
    ctx = folded._context(tmp_path)
    assert not a3._validate_ir(ir, ctx, tmp_path)
    record = ir["miller_nulling"]
    assert record["independent_parameters"] == ["knobs." + CAP, "knobs." + LENGTH]
    assert record["requested_capacitance_ff"] == 3900
    assert len(record["branches"]) == 2
    devices = {d["name"]: d for d in ir["devices"]}
    for index, output in [(1, "vo1"), (2, "vint")]:
        name = "rz_cc" + str(index)
        assert devices[name]["nets"] == ["nd2_" + str(index), "ncc" + str(index), "vss"]
        assert devices[name]["role"] == "res"
        assert cap_total(ir, "cc" + str(index)) == pytest.approx(3900)
    params, _, _, _ = a3._resolve_params(ir, folded.SPEC)
    assert params["rz_cc1"] == params["rz_cc2"]
    assert params["rz_cc1"]["w"] == .5
    assert params["rz_cc1"]["l"] == 3.8
    directory = tmp_path / "phase3/analog/converter"
    text = a3.render_netlist(ir, ctx, [], params, deck_dir=directory)
    assert all(not line.lower().startswith("r") for line in text.splitlines() if not line.startswith("*"))
    (directory / "converter.sp").write_text(text)
    a3.emit_lvs_view(tmp_path, "converter")
    assert a3.validate_lvs_view(tmp_path, "converter").is_file()


@pytest.mark.parametrize("variant", ["default", "parent", "diode"])
def test_absent_option_preserves_previous_graph_and_source(tmp_path, variant):
    sizing = ({} if variant == "default" else
              diode.inputs(tmp_path) if variant == "diode" else folded.inputs(tmp_path))
    lib = copy.deepcopy(a2.LIBRARY["delta_sigma"])
    lib.pop("miller_nulling", None)
    lib["spec_knobs"] = [row for row in lib["spec_knobs"] if row["name"] not in (CAP, LENGTH)]
    for group in a2._stage_groups(lib):
        group.pop("miller_nulling", None)
    current = build(tmp_path, sizing)
    previous = build(tmp_path, sizing, lib)
    for ir in (current, previous):
        ir.pop("_provenance")
    assert current == previous
    ctx = folded._context(tmp_path)
    assert a3.render_netlist(current, ctx, [], a3._resolve_params(current, folded.SPEC)[0]) == a3.render_netlist(
        previous, ctx, [], a3._resolve_params(previous, folded.SPEC)[0])


@pytest.mark.parametrize("missing", [CAP, LENGTH])
def test_partial_pair_refuses(tmp_path, missing):
    sizing = inputs(tmp_path)
    del sizing["knobs"][missing]
    with pytest.raises(a2.SizingInputsInvalid, match="requires both"):
        build(tmp_path, sizing)


@pytest.mark.parametrize("value", [0, -1, True, "3.8", None, math.inf])
def test_invalid_length_refuses(tmp_path, value):
    sizing = inputs(tmp_path)
    sizing["knobs"][LENGTH] = value
    with pytest.raises(a2.SizingInputsInvalid, match="finite positive"):
        build(tmp_path, sizing)


def test_absolute_capacitance_does_not_hide_legacy_scale(tmp_path):
    sizing = inputs(tmp_path)
    sizing["knobs"]["ota_compensation_scale"] = 1.5
    with pytest.raises(a2.SizingInputsInvalid, match="conflict"):
        build(tmp_path, sizing)


@pytest.mark.parametrize("device,param", [("rz_cc1", "w"), ("rz_cc2", "l"), ("cc1", "w"), ("cc2", "l")])
def test_individual_geometry_cannot_break_typed_coupling(tmp_path, device, param):
    sizing = inputs(tmp_path)
    sizing["device_parameters"][device] = {param: 1}
    with pytest.raises(a2.SizingInputsInvalid, match="expression-owned"):
        build(tmp_path, sizing)


@pytest.mark.parametrize("kind", ["endpoint", "body", "resistor_geometry", "resistor_removed",
                                  "capacitor_removed", "coupling_expr", "record", "selector", "extra_midpoint_cap"])
def test_actual_a3_refuses_tampered_series_component(tmp_path, kind):
    ir = build(tmp_path, inputs(tmp_path))
    by_name = {d["name"]: d for d in ir["devices"]}
    resistor = by_name["rz_cc1"]
    cap = next(d for d in ir["devices"] if d["role"] == "cap" and "ncc1" in d["nets"])
    if kind == "endpoint":
        resistor["nets"][0] = "vdd"
    elif kind == "body":
        resistor["nets"][2] = "vdd"
    elif kind == "resistor_geometry":
        resistor["l"] *= 2
    elif kind == "resistor_removed":
        ir["devices"].remove(resistor)
    elif kind == "capacitor_removed":
        ir["devices"].remove(cap)
    elif kind == "coupling_expr":
        next(e for e in ir["device_param_exprs"] if e["device"] == cap["name"] and e["param"] == "l")["expr"] = "1"
    elif kind == "record":
        ir["miller_nulling"]["branches"][0]["body"] = "vdd"
    elif kind == "selector":
        ir["knobs"][CAP] *= 2
    else:
        extra = copy.deepcopy(cap)
        extra["name"] = "extra_compensation_cap"
        ir["devices"].append(extra)
    assert any("series Miller" in p for p in a3._validate_ir(ir, folded._context(tmp_path), tmp_path))


def test_repo_spec_drives_actual_paired_capacitances(tmp_path):
    ir = build(tmp_path, inputs(tmp_path), repo_spec=True)
    assert cap_total(ir, "cc1") == pytest.approx(3900)
    assert cap_total(ir, "cc2") == pytest.approx(3900)
