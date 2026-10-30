"""D31 native controls use an explicitly supplied real-view neutral carrier.

No fixture is production qualification. Set D31_NATIVE_CARRIER to an immutable
project with real GDS/LEF/technology inputs; ordinary source runs skip native
controls when that input is absent, rather than inventing geometry.
"""
import json
import hashlib
import os
from pathlib import Path
import re
import shutil
from types import SimpleNamespace

import pytest
import flow109


@pytest.fixture
def carrier(tmp_path):
    source = os.environ.get("D31_NATIVE_CARRIER")
    if not source:
        pytest.skip("D31 real native physical-view carrier not supplied")
    project = tmp_path / "project"
    shutil.copytree(source, project)
    return project


def run(project):
    args = SimpleNamespace(flow="109", flow109_manifest=project / "manifest.json",
        flow109_plan_only=False, execution_mode="default", entry_step="D31", exit_step="D31", container=None)
    try:
        rc = flow109.prepare_front_door(args, project)
        result = json.loads((project / "reports/flow109/default_rows/D31.json").read_text())
    except flow109.Flow109Error as exc:
        rc, result = 2, {"component_status": exc.code, "reason": str(exc)}
    # Keep the exact observed value on both base and candidate, including refusals.
    (project.parent / "observed.json").write_text(json.dumps({"rc": rc, "result": result}, indent=2))
    return rc, result


def change(project, mutate):
    path = project / "input/flow109/D31.json"
    value = json.loads(path.read_text())
    mutate(value)
    path.write_text(json.dumps(value))


def revise_adopted_lef(project, transform):
    """Explicit negative copy; honestly rebind changed view and inventory bytes."""
    plan_path = project / "input/flow109/D31.json"
    plan = json.loads(plan_path.read_text())
    inventory_path = project / plan["macro_inventory"]["path"]
    inventory = json.loads(inventory_path.read_text())
    view = next(iter(inventory["instances"].values()))
    path, master = project / view["lef"]["path"], view["master"]
    text = path.read_text()
    pattern = r"(?ms)^MACRO\s+" + re.escape(master) + r"\s.*?^END\s+" + re.escape(master) + r"\s*$"
    matches = list(re.finditer(pattern, text))
    assert len(matches) == 1
    match = matches[0]
    replacement = transform(match[0])
    assert replacement != match[0]
    path.write_text(text[:match.start()] + replacement + text[match.end():])
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    for item in inventory["instances"].values():
        if item["lef"]["path"] == view["lef"]["path"]:
            item["lef"]["sha256"] = digest
    inventory_path.write_text(json.dumps(inventory))
    plan["macro_inventory"]["sha256"] = hashlib.sha256(inventory_path.read_bytes()).hexdigest()
    plan_path.write_text(json.dumps(plan))


def test_legal_real_views_native_readback(carrier):
    rc, row = run(carrier)
    assert row["component_status"] == "PASS", row
    assert rc == 2 and row["default_row_status"] == "NOT_MEASURED"
    assert row["completed"] is False and row["delivery_accepted"] is False
    assert row["qualification"] == "NOT_CLAIMED"
    measured = row["measurements"]
    assert measured["illegal_macro_overlap"] == 0 and measured["violations"] == []
    plan = json.loads((carrier / "input/flow109/D31.json").read_text())
    assert {r["name"] for r in measured["instances"]} == set(plan["placements"])
    assert all(r["pins"] == len(plan["placements"][r["name"]]["pins"]) for r in measured["instances"])
    assert len(row["executions"]) == 2 and all(r["returncode"] == 0 for r in row["executions"])
    assert (carrier / row["outputs"][0]["path"]).stat().st_size > 0


def test_adopted_lef_envelope_cannot_hide_behind_smaller_native_geometry(carrier):
    # Root's real-view countercase: only SIZE changes, with honest input hashes.
    revise_adopted_lef(carrier, lambda macro: re.sub(r"\bSIZE\s+[^;]+;", "SIZE 300 BY 180 ;", macro, count=1))
    rc, row = run(carrier)
    assert row["component_status"] == "FAIL", row
    assert rc == 1 and row["default_row_status"] == "FAIL"
    assert row["measurements"]["illegal_macro_overlap"] == 1
    assert row["measurements"]["floorplan_boundary_pin_feasibility"] == "FAIL"
    assert any(v.startswith("boundary:") for v in row["measurements"]["violations"])
    assert len(row["measurements"]["instances"]) == 2
    assert all(i["pins"] > 0 for i in row["measurements"]["instances"])


@pytest.mark.parametrize("case", ["missing_size", "malformed_size", "nonfinite_size",
    "zero_size", "negative_size", "nonzero_origin", "nonfinite_origin", "foreign_offset"])
def test_unsupported_lef_envelope_refuses_before_native(carrier, case):
    sizes = {"missing_size": "", "malformed_size": "SIZE 80 180 ;",
             "nonfinite_size": "SIZE NaN BY 180 ;", "zero_size": "SIZE 0 BY 180 ;",
             "negative_size": "SIZE 80 BY -180 ;"}
    def transform(macro):
        if case in sizes:
            return re.sub(r"\bSIZE\s+[^;]+;", sizes[case], macro, count=1)
        if case == "foreign_offset":
            return re.sub(r"(\bFOREIGN\s+\S+)\s+[^;]+;", r"\1 1 0 ;", macro, count=1)
        value = "1 0" if case == "nonzero_origin" else "NaN 0"
        return re.sub(r"\bORIGIN\s+[^;]+;", "ORIGIN " + value + " ;", macro, count=1)
    revise_adopted_lef(carrier, transform)
    rc, row = run(carrier)
    expected = "D31_LEF_SIZE_INVALID" if case in sizes else "D31_LEF_FRAME_UNSUPPORTED"
    assert expected in row["reason"], row
    assert row["component_status"] == row["default_row_status"] == "NOT_MEASURED"
    assert rc == 2 and row["native_started"] is False and row["executions"] == []
    assert not list((carrier / "reports/flow109/D31").glob("*/floorplan.gds"))


@pytest.mark.parametrize("fault", ["overlap", "boundary"])
def test_actual_bad_geometry_blocks_normal_frontdoor(carrier, fault):
    def mutate(value):
        a, b = sorted(value["placements"])[:2]
        value["placements"][b]["origin"] = value["placements"][a]["origin"][:] if fault == "overlap" else [100000, 100000]
    change(carrier, mutate)
    rc, row = run(carrier)
    assert row["component_status"] == "FAIL", row
    assert rc == 1 and row["default_row_status"] == "FAIL"
    assert row["native_started"] is True
    if fault == "overlap":
        assert row["measurements"]["illegal_macro_overlap"] > 0
    else:
        assert any(v.startswith("boundary:") for v in row["measurements"]["violations"])


@pytest.mark.parametrize("fault, reason", [
    ("macro", "D31_MACRO_POPULATION_INCOMPLETE"),
    ("pin", "D31_PIN_POPULATION_INCOMPLETE"),
    ("stale_view", "D31_INPUT_STALE"),
])
def test_incomplete_or_stale_input_refuses_before_native(carrier, fault, reason):
    def mutate(value):
        name = sorted(value["placements"])[0]
        if fault == "macro":
            del value["placements"][name]
        elif fault == "pin":
            pins = value["placements"][name]["pins"]
            del pins[sorted(pins)[0]]
        else:
            ref = value["macro_inventory"]
            inventory = json.loads((carrier / ref["path"]).read_text())
            view = next(iter(inventory["instances"].values()))["lef"]
            path = carrier / view["path"]
            path.write_text(path.read_text() + "\n# deliberately stale source view\n")
    change(carrier, mutate)
    rc, row = run(carrier)
    assert reason in row["reason"], row
    assert rc == 2 and row["component_status"] == "NOT_MEASURED"
    assert row["native_started"] is False and row["executions"] == []


def test_other_analog_profiles_still_refuse_full_window():
    registry = flow109.load_registry()
    features = next(p["features"] for p in registry["reference_profiles"] if p["name"] == "Analog IC external trim")
    plan = flow109.resolve_plan(features)
    with pytest.raises(flow109.Flow109Error) as error:
        flow109.resolve_execution_window(plan, "D31", "D32")
    assert error.value.code == "FLOW109_PRODUCER_UNIMPLEMENTED"


def test_d31_digital_owner_is_unchanged():
    registry = flow109.load_registry()
    features = next(p["features"] for p in registry["reference_profiles"] if p["name"] == "Small digital IC without DFT")
    row = flow109.resolve_step(flow109.resolve_plan(features), "D31")
    assert row["profile"]["id"] == "default"
    assert row["profile"]["dispatch"]["native_step_id"] == "15"


@pytest.mark.parametrize("original", ["PASS", "FAIL"])
def test_late_output_read_failure_never_keeps_pass(tmp_path, monkeypatch, original):
    """SOFTWARE replay of actual native bytes, not another native execution."""
    import flow109_analog_floorplan as owner
    source = os.environ.get("D31_" + original + "_REFERENCE")
    if not source:
        pytest.skip("actual native reference project not supplied for software reducer control")
    project = tmp_path / "project"
    shutil.copytree(source, project, ignore=shutil.ignore_patterns("reports"))
    reference = next((Path(source) / "reports/flow109/D31").glob("*/consume.json")).parent
    assert json.loads((reference / "consume.json").read_text())["status"] == original

    def native_bytes(argv, **kwargs):
        assert Path(argv[0]).name == "klayout"
        request = json.loads(Path(argv[-1].split("=", 1)[1]).read_text())
        output = Path(request["output"])
        for name in (request["mode"] + ".json", "floorplan.gds"):
            shutil.copyfile(reference / name, output / name)
        return SimpleNamespace(returncode=0, stdout="SOFTWARE replay of retained native bytes", stderr="")

    original_sha = owner.sha
    def unreadable_output(path):
        if Path(path).name == "floorplan.gds":
            raise OSError("TEST_ONLY: output became unreadable after native result")
        return original_sha(path)
    monkeypatch.setattr(owner.subprocess, "run", native_bytes)
    monkeypatch.setattr(owner, "sha", unreadable_output)
    rc, row = run(project)
    assert row["component_status"] == ("NOT_MEASURED" if original == "PASS" else "FAIL"), row
    assert row["default_row_status"] == ("NOT_MEASURED" if original == "PASS" else "FAIL")
    assert rc == (2 if original == "PASS" else 1)
    assert "became unreadable" in row["reason"]
    assert row["completed"] is False and row["delivery_accepted"] is False
