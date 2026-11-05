"""Backup reentry uses the admitted route and native per-row outcomes."""

import benchmark_dispatch as dispatch













def test_native_simulation_child_reaches_collection(tmp_path, monkeypatch):
    from test_runner_report_generation import _selected_d09_handoff
    project, argv, process, _ = _selected_d09_handoff(
        tmp_path, monkeypatch, row_id="D13")
    got = dispatch._collect_runner_result(process, argv, "neutral", "neutral", project)
    assert got["runner_diagnostics"]["status"] == "REPORTS_AVAILABLE", got
    assert "reason" not in got["runner_diagnostics"]


def test_native_simulation_child_still_rejects_wrong_window(tmp_path, monkeypatch):
    from test_runner_report_generation import _selected_d09_handoff
    project, argv, process, _ = _selected_d09_handoff(
        tmp_path, monkeypatch, damage="argv", row_id="D13")
    got = dispatch._collect_runner_result(process, argv, "neutral", "neutral", project)
    assert got["runner_diagnostics"]["status"] == "REPORT_BINDING_MISMATCH", got
    assert got["ok"] is False
