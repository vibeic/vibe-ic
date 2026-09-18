import json
import subprocess
from pathlib import Path

import macro_obs_geometry_intersect_check as M


def _project(tmp_path, *, missing=False):
    project = tmp_path / "project"
    pnr = project / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "routed.def").write_text(
        "VERSION 5.8 ;\nDESIGN chip ;\nCOMPONENTS 1 ;\n"
        "- u_macro fixture_macro + PLACED ( 0 0 ) N ;\n"
        "END COMPONENTS\nEND DESIGN\n")
    views = tmp_path / "run_views"
    views.mkdir()
    macro = views / "selected_macro.lef"
    macro.write_text(
        "VERSION 5.8 ;\nMACRO fixture_macro\n  CLASS BLOCK ;\n"
        "  SIZE 10 BY 10 ;\n  OBS\n    LAYER M1 ;\n      RECT 0 0 1 1 ;\n    END\n  END\nEND fixture_macro\nEND LIBRARY\n")
    paths = [str(tmp_path / "missing.lef")] if missing else [str(macro)]
    record = project / "reports" / "phase3" / "physical_view_inventory.json"
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({
        "schema": "vibe-ic/physical-view-inventory/1",
        "producer": "phase3_one_shot_runner", "verdict": "RECORDED",
        "scope": "pnr_read_lef_inputs", "read_lef_paths": paths}))
    return project


def test_macro_consumer_uses_recorded_run_view_outside_project(tmp_path):
    project = _project(tmp_path)
    assert M.main([str(project)]) == 0


def test_macro_consumer_refuses_missing_recorded_run_view(tmp_path):
    project = _project(tmp_path, missing=True)
    assert M.main([str(project)]) == 2


def test_progress_plan_binds_external_recorded_view(tmp_path):
    project = _project(tmp_path)
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.email",
                    "fixture@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.name",
                    "fixture"], check=True)
    subprocess.run(["git", "-C", str(project), "add", "."], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-qm", "fixture"],
                   check=True)
    record = json.loads(
        (project / "reports/phase3/physical_view_inventory.json").read_text())
    external = Path(record["read_lef_paths"][0]).resolve()
    plan = M._input_plan(project)
    assert external in [p.resolve() for p in plan.paths("macro-lef")]
