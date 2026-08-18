"""Unit tests for l9_completeness_check.py.

Tests verify correct detection of missing/empty sections in L9 Integration
Spec JSON, including invalid JSON, empty files, and alias resolution.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'l9_completeness_check.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import l9_completeness_check as l9c  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture: L9 JSON templates
# ---------------------------------------------------------------------------
COMPLETE_L9 = {
    "top_level_ports": [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "rst_n", "direction": "input", "width": 1},
        {"name": "data_out", "direction": "output", "width": 8},
    ],
    "submodules": [
        {"name": "uart_core", "module": "uart_tx_rx", "instance": "u_uart"},
        {"name": "spi_ctrl", "module": "spi_master", "instance": "u_spi"},
    ],
    "internal_wires": [
        {"name": "uart_data", "width": 8, "from": "u_uart.tx_data", "to": "u_spi.rx_data"},
    ],
    "registers": [
        {"name": "CTRL_REG", "address": "0x00", "width": 8, "reset": "0x00"},
        {"name": "STATUS_REG", "address": "0x01", "width": 8, "reset": "0x00"},
    ],
}

COMPLETE_L9_ALIASES = {
    "dtop_ports": [
        {"name": "clk", "direction": "input", "width": 1},
    ],
    "submodules": [
        {"name": "core", "module": "core_logic", "instance": "u_core"},
    ],
    "wire_map": [
        {"name": "data_bus", "width": 8},
    ],
    "register_infrastructure": [
        {"name": "REG0", "address": "0x00"},
    ],
}

MISSING_SUBMODULES = {
    "top_level_ports": [
        {"name": "clk", "direction": "input", "width": 1},
    ],
    # submodules is missing
    "internal_wires": [
        {"name": "data_bus", "width": 8},
    ],
    "registers": [
        {"name": "REG0", "address": "0x00"},
    ],
}

MISSING_WIRES = {
    "top_level_ports": [
        {"name": "clk", "direction": "input", "width": 1},
    ],
    "submodules": [
        {"name": "core", "module": "core_logic", "instance": "u_core"},
    ],
    # internal_wires is missing
    "registers": [
        {"name": "REG0", "address": "0x00"},
    ],
}

EMPTY_SECTIONS = {
    "top_level_ports": [],
    "submodules": [],
    "internal_wires": [],
    "registers": [],
}

MINIMAL_VALID = {
    "top_level_ports": [{"name": "clk"}],
    "submodules": [{"name": "core"}],
    "internal_wires": [{"name": "w1"}],
    "registers": [{"name": "r1"}],
}


# ===========================================================================
# Test 1: Complete L9 — PASS
# ===========================================================================
class TestCompleteL9:
    def test_all_sections_present(self, tmp_path):
        """Complete L9 with all sections → PASS."""
        f = tmp_path / "L9.json"
        f.write_text(json.dumps(COMPLETE_L9))
        findings, summary = l9c.audit_l9(f)
        error_findings = [fi for fi in findings if fi.severity == "ERROR"]
        assert len(error_findings) == 0

    def test_cli_pass(self, tmp_path):
        """CLI returns exit 0 for complete L9."""
        f = tmp_path / "L9.json"
        f.write_text(json.dumps(COMPLETE_L9))
        report = tmp_path / "report.json"

        res = subprocess.run(
            [sys.executable, str(SCRIPT),
             '--l9-file', str(f),
             '--json', str(report)],
            capture_output=True, text=True)
        assert res.returncode == 0
        data = json.loads(report.read_text())
        assert data["summary"]["pass"] is True


# ===========================================================================
# Test 2: Complete L9 with aliases — PASS
# ===========================================================================
class TestAliases:
    def test_alias_resolution(self, tmp_path):
        """L9 using dtop_ports/wire_map/register_infrastructure aliases → PASS."""
        f = tmp_path / "L9.json"
        f.write_text(json.dumps(COMPLETE_L9_ALIASES))
        findings, summary = l9c.audit_l9(f)
        error_findings = [fi for fi in findings if fi.severity == "ERROR"]
        assert len(error_findings) == 0
        assert summary["top_level_ports"]["key"] == "dtop_ports"
        assert summary["internal_wires"]["key"] == "wire_map"
        assert summary["registers"]["key"] == "register_infrastructure"


# ===========================================================================
# Test 3: Missing submodules — FAIL
# ===========================================================================
class TestMissingSubmodules:
    def test_no_submodules(self, tmp_path):
        """L9 without submodules section → MISSING_SECTION."""
        f = tmp_path / "L9.json"
        f.write_text(json.dumps(MISSING_SUBMODULES))
        findings, summary = l9c.audit_l9(f)
        error_findings = [fi for fi in findings if fi.severity == "ERROR"]
        assert len(error_findings) >= 1
        assert any(fi.section == "submodules" for fi in error_findings)

    def test_cli_fail_missing(self, tmp_path):
        """CLI returns exit 1 when submodules missing."""
        f = tmp_path / "L9.json"
        f.write_text(json.dumps(MISSING_SUBMODULES))

        res = subprocess.run(
            [sys.executable, str(SCRIPT),
             '--l9-file', str(f)],
            capture_output=True, text=True)
        assert res.returncode == 1


# ===========================================================================
# Test 4: Missing wires — FAIL
# ===========================================================================
class TestMissingWires:
    def test_no_wires(self, tmp_path):
        """L9 without internal_wires section → MISSING_SECTION."""
        f = tmp_path / "L9.json"
        f.write_text(json.dumps(MISSING_WIRES))
        findings, summary = l9c.audit_l9(f)
        error_findings = [fi for fi in findings if fi.severity == "ERROR"]
        assert len(error_findings) >= 1
        assert any(fi.section == "internal_wires" for fi in error_findings)


# ===========================================================================
# Test 5: Invalid JSON — FAIL (exit 2)
# ===========================================================================
class TestInvalidJson:
    def test_not_valid_json(self, tmp_path):
        """File with invalid JSON → INVALID_JSON finding."""
        f = tmp_path / "L9.json"
        f.write_text("{this is not valid json}")
        findings, summary = l9c.audit_l9(f)
        assert len(findings) >= 1
        assert findings[0].category == "INVALID_JSON"

    def test_cli_exit_2(self, tmp_path):
        """CLI returns exit 2 for invalid JSON."""
        f = tmp_path / "L9.json"
        f.write_text("{invalid json!!!}")

        res = subprocess.run(
            [sys.executable, str(SCRIPT),
             '--l9-file', str(f)],
            capture_output=True, text=True)
        assert res.returncode == 2


# ===========================================================================
# Test 6: Empty file — FAIL (exit 2)
# ===========================================================================
class TestEmptyFile:
    def test_empty_file(self, tmp_path):
        """Empty L9 file → INVALID_JSON."""
        f = tmp_path / "L9.json"
        f.write_text("")
        findings, summary = l9c.audit_l9(f)
        assert len(findings) >= 1
        assert findings[0].category == "INVALID_JSON"


# ===========================================================================
# Test 7: Minimal valid L9 — PASS
# ===========================================================================
class TestMinimalValid:
    def test_minimal_sections(self, tmp_path):
        """L9 with minimal but present sections → PASS."""
        f = tmp_path / "L9.json"
        f.write_text(json.dumps(MINIMAL_VALID))
        findings, summary = l9c.audit_l9(f)
        error_findings = [fi for fi in findings if fi.severity == "ERROR"]
        assert len(error_findings) == 0


# ===========================================================================
# Test 8: All sections empty — FAIL
# ===========================================================================
class TestEmptySections:
    def test_all_empty(self, tmp_path):
        """L9 with all sections empty → EMPTY_SECTION findings."""
        f = tmp_path / "L9.json"
        f.write_text(json.dumps(EMPTY_SECTIONS))
        findings, summary = l9c.audit_l9(f)
        error_findings = [fi for fi in findings if fi.severity == "ERROR"]
        assert len(error_findings) == 4
        assert all(fi.category == "EMPTY_SECTION" for fi in error_findings)


# ===========================================================================
# Test 9: File does not exist — FAIL (exit 2)
# ===========================================================================
class TestFileNotFound:
    def test_missing_file(self, tmp_path):
        """Non-existent L9 file → MISSING_FILE."""
        findings, summary = l9c.audit_l9(tmp_path / "nonexistent.json")
        assert len(findings) == 1
        assert findings[0].category == "MISSING_FILE"

    def test_cli_exit_2_missing(self, tmp_path):
        """CLI returns exit 2 for missing file."""
        res = subprocess.run(
            [sys.executable, str(SCRIPT),
             '--l9-file', str(tmp_path / "nonexistent.json")],
            capture_output=True, text=True)
        assert res.returncode == 2


# ===========================================================================
# v0.56 B2: nested orchestrator schema (dtop_top_level.ports)
# ===========================================================================
class TestNestedOrchestratorSchema:
    """phase1-orchestrate/SKILL.md puts ports under
    `dtop_top_level.ports`. Prior to v0.56 the audit only scanned root
    keys, so it false-positively flagged the orchestrator-shaped L9 as
    MISSING_SECTION (24LC256 + ADS1115 multi-IC validation hit this on
    every run)."""

    def test_orchestrator_nested_ports_accepted(self, tmp_path):
        l9 = tmp_path / "L9.json"
        l9.write_text(json.dumps({
            "dtop_top_level": {
                "ports": [{"name": "p0"}, {"name": "p1"}]
            },
            "submodules": ["a", "b"],
            "internal_wires": [{"name": "w0"}],
            "registers": [{"name": "r0"}],
        }))
        findings, _ = l9c.audit_l9(l9)
        rules = [(f.category, f.section) for f in findings]
        assert ("MISSING_SECTION", "top_level_ports") not in rules

    def test_root_top_level_ports_still_works(self, tmp_path):
        """Backwards compat: legacy root-level top_level_ports still found."""
        l9 = tmp_path / "L9.json"
        l9.write_text(json.dumps({
            "top_level_ports": [{"name": "p0"}],
            "submodules": ["a"],
            "internal_wires": [{"name": "w0"}],
            "registers": [{"name": "r0"}],
        }))
        findings, _ = l9c.audit_l9(l9)
        rules = [(f.category, f.section) for f in findings]
        assert ("MISSING_SECTION", "top_level_ports") not in rules

    def test_nested_under_dtop_alias_also_works(self, tmp_path):
        """`dtop` (without `_top_level`) is also recognised."""
        l9 = tmp_path / "L9.json"
        l9.write_text(json.dumps({
            "dtop": {"ports": [{"name": "p0"}]},
            "submodules": ["a"],
            "internal_wires": [{"name": "w0"}],
            "registers": [{"name": "r0"}],
        }))
        findings, _ = l9c.audit_l9(l9)
        assert all(f.section != "top_level_ports" for f in findings)


# ===========================================================================
# v0.57 D4: registers section conditional on L9.no_registers flag
# ===========================================================================
class TestNoRegistersFlag:
    """Pure-logic / pad-only / some analog-FE ICs have no addressable
    registers. Forcing them to fabricate an empty `registers: []` block
    (or fail completeness) is wrong; they should declare
    `no_registers: true` at L9 root and the gate skips the section."""

    def test_no_registers_true_skips_section(self, tmp_path):
        l9 = tmp_path / "L9.json"
        l9.write_text(json.dumps({
            "no_registers": True,
            "top_level_ports": [{"name": "p0"}],
            "submodules": ["a"],
            "internal_wires": [{"name": "w0"}],
            # NO registers block at all
        }))
        findings, summary = l9c.audit_l9(l9)
        errors = [f for f in findings if f.severity == "ERROR"]
        # No ERROR for missing registers
        assert all(f.section != "registers" for f in errors)
        # SKIPPED_SECTION info finding present
        skipped = [f for f in findings
                   if f.category == "SKIPPED_SECTION"
                   and f.section == "registers"]
        assert len(skipped) == 1
        assert summary["registers"]["skipped"] is True

    def test_registers_not_applicable_alias_also_works(self, tmp_path):
        """`registers_not_applicable: true` is accepted as an alias."""
        l9 = tmp_path / "L9.json"
        l9.write_text(json.dumps({
            "registers_not_applicable": True,
            "top_level_ports": [{"name": "p0"}],
            "submodules": ["a"],
            "internal_wires": [{"name": "w0"}],
        }))
        findings, _ = l9c.audit_l9(l9)
        errors = [f for f in findings if f.severity == "ERROR"]
        assert all(f.section != "registers" for f in errors)

    def test_no_registers_false_still_requires_section(self, tmp_path):
        """Backwards compat: when the flag is absent (or false), the
        registers section is still hard-required."""
        l9 = tmp_path / "L9.json"
        l9.write_text(json.dumps({
            "no_registers": False,
            "top_level_ports": [{"name": "p0"}],
            "submodules": ["a"],
            "internal_wires": [{"name": "w0"}],
            # NO registers block
        }))
        findings, _ = l9c.audit_l9(l9)
        errors = [f for f in findings if f.severity == "ERROR"]
        assert any(f.section == "registers" for f in errors)

    def test_no_registers_absent_still_requires_section(self, tmp_path):
        """Default behaviour (no flag at all) is the legacy hard-required."""
        l9 = tmp_path / "L9.json"
        l9.write_text(json.dumps({
            "top_level_ports": [{"name": "p0"}],
            "submodules": ["a"],
            "internal_wires": [{"name": "w0"}],
        }))
        findings, _ = l9c.audit_l9(l9)
        errors = [f for f in findings if f.severity == "ERROR"]
        assert any(f.section == "registers" for f in errors)
