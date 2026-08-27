#!/usr/bin/env python3
"""Tests for pdk_yosys_flatten_for_quartus.py — Quartus-SGN-crash flatten.

The program shells out to Yosys-in-docker + the atpg name harmoniser. To
pin its REAL control-flow deterministically (no dependence on container
state / yosys version), subprocess.run is mocked so each test drives one
of the program's actual decision branches:

  * PASS (rc 0) — yosys succeeds, output file is non-trivial, harmoniser
    succeeds → main() returns 0 and writes the harmonised output.
  * FAIL (rc 2) — yosys returns nonzero OR prints ERROR → return 2.
  * FAIL (rc 2) — yosys "succeeds" but the output file is missing/tiny
    (the real "yosys output missing" guard) → return 2.
  * FAIL (rc 2) — harmoniser returns nonzero → return 2.

Also pins the pure docker-path mapping helper and the YS template.
chip-AGNOSTIC.
"""
from __future__ import annotations

import importlib.util
import subprocess as _subprocess
import sys
import types
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent / "pdk_yosys_flatten_for_quartus.py"

_spec = importlib.util.spec_from_file_location(
    "pdk_yosys_flatten_for_quartus", _PROG)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


# ----------------------------------------------------------------------
# pure helpers — YS template + docker path mapping
# ----------------------------------------------------------------------
def test_ys_template_substitutes_all_fields():
    ys = mod.YS_TEMPLATE.format(
        pdk_shim="/x/shim.v", gate_netlist="/x/gate.v",
        top="chip_top_asic", out_path="/x/flat.v")
    assert "read_verilog /x/shim.v" in ys
    assert "read_verilog /x/gate.v" in ys
    assert "hierarchy -top chip_top_asic -check" in ys
    assert "flatten" in ys
    assert "write_verilog -noattr /x/flat.v" in ys


# ----------------------------------------------------------------------
# main() control-flow — subprocess.run mocked
# ----------------------------------------------------------------------
def _argv(tmp_path, out_name="flat.v"):
    gate = tmp_path / "gate.v"
    shim = tmp_path / "shim.v"
    gate.write_text("module chip_top_asic(); endmodule\n")
    shim.write_text("// shim\n")
    out = tmp_path / out_name
    return [
        "prog",
        "--gate-netlist", str(gate),
        "--pdk-shim", str(shim),
        "--top", "chip_top_asic",
        "--output", str(out),
    ], out


class _CP:
    def __init__(self, rc=0, stdout="", stderr=""):
        self.returncode = rc
        self.stdout = stdout
        self.stderr = stderr


def _declare_the_host_root(monkeypatch, tmp_path):
    """State the container mount pair instead of letting it be DISCOVERED.

    MEASURED, and the reason every test below needed it: `_patch_subprocess`
    installs its double on the SHARED `subprocess` module object, so it is not
    only the yosys launch that goes through it -- `_designs_root.container_mounts`
    reaches `docker inspect` through `subprocess.check_output`, which calls the
    module-global `run`, and the double answers it with an empty stdout. The
    mount table then parses as NOTHING:

        real mounts  2   -> basis container_mount
        faked mounts 0   -> basis undecided / project_dir_fallback

    So `main()` BLOCKED on an unmeasurable host root and returned 2 before it
    ever reached the behaviour under test. `test_main_pass` failed on it; the
    arms that assert rc == 2 PASSED on it, for a refusal that has nothing to do
    with yosys -- the same word for a different finding.

    Declaring the pair through the program's own documented input (option (b) in
    its refusal message) removes the discovery step from these tests entirely, so
    they answer the same on a host with a running EDA container and on one
    without.
    """
    monkeypatch.setenv("VIBEIC_DESIGNS_HOST_ROOT", str(tmp_path))
    monkeypatch.setenv("VIBEIC_DESIGNS_CONT_ROOT", "/foss/designs")


def _patch_subprocess(monkeypatch, behaviors):
    """behaviors: callable(cmd) -> _CP. Records calls for inspection."""
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return behaviors(cmd, calls)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    return calls


def test_main_pass(tmp_path, monkeypatch):
    argv, out = _argv(tmp_path)
    _declare_the_host_root(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", argv)
    tmp = out.resolve().parent / ".tmp_flatten"

    def behavior(cmd, calls):
        # First call = yosys-in-docker; create a non-trivial flat output.
        if "docker" in cmd[0]:
            (tmp / "flat_raw.v").write_text("module x();\n" * 50)
            return _CP(rc=0, stdout="stat\n  cells 1234\n")
        # Second call = the name harmoniser; create the final output.
        out.write_text("module x();\n" * 50)
        return _CP(rc=0, stdout="")

    _patch_subprocess(monkeypatch, behavior)
    rc = mod.main()
    assert rc == 0
    assert out.is_file()


def test_main_yosys_fail_returns_2(tmp_path, monkeypatch):
    argv, out = _argv(tmp_path)
    _declare_the_host_root(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", argv)

    def behavior(cmd, calls):
        return _CP(rc=1, stdout="ERROR: hierarchy check failed")

    _patch_subprocess(monkeypatch, behavior)
    assert mod.main() == 2


def test_main_yosys_error_string_returns_2(tmp_path, monkeypatch):
    """rc 0 but 'ERROR' in stdout is still a yosys failure (real guard)."""
    argv, out = _argv(tmp_path)
    _declare_the_host_root(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", argv)

    def behavior(cmd, calls):
        return _CP(rc=0, stdout="something ERROR something")

    _patch_subprocess(monkeypatch, behavior)
    assert mod.main() == 2


def test_main_yosys_output_missing_returns_2(tmp_path, monkeypatch):
    """yosys reports success but produces no (or a too-small) file."""
    argv, out = _argv(tmp_path)
    _declare_the_host_root(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", argv)

    def behavior(cmd, calls):
        # don't create flat_raw.v at all.
        return _CP(rc=0, stdout="stat\n")

    _patch_subprocess(monkeypatch, behavior)
    assert mod.main() == 2


def test_main_harmonise_fail_returns_2(tmp_path, monkeypatch):
    argv, out = _argv(tmp_path)
    _declare_the_host_root(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", argv)
    tmp = out.resolve().parent / ".tmp_flatten"

    def behavior(cmd, calls):
        if "docker" in cmd[0]:
            (tmp / "flat_raw.v").write_text("module x();\n" * 50)
            return _CP(rc=0, stdout="stat\n")
        # harmoniser fails.
        return _CP(rc=3, stdout="", stderr="bad escape ids")

    _patch_subprocess(monkeypatch, behavior)
    assert mod.main() == 2
