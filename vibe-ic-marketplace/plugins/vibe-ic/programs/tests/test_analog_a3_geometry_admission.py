"""A3 checks source-bound drawing dimensions before either view is emitted."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

import analog_a3_netlist_emit as a3
import analog_mos_geometry as mos


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture
def case(tmp_path, monkeypatch):
    proof = tmp_path / "input/proof"
    proof.mkdir(parents=True)
    grid = proof / "selected.tlef"
    grid.write_text("MANUFACTURINGGRID 0.005 ;\n")
    recipe = proof / "selected-resistor.tcl"
    recipe.write_text("set hl [/ $l 2.0]\nbox grow n ${hl}um\nbox grow s ${hl}um\n")
    ir = {"block": "divider", "block_type": "passive", "topology": "divider",
          "ports": ["out", "fb", "vss"], "devices": [
              {"name": "upper", "role": "res", "nets": ["out", "fb", "vss"],
               "w": 0.5, "l": 76.92}]}
    ctx = {"role_models": {"res": "selected_poly"}, "geometry_units": {"res": "metric"},
           "model_lib": "simulation.lib", "geometry_admission_project": tmp_path,
           "geometry_admission": {
               "version": 2, "grid_source": "case:input/proof/selected.tlef",
               "sources": {"case:input/proof/selected.tlef": digest(grid),
                           "case:input/proof/selected-resistor.tcl": digest(recipe)},
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


def admission_result(ir, ctx):
    try:
        return a3.resolve_admitted_geometry(ir, ctx, {})[1]
    except ValueError as exc:
        return {"status": "REFUSED", "reason": str(exc)}


def test_portable_case_sources_survive_relocation_after_original_is_deleted(case, tmp_path):
    ir, ctx, _ = case
    moved = tmp_path.parent / (tmp_path.name + "-moved")
    shutil.copytree(tmp_path, moved)
    shutil.rmtree(tmp_path)
    ctx["geometry_admission_project"] = moved
    record = admission_result(ir, ctx)
    assert record.get("status") == "ADMITTED", record
    assert record["devices"][0]["dimensions_um"] == {"w": 0.5, "l": 76.92}
    assert record["sources"] == ctx["geometry_admission"]["sources"]
    assert str(tmp_path) not in json.dumps(record) and str(moved) not in json.dumps(record)


def use_installed_grid(ctx, tmp_path):
    root = tmp_path / "installed-pdk"
    grid = root / "technology/selected.tlef"
    grid.parent.mkdir(parents=True)
    grid.write_bytes(b"MANUFACTURINGGRID 0.005 ;\r\n# exact bytes \xff\n")
    evidence = ctx["geometry_admission"]
    del evidence["sources"][evidence["grid_source"]]
    evidence["grid_source"] = "pdk:technology/selected.tlef"
    evidence["sources"][evidence["grid_source"]] = digest(grid)
    ctx["installed_pdk_root"] = str(root)
    return root, grid


def test_identical_selected_installed_pdk_can_move(case, tmp_path):
    ir, ctx, _ = case
    root, _ = use_installed_grid(ctx, tmp_path)
    moved = tmp_path / "another-installation"
    root.rename(moved)
    ctx["installed_pdk_root"] = str(moved)
    record = admission_result(ir, ctx)
    assert record.get("status") == "ADMITTED", record
    assert record["grid_um"] == 0.005
    assert set(record["sources"]) == {"case:input/proof/selected-resistor.tcl",
                                      "pdk:technology/selected.tlef"}


def test_portable_keys_resolve_against_runtime_roots(case):
    ir, ctx, _ = case
    record = admission_result(ir, ctx)
    assert record.get("status") == "ADMITTED", record
    assert record["devices"][0]["dimensions_um"] == {"w": 0.5, "l": 76.92}


def test_repository_technology_source_stays_bound_after_case_relocation(case, tmp_path):
    from _hostpaths import require_repo

    ir, ctx, recipe = case
    source = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
                          "fixtures", "flow109_density_fill", "tech.lef")
    grid = recipe.with_name("selected.tlef")
    grid.write_bytes(source.read_bytes())
    evidence = ctx["geometry_admission"]
    evidence["sources"][evidence["grid_source"]] = digest(grid)
    moved = tmp_path.parent / (tmp_path.name + "-portable")
    tmp_path.rename(moved)
    ctx["geometry_admission_project"] = moved
    record = admission_result(ir, ctx)
    assert record.get("status") == "ADMITTED", record
    assert record["grid_um"] == 0.001
    assert record["devices"][0]["dimensions_um"] == {"w": 0.5, "l": 76.92}


def test_changed_selected_installed_pdk_refuses_even_on_grid(case, tmp_path):
    ir, ctx, _ = case
    _, grid = use_installed_grid(ctx, tmp_path)
    grid.write_bytes(grid.read_bytes() + b"# changed\n")
    with pytest.raises(ValueError, match="GEOMETRY_ADMISSION_SOURCE_CHANGED: pdk:"):
        a3.resolve_admitted_geometry(ir, ctx, {})


@pytest.mark.parametrize("escape", [False, True])
def test_container_source_reader_checks_raw_bytes_and_containment(case, tmp_path, monkeypatch, escape):
    import analog_geometry_admission as admission

    ir, ctx, _ = case
    root, grid = use_installed_grid(ctx, tmp_path)
    ctx["container"] = "selected-container"
    if escape:
        outside = tmp_path / "outside.tlef"
        grid.rename(outside)
        grid.symlink_to(outside)
    entered = []

    def local_container(container, *arguments):
        entered.append((container, arguments[-2:]))
        return list(arguments)

    monkeypatch.setattr(admission._ce, "no_container_route", lambda: False)
    monkeypatch.setattr(admission._ce, "docker_exec_argv", local_container)
    if escape:
        with pytest.raises(ValueError, match="SOURCE_CHANGED: pdk:technology/selected.tlef"):
            a3.resolve_admitted_geometry(ir, ctx, {})
    else:
        assert a3.resolve_admitted_geometry(ir, ctx, {})[1]["grid_um"] == 0.005
    assert entered == [("selected-container", (str(root), "technology/selected.tlef"))]


def test_inside_container_reads_selected_pdk_locally(case, tmp_path, monkeypatch):
    import analog_geometry_admission as admission

    ir, ctx, _ = case
    use_installed_grid(ctx, tmp_path)
    ctx["container"] = "runtime-container"
    monkeypatch.setattr(admission._ce, "no_container_route", lambda: True)

    def no_nested_docker(*args, **kwargs):
        pytest.fail("no-container route must read selected PDK locally")

    monkeypatch.setattr(admission._ce, "docker_exec_argv", no_nested_docker)
    assert a3.resolve_admitted_geometry(ir, ctx, {})[1]["status"] == "ADMITTED"


def use_selected_pdk_wrapper(ctx, tmp_path):
    selected = tmp_path / "physical/family"
    grid = selected / "libs.ref/cells/selected.tlef"
    recipe = selected / "libs.tech/layout/selected.tcl"
    grid.parent.mkdir(parents=True)
    recipe.parent.mkdir(parents=True)
    grid.write_bytes(b"MANUFACTURINGGRID 0.005 ;\r\n# exact bytes \xff\n")
    recipe.write_bytes(b"selected drawing recipe\n")
    logical = tmp_path / "installed/family"
    logical.mkdir(parents=True)
    for name in ("libs.tech", "libs.ref"):
        (logical / name).symlink_to(selected / name, target_is_directory=True)
    evidence = ctx["geometry_admission"]
    evidence["grid_source"] = "pdk:libs.ref/cells/selected.tlef"
    evidence["sources"] = {evidence["grid_source"]: digest(grid),
                           "pdk:libs.tech/layout/selected.tcl": digest(recipe)}
    ctx["installed_pdk_root"] = str(logical)
    return logical, selected, grid


def selected_reader_route(ctx, monkeypatch, route):
    import analog_geometry_admission as admission

    ctx["container"] = "selected-container"
    monkeypatch.setattr(admission._ce, "no_container_route", lambda: route == "local")
    entered = []

    def local_container(container, *arguments):
        entered.append(container)
        return list(arguments)

    monkeypatch.setattr(admission._ce, "docker_exec_argv", local_container)
    return entered


@pytest.mark.parametrize("route", ["local", "container"])
@pytest.mark.parametrize("root_kind", ["logical", "canonical"])
def test_selected_pdk_wrapper_admits_same_physical_family(case, tmp_path, monkeypatch, route, root_kind):
    ir, ctx, _ = case
    _, selected, _ = use_selected_pdk_wrapper(ctx, tmp_path)
    if root_kind == "canonical":
        ctx["installed_pdk_root"] = str(selected)
    entered = selected_reader_route(ctx, monkeypatch, route)
    before = copy.deepcopy(ctx)
    record = admission_result(ir, ctx)
    assert record.get("status") == "ADMITTED", record
    assert record["grid_um"] == 0.005
    assert record["sources"] == ctx["geometry_admission"]["sources"]
    assert ctx == before
    assert entered == (["selected-container"] * 2 if route == "container" else [])


@pytest.mark.parametrize("route", ["local", "container"])
@pytest.mark.parametrize("problem", ["changed-bytes", "escaped-source", "wrong-family", "wrong-tech-name"])
def test_selected_pdk_wrapper_keeps_source_and_root_boundaries(case, tmp_path, monkeypatch, route, problem):
    ir, ctx, _ = case
    logical, selected, grid = use_selected_pdk_wrapper(ctx, tmp_path)
    selected_reader_route(ctx, monkeypatch, route)
    if problem == "changed-bytes":
        grid.write_bytes(grid.read_bytes() + b"changed\n")
    elif problem == "escaped-source":
        outside = tmp_path / "outside.tlef"
        grid.rename(outside)
        grid.symlink_to(outside)
    else:
        technology = logical / "libs.tech"
        technology.unlink()
        target = (tmp_path / "other/family/technology" if problem == "wrong-tech-name"
                  else tmp_path / "other/different-family/libs.tech")
        target.mkdir(parents=True)
        technology.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="GEOMETRY_ADMISSION_SOURCE_CHANGED: pdk:"):
        a3.resolve_admitted_geometry(ir, ctx, {})


@pytest.mark.parametrize("key", ["/absolute/proof.tlef", "case:/absolute", "case:../escape",
                                  "case:input/../proof", "case:./proof", "case:input//proof",
                                  "case:", "case:input/", "other:input/proof", "case:input\\proof",
                                  "case:input:proof"])
def test_invalid_portable_source_keys_refuse(case, key):
    ir, ctx, _ = case
    evidence = ctx["geometry_admission"]
    evidence["sources"] = {key: "a" * 64}
    evidence["grid_source"] = key
    with pytest.raises(ValueError, match="GEOMETRY_ADMISSION_(INVALID_SOURCE|LEGACY_ABSOLUTE)"):
        a3.resolve_admitted_geometry(ir, ctx, {})


@pytest.mark.parametrize("expected", ["0" * 63, "G" * 64, None, True])
def test_malformed_source_digest_refuses(case, expected):
    ir, ctx, _ = case
    evidence = ctx["geometry_admission"]
    evidence["sources"][evidence["grid_source"]] = expected
    with pytest.raises(ValueError, match="GEOMETRY_ADMISSION_INVALID_HASH"):
        a3.resolve_admitted_geometry(ir, ctx, {})


@pytest.mark.parametrize("source_kind", ["missing", "directory", "symlink"])
def test_nonregular_or_escaping_case_source_refuses(case, tmp_path, source_kind):
    ir, ctx, recipe = case
    original = recipe.read_bytes()
    recipe.unlink()
    if source_kind == "directory":
        recipe.mkdir()
    elif source_kind == "symlink":
        outside = tmp_path.parent / (tmp_path.name + "-outside")
        outside.write_bytes(original)
        recipe.symlink_to(outside)
    with pytest.raises(ValueError, match="GEOMETRY_ADMISSION_SOURCE_CHANGED: case:"):
        a3.resolve_admitted_geometry(ir, ctx, {})


def test_supplied_admission_requires_runtime_case_root(case):
    ir, ctx, _ = case
    del ctx["geometry_admission_project"]
    with pytest.raises(ValueError, match="GEOMETRY_ADMISSION_RUNTIME_ROOT_MISSING: case"):
        a3.render_netlist(ir, ctx, [], {})


def test_legacy_absolute_admission_requires_explicit_regeneration(case):
    ir, ctx, recipe = case
    grid = recipe.with_name("selected.tlef")
    ctx["geometry_admission"] = {"grid_source": str(grid),
                                "sources": {str(grid): digest(grid), str(recipe): digest(recipe)},
                                "models": {"selected_poly": {"w": 2, "l": 2}}}
    record = admission_result(ir, ctx)
    assert record.get("status") == "REFUSED", record
    assert "GEOMETRY_ADMISSION_LEGACY_ABSOLUTE" in record["reason"]


def test_resolved_context_retains_selected_pdk_runtime_root(tmp_path, monkeypatch):
    import analog_pdk_availability as availability
    import analog_pdk_deck_context as decks

    selected = {"pdk_root": "/selected/canonical/tree", "installed_pdk_root": "/install/logical"}
    monkeypatch.setattr(availability, "resolve_pdk", lambda *a, **kw: selected)
    monkeypatch.setattr(decks, "resolve_deck_context", lambda *a, **kw: SimpleNamespace(
        as_json=lambda: {"status": "OK", "family": "portable_test", "device_map": {"res": "selected_poly"}}))
    ctx = a3.resolve_pdk_context(tmp_path, "portable_test", "selected-container", ["res"])
    assert ctx.get("installed_pdk_root") == "/selected/canonical/tree"
    assert ctx["container"] == "selected-container"


def run_migration(project, pdk_root, legacy, mappings, output=None):
    command = [sys.executable, str(Path(a3.__file__).with_name("analog_geometry_admission.py")),
               "--project", str(project), "--pdk-root", str(pdk_root), "--input", str(legacy)]
    for mapping in mappings:
        command += ["--map-source", mapping]
    if output is not None:
        command += ["--output", str(output)]
    return subprocess.run(command, capture_output=True, text=True, timeout=30)


def legacy_input(case, tmp_path):
    ir, ctx, recipe = case
    _, grid = use_installed_grid(ctx, tmp_path)
    old_grid, old_recipe = "/old/install/selected.tlef", "/old/case/selected-resistor.tcl"
    legacy = {"grid_source": old_grid,
              "sources": {old_grid: digest(grid), old_recipe: digest(recipe)},
              "models": copy.deepcopy(ctx["geometry_admission"]["models"]),
              "basis": "source-bound drawing steps", "native_probe_cid": "full-container-identity"}
    legacy_path = tmp_path / "legacy.json"
    legacy_path.write_text(json.dumps(legacy))
    mappings = [old_grid + "=pdk:technology/selected.tlef",
                old_recipe + "=case:input/proof/selected-resistor.tcl"]
    return ir, ctx, legacy_path, legacy, mappings


def test_cli_migration_preserves_hashes_models_and_metadata(case, tmp_path):
    ir, ctx, legacy_path, legacy, mappings = legacy_input(case, tmp_path)
    before = legacy_path.read_bytes()
    result = run_migration(tmp_path, ctx["installed_pdk_root"], legacy_path, mappings)
    assert result.returncode == 0, result.stdout + result.stderr
    produced = json.loads((tmp_path / "input/analog_geometry_admission.json").read_text())
    assert produced == {"version": 2, "grid_source": "pdk:technology/selected.tlef",
                        "sources": ctx["geometry_admission"]["sources"],
                        "models": legacy["models"], "basis": legacy["basis"],
                        "native_probe_cid": legacy["native_probe_cid"]}
    assert legacy_path.read_bytes() == before
    ctx["geometry_admission"] = produced
    assert a3.resolve_admitted_geometry(ir, ctx, {})[1]["status"] == "ADMITTED"
    assert str(tmp_path) not in json.dumps(produced) and "/old/" not in json.dumps(produced)


@pytest.mark.parametrize("problem", ["changed-case", "changed-pdk", "unmapped", "duplicate-key",
                                     "duplicate-target", "traversal", "bad-model", "unknown-version"])
def test_cli_migration_refuses_before_replacing_destination(case, tmp_path, problem):
    _, ctx, legacy_path, legacy, mappings = legacy_input(case, tmp_path)
    if problem == "changed-case":
        (tmp_path / "input/proof/selected-resistor.tcl").write_bytes(b"changed")
    elif problem == "changed-pdk":
        (Path(ctx["installed_pdk_root"]) / "technology/selected.tlef").write_bytes(b"changed")
    elif problem == "unmapped":
        mappings.pop()
    elif problem == "duplicate-key":
        legacy_path.write_text('{"models": {},' + json.dumps(legacy)[1:])
    elif problem == "duplicate-target":
        mappings[1] = mappings[1].split("=", 1)[0] + "=pdk:technology/selected.tlef"
    elif problem == "traversal":
        mappings[1] = mappings[1].split("=", 1)[0] + "=case:../escape"
    elif problem == "bad-model":
        legacy["models"]["selected_poly"]["w"] = True
        legacy_path.write_text(json.dumps(legacy))
    else:
        legacy["version"] = 99
        legacy_path.write_text(json.dumps(legacy))
    destination = tmp_path / "input/analog_geometry_admission.json"
    destination.write_bytes(b"retained evidence\n")
    result = run_migration(tmp_path, ctx["installed_pdk_root"], legacy_path, mappings)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "GEOMETRY_ADMISSION_" in result.stdout + result.stderr
    if problem.startswith("changed"):
        assert "SOURCE_CHANGED" in result.stdout + result.stderr
    assert destination.read_bytes() == b"retained evidence\n"


def test_cli_output_cannot_escape_project(case, tmp_path):
    _, ctx, legacy_path, _, mappings = legacy_input(case, tmp_path)
    output = tmp_path.parent / (tmp_path.name + "-outside.json")
    output.write_bytes(b"retained outside project\n")
    result = run_migration(tmp_path, ctx["installed_pdk_root"], legacy_path, mappings, output)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "GEOMETRY_ADMISSION_OUTPUT_OUTSIDE_PROJECT" in result.stdout + result.stderr
    assert output.read_bytes() == b"retained outside project\n"


def prepare_emission(case, tmp_path, monkeypatch):
    ir, ctx, _ = case
    directory = tmp_path / "phase3/analog/divider"
    directory.mkdir(parents=True)
    (directory / "topology.json").write_text(json.dumps(ir))
    (directory / "spec.json").write_text('{"required": true}')
    (tmp_path / "input/analog_geometry_admission.json").write_text(json.dumps(ctx.pop("geometry_admission")))
    ctx.pop("geometry_admission_project")
    ctx["status"] = "OK"
    monkeypatch.setattr(a3, "resolve_pdk_context", lambda *a, **kw: ctx)
    monkeypatch.setattr(a3, "spec_values", lambda spec: {"length": 76.92})
    monkeypatch.setattr(a3, "_validate_ir", lambda *a: [])
    monkeypatch.setattr(a3, "_resolve_params", lambda *a: ({}, [], [], {}))
    return directory


def test_emitter_rechecks_sources_and_refuses_before_netlist_publication(case, tmp_path, monkeypatch):
    _, _, recipe = case
    directory = prepare_emission(case, tmp_path, monkeypatch)

    def mutate_after_first_check(*args):
        recipe.write_bytes(b"changed between early check and rendering")
        return []

    monkeypatch.setattr(a3, "bound_geometry_limit_violations", mutate_after_first_check)
    record = a3.emit_for_block(tmp_path, {"name": "divider"}, "portable_test", "", False)
    assert record["status"] == "GEOMETRY_NOT_REPRESENTABLE", record
    assert "SOURCE_CHANGED: case:input/proof/selected-resistor.tcl" in record["reason"]
    assert not (directory / "divider.sp").exists()


def test_emitter_refuses_duplicate_admission_json_keys(case, tmp_path, monkeypatch):
    prepare_emission(case, tmp_path, monkeypatch)
    path = tmp_path / "input/analog_geometry_admission.json"
    path.write_text('{"models": {},' + path.read_text()[1:])
    record = a3.emit_for_block(tmp_path, {"name": "divider"}, "portable_test", "", False)
    assert record["status"] == "GEOMETRY_NOT_REPRESENTABLE", record
    assert "GEOMETRY_ADMISSION_DUPLICATE_KEY" in record["reason"]


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


def prepare_staged_context(case, tmp_path, monkeypatch, installed):
    """A complete project-staged PDK resolves rung 1, which carries no installed root."""
    import analog_pdk_availability as availability

    _, ctx, _ = case
    root, _grid = use_installed_grid(ctx, tmp_path)
    ctx.pop("installed_pdk_root", None)
    directory = prepare_emission(case, tmp_path, monkeypatch)
    asked = []

    def resolve(target, **kwargs):
        asked.append((target, kwargs))
        return installed(root)

    monkeypatch.setattr(availability, "resolve_pdk", resolve)
    return directory, root, asked


def test_staged_context_verifies_pdk_sources_against_installed_family(case, tmp_path, monkeypatch):
    _ir, ctx, _recipe = case
    _directory, _root, asked = prepare_staged_context(
        case, tmp_path, monkeypatch, lambda root: {"pdk_root": str(root)})
    record = a3.emit_for_block(tmp_path, {"name": "divider"}, "portable_test", "", False)
    assert record.get("status") != "GEOMETRY_NOT_REPRESENTABLE", record
    assert ctx["geometry_admission_result"]["status"] == "ADMITTED"
    assert asked == [("portable_test", {"container": ""})]


def test_staged_context_refuses_when_installed_family_bytes_differ(case, tmp_path, monkeypatch):
    directory, root, _asked = prepare_staged_context(
        case, tmp_path, monkeypatch, lambda root: {"pdk_root": str(root)})
    (root / "technology/selected.tlef").write_text("MANUFACTURINGGRID 0.01 ;\n")
    record = a3.emit_for_block(tmp_path, {"name": "divider"}, "portable_test", "", False)
    assert record["status"] == "GEOMETRY_NOT_REPRESENTABLE", record
    assert "GEOMETRY_ADMISSION_SOURCE_CHANGED: pdk:technology/selected.tlef" in record["reason"]
    assert not (directory / "divider.sp").exists()


def test_staged_context_without_installed_family_still_refuses_by_name(case, tmp_path, monkeypatch):
    directory, _root, _asked = prepare_staged_context(
        case, tmp_path, monkeypatch, lambda root: {"available": False, "pdk_root": None})
    record = a3.emit_for_block(tmp_path, {"name": "divider"}, "portable_test", "", False)
    assert record["status"] == "GEOMETRY_NOT_REPRESENTABLE", record
    assert "GEOMETRY_ADMISSION_RUNTIME_ROOT_MISSING: pdk" in record["reason"]
    assert not (directory / "divider.sp").exists()
