import json
import subprocess
import sys

import pytest

import flow_engine as engine


@pytest.fixture
def retained_project(tmp_path):
    name = engine.read_json(engine.TABLE)["steps"][0]["name"]
    row = {"name": name, "title": "Neutral measurement", "status": "PASS", "metrics": [],
           "tool_exit_code": 0, "tool_seconds": 9, "program_seconds": 1, "ai_seconds": 2,
           "reviewed_at": 22, "started_at": 10, "completed_at": 20,
           "timing_group": "librelane", "tool_ran": True}
    engine.write_json(tmp_path / "steps" / name / "result.json", row)
    engine.write_json(tmp_path / "reports/flow_engine.json", {
        "steps": [row], "selected_names": [name], "selected": 1,
        "started_at": 0, "completed_at": 230, "native_common_started_at": 10,
        "native_common_completed_at": 20, "common_tools_complete": True,
        "pending_steps": ["pending native step"], "background_pending": ["pending independent step"],
        "budget_seconds": 1, "runtime_status": "legacy verdict", "common_budget_completed_at": 22})
    return tmp_path


def test_report_cli_refresh_removes_legacy_verdict_and_preserves_timing(retained_project):
    result = subprocess.run([sys.executable, str(engine.HERE / "flow_engine.py"), "report",
                             "--project", str(retained_project)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    refreshed = json.loads(result.stdout)
    assert all(key not in refreshed for key in ("budget_seconds", "runtime_status", "common_budget_completed_at"))
    assert refreshed["common_completed_at"] == 22
    assert refreshed["common_wall_seconds"] == 12
    assert refreshed["common_native_wall_seconds"] == 10
    assert refreshed["tool_seconds"] == 9
    assert refreshed["program_seconds"] == 1
    assert refreshed["ai_seconds"] == 2
    assert refreshed["pending_steps"] == ["pending native step"]
    assert refreshed["background_pending"] == ["pending independent step"]
    assert json.loads((retained_project / "reports/flow_engine.json").read_text()) == refreshed


def test_refresh_retains_legacy_completion_when_raw_native_bounds_are_missing(retained_project):
    path = retained_project / "reports/flow_engine.json"
    report = engine.read_json(path)
    del report["native_common_completed_at"]
    engine.write_json(path, report)
    refreshed = engine.refresh_report(retained_project)
    assert refreshed["common_completed_at"] == 22
    assert refreshed["common_native_wall_seconds"] is None
    assert refreshed["common_wall_seconds"] is None


def test_render_cli_keeps_tool_program_ai_and_common_times_without_a_time_verdict(retained_project):
    output = retained_project / "rendered"
    result = subprocess.run([sys.executable, str(engine.HERE / "flow_engine_report.py"),
                             "--project", str(retained_project), "--output", str(output),
                             "--head", "neutral", "--stage", "synthetic"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    text = (output / "RESULT.md").read_text()
    assert "Tool time 9.000 s. Program time 1.000 s." in text
    assert "Measured AI review time 2.000 s." in text
    assert "Common native window including review 12.000 s." in text
    assert "Budget" not in text
    assert "legacy verdict" not in text


@pytest.mark.parametrize(("script", "arguments"), [
    ("flow_engine.py", ["run"]), ("flow_engine.py", ["report"]), ("flow_engine_report.py", []),
])
def test_cli_help_has_no_time_budget_option(script, arguments):
    result = subprocess.run([sys.executable, str(engine.HERE / script), *arguments, "--help"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "--budget-seconds" not in result.stdout
