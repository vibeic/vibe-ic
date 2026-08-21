"""Unit tests for plugin_change_pytest_gate.py.

Covers the conditional gate: plugin code changed => a clean FULL-suite
pytest attestation (BOTH trees) is required; otherwise N/A PASS. Honest
FAIL/ERROR on missing/garbage/partial evidence.
"""
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "plugin_change_pytest_gate.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import plugin_change_pytest_gate as pg  # noqa: E402


CLEAN_FULL_LOG = (
    "rootdir: /repo/plugins/vibe-ic\n"
    "collected 2300 items\n"
    "programs/tests/test_foo.py ....\n"
    "tests/test_index_freshness.py .\n"
    "==== 2300 passed, 4 warnings in 90.12s ====\n"
)


# ---------------------------------------------------------------------------
# PASS: no plugin change -> gate inapplicable
# ---------------------------------------------------------------------------
def test_no_change_passes(tmp_path):
    res = pg.audit(tmp_path, pytest_log=None, changed_files=[])
    assert res.verdict == "PASS"
    assert res.passed is True
    assert res.summary["pytest_required"] is False


def test_only_nonpy_change_passes(tmp_path):
    res = pg.audit(tmp_path, pytest_log=None,
                   changed_files=["skills/x/SKILL.md", "README.md"])
    assert res.verdict == "PASS"
    assert res.passed is True


# ---------------------------------------------------------------------------
# PASS: plugin changed + clean full-suite log (both trees)
# ---------------------------------------------------------------------------
def test_change_with_clean_full_log_passes(tmp_path):
    log = tmp_path / "pytest.txt"
    log.write_text(CLEAN_FULL_LOG)
    res = pg.audit(tmp_path, pytest_log=log,
                   changed_files=["programs/benchmark_verify_report.py"])
    assert res.verdict == "PASS"
    assert res.passed is True
    assert any(f.rule == "PYTEST_FULL_SUITE_CLEAN" for f in res.findings)


# ---------------------------------------------------------------------------
# FAIL: plugin changed but no pytest log
# ---------------------------------------------------------------------------
def test_change_no_log_fails(tmp_path):
    res = pg.audit(tmp_path, pytest_log=None,
                   changed_files=["programs/coverage_metric_check.py"])
    assert res.verdict == "FAIL"
    assert res.passed is False
    assert any(f.rule == "PYTEST_LOG_REQUIRED" for f in res.findings)


# ---------------------------------------------------------------------------
# FAIL: plugin changed + FAILING pytest log
# ---------------------------------------------------------------------------
def test_change_failing_log_fails(tmp_path):
    log = tmp_path / "pytest.txt"
    log.write_text(
        "programs/tests/test_foo.py .F\n"
        "tests/test_x.py .\n"
        "==== 2 failed, 2298 passed in 91s ====\n")
    res = pg.audit(tmp_path, pytest_log=log,
                   changed_files=["programs/foo.py"])
    assert res.verdict == "FAIL"
    assert res.passed is False
    assert any(f.rule == "PYTEST_NOT_CLEAN" for f in res.findings)


def test_change_errors_log_fails(tmp_path):
    log = tmp_path / "pytest.txt"
    log.write_text(
        "programs/tests/test_foo.py E\n"
        "tests/test_x.py .\n"
        "==== 3 errors in 5s ====\n")
    res = pg.audit(tmp_path, pytest_log=log, changed_files=["programs/foo.py"])
    assert res.verdict == "FAIL"
    assert res.passed is False


# ---------------------------------------------------------------------------
# FAIL: plugin changed + PARTIAL suite (only programs/tests ran)
# ---------------------------------------------------------------------------
def test_change_partial_suite_fails(tmp_path):
    log = tmp_path / "pytest.txt"
    log.write_text(
        "programs/tests/test_foo.py ....\n"
        "==== 1900 passed in 70s ====\n")
    res = pg.audit(tmp_path, pytest_log=log, changed_files=["programs/foo.py"])
    assert res.verdict == "FAIL"
    assert res.passed is False
    assert any(f.rule == "PYTEST_PARTIAL_SUITE" for f in res.findings)


# ---------------------------------------------------------------------------
# FAIL: log path supplied but missing / garbage
# ---------------------------------------------------------------------------
def test_change_missing_log_fails(tmp_path):
    res = pg.audit(tmp_path, pytest_log=tmp_path / "nope.txt",
                   changed_files=["programs/foo.py"])
    assert res.verdict == "FAIL"
    assert any(f.rule == "PYTEST_LOG_MISSING" for f in res.findings)


def test_change_garbage_log_fails(tmp_path):
    log = tmp_path / "pytest.txt"
    log.write_text("this is not a pytest log at all\n")
    res = pg.audit(tmp_path, pytest_log=log, changed_files=["programs/foo.py"])
    assert res.verdict == "FAIL"
    assert res.passed is False
    assert any(f.rule == "PYTEST_NOT_CLEAN" for f in res.findings)


# ---------------------------------------------------------------------------
# ERROR: cannot determine git state and no explicit list -> never silent PASS
# ---------------------------------------------------------------------------
def test_non_git_dir_errors(tmp_path):
    # tmp_path is not a git repo; no --changed-files.
    res = pg.audit(tmp_path, pytest_log=None, changed_files=None)
    assert res.verdict == "ERROR"
    assert res.passed is False
    assert any(f.rule == "CHANGE_STATE_UNKNOWN" for f in res.findings)


# ---------------------------------------------------------------------------
# parse_pytest_log unit
# ---------------------------------------------------------------------------
def test_parse_clean():
    p = pg.parse_pytest_log(CLEAN_FULL_LOG)
    assert p["passed"] == 2300
    assert p["failed"] == 0
    assert p["errors"] == 0
    assert p["programs_tree"] is True
    assert p["tests_tree"] is True
    assert p["clean"] is True


def test_parse_failed():
    p = pg.parse_pytest_log("==== 2 failed, 100 passed in 1s ====")
    assert p["failed"] == 2
    assert p["clean"] is False


# ---------------------------------------------------------------------------
# CLI exit codes
# ---------------------------------------------------------------------------
def test_cli_exit_codes(tmp_path):
    log = tmp_path / "pytest.txt"
    log.write_text(CLEAN_FULL_LOG)
    # plugin changed + clean -> 0
    assert pg.main([str(tmp_path), "--pytest-log", str(log),
                    "--changed-files", "programs/foo.py"]) == 0
    # plugin changed + no log -> 1
    assert pg.main([str(tmp_path), "--changed-files", "programs/foo.py"]) == 1
    # no change -> 0
    assert pg.main([str(tmp_path), "--changed-files"]) == 0


def test_cli_json_output(tmp_path):
    log = tmp_path / "pytest.txt"
    log.write_text(CLEAN_FULL_LOG)
    out = tmp_path / "report.json"
    pg.main([str(tmp_path), "--pytest-log", str(log),
             "--changed-files", "programs/foo.py", "--json", str(out)])
    assert out.exists()
    import json
    data = json.loads(out.read_text())
    assert data["verdict"] == "PASS"
