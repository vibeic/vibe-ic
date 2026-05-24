"""Tests for reports_subfolder_taxonomy_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "programs"
        / "reports_subfolder_taxonomy_check.py")


def _run(project, *args):
    return subprocess.run(
        [sys.executable, str(PROG), str(project), *args],
        capture_output=True, text=True,
    )


def test_help():
    r = subprocess.run([sys.executable, str(PROG), "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0


def test_vacuous_pass_no_reports_dir(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "VACUOUS_PASS" in r.stdout


def test_pass_phase_aligned_subdirs_only(tmp_path):
    rep = tmp_path / "reports"
    rep.mkdir()
    for sub in ("phase1", "phase2", "phase3", "audit", "orchestrator"):
        (rep / sub).mkdir()
    (rep / "final_summary.md").write_text("# summary")
    (rep / "chip_specific_summary.md").write_text("# chip detail")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


def test_fail_flat_report_at_top(tmp_path):
    rep = tmp_path / "reports"
    rep.mkdir()
    (rep / "phase1").mkdir()
    (rep / "synth_netlist.json").write_text("{}")  # belongs in phase2/
    (rep / "drc_signoff.rpt").write_text("")  # belongs in phase3/
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "synth_netlist.json" in r.stdout
    assert "drc_signoff.rpt" in r.stdout


def test_fail_unknown_subdir(tmp_path):
    rep = tmp_path / "reports"
    rep.mkdir()
    (rep / "phase1").mkdir()
    (rep / "tmp").mkdir()  # not in whitelist
    (rep / "legacy").mkdir()
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "tmp" in r.stdout
    assert "legacy" in r.stdout


def test_hidden_entries_ignored(tmp_path):
    rep = tmp_path / "reports"
    rep.mkdir()
    (rep / ".keep").write_text("")
    (rep / "phase1").mkdir()
    r = _run(tmp_path)
    assert r.returncode == 0


def test_json_output(tmp_path):
    rep = tmp_path / "reports"
    rep.mkdir()
    (rep / "tmp").mkdir()
    out = tmp_path / "report.json"
    r = _run(tmp_path, "--json", str(out))
    assert r.returncode == 1
    data = json.loads(out.read_text())
    assert data["passed"] is False
    assert "tmp" in data["stray_dirs"]
