#!/usr/bin/env python3
"""Tests for v0.99.3 per-auditor waive_auditors logic in
device_fpga_de10lite_program.

The driver's `mode_program()` runs an RTL precheck gate; if any auditor
fails, the burn is hard-blocked unless one of the override paths fires:

  - allow_known_bugs=true       — blanket override (legacy)
  - waive_auditors=[name, ...]  — per-auditor (v0.99.3)

For waive_auditors, the contract is:
  * EVERY failing auditor must appear in the waive list → status
    becomes PASS_WITH_WAIVER and the burn proceeds.
  * If even ONE failing auditor is unwaived → still hard-blocks
    (returns the precheck_failed error code).

We exercise both paths by monkey-patching `_run_rtl_precheck_gate` to
return a controlled failure report, then calling `mode_program` and
asserting on the structured response. The Quartus binary is never
invoked because the test SOF path is fake — the precheck gate is the
only branch reached.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

DRIVER_PATH = (
    Path(__file__).resolve().parent.parent
    / "src" / "devices" / "fpga" / "terasic-de10lite" / "driver.py"
)
assert DRIVER_PATH.exists()


def _load_driver():
    """Import driver.py as a module without polluting sys.modules globals."""
    spec = importlib.util.spec_from_file_location(
        "de10lite_driver_under_test", DRIVER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def driver():
    return _load_driver()


@pytest.fixture
def fake_rtl_dir(tmp_path):
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "top.v").write_text("module top; endmodule\n")
    return rtl


def _gate_returning(failing_auditor_names):
    """Build a fake `_run_rtl_precheck_gate` returning rc=1 with a
    report listing the given auditor names as failed."""
    def fake(rtl_dir, l12_json):
        return 1, {
            "skipped": False,
            "auditors": [
                {"name": n, "passed": False, "stdout": "boom"}
                for n in failing_auditor_names
            ],
        }
    return fake


def test_all_failures_waived_proceeds_to_sof_check(
        driver, fake_rtl_dir, monkeypatch, tmp_path):
    """When every failing auditor is in waive_auditors, the precheck
    branch resolves to PASS_WITH_WAIVER and execution falls through to
    the SOF existence check. We supply a missing SOF path so the next
    error is `InvalidArgumentError(sof_path not found)` — proof we got
    past the precheck.

    v0.119.52 (Wave 20): also stub out the pre-burn flow_compliance
    gate so it does not interfere with the precheck-path test. The
    flow_compliance gate has its own dedicated test file
    (test_device_program_eco_guard.py).
    """
    monkeypatch.setattr(driver, "_run_rtl_precheck_gate",
                        _gate_returning(["pulse_decoder_edge_check",
                                         "fsm_error_invariant"]))
    monkeypatch.setattr(
        driver, "_run_flow_compliance_pre_burn",
        lambda root, timeout_s=180: (0, {
            "flow_compliance_verdict": "PASS",
            "exit_code": 0, "failed_gates": [],
            "stdout_tail": "Overall: PASS\n",
            "stderr_tail": "",
            "command": ["test-stub"],
        }))
    fake_sof = str(tmp_path / "does_not_exist.sof")
    with pytest.raises(driver.InvalidArgumentError) as exc:
        driver.mode_program({
            "sof_path":       fake_sof,
            "rtl_dir":        str(fake_rtl_dir),
            "waive_auditors": ["pulse_decoder_edge_check",
                               "fsm_error_invariant"],
        })
    assert "sof_path not found" in str(exc.value), \
        "expected to reach SOF check; precheck must have been waived"
    # Also assert the waiver was recorded in the error context.
    ctx = getattr(exc.value, "context", {}) or {}
    pre = ctx.get("rtl_precheck", {})
    assert pre.get("status") == "PASS_WITH_WAIVER", \
        f"expected PASS_WITH_WAIVER, got: {pre}"
    assert sorted(pre.get("waived_auditors", [])) == [
        "fsm_error_invariant", "pulse_decoder_edge_check"]


def test_partial_waiver_still_hard_blocks(
        driver, fake_rtl_dir, monkeypatch, tmp_path):
    """If only SOME failing auditors are waived, the burn must still
    fail with status=precheck_failed and `unwaived_failures` listing
    the leftovers."""
    monkeypatch.setattr(driver, "_run_rtl_precheck_gate",
                        _gate_returning(["pulse_decoder_edge_check",
                                         "tristate_active_drive_check"]))
    rc, resp = driver.mode_program({
        "sof_path":       str(tmp_path / "any.sof"),
        "rtl_dir":        str(fake_rtl_dir),
        "waive_auditors": ["pulse_decoder_edge_check"],   # only 1 of 2
    })
    assert rc == 1
    assert resp["success"] is False
    assert resp["error_code"] == "precheck_failed"
    assert resp["context"]["unwaived_failures"] == [
        "tristate_active_drive_check"], \
        f"expected tristate_active_drive_check unwaived, got: {resp}"


def test_empty_waive_list_blocks_unchanged(
        driver, fake_rtl_dir, monkeypatch, tmp_path):
    """Sanity: with no waive_auditors and no allow_known_bugs, behavior
    is the legacy hard-block — unchanged from pre-v0.99.3."""
    monkeypatch.setattr(driver, "_run_rtl_precheck_gate",
                        _gate_returning(["pulse_decoder_edge_check"]))
    rc, resp = driver.mode_program({
        "sof_path": str(tmp_path / "any.sof"),
        "rtl_dir":  str(fake_rtl_dir),
    })
    assert rc == 1
    assert resp["error_code"] == "precheck_failed"
    assert "unwaived_failures" in resp["context"]


def test_waive_auditors_must_be_list(driver, fake_rtl_dir, tmp_path):
    """Type-validation: passing a string instead of a list must raise
    InvalidArgumentError early, BEFORE the precheck runs (so a typo
    can't accidentally degrade gating to no-op)."""
    with pytest.raises(driver.InvalidArgumentError):
        driver.mode_program({
            "sof_path":       str(tmp_path / "any.sof"),
            "rtl_dir":        str(fake_rtl_dir),
            "waive_auditors": "pulse_decoder_edge_check",  # wrong type
        })
