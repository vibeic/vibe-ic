"""Tests for the antenna substance check (eda_report_audit --mode antenna +
antenna_report_check.py wrapper). Step 26 was presence-only; this gates on the
OpenROAD check_antennas violation count. Verifies: clean→PASS, violations→FAIL,
missing→FAIL, hand-typed-stub→FAIL — mirroring the EM/IR siblings, no regression
on a real clean report."""
import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
from eda_report_audit import main as audit_main, _check_antenna  # noqa: E402

CLEAN = (
    "# OpenROAD antenna check (gate-oxide protection)\n"
    "# Tool: openroad / check_antennas (ANT).\n"
    "antenna check: 0 net violations, 0 pin violations\n"
    "antenna clean: YES\n"
    "[INFO ANT-0002] Found 0 net violations.\n"
    "[INFO ANT-0001] Found 0 pin violations.\n"
)
VIOL = (
    "# OpenROAD antenna check\n# Tool: openroad / check_antennas (ANT).\n"
    "antenna check: 3 net violations, 1 pin violations\n"
    "antenna clean: NO\n"
    "[INFO ANT-0002] Found 3 net violations.\n"
    "[INFO ANT-0001] Found 1 pin violations.\n"
)


def _proj(tmp_path, rpt_text):
    d = tmp_path / "reports" / "phase3"
    d.mkdir(parents=True)
    (d / "antenna.rpt").write_text(rpt_text)
    return tmp_path


def test_clean_antenna_passes(tmp_path):
    r = _check_antenna(_proj(tmp_path, CLEAN))
    assert r.passed is True
    assert r.summary["violations"] == 0


def test_violating_antenna_fails(tmp_path):
    r = _check_antenna(_proj(tmp_path, VIOL))
    assert r.passed is False
    assert r.summary["violations"] == 4  # 3 net + 1 pin


def test_missing_report_fails(tmp_path):
    (tmp_path / "reports" / "phase3").mkdir(parents=True)
    r = _check_antenna(tmp_path)
    assert r.passed is False
    assert r.summary["files_found"] == 0


def test_handtyped_stub_fails(tmp_path):
    # below MIN_REPORT_BYTES(antenna)=200 and no tool signature → not authentic
    r = _check_antenna(_proj(tmp_path, "antenna clean: YES\n"))
    assert r.passed is False


def test_cli_exit_codes(tmp_path):
    proj = _proj(tmp_path, CLEAN)
    rc = subprocess.run([sys.executable, str(PROGRAMS / "antenna_report_check.py"),
                         str(proj)]).returncode
    assert rc == 0
    proj2 = _proj(tmp_path / "v", VIOL)
    rc2 = subprocess.run([sys.executable, str(PROGRAMS / "antenna_report_check.py"),
                          str(proj2)]).returncode
    assert rc2 != 0
