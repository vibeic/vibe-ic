#!/usr/bin/env python3
"""ORGANIC (GAP-E2E-5) — reference_tb SV-subset WAIVE for REUSED-IP.

An SV construct beyond the iverilog/sv2v OSS-sim subset (e.g. OpenTitan's
cross-package `pkg::PARAM` in a param default) blocks the reference_tb COMPILE
even though yosys+slang synthesises the SAME RTL clean. For an upstream-validated
REUSED-IP DUT that is a tool-subset limit, NOT a design defect → demote to a
DISCLOSED WAIVE, not a hard phase2 FAIL.

§4.05 NO-LEAK (load-bearing): demote ONLY when (a) the failure carries a genuine
SV-construct/syntax signature (NOT a missing-module / port structural defect) AND
(b) the project is REUSED-IP (SOURCE_MANIFEST reused_ip:true). An authored
(non-reused) RTL, or a real structural error, still hard-FAILs.

chip-AGNOSTIC: synthetic fixtures + the shared signature set.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import design_one_shot_runner as D   # noqa: E402


def _mk_project(tmp_path, reused_ip: bool) -> Path:
    project = tmp_path / "proj"
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "dut.sv").write_text("module dut(); endmodule\n")
    if reused_ip is not None:
        (rtl / "SOURCE_MANIFEST.json").write_text(
            json.dumps({"reused_ip": bool(reused_ip)}))
    return project


def test_is_reused_ip_project(tmp_path):
    assert D._is_reused_ip_project(_mk_project(tmp_path / "a", True)) is True
    assert D._is_reused_ip_project(_mk_project(tmp_path / "b", False)) is False
    # no manifest at all
    p = tmp_path / "c" / "proj"
    (p / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    assert D._is_reused_ip_project(p) is False


def _drive_oracle_with_compile(monkeypatch, tmp_path, reused_ip, compile_err):
    """Run _run_oracle_tb with iverilog present + the compile forced to FAIL
    with `compile_err`. Returns the StepResult (or None)."""
    project = _mk_project(tmp_path, reused_ip)
    tb = project / "phase2" / "stage1" / "sim_full_stack" / "tb.v"
    tb.parent.mkdir(parents=True, exist_ok=True)
    tb.write_text("module tb; endmodule\n")
    import shutil
    monkeypatch.setattr(shutil, "which", lambda _n: "/usr/bin/iverilog")
    # force the compile-with-sv-fallback to FAIL with the given signature
    monkeypatch.setattr(
        D, "_iverilog_compile_with_sv_fallback",
        lambda *a, **k: (2, "", compile_err, "iverilog_g2012"))
    return D._run_oracle_tb(project, "dut", tb, "test", 0.0, "vibeic-eda")


_SV_SUBSET_ERR = "aes_pkg.sv:19: sorry: constant selects not supported"
_REAL_DEFECT_ERR = "error: Unknown module type: missing_child_module"


def test_sv_subset_on_reused_ip_is_waived(monkeypatch, tmp_path):
    r = _drive_oracle_with_compile(monkeypatch, tmp_path, True, _SV_SUBSET_ERR)
    assert r is not None and r.status == "WAIVED"
    assert r.extras.get("sv_subset_waived") is True


def test_sv_subset_on_authored_rtl_still_fails(monkeypatch, tmp_path):
    # §4.05 NO-LEAK: non-reused (authored) RTL must NOT be waived.
    r = _drive_oracle_with_compile(monkeypatch, tmp_path, False, _SV_SUBSET_ERR)
    assert r is not None and r.status == "FAIL"


def test_real_defect_on_reused_ip_still_fails(monkeypatch, tmp_path):
    # §4.05 NO-LEAK: a real missing-module defect (no SV signature) must NOT be
    # waived even on a REUSED-IP design.
    r = _drive_oracle_with_compile(monkeypatch, tmp_path, True, _REAL_DEFECT_ERR)
    assert r is not None and r.status == "FAIL"
