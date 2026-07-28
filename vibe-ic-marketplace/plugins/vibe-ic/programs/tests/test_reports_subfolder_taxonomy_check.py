"""Tests for reports_subfolder_taxonomy_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
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
    """#528 — rc 2, and the disclosure in the form the CONSUMER matches.

    This test used to assert `returncode == 0` and `"VACUOUS_PASS" in stdout`.
    Both held, and the gate was still credited a plain PASS: the token was
    written `[VACUOUS_PASS]`, and
    `flow_compliance_check._stdout_signals_vacuous` matches
    `line.lstrip().startswith("VACUOUS_PASS")`, which a leading `[` defeats. An
    `in` test over the whole stream cannot tell those apart — it passes for a
    token nothing can read. The assertion is now the consumer's own predicate.
    """
    r = _run(tmp_path)
    assert r.returncode == 2, (r.stdout, r.stderr)
    snippet = (r.stdout[-300:] + "\n" + r.stderr[-300:]).strip()
    assert any(ln.lstrip().startswith("VACUOUS_PASS")
               for ln in snippet.splitlines()), snippet


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
