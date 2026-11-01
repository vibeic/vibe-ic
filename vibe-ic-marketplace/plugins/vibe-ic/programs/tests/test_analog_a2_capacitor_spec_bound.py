"""A declared capacitance reaches a two-terminal PDK capacitor netlist."""
from __future__ import annotations

import pytest

from _analog_producer_fixture import (
    A1, A2, A3, GATE_A2, bdir, block, make_project, read_json, run_prog,
    stage_custom_pdk,
)

BLK = "storage_alpha"
PDK = "ihp-sg13g2"


def _project(tmp_path, value=25000.0, unit="fF", missing=False):
    rows = ([{"name": "Vdd", "target": 1.2, "unit": "V"}]
            if missing else [])
    if not missing:
        rows.append({"name": "Capacitance", "target": value, "unit": unit,
                     "min": 0.9 * value, "max": 1.1 * value})
    entry = block(BLK, "capacitor", rows)
    entry["pins"] = [{"name": "TOP"}, {"name": "VSS"}]
    root = make_project(tmp_path, [entry])
    stage_custom_pdk(root, PDK)
    result = run_prog(A1, root)
    assert result.returncode == 0, result.stderr
    return root, bdir(root, BLK)


def test_a1_preserves_the_capacitor_value_unit_range_and_declared_pins(tmp_path):
    root, d = _project(tmp_path)
    spec = read_json(d / "spec.json")
    row = next(s for s in spec["specs"] if s["name"] == "capacitance")
    assert row["target"] == 25000.0
    assert row["unit"] == "fF"
    assert (row["min"], row["max"]) == pytest.approx((22500.0, 27500.0))
    assert [p["name"] for p in spec["interface"]["pins"]] == ["TOP", "VSS"]

    unrelated = make_project(tmp_path / "unrelated", [block(
        "amp_alpha", "ldo", [{"name": "Capacitance", "target": 25000,
                                "unit": "fF"},
                               {"name": "Vout", "target": 1.2, "unit": "V"}])])
    result = run_prog(A1, unrelated)
    assert result.returncode == 0, result.stderr
    other = read_json(bdir(unrelated, "amp_alpha") / "spec.json")
    assert {r["name"] for r in other["specs"]} == {"vout"}


@pytest.mark.parametrize("value", [100.0, 25000.0])
def test_bound_capacitance_survives_legal_geometry_and_a3_rendering(tmp_path,
                                                                  value):
    root, d = _project(tmp_path, value)
    result = run_prog(A2, root, "--pdk", PDK)
    assert result.returncode == 0, result.stderr
    assert run_prog(GATE_A2, root).returncode == 0
    ir = read_json(d / "topology.json")
    assert ir["ports"] == ["TOP", "VSS"]
    assert ir["internal_nets"] == []
    assert ir["devices"]
    assert all(dev["role"] == "cap" and dev["nets"] == ["TOP", "VSS"]
               for dev in ir["devices"])
    assert not (d / "topology_gap.json").exists()

    result = run_prog(A3, root, "--pdk", PDK)
    assert result.returncode == 0, result.stderr
    deck = (d / f"{BLK}.sp").read_text()
    assert f".subckt {BLK} TOP VSS" in deck
    instances = [line.split() for line in deck.splitlines()
                 if line.lower().startswith("x")]
    assert len(instances) == len(ir["devices"])
    measured = ir["pdk_measured_params"]
    area = measured["cap_area_ff_per_um2"]
    perimeter = measured.get("cap_perim_ff_per_um", 0.0)
    total = 0.0
    for instance in instances:
        assert instance[1:3] == ["TOP", "VSS"]
        assert instance[3] == "stg_cap_x_dev"
        params = dict(p.split("=", 1) for p in instance[4:] if "=" in p)
        w, l = (float(params[p].rstrip("u")) for p in ("w", "l"))
        assert 2.0 <= w <= 30.0 and 2.0 <= l <= 30.0
        total += area * w * l + 2 * perimeter * (w + l)
    assert total == pytest.approx(value, rel=1e-5)
    assert (len(instances) > 1) == (value == 25000.0)
    prov = read_json(d / "netlist_provenance.json")["_provenance"]
    assert prov["design_content"] == "structure_and_geometry"
    assert prov["spec_bound_params"]
    tb = (d / f"tb_{BLK}.sp").read_text()
    assert "v_vdd TOP 0 DC 0" in tb and "AC 1" in tb
    assert "ac lin 1 1e6 1e6" in tb
    assert "-imag(i(v_vdd))/(2*pi*frequency)*1e15" in tb
    assert 'echo "MEAS capacitance_ff=" $&c_measured' in tb


@pytest.mark.parametrize("value,unit,missing,requirement", [
    (25000.0, "fF", True, "spec_bound"),
    (25.0, "pF", False, "spec_unit"),
    (0.0, "fF", False, "derived_unresolvable"),
    (-1.0, "fF", False, "derived_range"),
    (float("nan"), "fF", False, "spec_finite"),
    (float("inf"), "fF", False, "spec_finite"),
    (-float("inf"), "fF", False, "spec_finite"),
])
def test_invalid_capacitance_refuses_without_emitting_topology(
        tmp_path, value, unit, missing, requirement):
    root, d = _project(tmp_path, value, unit, missing)
    result = run_prog(A2, root, "--pdk", PDK)
    assert result.returncode == 2, (result.stdout, result.stderr)
    gap = read_json(d / "topology_gap.json")
    assert any(r["requirement"] == requirement
               for r in gap["admission_refusals"]), gap
    assert not (d / "topology.json").exists()
    assert not (d / "topology.md").exists()
    assert not list(root.rglob("*.sp"))
