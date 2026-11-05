import json
import subprocess
import sys

import flow_engine as engine


def test_report_and_renderer_preserve_plain_row_and_native_durations(tmp_path):
    name = engine.read_json(engine.TABLE)["steps"][0]["name"]
    row = {"name": name, "title": "Neutral measurement", "status": "PASS", "metrics": [],
           "tool_exit_code": 0, "tool_seconds": 9, "program_seconds": 1, "ai_seconds": 2,
           "wall_seconds": 10, "tool_ran": True,
           "native_steps": [{"name": "Neutral native tool", "tool_seconds": 9}]}
    engine.write_json(tmp_path / "steps" / name / "result.json", row)
    engine.write_json(tmp_path / "reports/flow_engine.json", {
        "steps": [row], "selected_names": [name], "selected": 1})
    refreshed = engine.refresh_report(tmp_path)
    assert {key: refreshed[key] for key in ("tool_seconds", "program_seconds", "ai_seconds", "wall_seconds")} == {
        "tool_seconds": 9, "program_seconds": 1, "ai_seconds": 2, "wall_seconds": 10}
    assert refreshed["steps"][0]["native_steps"] == row["native_steps"]
    output = tmp_path / "rendered"
    result = subprocess.run([sys.executable, str(engine.HERE / "flow_engine_report.py"),
                             "--project", str(tmp_path), "--output", str(output),
                             "--head", "neutral", "--stage", "synthetic"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    text = (output / "RESULT.md").read_text()
    assert "Tool time 9.000 s. Program time 1.000 s." in text
    assert "Measured AI review time 2.000 s." in text
    assert "Total row wall time 10.000 s." in text
