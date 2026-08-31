"""Unit tests for integration_spec_audit.py.

Tests verify correct detection of missing top_module, missing submodules,
stub/placeholder text, register/reset/clock warnings, and empty directories.
"""
import json
import shutil
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'integration_spec_audit.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import integration_spec_audit as isa  # noqa: E402
from _hostpaths import require_repo


# ---------------------------------------------------------------------------
# Helper: write a valid L9 JSON with all required and optional keys
# ---------------------------------------------------------------------------
def make_valid_l9(**overrides):
    base = {
        "top_module": "dtop",
        "submodules": [
            {"name": "uart_core", "ports": ["clk", "rst_n", "tx", "rx"]},
            {"name": "spi_master", "ports": ["clk", "rst_n", "mosi", "miso"]},
        ],
        "internal_wires": ["clk_net", "rst_net"],
        "registers": {"ctrl": {"width": 8}},
        "reset": {"sequence": "sync"},
        "clock": {"main": "50MHz"},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Test 1: Valid L9 integration spec → PASS
# ---------------------------------------------------------------------------
def test_valid_l9_pass(tmp_path):
    data = make_valid_l9()
    (tmp_path / "L9_integration.json").write_text(json.dumps(data))

    result = isa.audit(str(tmp_path))
    assert result.passed is True
    assert result.summary["errors"] == 0


def test_gate_report_is_not_graded_as_an_integration_spec(tmp_path):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps(make_valid_l9()))

    reports = tmp_path / "reports" / "phase2" / "gates"
    reports.mkdir(parents=True)
    report = reports / "ip_integration.json"
    report.write_text(json.dumps({
        "program": "ip_integration_check",
        "verdict": "PASS_WITH_REVIEW",
    }))

    result = isa.audit(str(tmp_path))
    assert result.passed is True
    assert result.summary == {
        "files_checked": 1,
        "files_passed": 1,
        "errors": 0,
        "stubs_found": 0,
    }
    assert all(f.file != "reports/phase2/gates/ip_integration.json"
               for f in result.findings)


def test_real_l9_discovery_excludes_a_sibling_generated_report(tmp_path):
    source = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
        "fixtures", "l17_e1_rail", "shared.L9_INTEGRATION_SPEC.json")
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    spec = docs / "shared.L9_INTEGRATION_SPEC.json"
    shutil.copy2(source, spec)

    reports = tmp_path / "reports" / "phase2" / "gates"
    reports.mkdir(parents=True)
    (reports / "ip_integration.json").write_text(json.dumps({
        "program": "ip_integration_check",
        "verdict": "PASS_WITH_REVIEW",
    }))

    assert isa.discover_spec_files(tmp_path) == [spec]


# ---------------------------------------------------------------------------
# Test 2: Missing top_module → FAIL
# ---------------------------------------------------------------------------
def test_missing_top_module_fail(tmp_path):
    data = make_valid_l9()
    del data["top_module"]
    (tmp_path / "L9_integration.json").write_text(json.dumps(data))

    result = isa.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert any(f.rule == "MISSING_TOP" for f in errors)


# ---------------------------------------------------------------------------
# Test 3: Missing submodules → FAIL
# ---------------------------------------------------------------------------
def test_missing_submodules_fail(tmp_path):
    data = make_valid_l9()
    del data["submodules"]
    (tmp_path / "L9_integration.json").write_text(json.dumps(data))

    result = isa.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert any(f.rule == "MISSING_SUBMODULES" for f in errors)


# ---------------------------------------------------------------------------
# Test 4: Stub/TODO detected in submodule → FAIL
# ---------------------------------------------------------------------------
def test_stub_detected_fail(tmp_path):
    data = make_valid_l9()
    data["submodules"][0]["ports"] = ["clk", "TODO: add more ports"]
    (tmp_path / "L9_integration.json").write_text(json.dumps(data))

    result = isa.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert any(f.rule == "STUB_DETECTED" for f in errors)


# ---------------------------------------------------------------------------
# Test 5: Empty directory → FAIL
# ---------------------------------------------------------------------------
def test_no_json_fail(tmp_path):
    result = isa.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert any(f.rule == "NO_SPEC_FILE" for f in errors)


# ---------------------------------------------------------------------------
# Test 6: No register infrastructure → WARNING but PASS
# ---------------------------------------------------------------------------
def test_register_infra_warning(tmp_path):
    data = make_valid_l9()
    del data["registers"]
    (tmp_path / "L9_integration.json").write_text(json.dumps(data))

    result = isa.audit(str(tmp_path))
    assert result.passed is True
    warnings = [f for f in result.findings if f.severity == "WARNING"]
    assert any(f.rule == "REGISTER_INFRA_MISSING" for f in warnings)


# ---------------------------------------------------------------------------
# Test 7: No reset key → WARNING but PASS
# ---------------------------------------------------------------------------
def test_por_sync_warning(tmp_path):
    data = make_valid_l9()
    del data["reset"]
    (tmp_path / "L9_integration.json").write_text(json.dumps(data))

    result = isa.audit(str(tmp_path))
    assert result.passed is True
    warnings = [f for f in result.findings if f.severity == "WARNING"]
    assert any(f.rule == "POR_SYNC_MISSING" for f in warnings)


# ---------------------------------------------------------------------------
# Test 8: No clock key → WARNING but PASS
# ---------------------------------------------------------------------------
def test_clock_gating_warning(tmp_path):
    data = make_valid_l9()
    del data["clock"]
    (tmp_path / "L9_integration.json").write_text(json.dumps(data))

    result = isa.audit(str(tmp_path))
    assert result.passed is True
    warnings = [f for f in result.findings if f.severity == "WARNING"]
    assert any(f.rule == "CLOCK_GATING_MISSING" for f in warnings)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
