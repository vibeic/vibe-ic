#!/usr/bin/env python3
"""Wave 33 (mcp-eda v0.99.9) — eda_fpga_program back-door close.

These tests verify two independent claims:

1.  The eda_fpga_program JS handler delegates to the device-driver
    `device_fpga_de10lite_program` through the same JSON-IO contract
    (i.e. the wrapper is structural — there is no longer a separate
    `execSync("quartus_pgm ...")` call inside the eda_fpga_program
    handler). We verify by parsing src/index.js for the absence of
    the legacy direct-execSync site.

2.  When invoked end-to-end against a project whose
    `phase23_completion_audit.json` reports verdict=FAIL, the driver
    refuses to burn. This is the same fail-closed contract as
    Wave 30, but we additionally check that the wrapper cannot
    re-introduce `bypass_pre_burn_check=true` from the JS side
    (the literal string `bypass_pre_burn_check: false` is in the
    wrapper).
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INDEX_JS = ROOT / "src" / "index.js"
DRIVER_PATH = (
    ROOT / "src" / "devices" / "fpga" / "terasic-de10lite" / "driver.py"
)
assert INDEX_JS.exists()
assert DRIVER_PATH.exists()


def _load_driver():
    spec = importlib.util.spec_from_file_location(
        "de10lite_driver_wave33_test", DRIVER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_eda_fpga_program_no_direct_execsync_quartus_pgm():
    """Wave 33: index.js must NOT contain `execSync(...quartus_pgm` in
    the eda_fpga_program handler. The legacy back-door exec was the
    Hole-1 violation. The legacy `quartus_pgm -l` JTAG-list call
    inside verify_burn is still allowed because it's a read-only
    enumeration, not a burn.
    """
    src = INDEX_JS.read_text()
    # Locate the eda_fpga_program tool block.
    start = src.find('server.tool(\n  "eda_fpga_program"')
    assert start > 0, "eda_fpga_program handler not found in index.js"
    # Find the matching closing `);` for that server.tool call. We
    # use a pragmatic heuristic: look for the next "// ─── Tool: "
    # marker.
    end = src.find("// ─── Tool: ", start + 1)
    assert end > start, "could not locate eda_fpga_program block end"
    block = src[start:end]
    # Permitted: quartus_pgm -l (verify_burn JTAG-list inside an
    # execSync call). FORBIDDEN: any execSync that programs a SOF.
    forbidden = re.findall(
        r"execSync\([^)]*quartus_pgm\s+-c[^)]*-o", block)
    assert not forbidden, (
        f"WAVE33: eda_fpga_program contains direct burn execSync — "
        f"{forbidden}"
    )
    # Sanity: the wrapper hard-codes bypass false for the SOF path.
    assert "bypass_pre_burn_check: false" in block, (
        "WAVE33: eda_fpga_program must hard-code "
        "bypass_pre_burn_check: false to prevent back-door bypass"
    )
    # Sanity: the wrapper invokes the device driver path.
    assert "terasic-de10lite" in block and "driver.py" in block, (
        "WAVE33: eda_fpga_program must delegate to "
        "device_fpga_de10lite_program's driver.py"
    )


def test_driver_blocks_burn_on_audit_verdict_fail(tmp_path, monkeypatch):
    """End-to-end: driver receives a project whose
    phase23_completion_audit.json reports verdict=FAIL → burn blocked
    with error_code starting with `burn_blocked`."""
    driver = _load_driver()

    # Build a project tree that _resolve_project_root_from_sof will
    # accept (rtl/ marker), with a verdict=FAIL audit JSON.
    proj = tmp_path / "fake_project"
    proj.mkdir()
    (proj / "rtl").mkdir()
    (proj / "rtl" / "top.v").write_text("module top; endmodule\n")
    out_dir = proj / "fpga" / "output_files"
    out_dir.mkdir(parents=True)
    sof = out_dir / "top.sof"
    sof.write_bytes(b"\x00\x01\x02\x03")

    reports = proj / "reports"
    reports.mkdir()
    audit_json = reports / "phase23_completion_audit.json"
    audit_json.write_text(json.dumps({
        "schema_version": 1,
        "verdict": "FAIL",
        "failed_gates": ["slave_tx_no_device_break_check"],
        "failed_gate_count": 1,
    }))

    # Stub out quartus_pgm so the driver doesn't try to find the real
    # binary.
    monkeypatch.setattr(driver, "_require_quartus_pgm",
                        lambda: "/fake/quartus_pgm")
    monkeypatch.setattr(driver, "find_quartus_pgm",
                        lambda: "/fake/quartus_pgm")

    # Stub the flow_compliance subprocess: simulate the runner
    # producing rc=1 + stdout that triggers the JSON-artifact branch
    # (which we just wrote on disk).
    def fake_run_fc(project_root, timeout_s=180):
        return 1, {
            "flow_compliance_verdict": "FAIL",
            "exit_code": 1,
            "failed_gates": ["slave_tx_no_device_break_check"],
            "step_level_warnings": [],
            "audit_json_present": True,
            "audit_json_path": str(audit_json),
            "stdout_tail": "Overall: FAIL\n",
            "stderr_tail": "",
            "command": ["flow_compliance_check.py"],
        }
    monkeypatch.setattr(driver, "_run_flow_compliance_pre_burn",
                        fake_run_fc)

    rc, body = driver.mode_program({
        "sof_path": str(sof),
        "skip_rtl_precheck": True,
        # Critical: bypass_pre_burn_check is NOT set (defaults False)
        # — exactly what the new eda_fpga_program wrapper passes.
    })
    assert rc == 1, body
    assert body.get("success") is False
    err_code = body.get("error_code", "")
    assert err_code.startswith("burn_blocked"), body


def test_wrapper_does_not_expose_bypass_in_schema():
    """Wave 33: the eda_fpga_program zod schema must not declare a
    bypass_pre_burn_check parameter — a caller cannot reach the
    override knob via this tool."""
    src = INDEX_JS.read_text()
    start = src.find('server.tool(\n  "eda_fpga_program"')
    end = src.find("// ─── Tool: ", start + 1)
    block = src[start:end]
    # The async-handler signature line lists the destructured args.
    # We accept the literal `bypass_pre_burn_check: false` which is
    # the hard-coded delegate value, but reject any zod schema entry.
    handler_match = re.search(
        r"async\s*\(\s*\{([^}]+)\}\s*\)\s*=>", block)
    assert handler_match, "could not locate eda_fpga_program async handler"
    args = handler_match.group(1)
    assert "bypass_pre_burn_check" not in args, (
        f"WAVE33: eda_fpga_program handler must not accept "
        f"bypass_pre_burn_check from caller (found: {args!r})"
    )
