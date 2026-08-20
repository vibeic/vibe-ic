#!/usr/bin/env python3
"""Tests for memory_read_pipeline_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "memory_read_pipeline_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_clean_rtl(tmp_path):
    """v1.6.125 (#47 Fix 3) — registered_read_undocumented is a WARN
    finding. Per #47 spec, WARN-only must NOT gate the flow. Earlier
    behaviour escalated WARN to exit 1; corrected to exit 0 with
    verdict=WARN surfaced via JSON for visibility.
    """
    rtl = tmp_path / "mem.v"
    rtl.write_text("module mem(input clk, input [7:0] addr, output reg [7:0] data);\n  reg [7:0] ram [0:255];\n  always @(posedge clk) data <= ram[addr];\nendmodule\n")
    r = _run([str(tmp_path)])
    assert r.returncode == 0  # WARN-only no longer gates the flow.


def _finding_severities() -> set:
    """Severity literal of every ``Finding(...)`` this program constructs.

    Read from the AST, not from a run: a severity that only one rare input
    reaches is still a severity the program CAN emit, and the exit-code
    contract has to account for it.
    """
    import ast
    tree = ast.parse(PROG.read_text())
    out = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Finding"):
            first = None
            if node.args:
                first = node.args[0]
            else:
                for kw in node.keywords:
                    if kw.arg == "severity":
                        first = kw.value
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                out.add(first.value)
    return out


def _documents_content_exit_one() -> bool:
    """Does the module docstring's `Exit codes` table advertise a `1 = ...`?"""
    import ast
    doc = ast.get_docstring(ast.parse(PROG.read_text())) or ""
    body = doc.split("Exit codes", 1)[-1]
    return any(line.strip().startswith("1 =") for line in body.splitlines())


def test_the_documented_exit_codes_match_the_reachable_ones():
    """A blocking clause may not advertise an exit its code cannot produce.

    The flow declares this program under `optional_program_exit_zero`, which
    BLOCKS on a non-zero exit. `main()` returns 1 only when `verdict == "FAIL"`,
    and `verdict` is "FAIL" only when some `Finding` carries severity "FAIL".
    So the two halves must agree:

      a FAIL severity exists   <=>  the exit table documents a content `1 = ...`

    Both directions are load-bearing. Left-to-right: the day someone makes an
    undocumented registered read blocking, this table must say so, and whether
    the flow should keep blocking on it gets re-decided in that same change.
    Right-to-left is the one that was RED when this test was written — the
    table promised `1 = at least one memory module has undeclared read latency`
    while every Finding in the file was a WARN, so the clause could not block
    on the very defect the gate is named for.
    """
    severities = _finding_severities()
    assert severities, (
        "no `Finding(...)` construction found — the AST reader is broken, and a "
        "guard that reads nothing would pass on any program")
    can_fail = "FAIL" in severities
    documented = _documents_content_exit_one()
    assert can_fail == documented, (
        f"exit-code contract disagrees with the code: severities constructed = "
        f"{sorted(severities)} (FAIL reachable: {can_fail}), while the module "
        f"docstring's `Exit codes` table "
        f"{'DOES' if documented else 'does NOT'} document a content `1 = ...`. "
        f"A gate wired under `optional_program_exit_zero` blocks on a non-zero "
        f"exit; if no FAIL severity is constructible the clause cannot block on "
        f"content, and the table must not say otherwise.")
