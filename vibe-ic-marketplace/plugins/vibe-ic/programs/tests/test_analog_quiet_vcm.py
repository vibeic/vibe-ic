from copy import deepcopy
import json
import re

import pytest

import analog_a2_topology_emit as a2
from _analog_producer_fixture import A2, A3, bdir, read_json, run_prog
from test_analog_ciff import _project


FIELDS = ("vcm_reference_cap_ff", "vcm_integrator_cap_ff")


def _case(tmp_path, rows, ciff=1):
    project = _project(tmp_path, order=2 if ciff == 0 else 3, ciff=ciff)
    directory = bdir(project, "mod_alpha")
    spec = read_json(directory / "spec.json")
    spec["specs"].extend(rows)
    (directory / "spec.json").write_text(json.dumps(spec))
    return project, directory, run_prog(A2, project)


def _rows(reference=900.0, integrator=2400.0):
    return [{"name": name, "target": value, "unit": "fF"}
            for name, value in zip(FIELDS, (reference, integrator))]


@pytest.mark.parametrize("ciff", [0, 1])
def test_declared_filter_connectivity_and_capacitance_reach_the_netlist(tmp_path, ciff):
    project, directory, result = _case(tmp_path, _rows(), ciff=ciff)
    assert result.returncode == 0, result.stdout + result.stderr
    ir = read_json(directory / "topology.json")
    devices = {device["name"]: device for device in ir["devices"]}
    assert len(devices) == len(ir["devices"])
    assert "vcm_buf" in ir["internal_nets"]
    assert devices["mn_cmfb"]["nets"] == ["nd1_cm", "vcm_buf", "ntail_cm", "vss"]
    assert devices["mp_cmo"]["nets"][:3] == ["vcm_buf", "nd2_cm", "vdd"]
    assert devices["mn_cmo"]["nets"][0] == "vcm_buf"
    compensation = [device for name, device in devices.items()
                    if name == "c_cmc" or name.startswith("c_cmc_u")]
    assert compensation
    assert all(device["nets"] == ["nd2_cm", "vcm_buf"] for device in compensation)
    assert devices["r_vcm_iso"]["nets"] == ["vcm_buf", "vcm", "vss"]
    assert devices["r_vcm_iso"]["w"] == .5
    assert devices["r_vcm_iso"]["l"] == 12.
    assert run_prog(A3, project).returncode == 0
    text = (directory / "mod_alpha.sp").read_text()
    params = ir["pdk_measured_params"]
    for base, nodes, requested in [("c_vcm_ref", ["nvcmr", "vss"], 900.),
                                   ("c_vcm_int", ["vcm", "vss"], 2400.)]:
        cards = [line for line in text.splitlines()
                 if re.match(r"x" + base + r"(?:_u\d+)?\s", line)]
        assert cards, base
        total = 0.
        for card in cards:
            assert card.split()[1:3] == nodes
            width = float(re.search(r"\bw=([0-9.eE+-]+)", card)[1])
            length = float(re.search(r"\bl=([0-9.eE+-]+)", card)[1])
            total += (params["cap_area_ff_per_um2"] * width * length
                      + 2 * params.get("cap_perim_ff_per_um", 0) * (width + length))
        assert total == pytest.approx(requested, rel=1e-5)


def test_undeclared_filter_keeps_existing_common_mode_connections(tmp_path):
    _, directory, result = _case(tmp_path, [])
    assert result.returncode == 0, result.stdout + result.stderr
    ir = read_json(directory / "topology.json")
    devices = {device["name"]: device for device in ir["devices"]}
    assert "vcm_buf" not in ir["internal_nets"]
    assert "r_vcm_iso" not in devices
    assert not any(name.startswith(("c_vcm_ref", "c_vcm_int")) for name in devices)
    assert devices["mn_cmfb"]["nets"] == ["nd1_cm", "vcm", "ntail_cm", "vss"]
    assert devices["mp_cmo"]["nets"][0] == "vcm"


def test_library_selection_does_not_change_the_global_default():
    original = deepcopy(a2.LIBRARY["delta_sigma"])
    selected = a2.ciff_library(a2.LIBRARY["delta_sigma"], dict(zip(FIELDS, (900., 2400.))))
    assert any(device["name"] == "r_vcm_iso" for device in selected["devices"])
    assert a2.LIBRARY["delta_sigma"] == original
    assert not any(device["name"] == "r_vcm_iso"
                   for device in a2.ciff_library(a2.LIBRARY["delta_sigma"], {})["devices"])


@pytest.mark.parametrize("missing", FIELDS)
def test_partial_filter_declaration_is_refused(tmp_path, missing):
    _, directory, result = _case(tmp_path, [row for row in _rows() if row["name"] != missing])
    assert result.returncode != 0
    gap = read_json(directory / "topology_gap.json")
    assert missing in json.dumps(gap)
    assert not (directory / "topology.json").exists()


@pytest.mark.parametrize("value", [True, "900", None, 0., -1., float("nan"), float("inf")])
def test_filter_values_must_be_positive_finite_numbers(tmp_path, value):
    _, directory, result = _case(tmp_path, _rows(reference=value))
    assert result.returncode != 0
    assert FIELDS[0] in json.dumps(read_json(directory / "topology_gap.json"))
    assert not (directory / "topology.json").exists()


@pytest.mark.parametrize("unit", ["pF", "V", ""])
def test_filter_capacitance_units_are_not_silently_reinterpreted(tmp_path, unit):
    rows = _rows()
    rows[0]["unit"] = unit
    _, directory, result = _case(tmp_path, rows)
    assert result.returncode != 0
    assert FIELDS[0] in json.dumps(read_json(directory / "topology_gap.json"))


def test_invalid_rows_cannot_disappear_into_the_undeclared_default(tmp_path):
    rows = _rows(True, "2400")
    for row in rows:
        del row["unit"]
    _, directory, result = _case(tmp_path, rows)
    assert result.returncode != 0
    assert not (directory / "topology.json").exists()


def test_duplicate_filter_fields_are_refused(tmp_path):
    _, directory, result = _case(tmp_path, _rows() + [_rows()[0]])
    assert result.returncode != 0
    assert FIELDS[0] in json.dumps(read_json(directory / "topology_gap.json"))


def test_untyped_target_cannot_fall_back_to_a_numeric_minimum(tmp_path):
    rows = _rows(reference="900")
    rows[0]["min"] = 900.
    _, directory, result = _case(tmp_path, rows)
    assert result.returncode != 0
    assert FIELDS[0] in json.dumps(read_json(directory / "topology_gap.json"))
