#!/usr/bin/env python3
"""v0.114.1 (issue #32) — pre-burn audit must forward
`--allow-thin-input` to flow_compliance_check.py so that legitimate
thin-input WAIVED-DEFERRED gates (ticket=thin-input-v1.6.97) propagate
as PASS_WITH_WAIVERS instead of raw FAIL.

Background: the plugin's `--allow-thin-input` flag is itself gated by
the v1.6.98 coverage-shape predicate — only projects whose input docs
have genuine thin-input shape become eligible. Thick-input projects
with the same gates STAY FAIL even when this flag is set, so passing
it unconditionally from the pre-burn audit cannot weaken the burn-
block for normal projects. It just unblocks the legitimate thin-input
case.

These tests:
  * positive: cmd list passed to subprocess.run contains
    `--allow-thin-input`
  * reject  : `--strict-structural` and `--phase 2` are still present
              (didn't accidentally remove the existing flags)
  * happy   : when the mocked subprocess returns 0, the function
              honors the existing success contract (verdict=PASS or
              UNKNOWN; exit_code is the real subprocess returncode).
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

DRIVER_PATH = (
    Path(__file__).resolve().parent.parent
    / "src" / "devices" / "fpga" / "terasic-de10lite" / "driver.py"
)
assert DRIVER_PATH.exists(), DRIVER_PATH


def _load_driver():
    spec = importlib.util.spec_from_file_location(
        "de10lite_driver_pre_burn_audit_test", DRIVER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def driver():
    return _load_driver()


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _force_plugin_program(monkeypatch, driver, fake_path):
    monkeypatch.setattr(
        driver, "_find_plugin_program",
        lambda name: str(fake_path),
    )


def _capture_argv(monkeypatch, driver):
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = list(argv)
        captured["kwargs"] = kwargs
        return _FakeCompleted(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(driver.subprocess, "run", fake_run)
    return captured


def test_pre_burn_audit_subprocess_includes_allow_thin_input(
        monkeypatch, driver, tmp_path):
    """Positive: the subprocess invocation MUST include --allow-thin-input."""
    fake_gate = tmp_path / "flow_compliance_check.py"
    fake_gate.write_text("# fake\n")
    _force_plugin_program(monkeypatch, driver, fake_gate)
    captured = _capture_argv(monkeypatch, driver)

    project = tmp_path / "project"
    project.mkdir()
    driver._run_flow_compliance_pre_burn(str(project))

    argv = captured["argv"]
    assert "--allow-thin-input" in argv, (
        "pre-burn audit must forward --allow-thin-input to "
        "flow_compliance_check.py — see issue #32. argv was: "
        f"{argv}"
    )


def test_pre_burn_audit_still_passes_strict_structural(
        monkeypatch, driver, tmp_path):
    """Reject: existing flags must still be present."""
    fake_gate = tmp_path / "flow_compliance_check.py"
    fake_gate.write_text("# fake\n")
    _force_plugin_program(monkeypatch, driver, fake_gate)
    captured = _capture_argv(monkeypatch, driver)

    project = tmp_path / "project"
    project.mkdir()
    driver._run_flow_compliance_pre_burn(str(project))

    argv = captured["argv"]
    assert "--strict-structural" in argv, (
        f"--strict-structural was lost. argv: {argv}")
    # --phase 2 must appear as adjacent tokens
    assert "--phase" in argv, f"--phase was lost. argv: {argv}"
    phase_idx = argv.index("--phase")
    assert argv[phase_idx + 1] == "2", (
        f"--phase value must remain '2', got: {argv[phase_idx + 1]}")
    # project root must still be the first positional after the script
    assert str(project) in argv, (
        f"project_root was lost. argv: {argv}")


def test_pre_burn_audit_returns_pass_when_subprocess_returncode_zero(
        monkeypatch, driver, tmp_path):
    """Happy path: returncode=0 from subprocess flows through to caller."""
    fake_gate = tmp_path / "flow_compliance_check.py"
    fake_gate.write_text("# fake\n")
    _force_plugin_program(monkeypatch, driver, fake_gate)
    _capture_argv(monkeypatch, driver)

    project = tmp_path / "project"
    project.mkdir()
    rc, report = driver._run_flow_compliance_pre_burn(str(project))

    # Contract from the docstring: exit_code 0 = safe to burn. The function
    # may parse the audit JSON for richer detail but at minimum the
    # exit_code surface must reflect the subprocess returncode.
    assert rc == 0, (
        f"expected exit_code==0 when subprocess returncode==0, got rc={rc} "
        f"report={report}")
    assert isinstance(report, dict), (
        f"report must be a dict, got: {type(report).__name__}")


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
