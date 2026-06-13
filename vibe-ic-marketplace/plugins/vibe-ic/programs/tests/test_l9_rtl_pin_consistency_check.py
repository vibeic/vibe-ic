#!/usr/bin/env python3
"""Tests for l9_rtl_pin_consistency_check.py — Wave 79 cross-layer
integrity gate.

Covers six paths:
  1. POSITIVE_PASS         — L9 + RTL agree on pin set + directions
  2. FAIL_extra_l9         — L9 declares a pin RTL doesn't expose
  3. FAIL_extra_rtl        — RTL has a port L9 doesn't declare
  4. FAIL_direction        — L9 says input but RTL says output
  5. SKIP_no_rtl           — L9 present, no rtl/ dir
  6. SKIP_no_l9            — rtl/ present, no L9 doc
plus:
  7. PASS_WITH_WAIVER      — failure suppressed by valid waiver
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


def _write_l9(project: Path, ports: list[dict],
              dtop_name: str = "test_dtop") -> None:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "layer": "L9",
        "ic_name": "TEST",
        "dtop_top_level": {"module_name": dtop_name},
        "top_level_ports": ports,
    }, indent=2))


def _write_rtl_top(project: Path, name: str, port_lines: list[str]) -> None:
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    body = ",\n  ".join(port_lines)
    (rtl / f"{name}.sv").write_text(
        f"module {name} (\n  {body}\n);\n"
        "endmodule\n"
    )


# ─── 1. PASS ──────────────────────────────────────────────────────
def test_pass_when_l9_and_rtl_agree(tmp_path):
    project = tmp_path / "p"; project.mkdir(parents=True, exist_ok=True)
    _write_l9(project, [
        {"name": "clk",       "direction": "input",  "width": 1},
        {"name": "rst_n",     "direction": "input",  "width": 1},
        {"name": "id_bus_tx", "direction": "output", "width": 1},
    ])
    _write_rtl_top(project, "test_dtop", [
        "input  wire clk",
        "input  wire rst_n",
        "output wire id_bus_tx",
    ])
    r = _run(project)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout
    # fixture-flip-acknowledged: test_pass_when_l9_and_rtl_agree:
    # "agree on 3 pins" -> "agree on 1 pins". v1.6.85 (#17 Bug B)
    # originally stripped only the EXACT names `clk` / `reset_n`, so this
    # fixture (clk/rst_n/id_bus_tx) dropped just `clk` and reported
    # "agree on 2 pins". ORGANIC-20260606 #491 (b) widened the strip to a
    # NAME-PATTERN over the clock + reset families, so `rst_n` is now ALSO
    # recognised as an implicit reset port and stripped. Only the real
    # functional port `id_bus_tx` remains → "agree on 1 pins". This is the
    # intended behavioural change (the old comment's "rst_n is NOT in
    # _IMPLICIT_PINS" was exactly the #491 false-mismatch bug).
    assert "agree on 1/" in r.stdout  # #591 format: N/TOTAL


# ─── v1.6.19 regression — schema-v2 top_module field is honoured ──
def test_v1_6_19_schema_v2_top_module_field_honoured(tmp_path):
    """Real v1069-vendor L9 v2 carries `top_module="chip_top"` (no
    legacy `dtop_module_name` / `dtop_top_level.module_name`). Pre-v1.6.19
    `find_rtl_top` ignored that field and the gate SKIPped silently with
    'no RTL top file'. After the fix the gate must locate rtl/chip_top.sv
    and run a full PASS/FAIL comparison."""
    project = tmp_path / "p"; project.mkdir(parents=True, exist_ok=True)
    gd = project / "phase1" / "generated_docs"; gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "schema_version": 2,
        "ic_name": "TESTCHIP",
        "top_module": "chip_top",
        "top_level_ports": [
            {"name": "clk",    "direction": "input",  "width": 1},
            {"name": "id_bus", "direction": "inout",  "width": 1},
        ],
    }))
    _write_rtl_top(project, "chip_top", [
        "input  wire clk",
        "inout  wire id_bus",
    ])
    r = _run(project)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout and "chip_top.sv" in r.stdout, r.stdout


def test_v1_6_19_top_filename_diff_from_module_name_via_content_scan(tmp_path):
    """Content-scan fallback: top_module="chip_top" but the only RTL file
    is named rtl/asic_top_pad_wrapper.sv (filename ≠ module name, single
    module per file). The scan fallback must grep for `module chip_top`
    and return that file. Multi-module-per-file bundling is a separate
    parser-level concern out of scope for this fix."""
    project = tmp_path / "p"; project.mkdir(parents=True, exist_ok=True)
    gd = project / "phase1" / "generated_docs"; gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "schema_version": 2,
        "top_module": "chip_top",
        "top_level_ports": [
            {"name": "clk", "direction": "input", "width": 1},
        ],
    }))
    rtl = project / "phase2" / "stage1" / "rtl"; rtl.mkdir(parents=True)
    (rtl / "asic_top_pad_wrapper.sv").write_text(
        "module chip_top (\n  input wire clk\n);\nendmodule\n"
    )
    r = _run(project)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout
    assert "asic_top_pad_wrapper.sv" in r.stdout, r.stdout


# ─── 2. FAIL — pin missing from RTL ───────────────────────────────
def test_fail_when_l9_has_extra_pin(tmp_path):
    project = tmp_path / "p"; project.mkdir(parents=True, exist_ok=True)
    _write_l9(project, [
        {"name": "clk",     "direction": "input"},
        {"name": "missing", "direction": "input"},
    ])
    _write_rtl_top(project, "test_dtop", [
        "input wire clk",
    ])
    r = _run(project)
    assert r.returncode == 1, r.stdout
    assert "FAIL" in r.stdout
    assert "missing" in r.stdout


# ─── 3. FAIL — port missing from L9 ───────────────────────────────
def test_fail_when_rtl_has_extra_port(tmp_path):
    project = tmp_path / "p"; project.mkdir(parents=True, exist_ok=True)
    _write_l9(project, [
        {"name": "clk", "direction": "input"},
    ])
    _write_rtl_top(project, "test_dtop", [
        "input  wire clk",
        "output wire stray_port",
    ])
    r = _run(project)
    assert r.returncode == 1, r.stdout
    assert "FAIL" in r.stdout
    assert "stray_port" in r.stdout


# ─── 4. FAIL — direction mismatch ─────────────────────────────────
def test_fail_when_directions_disagree(tmp_path):
    project = tmp_path / "p"; project.mkdir(parents=True, exist_ok=True)
    _write_l9(project, [
        {"name": "clk",    "direction": "input"},
        {"name": "id_bus", "direction": "output"},
    ])
    _write_rtl_top(project, "test_dtop", [
        "input wire clk",
        "inout wire id_bus",   # L9 says output, RTL says inout
    ])
    r = _run(project)
    assert r.returncode == 1, r.stdout
    assert "direction mismatches" in r.stdout
    assert "id_bus" in r.stdout
    assert "output" in r.stdout
    assert "inout" in r.stdout


# ─── 5. SKIP — no RTL ─────────────────────────────────────────────
def test_skip_when_no_rtl(tmp_path):
    project = tmp_path / "p"; project.mkdir(parents=True, exist_ok=True)
    _write_l9(project, [{"name": "clk", "direction": "input"}])
    # No rtl/ directory
    r = _run(project)
    assert r.returncode == 0, r.stdout
    assert "SKIP" in r.stdout
    assert "RTL" in r.stdout


# ─── 6. SKIP — no L9 ──────────────────────────────────────────────
def test_skip_when_no_l9(tmp_path):
    project = tmp_path / "p"; project.mkdir(parents=True, exist_ok=True)
    _write_rtl_top(project, "test_dtop", ["input wire clk"])
    r = _run(project)
    assert r.returncode == 0, r.stdout
    assert "SKIP" in r.stdout
    assert "L9" in r.stdout


# ─── 7. PASS_WITH_WAIVER ──────────────────────────────────────────
def test_pass_with_valid_waiver(tmp_path):
    project = tmp_path / "p"; project.mkdir(parents=True, exist_ok=True)
    _write_l9(project, [{"name": "clk", "direction": "input"}])
    _write_rtl_top(project, "test_dtop", [
        "input  wire clk",
        "output wire stray_port",
    ])
    (project / "waivers.json").write_text(json.dumps({
        "l9_rtl_pin_consistency_intentional": {
            "rationale": (
                "stray_port is a TEST-mode pin intentionally exposed "
                "in synth wrapper but not yet documented in L9; "
                "tracked in BACKLOG-Wave-79-followup."
            ),
        },
    }))
    r = _run(project)
    assert r.returncode == 0, r.stdout
    assert "PASS_WITH_WAIVER" in r.stdout


def test_usage_error_no_args():
    r = subprocess.run(
        [sys.executable, str(PROG)], capture_output=True, text=True,
    )
    assert r.returncode == 2


# ─── Wave 82 Fix G — debug/scan/tb port allowlist ────────────────
# RTL ports matching debug/scan/tb naming patterns are test hooks
# and may legitimately be omitted from the L9 production pin
# contract. Real customer-facing pins MUST still appear in L9.

def test_debug_state_port_allowed_when_missing_from_l9(tmp_path):
    project = tmp_path / "p"; project.mkdir(parents=True, exist_ok=True)
    _write_l9(project, [
        {"name": "clk", "direction": "input"},
    ])
    _write_rtl_top(project, "test_dtop", [
        "input wire clk",
        "output wire [3:0] debug_state",
    ])
    r = _run(project)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout
    assert "debug_state" in r.stdout
    assert "debug/scan/tb-only" in r.stdout


def test_scan_ports_allowed_when_missing_from_l9(tmp_path):
    project = tmp_path / "p"; project.mkdir(parents=True, exist_ok=True)
    _write_l9(project, [
        {"name": "clk", "direction": "input"},
    ])
    _write_rtl_top(project, "test_dtop", [
        "input wire clk",
        "input wire scan_clk",
        "input wire scan_in",
        "output wire scan_out",
    ])
    r = _run(project)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout


def test_tb_done_port_allowed_when_missing_from_l9(tmp_path):
    project = tmp_path / "p"; project.mkdir(parents=True, exist_ok=True)
    _write_l9(project, [
        {"name": "clk", "direction": "input"},
    ])
    _write_rtl_top(project, "test_dtop", [
        "input wire clk",
        "output wire tb_done",
    ])
    r = _run(project)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout


def test_dbg_suffix_allowed_when_missing_from_l9(tmp_path):
    project = tmp_path / "p"; project.mkdir(parents=True, exist_ok=True)
    _write_l9(project, [
        {"name": "clk", "direction": "input"},
    ])
    _write_rtl_top(project, "test_dtop", [
        "input wire clk",
        "output wire nominal_pin_dbg",
    ])
    r = _run(project)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout


def test_customer_facing_port_still_fails_when_missing_from_l9(tmp_path):
    project = tmp_path / "p"; project.mkdir(parents=True, exist_ok=True)
    _write_l9(project, [
        {"name": "clk", "direction": "input"},
    ])
    _write_rtl_top(project, "test_dtop", [
        "input wire clk",
        "output wire customer_facing_pin",
    ])
    r = _run(project)
    assert r.returncode == 1, r.stdout
    assert "FAIL" in r.stdout
    assert "customer_facing_pin" in r.stdout


def test_listed_in_structural_rtl_gates():
    """Wave 79 — gate is wired into flow_compliance_check's
    _STRUCTURAL_RTL_GATES tuple so strict-mode statistics include it.
    """
    fc = (
        Path(__file__).resolve().parent.parent / "flow_compliance_check.py"
    )
    text = fc.read_text()
    assert "l9_rtl_pin_consistency_check" in text, (
        "l9_rtl_pin_consistency_check must appear in "
        "flow_compliance_check._STRUCTURAL_RTL_GATES"
    )
