import json
from pathlib import Path

import pytest

import flow_engine
import flow_engine_frontend as frontend
import flow_explore


@pytest.mark.parametrize("arguments,expected", [([], 2), (["--ppa-level", "1"], 1), (["--ppa"], 3)])
def test_public_physical_run_selects_the_requested_exploration(tmp_path, monkeypatch, arguments, expected):
    docs = tmp_path / "input/docs"
    docs.mkdir(parents=True)
    (docs / "requirements.md").write_text("Build a synchronous counter hard macro IP.\n")
    calls = []
    monkeypatch.setattr(flow_engine, "run", lambda *a, **k: calls.append("single") or {"fail": 0, "not_measured": 0})

    def explore(project, **options):
        calls.append(options)
        return 0

    monkeypatch.setattr(flow_explore, "explore_public", explore)
    assert frontend.phase_main([str(tmp_path), "--route", "ip", *arguments]) == 0
    assert calls != ["single"]
    assert len(calls) == 1 and calls[0]["level"] == expected
    assert "--ppa-level" not in calls[0]["flow_args"]


def test_public_zero_level_runs_the_native_flow_once(tmp_path, monkeypatch):
    docs = tmp_path / "input/docs"
    docs.mkdir(parents=True)
    (docs / "requirements.md").write_text("Build a counter IP.\n")
    calls = []
    monkeypatch.setattr(flow_engine, "run", lambda *a, **k: calls.append(k) or {"fail": 0, "not_measured": 0})
    assert frontend.phase_main([str(tmp_path), "--route", "ip", "--ppa-level", "0"]) == 0
    assert len(calls) == 1
    assert json.loads((tmp_path / "reports/flow_engine.json").read_text())["ppa_level"] == 0


def test_adopted_public_trial_is_published_with_loadable_local_views(tmp_path, monkeypatch):
    project = tmp_path / "project"
    docs = project / "input/docs"
    docs.mkdir(parents=True)
    (docs / "requirements.md").write_text("Original requirements.\n")

    def explore(source, output, **options):
        trial = output / "reference"
        steps = trial / "steps/mapping"
        steps.mkdir(parents=True)
        view = steps / "unit.odb"
        view.write_text("native view")
        (steps / "state_out.json").write_text(json.dumps({"odb": str(view)}))
        reports = trial / "reports"
        reports.mkdir()
        (reports / "flow_engine.json").write_text(json.dumps({"wall_seconds": 1,
            "steps": [{"name": "mapping", "status": "PASS", "reports": [str(view)]}]}))
        (output / "results.json").write_text("{}")
        return {"selected": "reference", "selected_project": str(trial), "wall_seconds": 2,
                "variants": [{"project": str(trial), "cpu_hours": .01}]}

    monkeypatch.setattr(flow_explore, "explore", explore)
    assert flow_explore.explore_public(project, level=2, level_source="default") == 0
    state = json.loads((project / "steps/mapping/state_out.json").read_text())
    assert Path(state["odb"]).read_text() == "native view"
    assert state["odb"] == str(project / "steps/mapping/unit.odb")
    summary = json.loads((project / "reports/flow_engine.json").read_text())
    assert summary["ppa_level"] == 2 and summary["wall_seconds"] == 1
    assert summary["public_wall_seconds"] >= 0
    assert Path(summary["ppa"]["results"]).is_file()
    assert (docs / "requirements.md").read_text() == "Original requirements.\n"
