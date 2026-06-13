"""Tests for top_level_outputs_in_canonical_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "top_level_outputs_in_canonical_check.py")


def _run(project, *args):
    return subprocess.run(
        [sys.executable, str(PROG), str(project), *args],
        capture_output=True, text=True,
    )


def test_help():
    r = subprocess.run([sys.executable, str(PROG), "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0


def test_vacuous_pass_empty_project(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "VACUOUS_PASS" in r.stdout


def test_pass_canonical_only(tmp_path):
    for d in ("input", "phase1", "phase2", "phase3", "reports"):
        (tmp_path / d).mkdir()
    for f in ("provenance.jsonl", "rig_topology.json", "waivers.json"):
        (tmp_path / f).write_text("{}")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


def test_fail_stray_top_level_dir(tmp_path):
    (tmp_path / "phase1").mkdir()
    (tmp_path / "rtl").mkdir()  # legacy flat-top
    (tmp_path / "run_logs").mkdir()
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "stray dir" in r.stdout
    assert "rtl" in r.stdout
    assert "run_logs" in r.stdout


def test_fail_stray_top_level_file(tmp_path):
    (tmp_path / "phase1").mkdir()
    # Intentionally write an extraction_patterns.json at the project ROOT
    # (where it does NOT belong; it should live under phase1/).
    (tmp_path / "extraction_patterns.json").write_text("{}")
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "extraction_patterns.json" in r.stdout


def test_hidden_files_ignored(tmp_path):
    (tmp_path / ".gitignore").write_text("*.pyc\n")
    (tmp_path / ".DS_Store").write_text("")
    (tmp_path / "input").mkdir()
    r = _run(tmp_path)
    assert r.returncode == 0


def test_top_level_md_files_ignored(tmp_path):
    (tmp_path / "AGENT_REPORT.md").write_text("# top-level report")
    (tmp_path / "RESULTS.md").write_text("# results")
    (tmp_path / "input").mkdir()
    r = _run(tmp_path)
    assert r.returncode == 0


def test_json_output(tmp_path):
    (tmp_path / "rtl").mkdir()
    out = tmp_path / "report.json"
    r = _run(tmp_path, "--json", str(out))
    assert r.returncode == 1
    data = json.loads(out.read_text())
    assert data["passed"] is False
    assert "rtl" in data["stray_dirs"]
