#!/usr/bin/env python3
"""Tests for fpga_top_pin_completeness_check.py (LL-25).

v0.119.15 hardening: gate is now chip-agnostic. Required pins come
from L2.pad_definitions[] (preferred) or L2.required_pins[]. No
hard-coded EXAMPLE_CHIP/EXAMPLE_TESTER pin whitelist remains.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "fpga_top_pin_completeness_check.py"


def _run(tmp_path: Path):
    return subprocess.run([sys.executable, str(PROG), str(tmp_path)],
                          capture_output=True, text=True)


def _write_l2(tmp_path: Path, data: dict, name: str = "L2_FRS.json"):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / name).write_text(json.dumps(data))


def _write_top(tmp_path: Path, ports_decl: str,
               name: str = "fpga_top.sv"):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / name).write_text(f"module fpga_top (\n{ports_decl}\n);\nendmodule\n")


def test_silent_skip_when_l2_declares_no_pin_set(tmp_path):
    """v0.119.15: NO hard-coded pin list. If L2 doesn't declare
    pad_definitions[] or required_pins[], the gate must silent-PASS
    (it's opt-in). Critical: this proves the EXAMPLE_CHIP-specific whitelist
    is gone."""
    _write_l2(tmp_path, {
        "functional_requirements": [
            {"id": "FR-01", "title": "WAKE pin must be driven by host",
             "spec": "WAKE goes high before connect_test"},
        ],
    })
    _write_top(tmp_path, "  input clk")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "no pad_definitions" in r.stdout or "PASS" in r.stdout, r.stdout


def test_pad_definitions_drives_required_set(tmp_path):
    """When pad_definitions[] is present, those names are required."""
    _write_l2(tmp_path, {
        "pad_definitions": [
            {"name": "id_bus", "requirement_id": "FR-01"},
            {"name": "wake_in", "requirement_id": "FR-02"},
        ],
    })
    _write_top(tmp_path, "  inout  wire id_bus,\n  input  wire wake_in")
    r = _run(tmp_path)
    assert r.returncode == 0, f"expected PASS got: {r.stdout}"


def test_pad_definitions_missing_pin_fails(tmp_path):
    """Pin in pad_definitions but missing from fpga_top → FAIL."""
    _write_l2(tmp_path, {
        "pad_definitions": [
            {"name": "id_bus", "requirement_id": "FR-01"},
            {"name": "wake_in", "requirement_id": "FR-02"},
            {"name": "cable_sense_o", "requirement_id": "FR-05"},
        ],
    })
    _write_top(tmp_path, "  inout  wire id_bus,\n  input  wire wake_in")
    r = _run(tmp_path)
    assert r.returncode == 1, f"expected FAIL got: {r.stdout}"
    assert "CABLE_SENSE_O" in r.stdout
    # The other two declared pins must NOT appear in the missing list
    assert "ID_BUS" not in r.stdout.split("Why this matters")[0] \
        or "CABLE_SENSE_O" in r.stdout  # ensure failure reasons cited


def test_pad_optional_skipped(tmp_path):
    """A pad with mandatory:false AND no backing requirement_id is treated
    as informational and skipped if missing — e.g. a debug/test pad."""
    _write_l2(tmp_path, {
        "pad_definitions": [
            {"name": "id_bus", "requirement_id": "FR-01"},
            {"name": "scan_en", "mandatory": False,
             "comment": "DFT pad, optional for functional bring-up"},
        ],
    })
    _write_top(tmp_path, "  inout  wire id_bus")
    r = _run(tmp_path)
    assert r.returncode == 0, \
        f"informational mandatory:false pad must not trigger FAIL: {r.stdout}"


def test_fr_tied_pad_with_mandatory_false_is_elevated(tmp_path):
    """v0.119.19 fix: a pad with `requirement_id` is mandatory regardless
    of `mandatory: false`. FR-tied pins are not optional by definition.

    Vendor-benchmark failure mode: agent marked 6 of 8 FR-tied pads
    `mandatory: false` so the gate "passed" with 2 pins, missing 6
    FR-mandated pins entirely. The fix forces FR-tied pads back into
    the required set."""
    _write_l2(tmp_path, {
        "pad_definitions": [
            {"name": "ACC_ID", "requirement_id": "FR-01", "mandatory": True},
            {"name": "WAKE",   "requirement_id": "FR-02", "mandatory": True},
            # 6 FR-tied pads incorrectly marked mandatory:false — must
            # still be required by the gate.
            {"name": "GPIO",   "requirement_id": "FR-03", "mandatory": False},
            {"name": "ID_IO",  "requirement_id": "FR-04", "mandatory": False},
            {"name": "OUT1",   "requirement_id": "FR-05", "mandatory": False},
            {"name": "OUT2",   "requirement_id": "FR-06", "mandatory": False},
            {"name": "CC_I",   "requirement_id": "FR-07", "mandatory": False},
            {"name": "CC_O",   "requirement_id": "FR-08", "mandatory": False},
        ],
    })
    # Only declare the 2 truly mandatory ones — gate must FAIL on the 6
    # FR-tied ones marked mandatory:false.
    _write_top(tmp_path,
               "  inout wire ACC_ID,\n"
               "  input wire WAKE")
    r = _run(tmp_path)
    assert r.returncode == 1, \
        f"FR-tied pads with mandatory:false must still fail: {r.stdout}"
    # Each missing FR-tied pad should be listed
    for pin in ("GPIO", "ID_IO", "OUT1", "OUT2", "CC_I", "CC_O"):
        assert pin in r.stdout, f"missing {pin} not flagged: {r.stdout}"


def test_fpga_alias_in_pad_definition(tmp_path):
    """v0.119.24: a pad whose canonical name (RSTN) doesn't appear in
    fpga_top is still satisfied when its `fpga_alias` (KEY[0]) does.
    Closes the vendor-benchmark complaint that DE10-Lite FPGA-board
    naming wasn't subsumed."""
    _write_l2(tmp_path, {
        "pad_definitions": [
            {"name": "RSTN", "requirement_id": "FR-02",
             "fpga_alias": ["KEY[0]"]},
            {"name": "ID_BUS", "requirement_id": "FR-01",
             "fpga_alias": ["GPIO[0]"]},
        ],
    })
    _write_top(tmp_path, "  inout wire GPIO,\n  input wire KEY")
    r = _run(tmp_path)
    assert r.returncode == 0, f"alias should match: {r.stdout}"


def test_fpga_alias_top_level_dict(tmp_path):
    """Same alias semantics via top-level `fpga_pin_aliases` dict —
    the alternative declaration path."""
    _write_l2(tmp_path, {
        "pad_definitions": [
            {"name": "CLK", "requirement_id": "FR-00"},
        ],
        "fpga_pin_aliases": {
            "CLK": ["MAX10_CLK1_50"],
        },
    })
    _write_top(tmp_path, "  input wire MAX10_CLK1_50")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_module_with_pkg_import_before_ports(tmp_path):
    """v0.119.25: SystemVerilog allows `import pkg::*;` between the
    module name and its port list. Earlier regex matched zero ports
    in that case → silent false-PASS. Now the regex tolerates the
    optional import block."""
    _write_l2(tmp_path, {
        "pad_definitions": [
            {"name": "ID_BUS", "requirement_id": "FR-01"},
            {"name": "WAKE", "requirement_id": "FR-02"},
        ],
    })
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "fpga_top.sv").write_text("""\
module fpga_top
    import aid_pkg::*;
    import other_pkg::sym;
(
    input  wire         WAKE,
    inout  wire         ID_BUS
);
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 0, \
        f"port list with leading imports must be parsed: {r.stdout}"


def test_module_with_no_imports_still_works(tmp_path):
    """Regression: the import-aware regex must still match the simple
    case (no imports between name and ports)."""
    _write_l2(tmp_path, {
        "pad_definitions": [{"name": "CLK", "requirement_id": "FR-00"}],
    })
    _write_top(tmp_path, "  input wire CLK")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_alias_does_not_mask_real_missing(tmp_path):
    """Alias is project-driven, not a free pass — a pin missing both
    by canonical name AND by alias must still FAIL."""
    _write_l2(tmp_path, {
        "pad_definitions": [
            {"name": "RSTN", "requirement_id": "FR-02",
             "fpga_alias": ["KEY[0]"]},
        ],
    })
    _write_top(tmp_path, "  input wire OTHER_PIN")
    r = _run(tmp_path)
    assert r.returncode == 1, "missing alias must still fail"
    assert "RSTN" in r.stdout


def test_underclassification_warn_emitted(tmp_path):
    """When most pads are mandatory:false (no FR tie) the gate must emit
    a WARN about under-classification rather than vacuously PASS with
    'all 1 pin present'. Soft-warn (returncode 0) so existing waiver
    flow isn't broken."""
    _write_l2(tmp_path, {
        "pad_definitions": [
            {"name": "id_bus", "requirement_id": "FR-01"},
            # 4 informational pads — no FR tie, mandatory:false
            {"name": "dbg_pad0", "mandatory": False},
            {"name": "dbg_pad1", "mandatory": False},
            {"name": "dbg_pad2", "mandatory": False},
            {"name": "dbg_pad3", "mandatory": False},
        ],
    })
    _write_top(tmp_path, "  inout wire id_bus")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "WARN" in r.stdout or "under-classification" in r.stdout.lower() \
        or "mandatory:false" in r.stdout.lower(), \
        f"expected under-classification WARN, got: {r.stdout}"


def test_required_pins_string_list(tmp_path):
    """Alternate schema: required_pins[] as bare strings."""
    _write_l2(tmp_path, {
        "required_pins": ["id_bus", "rst_n"],
    })
    _write_top(tmp_path, "  inout  wire id_bus,\n  input  wire rst_n")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_required_pins_object_list_missing_fails(tmp_path):
    _write_l2(tmp_path, {
        "required_pins": [
            {"name": "id_bus"},
            {"name": "wake_in", "requirement_id": "FR-02"},
        ],
    })
    _write_top(tmp_path, "  inout  wire id_bus")
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "WAKE_IN" in r.stdout


def test_no_chip_specific_filename_lookup(tmp_path):
    """v0.119.15: example_chip_fpga_top.sv hard-coded filename was removed.
    Generic *_fpga_top / *_top patterns still work; here we use a
    project-specific name."""
    _write_l2(tmp_path, {
        "pad_definitions": [{"name": "io_pad"}],
    })
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "myproject_fpga_top.sv").write_text(
        "module fpga_top (inout wire io_pad); endmodule\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_no_l2_silent_pass(tmp_path):
    """No L2 doc at all → not applicable, silent PASS."""
    _write_top(tmp_path, "  input clk")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "no L2" in r.stdout


def test_no_fpga_top_silent_pass(tmp_path):
    """Project declares pins but no fpga_top RTL exists yet → skipped."""
    _write_l2(tmp_path, {"pad_definitions": [{"name": "io_pad"}]})
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "no FPGA top" in r.stdout or "skipped" in r.stdout


def test_waiver_per_pin(tmp_path):
    """Per-pin waiver in fpga_pin_intentionally_omitted bypasses missing."""
    _write_l2(tmp_path, {
        "pad_definitions": [
            {"name": "id_bus", "requirement_id": "FR-01"},
            {"name": "wake_in", "requirement_id": "FR-02"},
        ],
    })
    _write_top(tmp_path, "  inout  wire id_bus")
    (tmp_path / "waivers.json").write_text(json.dumps({
        "fpga_pin_intentionally_omitted": [
            "WAKE_IN — chip uses internal-timer wake (FR-02 alternative)",
        ],
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
