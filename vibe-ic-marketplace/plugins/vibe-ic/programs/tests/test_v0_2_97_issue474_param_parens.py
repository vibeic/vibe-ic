#!/usr/bin/env python3
"""Tests for GitHub #474 (MEDIUM) — balanced-paren handling in the
module-header parameter block of l9_rtl_pin_consistency_check.py.

THE DEFECT (現象)
=================
parse_rtl_top_ports() pre-fixed the optional parameter port list with
the regex fragment `#\\s*\\([^)]*\\)`. `[^)]*` cannot span nested
parens, so a parameter default containing a function call — e.g.

    module my_top #(parameter aw = $clog2(memsize)) ( ... );

closed the parameter block at the INNER `)` of `$clog2(memsize)`,
leaving the REAL port list unmatched. The port-list regex then failed,
parse_rtl_top_ports() returned [], and the gate emitted the end-state

    FAIL — RTL top <file> parsed zero ports — either the module
    declaration is malformed or the regex failed; investigate.

THE FIX
=======
A balanced-paren depth-counter scanner (`_strip_param_block`) splices
out the entire `#(...)` span — arbitrary nesting — BEFORE the port-list
regex runs, so the real ports are parsed.

ACCEPTANCE DOCTRINE
===================
test_acceptance_end_to_end_zero_ports_error_gone builds a defect-artifact
fixture shaped exactly like the issue's 現象 (a real project tree with an
L9 doc + an RTL top whose parameter default holds a function call) and
EXECUTES the program end-to-end (subprocess, the real gate invocation),
asserting the END state: the 'parsed zero ports' FAIL is gone and the
gate now reports a real port comparison.
"""
from __future__ import annotations
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

PROG = (
    Path(__file__).resolve().parent.parent / "l9_rtl_pin_consistency_check.py"
)


# ─── load parse helpers directly (cwd=programs so sibling imports work) ─
def _load_module():
    progs = PROG.parent
    spec = importlib.util.spec_from_file_location(
        "l9_pin_mod_474", str(PROG)
    )
    mod = importlib.util.module_from_spec(spec)
    old = sys.path[:]
    sys.path.insert(0, str(progs))
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path[:] = old
    return mod


MOD = _load_module()


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _parse(tmp_path: Path, name: str, src: str) -> list[dict]:
    f = tmp_path / f"{name}.sv"
    f.write_text(src)
    return MOD.parse_rtl_top_ports(f)


# ─── unit: the exact defect shape now parses the real ports ───────────
def test_param_default_with_function_call_parses_real_ports(tmp_path):
    ports = _parse(tmp_path, "fn_default", """
module my_top #(
  parameter aw = $clog2(memsize),
  parameter dw = 32
) (
  input  wire clk,
  input  wire rst_n,
  output wire ready
);
endmodule
""")
    names = [p["name"] for p in ports]
    assert names == ["clk", "rst_n", "ready"], names
    # The fix must NOT have swallowed the port list (regression on #474).
    assert ports != []


# ─── nastier shape 1: nested function calls in a default ──────────────
def test_nested_function_call_default(tmp_path):
    ports = _parse(tmp_path, "nested", """
module n_top #(parameter W = $clog2($max(A, B) + 1)) (
  input  wire clk,
  output wire done
);
endmodule
""")
    assert [p["name"] for p in ports] == ["clk", "done"]


# ─── nastier shape 2: multiple params, parens in defaults, line breaks ─
def test_multiple_params_with_calls_and_linebreaks(tmp_path):
    ports = _parse(tmp_path, "multi", """
module m_top
#(
  parameter A = $clog2(N),
  parameter B = (A + 1),
  parameter C = func(x, y, z)
)
(
  input  wire        clk,
  input  wire        rst,
  output wire [7:0]  data,
  inout  wire        io_pin
);
endmodule
""")
    assert [p["name"] for p in ports] == ["clk", "rst", "data", "io_pin"]
    dirs = {p["name"]: p["direction"] for p in ports}
    assert dirs["clk"] == "input"
    assert dirs["data"] == "output"
    assert dirs["io_pin"] == "inout"


# ─── nastier shape 3: SV import after the parameter block ─────────────
def test_param_call_then_sv_import(tmp_path):
    ports = _parse(tmp_path, "imp", """
module imp_top #(parameter W = $clog2(D)) import pkg::*; (
  input  wire clk,
  output wire ready
);
endmodule
""")
    assert [p["name"] for p in ports] == ["clk", "ready"]


# ─── regression: plain module without parameters parses identically ───
def test_plain_module_no_parameters_unchanged(tmp_path):
    ports = _parse(tmp_path, "plain", """
module p_top (
  input  wire clk,
  output wire q
);
endmodule
""")
    assert [p["name"] for p in ports] == ["clk", "q"]


# ─── regression: simple param (no call) still parses identically ──────
def test_simple_param_no_call_unchanged(tmp_path):
    ports = _parse(tmp_path, "sp", """
module sp_top #(parameter WIDTH = 8) (
  input  wire             clk,
  output wire [WIDTH-1:0] q
);
endmodule
""")
    assert [p["name"] for p in ports] == ["clk", "q"]


# ─── _strip_param_block: spans the call paren, keeps the port parens ──
def test_strip_param_block_balanced_scanner():
    src = "module t #(parameter a = $clog2(x)) (input clk, output q);"
    stripped = MOD._strip_param_block(src)
    # The #(...) block (incl the function call) is gone …
    assert "$clog2" not in stripped
    assert "parameter" not in stripped
    # … but the real port list survives verbatim.
    assert "input clk" in stripped
    assert "output q" in stripped


# ─── ACCEPTANCE: defect-artifact fixture, end-to-end gate run ─────────
def test_acceptance_end_to_end_zero_ports_error_gone(tmp_path):
    """Build the issue's 現象 as a real project tree and EXECUTE the gate
    end-to-end. END state: the 'parsed zero ports' FAIL is gone and the
    gate reports a real port-set comparison."""
    project = tmp_path / "proj"
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)

    # L9 declares the real ports.
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "schema_version": 2,
        "ic_name": "PARAMCHIP",
        "top_module": "chip_top",
        "top_level_ports": [
            {"name": "clk",   "direction": "input",  "width": 1},
            {"name": "rst_n", "direction": "input",  "width": 1},
            {"name": "ready", "direction": "output", "width": 1},
        ],
    }, indent=2))

    # RTL top whose parameter default holds a function-call paren —
    # the exact shape that produced ZERO ports before #474.
    (rtl / "chip_top.sv").write_text(
        "module chip_top #(\n"
        "  parameter aw = $clog2(memsize),\n"
        "  parameter dw = 32\n"
        ") (\n"
        "  input  wire clk,\n"
        "  input  wire rst_n,\n"
        "  output wire ready\n"
        ");\n"
        "endmodule\n"
    )

    r = _run(project)
    end_state = r.stdout + r.stderr

    # The defect end-state must be GONE.
    assert "parsed zero ports" not in end_state, end_state
    # And the gate must now do a real comparison and PASS (sets agree).
    assert r.returncode == 0, end_state
    assert "PASS" in end_state, end_state
    assert "chip_top.sv" in end_state, end_state


def test_acceptance_defect_artifact_would_have_failed_pre_fix(tmp_path):
    """Pin the defect mechanism: the OLD `#\\s*\\([^)]*\\)` fragment, run
    against the same artifact, would have closed at the inner `)` and
    matched zero ports. We re-derive the OLD behaviour inline and assert
    it yields zero ports — proving the fixture genuinely reproduces #474
    — then assert the FIXED parser yields the real ports."""
    import re
    src = (
        "module chip_top #(\n"
        "  parameter aw = $clog2(memsize),\n"
        "  parameter dw = 32\n"
        ") (\n"
        "  input  wire clk,\n"
        "  output wire ready\n"
        ");\n"
        "endmodule\n"
    )
    old_re = re.compile(
        r"module\s+\w+\s*"
        r"(?:#\s*\([^)]*\)\s*)?"
        r"(?:import\s+[\w:\*\s,]+;\s*)*"
        r"\(([^;]+?)\)\s*;",
        flags=re.DOTALL,
    )
    m = old_re.search(src)
    # OLD: the optional param group ate the inner `)`, the port-list `(`
    # then matched the function-call argument list, NOT the real ports —
    # the captured body has no input/output port tokens.
    old_body = m.group(1) if m else ""
    assert "input" not in old_body and "output" not in old_body, old_body

    # FIXED parser recovers the real ports.
    f = tmp_path / "chip_top.sv"
    f.write_text(src)
    ports = MOD.parse_rtl_top_ports(f)
    assert [p["name"] for p in ports] == ["clk", "ready"]
