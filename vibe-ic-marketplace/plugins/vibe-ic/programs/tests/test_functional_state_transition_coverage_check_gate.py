#!/usr/bin/env python3
"""Tests for functional_state_transition_coverage_check.py"""
from __future__ import annotations
import subprocess, sys, json
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "functional_state_transition_coverage_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_with_cov(tmp_path):
    # This fixture used to be a bare $display and it still exited 0 — but
    # for the wrong reason: the file is named `tb.v`, which matched none of
    # the gate's four discovery globs, so the gate scanned ZERO files and
    # reported PASS. The rc==0 was never earned. The fixture now actually
    # drives the opcode and asserts the side-effect, and the assertion
    # below checks the gate read something before certifying it.
    tb = tmp_path / "tb.v"
    tb.write_text(
        "module tb;\n"
        "  initial begin\n"
        "    send_cmd(8'h74);\n"
        "    #10;\n"
        "    if (awake_q !== 1'b1) $fatal;\n"
        "    $finish;\n"
        "  end\n"
        "endmodule\n"
    )
    out = tmp_path / "rep.json"
    r = _run([str(tmp_path), "--cov", "0x74:awake_q == 1'b1", "--json", str(out)])
    assert r.returncode == 0
    data = json.loads(out.read_text())
    assert data["verdict"] == "PASS"
    assert data["tb_files_scanned"] == 1, "a PASS must have read a testbench"
