"""A3 checks source-bound drawing dimensions before either view is emitted."""
import copy
import hashlib
import json

import pytest

import analog_a3_netlist_emit as a3
import analog_mos_geometry as mos


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture
def case(tmp_path, monkeypatch):
    grid = tmp_path / "selected.tlef"
    grid.write_text("MANUFACTURINGGRID 0.005 ;\n")
    recipe = tmp_path / "selected-resistor.tcl"
    recipe.write_text("set hl [/ $l 2.0]\nbox grow n ${hl}um\nbox grow s ${hl}um\n")
    ir = {"block": "divider", "block_type": "passive", "topology": "divider",
          "ports": ["out", "fb", "vss"], "devices": [
              {"name": "upper", "role": "res", "nets": ["out", "fb", "vss"],
               "w": 0.5, "l": 76.92}]}
    ctx = {"role_models": {"res": "selected_poly"}, "geometry_units": {"res": "metric"},
           "model_lib": "simulation.lib", "geometry_admission": {
               "grid_source": str(grid), "sources": {str(grid): digest(grid), str(recipe): digest(recipe)},
               "models": {"selected_poly": {"w": 2, "l": 2}}}}
    monkeypatch.setattr(mos, "discover_context", lambda *a, **k: {})
    monkeypatch.setattr(mos, "apply_fingers", lambda ir, values, ctx: (values, []))
    return ir, ctx, recipe


def test_normal_render_and_structural_view_share_admitted_dimensions(case, tmp_path):
    ir, ctx, _ = case
    before = copy.deepcopy(ir)
    directory = tmp_path / "phase3/analog/divider"
    directory.mkdir(parents=True)
    (directory / "topology.json").write_text(json.dumps(ir))
    text = a3.render_netlist(ir, ctx, [], {}, directory)
    assert "w=0.5u l=76.92u" in text
    (directory / "divider.sp").write_text(text)
    a3.emit_lvs_view(tmp_path, "divider")
    view = a3.validate_lvs_view(tmp_path, "divider").read_text()
    assert "Rupper out fb vss selected_poly w=0.5u l=76.92u" in view
    assert ir == before and (directory / "divider.sp").read_text() == text
    assert a3.resolve_admitted_geometry(ir, ctx, {})[1]["devices"][0]["dimensions_um"] == {"w": 0.5, "l": 76.92}


@pytest.mark.parametrize("values", [{"l": 76.9228}, {"l": 153.846}, {"l": 76.925}, {"w": 0.505}])
def test_off_grid_and_half_dimension_grid_resolve_before_both_views(case, values):
    ir, ctx, _ = case
    before = copy.deepcopy(ir)
    effective, record = a3.resolve_admitted_geometry(ir, ctx, {"upper": values})
    text = a3.render_netlist(ir, ctx, [], {"upper": values})
    assert ir == before
    assert record["status"] == "ADMITTED"
    assert effective["upper"] != values
    assert all(str(v) + "u" not in text for v in values.values())


def test_changed_pdk_source_refuses_even_on_grid(case):
    ir, ctx, recipe = case
    recipe.write_text("changed PDK recipe")
    with pytest.raises(ValueError, match="GEOMETRY_ADMISSION_SOURCE_CHANGED"):
        a3.render_netlist(ir, ctx, [], {})


def test_missing_unbound_and_unreadable_grid_do_not_admit(case):
    ir, ctx, _ = case
    evidence = ctx["geometry_admission"]
    grid_path = evidence["grid_source"]
    del evidence["sources"][grid_path]
    with pytest.raises(ValueError, match="GRID_UNBOUND"):
        a3.resolve_admitted_geometry(ir, ctx, {})[1]


def test_absent_context_is_explicitly_unmeasured_and_retained_source_is_unchanged(case):
    ir, ctx, _ = case
    del ctx["geometry_admission"]
    assert a3.resolve_admitted_geometry(ir, ctx, {})[1] == {"status": "NOT_MEASURED", "devices": []}
    ir["devices"][0]["l"] = 76.9228
    assert "l=76.9228u" in a3.render_netlist(ir, ctx, [], {})


def test_evaluation_noise_resolves_to_the_same_legal_dimension(case):
    ir, ctx, _ = case
    overrides = {"upper": {"l": 0.1 + 0.2}}
    assert a3.resolve_admitted_geometry(ir, ctx, overrides)[1]["devices"][0]["dimensions_um"]["l"] == 0.3


@pytest.mark.parametrize("width,count,total,finger", [(512.,52,512.2,9.85),(28.,3,27.99,9.33)])
def test_total_mos_width_follows_admitted_finger_width_without_changing_count(case,width,count,total,finger):
    ir,ctx,_=case
    ir["devices"][0].update(role="pmos",w=width,ng=count,l=0.5)
    ctx["role_models"]["pmos"]="selected_poly"
    effective,record=a3.resolve_admitted_geometry(ir,ctx,{})
    assert effective["upper"]["w"]==total
    assert record["devices"][0]["finger_width_um"]==finger
    assert ir["devices"][0]["ng"]==count
    again,_=a3.resolve_admitted_geometry(ir,ctx,effective)
    assert again==effective


def test_any_uncovered_model_refuses_instead_of_partial_admission(case):
    ir,ctx,_=case
    ctx["geometry_admission"]["models"]={}
    with pytest.raises(ValueError,match="MODEL_UNBOUND"):
        a3.resolve_admitted_geometry(ir,ctx,{})


@pytest.mark.parametrize("parameter,value",[("w",True),("w",float("inf")),("l",0)])
def test_invalid_or_zero_dimensions_refuse(case,parameter,value):
    ir,ctx,_=case
    with pytest.raises(ValueError,match="INVALID_DIMENSION"):
        a3.resolve_admitted_geometry(ir,ctx,{"upper":{parameter:value}})
