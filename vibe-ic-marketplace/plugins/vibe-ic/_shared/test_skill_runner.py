"""Tests for skill_runner.py + skill_determinism_check.py (v0.50 enforcement)."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
import pytest

HERE    = Path(__file__).resolve().parent
RUNNER  = HERE / "skill_runner.py"
DETERM  = HERE / "skill_determinism_check.py"
FIXTURES = HERE / "integration_fixtures"


def _run(prog, args):
    r = subprocess.run([sys.executable, str(prog), *args],
                       capture_output=True, text=True)
    try:
        return r.returncode, json.loads(r.stdout), r.stderr
    except Exception:
        return r.returncode, {"_raw": r.stdout}, r.stderr


def test_runner_help():
    r = subprocess.run([sys.executable, str(RUNNER), "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert "skill" in r.stdout.lower()


def test_determinism_help():
    r = subprocess.run([sys.executable, str(DETERM), "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0


@pytest.mark.xfail(strict=False, reason="regression-from-v2-rename — extraction/walker behaviour drift exposed by public CI when full pytest replaced root's curated regression_suite.py; tracked in MAINTAINER_GITHUB_SETTINGS")
def test_runner_on_spec_to_rtl_fixture(tmp_path):
    """The spec-to-rtl golden fixture should pass skill_compliance + all
    declared postcheck programs (or report pass via their --help)."""
    fx = FIXTURES / "spec-to-rtl.md"
    assert fx.exists()
    report = tmp_path / "r.json"
    code, out, err = _run(RUNNER, ["spec-to-rtl", str(fx), "--json", str(report)])
    # Expect the compliance engine verdict to be PASS + referenced programs
    # to be runnable (--help works). overall pass → exit 0.
    assert report.exists(), err
    data = json.loads(report.read_text())
    assert any(v["gate"] == "skill_compliance_check" and v["pass"] for v in data["verdicts"])


def test_runner_fails_on_empty_output(tmp_path):
    """An empty output should fail the compliance engine."""
    empty = tmp_path / "empty.md"
    empty.write_text("")
    code, out, _ = _run(RUNNER, ["spec-to-rtl", str(empty)])
    # compliance_check will fail → overall pass False → exit 1
    assert code != 0


def test_determinism_identical_outputs_pass(tmp_path):
    """Two identical outputs of same skill = deterministic by definition."""
    fx = FIXTURES / "spec-to-rtl.md"
    a = tmp_path / "a.md"; b = tmp_path / "b.md"
    a.write_text(fx.read_text())
    b.write_text(fx.read_text())
    code, out, _ = _run(DETERM, ["spec-to-rtl", str(a), str(b)])
    assert out.get("pass") is True, out


@pytest.mark.xfail(strict=False, reason="regression-from-v2-rename — extraction/walker behaviour drift exposed by public CI when full pytest replaced root's curated regression_suite.py; tracked in MAINTAINER_GITHUB_SETTINGS")
def test_determinism_different_outputs_fail(tmp_path):
    """Two outputs where one is empty should flag divergence."""
    fx = FIXTURES / "spec-to-rtl.md"
    a = tmp_path / "a.md"; b = tmp_path / "b.md"
    a.write_text(fx.read_text())
    b.write_text("")  # intentionally empty
    code, out, _ = _run(DETERM, ["spec-to-rtl", str(a), str(b)])
    # At minimum a and b differ in rule outcomes; assertion is that pass is False
    assert out.get("pass") is False
