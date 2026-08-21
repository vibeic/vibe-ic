#!/usr/bin/env python3
"""Tests for dispatcher_awake_gate_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "dispatcher_awake_gate_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_skip_no_rtl(tmp_path):
    r = _run([str(tmp_path)])
    assert r.returncode == 0


# --- the exit code, and the argv that made it untestable

def test_main_takes_argv_at_all():
    """`gate_cli_mutation_probe` reported this gate SILENT, and the cause was
    not a missing test — it was that no test COULD exist.

    `def main():` read `sys.argv` unconditionally, so nothing could drive it
    with arguments. 200 of the other gates here take `main(argv=None)`; this one
    did not, and the path from verdict to exit code was therefore unreachable
    from a test.
    """
    import inspect
    import dispatcher_awake_gate_check as D
    assert "argv" in inspect.signature(D.main).parameters, \
        "main() ignores its arguments, so no test can drive it"


def test_main_refuses_on_a_missing_project(tmp_path):
    """rc 2 — could not ask, which is not a pass."""
    import dispatcher_awake_gate_check as D
    assert D.main([str(tmp_path / "nope")]) == 2


def test_main_exits_zero_when_the_spec_says_wake_is_not_required(tmp_path,
                                                                 monkeypatch):
    """The documented skip: a design that declares wake_required=false has
    nothing for this gate to check, and says so."""
    import dispatcher_awake_gate_check as D
    monkeypatch.setattr(D, "_l2_l9_wake_required", lambda p: False)
    assert D.main([str(tmp_path)]) == 0


def test_no_dispatcher_is_a_documented_skip_not_a_failure(tmp_path, monkeypatch):
    """My first version asserted rc 1 here. It is rc 0 BY DESIGN — the branch
    prints "(skip — no dispatcher)" and records `"pass": true`. A design with
    no dispatcher RTL has nothing for this gate to check, and inventing a
    failure there would have enforced the opposite of a recorded decision."""
    import dispatcher_awake_gate_check as D
    monkeypatch.setattr(D, "_l2_l9_wake_required", lambda p: True)
    monkeypatch.setattr(D, "_find_dispatcher", lambda p: None)
    assert D.main([str(tmp_path)]) == 0


def test_a_dispatcher_with_no_awake_gate_exits_non_zero(tmp_path):
    """The real failure path, driven by RTL rather than by stubbing.

    Two wrong turns getting here, both from guessing instead of reading:
    monkeypatching `audit()`/`_audit_dispatcher()` (neither exists — the
    findings are built inline in `main()`), then putting the RTL in `rtl/`
    (the program resolves `phase2/stage1/rtl` through the project layout).
    """
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "dispatcher.v").write_text(
        "module cmd_dispatcher (input clk, input rstn, input awake_q,\n"
        "                       input [7:0] op, output reg do_cmd);\n"
        "    always @(posedge clk) begin\n"
        "        case (op)\n"
        "            8'h01: do_cmd <= 1'b1;\n"
        "            8'h02: do_cmd <= 1'b1;\n"
        "            default: do_cmd <= 1'b0;\n"
        "        endcase\n"
        "    end\n"
        "endmodule\n")
    r = _run([str(tmp_path)])
    assert r.returncode == 1, (
        "an ungated dispatcher exited %d\n%s%s" % (r.returncode, r.stdout, r.stderr))
