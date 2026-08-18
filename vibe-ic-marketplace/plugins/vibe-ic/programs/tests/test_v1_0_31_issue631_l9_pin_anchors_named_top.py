#!/usr/bin/env python3
"""ORGANIC-20260614 regression — l9_rtl_pin_consistency_check must parse
the L9-NAMED top module, not the FIRST `module` in the resolved RTL file.

Bug (issue #631): find_rtl_top() resolves the RTL FILE via the L9 top-
module name (and even has a content-scan fallback for tops bundled inside
multi-module files), but parse_rtl_top_ports(rtl_path) was called with
only the file path. Its regex `module\\s+\\w+\\s*...(\\(...\\))\\s*;`
matched the FIRST `module <name>(...)` in the file, so when the resolved
top is NOT declared first the gate compared L9's top-port surface against
a SUB-module's ports and emitted a false FAIL. The bug was latent on disk
only because a design agent manually reordered the top module first.

Coverage:
  POSITIVE (the bug)   — helper module FIRST, named top SECOND, ports
                         match -> must PASS (exit 0). Pre-fix: false FAIL.
  POSITIVE (content-   — file named differently from the module, top
   scan worst case)      declared after a sibling module -> must PASS.
  NO-LEAK 1            — genuine missing L9 pin on the correctly-anchored
                         (non-first) top -> must still FAIL.
  NO-LEAK 2            — genuine extra RTL port on the correctly-anchored
                         (non-first) top -> must still FAIL.
  NO-LEAK 3            — genuine direction mismatch on the correctly-
                         anchored (non-first) top -> must still FAIL.
  NO-LEAK 4 (fallback) — L9 names a top ABSENT from the file -> parser
                         falls back to the first module and STILL catches
                         a genuine mismatch (never silent PASS/zero ports).
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

PROG = (
    Path(__file__).resolve().parent.parent / "l9_rtl_pin_consistency_check.py"
)


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _write_l9(project: Path, top_module: str, ports: list[dict]) -> None:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "schema_version": 2,
        "ic_name": "TESTCHIP",
        "top_module": top_module,
        "top_level_ports": ports,
    }, indent=2))


def _write_rtl_file(project: Path, filename: str, body: str) -> None:
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / filename).write_text(body)


# ── POSITIVE: the bug — helper module FIRST, named top SECOND ──────
def test_named_top_not_first_module_passes(tmp_path):
    """L9 top_module='mytop' with ports [a,b]. The file declares a helper
    submodule [x,y] FIRST and mytop [a,b] SECOND. Pre-fix the gate matched
    the first module and false-FAILed ('L9 declares pins missing'; 'RTL
    top has ports not in L9'). After the fix it anchors on mytop -> PASS."""
    project = tmp_path / "p"; project.mkdir(parents=True, exist_ok=True)
    _write_l9(project, "mytop", [
        {"name": "a", "direction": "input"},
        {"name": "b", "direction": "output"},
    ])
    _write_rtl_file(project, "mytop.sv",
        "module helper (\n"
        "  input  wire x,\n"
        "  output wire y\n"
        ");\nendmodule\n\n"
        "module mytop (\n"
        "  input  wire a,\n"
        "  output wire b\n"
        ");\n"
        "  helper u_h (.x(a), .y(b));\n"
        "endmodule\n")
    r = _run(project)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout, r.stdout
    # Must NOT have leaked the submodule's ports into the comparison.
    assert "x" not in r.stdout.split("agree")[0] or "PASS" in r.stdout
    assert "missing from RTL" not in r.stdout, r.stdout


# ── POSITIVE: content-scan worst case (filename != module, top later) ─
def test_content_scan_bundle_top_after_sibling_passes(tmp_path):
    """File named design_bundle.v (filename != module name) forces
    find_rtl_top's content-scan fallback. accel_top is declared AFTER the
    alu sibling. The fix anchors the port parse on accel_top -> PASS, even
    though the content-scan fallback only ever resolved the FILE."""
    project = tmp_path / "p"; project.mkdir(parents=True, exist_ok=True)
    _write_l9(project, "accel_top", [
        {"name": "din", "direction": "input"},
        {"name": "dout", "direction": "output"},
    ])
    _write_rtl_file(project, "design_bundle.v",
        "module alu (\n"
        "  input  wire [7:0] op_a,\n"
        "  input  wire [7:0] op_b,\n"
        "  output wire [7:0] result\n"
        ");\nendmodule\n\n"
        "module accel_top (\n"
        "  input  wire [7:0] din,\n"
        "  output wire [7:0] dout\n"
        ");\n"
        "  alu u_alu (.op_a(din), .op_b(din), .result(dout));\n"
        "endmodule\n")
    r = _run(project)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout, r.stdout
    assert "design_bundle.v" in r.stdout, r.stdout


# ── NO-LEAK 1: genuine missing L9 pin on the (non-first) named top ──
def test_no_leak_genuine_missing_pin_on_named_top_fails(tmp_path):
    project = tmp_path / "p"; project.mkdir(parents=True, exist_ok=True)
    _write_l9(project, "mytop", [
        {"name": "a", "direction": "input"},
        {"name": "b", "direction": "output"},
        {"name": "real_missing_pin", "direction": "output"},
    ])
    _write_rtl_file(project, "mytop.sv",
        "module helper ( input wire x, output wire y ); endmodule\n"
        "module mytop ( input wire a, output wire b ); endmodule\n")
    r = _run(project)
    assert r.returncode == 1, r.stdout
    assert "FAIL" in r.stdout, r.stdout
    assert "real_missing_pin" in r.stdout, r.stdout
    # The submodule helper's ports must NOT pollute the finding.
    assert "'x'" not in r.stdout and "'y'" not in r.stdout, r.stdout


# ── NO-LEAK 2: genuine extra RTL port on the (non-first) named top ──
def test_no_leak_genuine_extra_rtl_port_on_named_top_fails(tmp_path):
    project = tmp_path / "p"; project.mkdir(parents=True, exist_ok=True)
    _write_l9(project, "mytop", [
        {"name": "a", "direction": "input"},
        {"name": "b", "direction": "output"},
    ])
    _write_rtl_file(project, "mytop.sv",
        "module helper ( input wire a, output wire b ); endmodule\n"
        "module mytop ( input wire a, output wire b, "
        "output wire genuine_extra ); endmodule\n")
    r = _run(project)
    assert r.returncode == 1, r.stdout
    assert "FAIL" in r.stdout, r.stdout
    assert "genuine_extra" in r.stdout, r.stdout


# ── NO-LEAK 3: genuine direction mismatch on the (non-first) named top ─
def test_no_leak_direction_mismatch_on_named_top_fails(tmp_path):
    project = tmp_path / "p"; project.mkdir(parents=True, exist_ok=True)
    _write_l9(project, "mytop", [
        {"name": "a", "direction": "input"},
        {"name": "b", "direction": "output"},
    ])
    _write_rtl_file(project, "mytop.sv",
        "module helper ( input wire a, output wire b ); endmodule\n"
        "module mytop ( input wire a, inout wire b ); endmodule\n")
    r = _run(project)
    assert r.returncode == 1, r.stdout
    assert "direction mismatches" in r.stdout, r.stdout
    assert "b: L9=output vs RTL=inout" in r.stdout, r.stdout


# ── NO-LEAK 4: named top ABSENT -> fallback to first module still gates ─
def test_no_leak_absent_named_top_falls_back_and_still_gates(tmp_path):
    """L9 names 'phantom_top' which does NOT appear in the file. The parser
    must fall back to the first module (historical behaviour) and STILL
    catch a genuine extra port — it must NOT silently PASS with zero ports
    just because the anchored regex found no match."""
    project = tmp_path / "p"; project.mkdir(parents=True, exist_ok=True)
    _write_l9(project, "phantom_top", [
        {"name": "a", "direction": "input"},
    ])
    # find_rtl_top resolves this via the chip_top.sv fallback candidate;
    # the only module 'realtop' has an extra port not in L9.
    _write_rtl_file(project, "chip_top.sv",
        "module realtop ( input wire a, output wire genuine_extra ); "
        "endmodule\n")
    r = _run(project)
    assert r.returncode == 1, r.stdout
    assert "FAIL" in r.stdout, r.stdout
    assert "genuine_extra" in r.stdout, r.stdout
