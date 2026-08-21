#!/usr/bin/env python3
"""Wave 75 — coverage inventory for mcp-eda tools.

Static (no-docker) inventory check. Lists every tool registered via
`server.tool("...", ...)` in src/index.js and asserts each one is
either covered by a dedicated test file under test/ or is on the
explicit "deferred" list (with a documented reason).

Rationale
---------
v0.130 found 38 tools registered but only 4 had any unit test. This
inventory pins the coverage baseline so a future PR that adds a tool
without a test fails fast in CI.

Failure mode: a new tool name in src/index.js that's neither in
TESTED_TOOLS nor DEFERRED_TOOLS will FAIL this test — forcing the
author to add at least a static-shape test or document the deferral.
"""
from __future__ import annotations
import re
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
INDEX_JS = ROOT / "src" / "index.js"
TEST_DIR = ROOT / "test"


def _registered_tools() -> list[str]:
    """Parse server.tool("name", ...) entries from index.js."""
    src = INDEX_JS.read_text()
    # The ServerToolFactory call lays the name on the line *after* `server.tool(`.
    # Match: `server.tool(\n  "tool_name",`
    pat = re.compile(r'server\.tool\(\s*\n\s*"([a-z0-9_]+)"', re.MULTILINE)
    names = pat.findall(src)
    return sorted(set(names))


# Tools that have at least one dedicated test file under test/
# (file content must reference the tool name verbatim).
TESTED_TOOLS = {
    "eda_lint",
    "eda_equiv",
    "eda_fpga_program",
    "eda_drc_klayout",  # auto_drc_deck.py covers DRC deck generation
    # Wave 75 additions:
    "eda_oracle_bytewise_dump",
    "mcp_server_health_check",
    "eda_phase23_completion_audit",
    "eda_doctor",
    "eda_pdk_lint",
}

# Tools deliberately deferred (require live docker / hardware to test
# meaningfully). Each entry MUST include a one-line rationale. Anything
# not listed here and not in TESTED_TOOLS will FAIL the inventory.
DEFERRED_TOOLS = {
    "eda_professional_tb": "requires Icarus Verilog to compile/run the generated TB; covered by Phase-2 full-stack-tb integration",
    "eda_synth": "requires Yosys + PDK liberty; covered by integration runs",
    "eda_simulate": "requires Icarus Verilog; covered by Phase-2b benchmark",
    "eda_formal": "requires SymbiYosys + yices",
    "eda_pnr": "requires OpenROAD; covered by Phase-3 benchmark",
    "eda_gds": "requires Magic; covered by tapeout-checklist suite",
    "eda_sta": "requires OpenSTA; covered by Phase-3 benchmark",
    "eda_lvs": "requires Magic+netgen",
    "eda_ir_drop": "requires OpenROAD PDN flow",
    "eda_extraction": "requires Magic ext+ext2spice",
    "eda_spice": "requires Ngspice",
    "eda_xschem_netlist": "requires xschem (GUI)",
    "eda_spice_corner": "requires Ngspice + corner libs",
    "eda_dft": "requires Yosys scan-chain pass",
    "eda_ic_search": "online catalog probe; covered by manual smoke",
    "eda_sta_mcorner": "requires OpenSTA + multi-corner libs",
    "eda_rtl_audit": "wrapped Python program; covered by plugin tests",
    "eda_cocotb": "requires cocotb runtime",
    "eda_fpga_compile": "requires Quartus",
    "eda_doc_extract": "requires pdf+docx parsers; covered by phase1_fg tests",
    "eda_run_tcl": "thin TCL pass-through",
    "eda_workflow_run": "orchestrator; covered by phase23_completion gate",
    "eda_scope_protocol_decode": "requires scope CSV + L2 timing fixtures",
    "eda_pass_reference_scope_diff": "requires reference scope baseline",
    "eda_rtl_signaltap_autogen": "requires Quartus; covered by hardware lab smoke",
    "eda_spinalhdl_gen": "requires OpenJDK 17 + sbt in vibeic-eda + Maven Central; covered by VexRiscv GenSmallest generation smoke",
    "eda_analog_layout": "requires Magic; covered by analog A1-A8 suite",
    "eda_fpga_adc_read": "requires DE10-Lite hardware + ADC test pattern",
    "device_camera_capture": "requires connected webcam",
    "device_camera_led_diff": "requires LED + camera setup",
    # Wrapped pure-Python programs — fully covered by the plugin test tree
    # (plugins/vibe-ic/programs/tests/test_<name>.py); the MCP layer is a thin
    # spawn wrapper, so the deferral rationale points at the program test.
    "eda_spec_conformance": "wrapped Python program; covered by plugin tests test_spec_conformance_check.py",
    "eda_spec_lint": "wrapped Python program; covered by plugin tests test_spec_self_consistency_check.py",
    "eda_fsm_table_gen": "wrapped Python program; covered by plugin tests test_fsm_table_rtl_gen.py",
    "eda_truth_table_gen": "wrapped Python program; covered by plugin tests test_truth_table_rtl_gen.py",
    "eda_gate_netlist_gen": "wrapped Python program; covered by plugin tests test_gate_netlist_rtl_gen.py",
    "eda_vector_op_gen": "wrapped Python program; covered by plugin tests test_vector_op_rtl_gen.py",
    "eda_rtl_dispatch": "wrapped Python program; covered by plugin tests test_deterministic_rtl_dispatcher.py",
    # The tool name and the program it spawns differ (`rtl_signal_name_...`),
    # and the deferral rationale had drifted to the TOOL name — citing
    # `test_rtl_name_semantic_check.py`, which exists nowhere. The coverage
    # itself was real; the sentence pointing at it was not.
    "eda_rtl_name_semantic_check": "wrapped Python program (rtl_signal_name_semantic_check); covered by plugin tests test_rtl_signal_name_semantic_check.py",
    "eda_chip_top_gate_wrapper_gen": "wrapped Python program (chip_top_gate_wrapper_gen); covered by plugin tests",
    "eda_fpga_gate_attestation_check": "requires Quartus gate-level compile artifacts (FPGA lab)",
    "eda_fpga_gds_reverify": "requires the FPGA gate-level reverify chain (Quartus + scope/UDP shim)",
}


def test_inventory_completeness() -> None:
    """Every registered tool MUST be either tested or deferred."""
    registered = set(_registered_tools())
    classified = TESTED_TOOLS | set(DEFERRED_TOOLS.keys())
    unclassified = registered - classified
    assert not unclassified, (
        f"{len(unclassified)} tool(s) registered in src/index.js have "
        f"neither a test nor a deferral entry: {sorted(unclassified)}. "
        f"Add a test_<name>.py under test/ and append the name to "
        f"TESTED_TOOLS, OR add an entry to DEFERRED_TOOLS with a "
        f"one-line rationale (live-hardware / live-docker dependency)."
    )


def test_tested_tools_actually_have_tests() -> None:
    """Every TESTED_TOOLS entry MUST appear in at least one test file."""
    test_files = [
        p.read_text() for p in TEST_DIR.glob("*.py") if p.name != Path(__file__).name
    ]
    blob = "\n".join(test_files)
    missing = [t for t in TESTED_TOOLS if t not in blob]
    assert not missing, (
        f"Tools claimed tested but no test file references them: {missing}. "
        f"Add the tool name (as a string literal) to one of the test files, "
        f"or remove it from TESTED_TOOLS."
    )


def test_inventory_count_matches_37() -> None:
    """v1.6.45 baseline: 37 tools registered (down from v0.130's 38 —
    `device_id_bus_force_low_pulse` was intentionally retired
    post-v0.130 because the USB-HID tester drives the bus directly
    and the wrapper added no value over `device_id_bus_send_opcode`).
    If this changes, update the INSTALL_GUIDE.md count."""
    registered = _registered_tools()
    # Allow growth (>=37) but flag shrinkage (would mean a regression).
    assert len(registered) >= 37, (
        f"Tool count regressed: {len(registered)} < 37. "
        f"If a tool was intentionally removed, lower this floor explicitly."
    )


def test_no_duplicate_registrations() -> None:
    """Each tool name MUST be registered exactly once."""
    src = INDEX_JS.read_text()
    pat = re.compile(r'server\.tool\(\s*\n\s*"([a-z0-9_]+)"', re.MULTILINE)
    names = pat.findall(src)
    seen: dict[str, int] = {}
    for n in names:
        seen[n] = seen.get(n, 0) + 1
    dupes = {k: v for k, v in seen.items() if v > 1}
    assert not dupes, f"duplicate server.tool registrations: {dupes}"
