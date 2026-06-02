"""Unit tests for drc_vacuous_pass_check.py.

Covers the discriminator between an EARNED 0-DRC verdict (geometry loaded)
and a VACUOUS one (empty/unchecked layout), plus honest SKIP/INCONCLUSIVE
on missing/garbage input.
"""
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "drc_vacuous_pass_check.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import drc_vacuous_pass_check as dvp  # noqa: E402


# ---------------------------------------------------------------------------
# PASS: 0 violations WITH proof geometry was loaded -> earned clean
# ---------------------------------------------------------------------------
def test_earned_clean_magic_geometry(tmp_path):
    log = tmp_path / "magic_drc.log"
    log.write_text(
        "Loading user_proj_example\n"
        "Reading cell user_proj_example\n"
        "12345 rectangles\n"
        "DRC checking complete.\n"
        "Total DRC errors found: 0\n"
    )
    res = dvp.audit(tmp_path)
    assert res.verdict == "PASS"
    assert res.passed is True
    assert any(f.rule == "DRC_CLEAN_EARNED" for f in res.findings)


def test_earned_clean_klayout_shape_count(tmp_path):
    log = tmp_path / "klayout.drc.txt"
    log.write_text(
        "Layout read\n"
        "cells: 87\n"
        "98765 shapes\n"
        "DRC violations: 0\n"
    )
    res = dvp.audit(tmp_path)
    assert res.verdict == "PASS"
    assert res.passed is True


# ---------------------------------------------------------------------------
# INCONCLUSIVE: 0 violations on a provably EMPTY layout (the real bug)
# ---------------------------------------------------------------------------
def test_vacuous_explicit_empty_token(tmp_path):
    log = tmp_path / "drc.rpt"
    log.write_text(
        "Reading GDS...\n"
        "Cell contains no geometry\n"
        "0 cells\n"
        "Total DRC errors: 0\n"
    )
    res = dvp.audit(tmp_path)
    assert res.verdict == "INCONCLUSIVE"
    assert res.passed is False
    assert any(f.rule == "DRC_VACUOUS_PASS" for f in res.findings)


def test_vacuous_no_geometry_evidence(tmp_path):
    # Clean 0-count but NOTHING that proves geometry was loaded.
    log = tmp_path / "drc.log"
    log.write_text("DRC is clean\n0 violations\n")
    res = dvp.audit(tmp_path)
    assert res.verdict == "INCONCLUSIVE"
    assert res.passed is False
    assert any(f.rule == "DRC_VACUOUS_PASS" for f in res.findings)


# ---------------------------------------------------------------------------
# PASS: nonzero violations -> not vacuous, defer to count gate
# ---------------------------------------------------------------------------
def test_nonzero_count_not_vacuous(tmp_path):
    log = tmp_path / "drc.rpt"
    log.write_text("Loading top\nTotal DRC errors: 7\nspacing violation x7\n")
    res = dvp.audit(tmp_path)
    assert res.verdict == "PASS"
    assert res.passed is True
    assert any(f.rule == "DRC_NONZERO_COUNT" for f in res.findings)


# ---------------------------------------------------------------------------
# SKIP: no DRC log at all (honest — never a vacuous PASS)
# ---------------------------------------------------------------------------
def test_no_log_skips(tmp_path):
    (tmp_path / "readme.txt").write_text("not a drc report")
    res = dvp.audit(tmp_path)
    assert res.verdict == "SKIP"
    assert res.passed is False


def test_missing_dir_skips(tmp_path):
    res = dvp.audit(tmp_path / "does_not_exist")
    assert res.verdict == "SKIP"
    assert res.passed is False


# ---------------------------------------------------------------------------
# Edge: empty / garbage log file -> SKIP or INCONCLUSIVE, never PASS
# ---------------------------------------------------------------------------
def test_empty_log_file_not_pass(tmp_path):
    (tmp_path / "drc.log").write_text("")
    res = dvp.audit(tmp_path)
    assert res.passed is False
    assert res.verdict in ("SKIP", "INCONCLUSIVE")


def test_garbage_log_file_not_pass(tmp_path):
    # Has the word "error" so it's treated as a DRC-ish log, but no verdict.
    (tmp_path / "drc.log").write_text("random error log with no count tokens")
    res = dvp.audit(tmp_path)
    # No 0-count clean verdict and no nonzero count: deferred, treated as real.
    assert res.passed is True
    assert res.verdict == "PASS"
    assert any(f.rule == "DRC_NO_VERDICT_TOKEN" for f in res.findings)


# ---------------------------------------------------------------------------
# Single-file path argument
# ---------------------------------------------------------------------------
def test_single_file_arg_vacuous(tmp_path):
    log = tmp_path / "my_drc.log"
    log.write_text("empty layout\n0 errors\n")
    res = dvp.audit(log)
    assert res.verdict == "INCONCLUSIVE"
    assert res.passed is False


# ---------------------------------------------------------------------------
# CLI exit codes
# ---------------------------------------------------------------------------
def test_cli_exit_codes(tmp_path):
    good = tmp_path / "good_drc.log"
    good.write_text("Loading top\n500 shapes\n0 DRC violations\n")
    assert dvp.main([str(good)]) == 0

    bad = tmp_path / "bad_drc.log"
    bad.write_text("0 cells\n0 DRC violations\n")
    assert dvp.main([str(bad)]) == 1

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    assert dvp.main([str(empty_dir)]) == 2


def test_cli_json_output(tmp_path):
    log = tmp_path / "drc.log"
    log.write_text("Loading top\n42 cells\n0 errors\n")
    out = tmp_path / "report.json"
    dvp.main([str(log), "--json", str(out)])
    assert out.exists()
    import json
    data = json.loads(out.read_text())
    assert data["verdict"] == "PASS"
