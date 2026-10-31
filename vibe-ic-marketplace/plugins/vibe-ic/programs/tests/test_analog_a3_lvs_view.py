"""Resolved SPICE stays unchanged while the normal producer emits its LVS view."""
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

import analog_a2_topology_emit as a2
import analog_a3_netlist_emit as a3
import analog_mos_geometry as mos
from _hostpaths import require_repo
from _pad_ring import assemble_lvs_top, parse_spice_subckts


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def resolved(tmp_path, monkeypatch):
    monkeypatch.setattr(mos, "discover_context", lambda *a, **k: {})
    monkeypatch.setattr(mos, "apply_fingers", lambda ir, overrides, geometry: (overrides, []))
    registry = json.loads(require_repo(
        "vibe-ic-marketplace/plugins/vibe-ic/programs/pdk_registry.json").read_text())
    entry = next(e for e in registry["pdks"] if e.get("device_map", {}).get("res_poly"))
    mapping = entry["device_map"]
    context = {"role_models": {"nmos": mapping["nmos_hv"], "pmos": mapping["pmos_hv"],
                              "res": mapping["res_poly"], "cap": mapping["cap_mim"]},
               "geometry_units": {r: "metric" for r in ("nmos", "pmos", "res", "cap")},
               "model_lib": "/simulation-only/corner.lib", "typ_section": "typ"}
    def make(kind="ldo", name="regulator_alpha"):
        ir = copy.deepcopy(a2.LIBRARY[kind])
        ir.update(block=name, block_type=kind)
        root = tmp_path / "project"
        directory = root / "phase3/analog" / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "topology.json").write_text(json.dumps(ir))
        simulation = directory / f"{name}.sp"
        simulation.write_text(a3.render_netlist(ir, context, [], {}, directory))
        return root, ir, simulation
    return make


@pytest.mark.parametrize("kind,name", [("ldo", "regulator_alpha"), ("delta_sigma", "modulator_beta")])
def test_retained_source_body_geometry_and_models_are_preserved(resolved, kind, name):
    root, ir, source = resolved(kind, name)
    before = source.read_bytes()
    record = a3.emit_lvs_view(root, name, expected_simulation_sha256=digest(source))
    view = a3.validate_lvs_view(root, name)
    assert source.read_bytes() == before
    assert ".lib " in source.read_text() and ".lib " not in view.read_text()
    assert ".include " not in view.read_text()
    sp_ports, sp_body = parse_spice_subckts(source.read_text())[name]
    cdl_ports, cdl_body = parse_spice_subckts(view.read_text())[name]
    assert cdl_ports == sp_ports == ir["ports"]
    assert len(cdl_body) == len(sp_body) == len(ir["devices"])
    for original, structural, device in zip(sp_body, cdl_body, ir["devices"]):
        assert original[1:] == structural[1:]  # every net/model/parameter token, including W/L/m/ng
        assert structural[0][1:] == original[0][1:]
        assert structural[0][0] == {"nmos": "M", "pmos": "M", "res": "R", "cap": "C"}[device["role"]]
    assert record["simulation_sha256"] == hashlib.sha256(before).hexdigest()
    assert record["view_sha256"] == digest(view)
    assert record["subcircuits"][name]["body"] == cdl_body


def test_normal_producer_emits_both_views_without_simulation_verification(tmp_path):
    from _analog_producer_fixture import A1, A2, A3, block, make_project, run_prog
    root = make_project(tmp_path, [block("regulator_alpha", "ldo", [
        {"name": "Vout", "target": 1.8, "unit": "V"},
        {"name": "Vin", "target": 3.0, "unit": "V"}])])
    assert run_prog(A1, root).returncode == 0
    assert run_prog(A2, root).returncode == 0
    result = run_prog(A3, root)
    assert result.returncode == 0, result.stdout + result.stderr
    source = root / "phase3/analog/regulator_alpha/regulator_alpha.sp"
    before = source.read_bytes()
    assert a3.validate_lvs_view(root, "regulator_alpha").is_file()
    assert run_prog(A3, root).returncode == 0
    assert source.read_bytes() == before
    assert a3.validate_lvs_view(root, "regulator_alpha").is_file()


@pytest.mark.parametrize("fault", ["removed_device", "wrong_geometry", "changed_net", "changed_port"])
def test_altered_view_refuses_even_with_rehashed_sidecar(resolved, fault):
    root, ir, source = resolved()
    a3.emit_lvs_view(root, ir["block"])
    view = a3.validate_lvs_view(root, ir["block"])
    lines = view.read_text().splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith("M"))
    if fault == "removed_device":
        del lines[index]
    elif fault == "wrong_geometry":
        lines[index] = lines[index].replace("w=2u", "w=22u")
        assert "w=22u" in lines[index]
    elif fault == "changed_net":
        tokens = lines[index].split();tokens[1] = "different_net";lines[index] = " ".join(tokens)
    else:
        index = next(i for i, line in enumerate(lines) if line.startswith(".subckt"))
        lines[index] += " different_port"
    view.write_text("\n".join(lines) + "\n")
    path = view.parent / "lvs_provenance.json"
    record = json.loads(path.read_text());record["view_sha256"] = digest(view)
    record["subcircuits"] = {name: {"ports": ports, "body": body}
        for name, (ports, body) in parse_spice_subckts(view.read_text(), preserve_parameters=True).items()}
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="LVS_VIEW_SOURCE_OR_BODY_CHANGED"):
        a3.validate_lvs_view(root, ir["block"])


def test_total_width_fingers_and_multiplicity_are_not_resolved_again(resolved):
    root, ir, source = resolved()
    text = source.read_text().replace("w=2u l=2u", "w=0.5u l=2u ng=4 m=3", 1)
    source.write_text(text)
    a3.emit_lvs_view(root, ir["block"])
    assert "w=0.5u l=2u ng=4 m=3" in a3.validate_lvs_view(root, ir["block"]).read_text()
    assert source.read_text() == text


def test_hierarchy_and_functional_child_body_are_preserved(resolved):
    root, ir, source = resolved()
    ir["devices"].append({"name": "functional", "role": "subcircuit", "nets": ["vin", "vout"]})
    (source.parent / "topology.json").write_text(json.dumps(ir))
    source.write_text(source.read_text().replace(".ends " + ir["block"],
        "xfunctional vin vout functional_leaf\n.ends " + ir["block"]) +
        "\n.subckt functional_leaf A B params: gain=2\nRkeep A B neutral_res R=500\n.ends functional_leaf\n")
    a3.emit_lvs_view(root, ir["block"])
    text = a3.validate_lvs_view(root, ir["block"]).read_text()
    assert "xfunctional vin vout functional_leaf" in text
    assert ".subckt functional_leaf A B params: gain=2" in text
    assert "Rkeep A B neutral_res R=500" in text


def test_sha_guard_refuses_changed_simulation_without_outputs(resolved):
    root, ir, source = resolved()
    original = digest(source);source.write_text(source.read_text() + "* changed\n")
    with pytest.raises(ValueError, match="LVS_SIMULATION_SHA_CHANGED"):
        a3.emit_lvs_view(root, ir["block"], expected_simulation_sha256=original)
    assert not (source.parent / (ir["block"] + ".lvs.cdl")).exists()


def test_lvs_only_cli_leaves_simulation_and_topology_bytes_unchanged(resolved):
    root, ir, source = resolved();topology = source.parent / "topology.json"
    before = (source.read_bytes(), topology.read_bytes())
    result = subprocess.run([sys.executable, a3.__file__, str(root), "--block", ir["block"],
        "--lvs-only", "--expected-simulation-sha256", digest(source)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (source.read_bytes(), topology.read_bytes()) == before
    assert a3.validate_lvs_view(root, ir["block"]).is_file()


def test_normal_top_assembly_selects_structural_views_for_multiple_blocks(resolved, tmp_path):
    root, ir_a, source_a = resolved()
    _, ir_b, source_b = resolved("delta_sigma", "modulator_beta")
    for ir in (ir_a, ir_b):a3.emit_lvs_view(root, ir["block"])
    destination = root / "top/top.cdl"
    instances = [["Xreg", *ir_a["ports"], ir_a["block"]], ["Xadc", *ir_b["ports"], ir_b["block"]]]
    result = assemble_lvs_top(root, destination, "complete_top", ["vin", "vss"],
                              instances, [ir_a["block"], ir_b["block"]], [])
    text = destination.read_text()
    assert str(source_a) not in text and str(source_b) not in text
    assert "regulator_alpha.lvs.cdl" in text and "modulator_beta.lvs.cdl" in text
    assert parse_spice_subckts(text)["complete_top"][1] == instances
    assert result["instances"] == instances
    bad = source_a.parent / (ir_a["block"] + ".lvs.cdl")
    bad.write_text(source_a.read_text())
    with pytest.raises(ValueError, match="LVS_VIEW_SOURCE_OR_BODY_CHANGED"):
        assemble_lvs_top(root, destination, "complete_top", [], instances,
                         [ir_a["block"], ir_b["block"]], [])


def test_global_and_functional_parameters_stay_in_the_structural_view(resolved):
    root, ir, source = resolved()
    source.write_text('.global common_body\n.param gain=2\n+ offset=0\n' + source.read_text())
    a3.emit_lvs_view(root, ir['block'])
    text = a3.validate_lvs_view(root, ir['block']).read_text()
    assert '.global common_body\n.param gain=2\n+ offset=0' in text


def test_duplicate_hierarchy_refuses_instead_of_dropping_a_body(resolved):
    root, ir, source = resolved()
    source.write_text(source.read_text() + source.read_text())
    with pytest.raises(ValueError, match='DUPLICATE_SPICE_SUBCIRCUIT'):
        a3.emit_lvs_view(root, ir['block'])


def test_provenance_inventory_is_validated(resolved):
    root, ir, source = resolved()
    a3.emit_lvs_view(root, ir['block'])
    path = source.parent / 'lvs_provenance.json'
    record = json.loads(path.read_text());record['subcircuits'][ir['block']]['body'].pop()
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match='LVS_VIEW_SOURCE_OR_BODY_CHANGED'):
        a3.validate_lvs_view(root, ir['block'])


def test_top_assembly_quotes_include_paths_with_spaces_and_hyphens(resolved):
    root, ir, source = resolved()
    a3.emit_lvs_view(root, ir['block'])
    library = root / 'vendor views-with-hyphens' / 'original.cdl'
    library.parent.mkdir()
    library.write_text('.subckt pad A B\nRbody A B neutral_res R=1\n.ends pad\n')
    target = root / 'top/top.cdl'
    assemble_lvs_top(root, target, 'parent', ['vin', 'vss'],
        [['Xcore', *ir['ports'], ir['block']], ['Xpad', 'vin', 'vss', 'pad']],
        [ir['block']], [library])
    includes = [line for line in target.read_text().splitlines() if line.startswith('.include')]
    assert includes == [f'.include "{source.parent / (ir["block"] + ".lvs.cdl")}"',
                        f'.include "{library}"']


@pytest.mark.parametrize("step", ["A12", "A18"])
def test_lvs_consumers_bind_structural_views_without_invalidating_sizing(resolved, step):
    import analog_native_flow as native

    root, ir, source = resolved()
    a3.emit_lvs_view(root, ir['block'])
    view = source.parent / (ir['block'] + '.lvs.cdl')
    provenance = source.parent / 'lvs_provenance.json'
    before = native._input_views(root, ir['block'], step)
    upstream = native._input_views(root, ir['block'], 'A05')
    assert before[str(view)] == digest(view)
    assert before[str(provenance)] == digest(provenance)
    assert str(view) not in upstream and str(provenance) not in upstream

    changed = view.read_text().replace(ir['ports'][0], 'changed_port')
    assert changed != view.read_text()
    view.write_text(changed)
    after_view = native._input_views(root, ir['block'], step)
    assert after_view[str(view)] != before[str(view)]
    assert native._input_views(root, ir['block'], 'A05') == upstream

    record = json.loads(provenance.read_text())
    record['view_sha256'] = '0' * 64
    provenance.write_text(json.dumps(record))
    assert native._input_views(root, ir['block'], step)[str(provenance)] != before[str(provenance)]
    assert native._input_views(root, ir['block'], 'A05') == upstream
