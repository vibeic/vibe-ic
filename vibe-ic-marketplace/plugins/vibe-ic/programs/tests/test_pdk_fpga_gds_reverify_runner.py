#!/usr/bin/env python3
"""Tests for pdk_fpga_gds_reverify_runner.py — FPGA gate-level reverify
orchestrator (GDS → SOF + attestation).

The runner shells out to per-step helper programs + Quartus. To pin its
REAL orchestration logic deterministically, subprocess.run is mocked so
each test drives the program's actual decision branches:

  * IO error (rc 2) — project dir does not exist → main() returns 2
    BEFORE running any step (honest missing-data behavior).
  * post-compile-only PASS (rc 0) — the single attestation step succeeds
    → verdict PASS, report written with the one step.
  * post-compile-only FAIL (rc 1) — the attestation step fails → verdict
    FAIL (the real "no RTL fallback" gate firing).
  * StepResult.ok pins rc==0 semantics; _step turns a missing executable
    (FileNotFoundError) into rc 2.

chip-AGNOSTIC.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent / "pdk_fpga_gds_reverify_runner.py"

_spec = importlib.util.spec_from_file_location(
    "pdk_fpga_gds_reverify_runner", _PROG)
mod = importlib.util.module_from_spec(_spec)
# Register before exec so the @dataclass in the module can resolve its own
# __module__ in sys.modules (dataclasses._is_type needs this).
sys.modules["pdk_fpga_gds_reverify_runner"] = mod
_spec.loader.exec_module(mod)


# ----------------------------------------------------------------------
# StepResult / _step unit pins
# ----------------------------------------------------------------------
def test_stepresult_ok_semantics():
    assert mod.StepResult(step="x", cmd=[], rc=0).ok is True
    assert mod.StepResult(step="x", cmd=[], rc=1).ok is False


def test_step_missing_executable_is_rc2():
    r = mod._step("nope", ["/definitely/not/a/real/binary_xyz"])
    assert r.rc == 2
    assert not r.ok


# ----------------------------------------------------------------------
# IO / arg error — project dir absent
# ----------------------------------------------------------------------
def _base_argv(project):
    return [
        "--project", str(project),
        "--pnr-netlist", "phase3/pnr.v",
        "--pdk-behavioral", "pdk/beh.v",
        "--otp-hex", "input/otp.hex",
        "--rtl-chip-top", "rtl/chip_top.sv",
        "--rtl-chip-top-asic", "rtl/chip_top_asic.sv",
        "--fpga-qsf", "fpga/de10lite_top.qsf",
    ]


def test_missing_project_dir_returns_2(tmp_path, monkeypatch):
    # ensure no step ever runs.
    def boom(*a, **k):
        raise AssertionError("no step should run when project is missing")
    monkeypatch.setattr(mod, "_step", boom)
    rc = mod.main(_base_argv(tmp_path / "does_not_exist"))
    assert rc == 2


# ----------------------------------------------------------------------
# post-compile-only — attestation PASS / FAIL drives verdict
# ----------------------------------------------------------------------
class _CP:
    def __init__(self, rc, stdout="", stderr=""):
        self.returncode = rc
        self.stdout = stdout
        self.stderr = stderr


def _run_post_compile(tmp_path, monkeypatch, att_rc):
    project = tmp_path / "bench-a"
    project.mkdir()
    map_rpt = project / "de10lite_top.map.rpt"
    map_rpt.write_text("; Quartus map report\n")
    out_json = tmp_path / "report.json"

    def fake_run(cmd, **kw):
        # only the attestation helper is invoked in post-compile-only.
        return _CP(rc=att_rc, stdout="attest stdout", stderr="")

    monkeypatch.setattr(mod._pr, "run", fake_run)
    argv = _base_argv(project) + [
        "--post-compile-only", str(map_rpt),
        "--json", str(out_json),
    ]
    rc = mod.main(argv)
    report = json.loads(out_json.read_text())
    return rc, report


def test_post_compile_only_pass(tmp_path, monkeypatch):
    rc, report = _run_post_compile(tmp_path, monkeypatch, att_rc=0)
    assert rc == 0
    assert report["verdict"] == "PASS"
    assert report["phase"] == "post_compile_only"
    assert len(report["steps"]) == 1
    assert report["steps"][0]["step"] == "7-attestation"
    assert report["steps"][0]["rc"] == 0


def test_post_compile_only_fail(tmp_path, monkeypatch):
    """Attestation FAIL (e.g. RTL fallback detected) → overall FAIL,
    main() returns 1."""
    rc, report = _run_post_compile(tmp_path, monkeypatch, att_rc=1)
    assert rc == 1
    assert report["verdict"] == "FAIL"
    assert report["steps"][0]["rc"] == 1


# ----------------------------------------------------------------------
# pre-compile — step 1 failure short-circuits the chain
# ----------------------------------------------------------------------
def test_pre_compile_step1_fail_short_circuits(tmp_path, monkeypatch):
    project = tmp_path / "bench-b"
    project.mkdir()
    out_json = tmp_path / "r.json"

    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        # The first step (udp-shim) fails; chain must stop immediately.
        return _CP(rc=1, stdout="", stderr="shim failed")

    monkeypatch.setattr(mod._pr, "run", fake_run)
    argv = _base_argv(project) + ["--no-quartus", "--json", str(out_json)]
    rc = mod.main(argv)
    report = json.loads(out_json.read_text())
    assert rc == 1
    assert report["verdict"] == "FAIL"
    # only the first step ran (short-circuit on failure).
    assert len(report["steps"]) == 1
    assert report["steps"][0]["step"] == "1-udp-shim"
