#!/usr/bin/env python3
"""Tests for v0.119.52 (Wave 20) pre-burn flow_compliance ECO guard
in device_fpga_de10lite_program.

The driver's `mode_program()` calls `_run_flow_compliance_pre_burn(
project_root)` AFTER the RTL precheck gate clears, BEFORE checking
SOF existence. If flow_compliance reports `Overall: FAIL` with one
or more structural-gate failures, the burn is rejected with
`BURN_BLOCKED_STRUCTURAL_GATES_FAIL`. Caller may explicitly bypass
with `bypass_pre_burn_check=true` for emergency / oracle-burn flows.

We monkey-patch the helpers to drive the branches without invoking
real Quartus or the real flow_compliance script.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

DRIVER_PATH = (
    Path(__file__).resolve().parent.parent
    / "src" / "devices" / "fpga" / "terasic-de10lite" / "driver.py"
)
assert DRIVER_PATH.exists()


def _load_driver():
    spec = importlib.util.spec_from_file_location(
        "de10lite_driver_eco_guard_test", DRIVER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def driver():
    return _load_driver()


@pytest.fixture
def fake_project(tmp_path):
    """Build a project tree with an SOF inside fpga/output_files/ and
    a marker dir (rtl/) so _resolve_project_root_from_sof returns the
    tree root."""
    proj = tmp_path / "fake_project"
    proj.mkdir()
    (proj / "rtl").mkdir()
    (proj / "rtl" / "top.v").write_text("module top; endmodule\n")
    out_dir = proj / "fpga" / "output_files"
    out_dir.mkdir(parents=True)
    sof = out_dir / "top.sof"
    sof.write_bytes(b"\x00\x01\x02\x03")  # any bytes — we never burn
    return proj, sof


def _flow_returning(verdict: str, failed_gates=None, rc=None,
                    audit_json_present=True):
    """Fake `_run_flow_compliance_pre_burn` returning a controlled
    verdict + failed-gates list. Wave 30: also returns
    `audit_json_present` (defaults True for backward-compat tests)."""
    failed_gates = failed_gates or []
    if rc is None:
        rc = 0 if verdict in ("PASS", "PASS_WITH_WAIVERS") else 1

    def fake(project_root, timeout_s=180):
        return rc, {
            "flow_compliance_verdict": verdict,
            "exit_code": rc,
            "failed_gates": list(failed_gates),
            "audit_json_present": audit_json_present,
            "audit_json_path": f"{project_root}/reports/phase23_completion_audit.json",
            "stdout_tail": f"Overall: {verdict}\n",
            "stderr_tail": "",
            "command": ["/path/to/flow_compliance_check.py",
                        project_root,
                        "--phase", "2", "--strict-structural"],
        }
    return fake


def _stub_quartus_pgm(driver, monkeypatch):
    """Pretend quartus_pgm exists and the burn succeeded — we want the
    test to NOT fail on the real binary missing."""
    monkeypatch.setattr(
        driver, "_require_quartus_pgm", lambda: "/fake/quartus_pgm")
    monkeypatch.setattr(
        driver, "find_quartus_pgm", lambda: "/fake/quartus_pgm")

    def fake_run(cmd, timeout_s=110):
        return 0, ("Quartus Prime Programmer was successful. "
                   "Operations done.\n"), ""
    monkeypatch.setattr(driver, "run", fake_run)


def test_burn_allowed_when_flow_compliance_pass(
        driver, fake_project, monkeypatch):
    """flow_compliance Overall: PASS → burn proceeds (we stub the
    actual quartus_pgm subprocess)."""
    proj, sof = fake_project
    monkeypatch.setattr(
        driver, "_run_flow_compliance_pre_burn",
        _flow_returning("PASS"))
    _stub_quartus_pgm(driver, monkeypatch)

    rc, body = driver.mode_program({
        "sof_path": str(sof),
        "skip_rtl_precheck": True,  # focus on the new gate
    })
    assert rc == 0, body
    assert body.get("success") is True
    assert body["flow_compliance"][
        "flow_compliance_verdict"] == "PASS"


def test_burn_allowed_when_flow_compliance_pass_with_waivers(
        driver, fake_project, monkeypatch):
    """PASS_WITH_WAIVERS still proceeds (waivers represent deferred
    open work but are not blocking)."""
    proj, sof = fake_project
    monkeypatch.setattr(
        driver, "_run_flow_compliance_pre_burn",
        _flow_returning("PASS_WITH_WAIVERS"))
    _stub_quartus_pgm(driver, monkeypatch)

    rc, body = driver.mode_program({
        "sof_path": str(sof),
        "skip_rtl_precheck": True,
    })
    assert rc == 0, body
    assert body["flow_compliance"][
        "flow_compliance_verdict"] == "PASS_WITH_WAIVERS"


def test_burn_rejected_when_flow_compliance_fail(
        driver, fake_project, monkeypatch):
    """FAIL with structural gates listed → burn rejected with
    BURN_BLOCKED_STRUCTURAL_GATES_FAIL."""
    proj, sof = fake_project
    monkeypatch.setattr(
        driver, "_run_flow_compliance_pre_burn",
        _flow_returning(
            "FAIL",
            failed_gates=[
                "bram_init_file_actually_loaded_check",
                "wake_pulse_emit_gated_by_first_rx_command_check",
            ],
            rc=1,
        ))
    _stub_quartus_pgm(driver, monkeypatch)

    rc, body = driver.mode_program({
        "sof_path": str(sof),
        "skip_rtl_precheck": True,
    })
    assert rc == 1, body
    assert body.get("success") is False
    assert body.get("error") == "BURN_BLOCKED_STRUCTURAL_GATES_FAIL"
    assert "bram_init_file_actually_loaded_check" in body["failed_gates"]
    assert body["flow_compliance"][
        "flow_compliance_verdict"] == "FAIL"


def test_burn_allowed_when_bypass_pre_burn_check_true(
        driver, fake_project, monkeypatch, capsys):
    """bypass_pre_burn_check=true skips the gate — burn proceeds even
    when flow_compliance would have FAILed."""
    proj, sof = fake_project

    def should_not_run(*a, **kw):  # pragma: no cover
        raise AssertionError(
            "_run_flow_compliance_pre_burn should not be invoked when "
            "bypass_pre_burn_check=true")
    monkeypatch.setattr(
        driver, "_run_flow_compliance_pre_burn", should_not_run)
    _stub_quartus_pgm(driver, monkeypatch)

    rc, body = driver.mode_program({
        "sof_path": str(sof),
        "skip_rtl_precheck": True,
        "bypass_pre_burn_check": True,
    })
    assert rc == 0, body
    assert body.get("success") is True
    assert body["flow_compliance"]["skipped"] is True
    assert "bypass_pre_burn_check=true" in body[
        "flow_compliance"]["reason"]


def test_helpful_error_when_project_root_unresolvable(
        driver, tmp_path, monkeypatch):
    """SOF without surrounding project markers → flow_compliance
    soft-skips with a helpful reason; burn proceeds (but is also
    diagnosed in the response)."""
    bare_dir = tmp_path / "isolated"
    bare_dir.mkdir()
    sof = bare_dir / "stranded.sof"
    sof.write_bytes(b"\x00")

    def should_not_run(*a, **kw):  # pragma: no cover
        raise AssertionError(
            "_run_flow_compliance_pre_burn should not run when project "
            "root cannot be resolved")
    monkeypatch.setattr(
        driver, "_run_flow_compliance_pre_burn", should_not_run)
    _stub_quartus_pgm(driver, monkeypatch)

    rc, body = driver.mode_program({
        "sof_path": str(sof),
        "skip_rtl_precheck": True,
    })
    # Burn proceeds because we cannot run the audit — but diagnosis is
    # surfaced.
    assert rc == 0, body
    assert body["flow_compliance"]["skipped"] is True
    assert "could not resolve project root" in body[
        "flow_compliance"]["reason"]


def test_resolve_project_root_walks_up(driver, tmp_path):
    proj = tmp_path / "myproj"
    proj.mkdir()
    (proj / "generated_docs").mkdir()
    out = proj / "fpga" / "output_files"
    out.mkdir(parents=True)
    sof = out / "x.sof"
    sof.write_bytes(b"\x00")
    got = driver._resolve_project_root_from_sof(str(sof))
    assert got is not None
    assert Path(got).resolve() == proj.resolve()


# ====================================================================
# Wave 21 (v0.119.53) — pre-burn guard scope correction.
# `--strict-structural` must scope the burn-block to structural-RTL
# gate failures only. Step-level gate FAIL/MISSING is informational
# (surfaced as a warning on the burn response) and never blocks.
# ====================================================================


def _flow_returning_w21(verdict: str, failed_gates=None,
                        step_level_warnings=None, rc=None,
                        audit_json_present=True):
    """Wave-21 fake: also returns the step_level_warnings list that the
    new parser extracts from `Step-level gates (informational, not
    gating --strict-structural)` block. Wave 30 (v0.119.62): also
    returns `audit_json_present` so the new fail-closed branch can
    distinguish missing-audit-json from real-FAIL cases."""
    failed_gates = failed_gates or []
    step_level_warnings = step_level_warnings or []
    if rc is None:
        rc = 0 if verdict in ("PASS", "PASS_WITH_WAIVERS") else 1

    def fake(project_root, timeout_s=180):
        return rc, {
            "flow_compliance_verdict": verdict,
            "exit_code": rc,
            "failed_gates": list(failed_gates),
            "step_level_warnings": list(step_level_warnings),
            "audit_json_present": audit_json_present,
            "audit_json_path": f"{project_root}/reports/phase23_completion_audit.json",
            "stdout_tail": f"Overall: {verdict}\n",
            "stderr_tail": "",
            "command": ["/path/to/flow_compliance_check.py",
                        project_root,
                        "--phase", "2", "--strict-structural"],
        }
    return fake


def test_w21_step_level_warnings_surfaced_on_pass(
        driver, fake_project, monkeypatch):
    """Wave 21: structural gates PASS but step-level gates FAIL/MISSING
    → burn proceeds AND step-level warnings appear on the response."""
    proj, sof = fake_project
    monkeypatch.setattr(
        driver, "_run_flow_compliance_pre_burn",
        _flow_returning_w21(
            "PASS",
            step_level_warnings=[
                "step2 (Lint): FAIL — missing report",
                "step3 (CDC / RDC check): FAIL — missing crossing.json",
                "step4 (Verilator coverage): MISSING",
            ],
        ))
    _stub_quartus_pgm(driver, monkeypatch)

    rc, body = driver.mode_program({
        "sof_path": str(sof),
        "skip_rtl_precheck": True,
    })
    assert rc == 0, body
    assert body.get("success") is True
    assert "warnings" in body, body
    found = [w for w in body["warnings"]
             if w.get("kind") == "step_level_artifact_missing"]
    assert found, body["warnings"]
    assert len(found[0]["entries"]) == 3
    assert "step2" in found[0]["entries"][0]


def test_w30_verdict_fail_with_no_failed_gates_blocks_burn(
        driver, fake_project, monkeypatch):
    """Wave 30 (v0.119.62) regression: Overall: FAIL with empty
    failed_gates is now BLOCKED, not soft-skipped. This is the
    v0.119.61 35th-attempt root cause — the regex parser produced 0
    failed gates from 14 real structural FAILs and the burn was
    allowed. Fail-closed policy now blocks every non-PASS verdict
    regardless of the parsed failed_gates count."""
    proj, sof = fake_project
    monkeypatch.setattr(
        driver, "_run_flow_compliance_pre_burn",
        _flow_returning_w21(
            "FAIL",
            failed_gates=[],  # parser extracted nothing
            step_level_warnings=[
                "step5 (Formal verification): FAIL — missing all_proved",
            ],
            rc=1,
        ))
    _stub_quartus_pgm(driver, monkeypatch)

    rc, body = driver.mode_program({
        "sof_path": str(sof),
        "skip_rtl_precheck": True,
    })
    assert rc == 1, body
    assert body.get("success") is False
    assert body.get("error") == "BURN_BLOCKED_STRUCTURAL_GATES_FAIL"
    assert body.get("error_code") == "burn_blocked_verdict_fail_no_gates"


def test_w30_verdict_fail_audit_json_missing_blocks_burn(
        driver, fake_project, monkeypatch):
    """Wave 30 (v0.119.62): when phase23_completion_audit.json is
    missing, the burn is blocked with
    burn_blocked_audit_json_missing — agent never ran the self-audit."""
    proj, sof = fake_project
    monkeypatch.setattr(
        driver, "_run_flow_compliance_pre_burn",
        _flow_returning_w21(
            "FAIL",
            failed_gates=[],
            audit_json_present=False,
            rc=1,
        ))
    _stub_quartus_pgm(driver, monkeypatch)

    rc, body = driver.mode_program({
        "sof_path": str(sof),
        "skip_rtl_precheck": True,
    })
    assert rc == 1, body
    assert body.get("success") is False
    assert body.get("error_code") == "burn_blocked_audit_json_missing"


def test_w21_structural_fail_still_blocks_burn(
        driver, fake_project, monkeypatch):
    """Wave 21 regression: a real structural-RTL gate FAIL still
    blocks the burn (Wave 21 only changes the scope rules, not the
    burn-block discipline)."""
    proj, sof = fake_project
    monkeypatch.setattr(
        driver, "_run_flow_compliance_pre_burn",
        _flow_returning_w21(
            "FAIL",
            failed_gates=["otp_module_uses_supported_pattern_check"],
            step_level_warnings=[
                "step3: FAIL — missing crossing.json",
            ],
            rc=1,
        ))
    _stub_quartus_pgm(driver, monkeypatch)

    rc, body = driver.mode_program({
        "sof_path": str(sof),
        "skip_rtl_precheck": True,
    })
    assert rc == 1, body
    assert body.get("error") == "BURN_BLOCKED_STRUCTURAL_GATES_FAIL"
    assert "otp_module_uses_supported_pattern_check" in body["failed_gates"]
    # Step-level warnings must still be attached on the rejection too.
    assert body.get("step_level_warnings"), body


class TestASharedDirectoryIsNeverAProjectRoot:
    """`_resolve_project_root_from_sof` scores a directory by whether it
    CONTAINS a name like `input/`, `rtl/` or `waivers.json`.

    That is a PROXY for "this is a project root", and in a directory shared by
    every process on the box the proxy fires without the property. MEASURED on
    a fleet host: a stray `/tmp/waivers.json` left by an unrelated run in July
    made the resolver return `/tmp` for a SOF anywhere beneath it, so the
    pre-burn flow_compliance audit ran against `/tmp` as though it were the
    user's project.

    The failure that surfaced it is the shape worth remembering: the SAME
    COMMIT was green on a host with a clean `/tmp` and red on one without. A
    verdict that depends on another process's litter is not reproducible from
    the tree, so neither result could be believed.
    """

    def test_the_directories_no_project_can_own_are_refused(self, driver,
                                                            tmp_path):
        import os
        assert driver._is_shared_directory("/tmp") is True
        assert driver._is_shared_directory("/") is True
        assert driver._is_shared_directory(os.path.expanduser("~")) is True
        # …and an ordinary directory is still perfectly able to be a root.
        assert driver._is_shared_directory(str(tmp_path)) is False

    def test_a_marker_sitting_in_a_shared_directory_does_not_elect_it(
            self, driver, tmp_path, monkeypatch):
        """The regression, driven deterministically.

        `/tmp` cannot be used as the fixture — whether it carries a marker is
        exactly the machine-dependent fact this test exists to stop mattering.
        So a directory is DECLARED shared for the duration, a marker is planted
        in it, and the resolver must still refuse to elect it.

        Without the shared-directory filter this returns the planted directory
        and the test fails, which is the whole point of writing it this way.
        """
        shared = tmp_path / "shared"
        (shared / "deep" / "fpga").mkdir(parents=True)
        (shared / "waivers.json").write_text("{}")      # the stray marker
        sof = shared / "deep" / "fpga" / "stranded.sof"
        sof.write_bytes(b"\x00")

        # APPEND, never replace: replacing drops the real `/tmp` from the list,
        # and this walk passes through `/tmp` on the way up. The first draft of
        # this test replaced, and on a host with a stray `/tmp/waivers.json` the
        # resolver elected `/tmp` — the test reproduced the very bug it guards.
        monkeypatch.setattr(driver, "_SHARED_ROOTS",
                            driver._SHARED_ROOTS + (str(shared),))
        assert driver._resolve_project_root_from_sof(str(sof)) is None

    def test_a_real_project_under_a_shared_directory_is_still_found(
            self, driver, tmp_path, monkeypatch):
        """Refusing the shared directory must not refuse what is INSIDE it.

        Scratch checkouts genuinely live under `/tmp`, and a project there is
        a real project. Only the shared directory ITSELF is disqualified.
        """
        shared = tmp_path / "shared"
        project = shared / "myproj"
        (project / "fpga" / "output_files").mkdir(parents=True)
        (project / "rtl").mkdir()
        (project / "input").mkdir()
        (shared / "waivers.json").write_text("{}")      # the stray marker again
        sof = project / "fpga" / "output_files" / "top.sof"
        sof.write_bytes(b"\x00")

        # APPEND, never replace: replacing drops the real `/tmp` from the list,
        # and this walk passes through `/tmp` on the way up. The first draft of
        # this test replaced, and on a host with a stray `/tmp/waivers.json` the
        # resolver elected `/tmp` — the test reproduced the very bug it guards.
        monkeypatch.setattr(driver, "_SHARED_ROOTS",
                            driver._SHARED_ROOTS + (str(shared),))
        assert driver._resolve_project_root_from_sof(str(sof)) == str(project)
