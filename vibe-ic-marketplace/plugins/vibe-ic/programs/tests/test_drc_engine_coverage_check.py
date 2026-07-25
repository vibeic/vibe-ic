#!/usr/bin/env python3
"""Bidirectional tests for DEFECT 2: DRC dual-engine requirement silently unmet.

DEFECT direction: engines_run=["klayout"] with required={"klayout","magic"}
  FAILS the gate (the spec requires two engines).
FIXED direction: engines_run=["klayout","magic"] PASSES.
EDGE cases:
  - required set empty/unknown → vacuous-pass with explicit note, no crash.
  - magic(vacuous) in engines_run is NOT counted as a clean magic run.
  - missing drc_signoff.json → ERROR (exit 2), not silent pass.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import drc_engine_coverage_check as decc


# ---------------------------------------------------------------------------
# Unit tests of core logic (no subprocess, no disk I/O beyond fixtures)
# ---------------------------------------------------------------------------

class TestCheckCoverage:
    """Tests for decc.check_coverage() — pure logic, no I/O."""

    # --- DEFECT direction ---
    def test_defect_single_engine_fails_dual_requirement(self):
        """engines_run=["klayout"], required=["klayout","magic"] → FAIL."""
        result = decc.check_coverage(["klayout"], ["klayout", "magic"])
        assert result["status"] == "FAIL"
        assert "magic" in result["missing"]

    def test_defect_no_engines_fails_any_requirement(self):
        """engines_run=[], required=["klayout"] → FAIL."""
        result = decc.check_coverage([], ["klayout"])
        assert result["status"] == "FAIL"
        assert "klayout" in result["missing"]

    # --- FIXED direction ---
    def test_fixed_both_engines_passes_dual_requirement(self):
        """engines_run=["klayout","magic"], required=["klayout","magic"] → PASS."""
        result = decc.check_coverage(["klayout", "magic"],
                                     ["klayout", "magic"])
        assert result["status"] == "PASS"
        assert result["missing"] == []

    def test_fixed_superset_engines_also_passes(self):
        """engines_run=["klayout","magic","calibre"], required=["klayout","magic"] → PASS."""
        result = decc.check_coverage(["klayout", "magic", "calibre"],
                                     ["klayout", "magic"])
        assert result["status"] == "PASS"

    # --- Empty / unknown required set ---
    def test_empty_required_vacuous_pass(self):
        """required=[] → VACUOUS_PASS with explicit note, never a crash."""
        result = decc.check_coverage(["klayout"], [])
        assert result["status"] == "VACUOUS_PASS"
        assert "vacuous" in result["note"].lower() or "empty" in result["note"].lower()

    def test_none_required_treated_as_empty(self):
        """required=[] (default) → vacuous-pass."""
        result = decc.check_coverage(["klayout"], [])
        assert result["status"] == "VACUOUS_PASS"

    # --- Vacuous magic run NOT counted ---
    def test_magic_vacuous_not_counted_as_clean(self):
        """engines_run=["klayout","magic(vacuous)"], required=["klayout","magic"] → FAIL."""
        result = decc.check_coverage(["klayout", "magic(vacuous)"],
                                     ["klayout", "magic"])
        assert result["status"] == "FAIL"
        assert "magic" in result["missing"]

    # --- Case-insensitive comparison ---
    def test_case_insensitive_engine_names(self):
        """Engine names are compared case-insensitively."""
        result = decc.check_coverage(["KLayout", "Magic"],
                                     ["klayout", "magic"])
        assert result["status"] == "PASS"

    # --- Result note is always present ---
    def test_result_always_has_note(self):
        for er, req, expected in [
            (["klayout"], ["klayout", "magic"], "FAIL"),
            (["klayout", "magic"], ["klayout", "magic"], "PASS"),
            (["klayout"], [], "VACUOUS_PASS"),
        ]:
            result = decc.check_coverage(er, req)
            assert result["status"] == expected
            assert isinstance(result["note"], str) and result["note"]

    # --- FAIL note must say "one engine does NOT satisfy" ---
    def test_fail_note_explains_two_engine_requirement(self):
        result = decc.check_coverage(["klayout"], ["klayout", "magic"])
        assert ("one engine" in result["note"].lower()
                or "does not satisfy" in result["note"].lower()
                or "multi-engine" in result["note"].lower()
                or "not satisfy" in result["note"].lower())


# ---------------------------------------------------------------------------
# I/O tests: load_engines_run + check_coverage with real drc_signoff.json
# ---------------------------------------------------------------------------

class TestLoadEnginesRun:
    def test_reads_engines_run_from_json(self, tmp_path):
        d = tmp_path / "reports" / "phase3"
        d.mkdir(parents=True)
        (d / "drc_signoff.json").write_text(json.dumps({
            "verdict": "PASS",
            "engines_run": ["klayout"],
        }))
        er = decc.load_engines_run(tmp_path)
        assert er == ["klayout"]

    def test_reads_from_flat_reports_dir_too(self, tmp_path):
        d = tmp_path / "reports"
        d.mkdir(parents=True)
        (d / "drc_signoff.json").write_text(json.dumps({
            "verdict": "PASS",
            "engines_run": ["klayout", "magic"],
        }))
        er = decc.load_engines_run(tmp_path)
        assert set(er) == {"klayout", "magic"}

    def test_absent_json_returns_none(self, tmp_path):
        er = decc.load_engines_run(tmp_path)
        assert er is None


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------

PROG = Path(__file__).resolve().parent.parent / "drc_engine_coverage_check.py"


def _run(args, **kw):
    return subprocess.run(
        [sys.executable, str(PROG)] + list(args),
        capture_output=True, text=True, **kw)


def _make_signoff_json(tmp_path: Path, engines_run: list) -> None:
    d = tmp_path / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    (d / "drc_signoff.json").write_text(json.dumps({
        "verdict": "PASS",
        "status": "PASS",
        "violations": 0,
        "engines_run": engines_run,
    }))


class TestCLI:
    def test_defect_single_engine_fails_cli(self, tmp_path):
        """CLI: engines_run=[klayout], required klayout magic → exit 1."""
        _make_signoff_json(tmp_path, ["klayout"])
        r = _run([str(tmp_path), "--required", "klayout", "magic"])
        assert r.returncode == 1
        assert "FAIL" in r.stdout

    def test_fixed_both_engines_passes_cli(self, tmp_path):
        """CLI: engines_run=[klayout,magic], required klayout magic → exit 0."""
        _make_signoff_json(tmp_path, ["klayout", "magic"])
        r = _run([str(tmp_path), "--required", "klayout", "magic"])
        assert r.returncode == 0
        assert "PASS" in r.stdout

    def test_empty_required_vacuous_pass_cli(self, tmp_path):
        """CLI: no --required → vacuous-pass, exit 0."""
        _make_signoff_json(tmp_path, ["klayout"])
        r = _run([str(tmp_path)])
        assert r.returncode == 0
        assert "vacuous" in r.stdout.lower() or "VACUOUS" in r.stdout

    def test_missing_json_exit_2(self, tmp_path):
        """CLI: no drc_signoff.json → exit 2 (ERROR, not silent pass)."""
        r = _run([str(tmp_path), "--required", "klayout", "magic"])
        assert r.returncode == 2

    def test_json_out_written(self, tmp_path):
        """--json-out writes a valid JSON result file."""
        _make_signoff_json(tmp_path, ["klayout", "magic"])
        out = tmp_path / "coverage_result.json"
        r = _run([str(tmp_path), "--required", "klayout", "magic",
                  "--json-out", str(out)])
        assert r.returncode == 0
        assert out.is_file()
        d = json.loads(out.read_text())
        assert d["status"] == "PASS"
        assert "engines_run_raw" in d

    def test_this_run_single_engine_fails_gate(self, tmp_path):
        """Simulate this run's actual record: engines_run=[klayout],
        required=[klayout,magic] → FAIL (the real in-situ test)."""
        _make_signoff_json(tmp_path, ["klayout"])
        r = _run([str(tmp_path), "--required", "klayout", "magic"])
        assert r.returncode == 1
        assert "klayout" in r.stdout
        assert "magic" in r.stdout
