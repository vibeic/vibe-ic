"""Unit tests for upf_syntax_check.py.

Tests verify correct detection of UPF files and required power-intent commands.
"""
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'upf_syntax_check.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import upf_syntax_check as usc  # noqa: E402


VALID_UPF = """\
# Power intent for top-level design
set_scope /top
create_power_domain PD_TOP -include_scope
create_supply_net VDD -domain PD_TOP
create_supply_net VSS -domain PD_TOP
create_supply_port VDD -direction in
set_domain_supply_net PD_TOP -primary_power_net VDD -primary_ground_net VSS
"""


# ---------------------------------------------------------------------------
# PASS: Valid UPF with power domain and supply
# ---------------------------------------------------------------------------
def test_valid_upf_pass(tmp_path):
    (tmp_path / "power.upf").write_text(VALID_UPF)

    result = usc.audit_upf(tmp_path)
    assert result.passed is True
    assert result.summary["has_power_domain"] is True
    assert result.summary["has_supply_def"] is True
    assert len(result.summary["valid_files"]) == 1


# ---------------------------------------------------------------------------
# FAIL: No UPF files
# ---------------------------------------------------------------------------
def test_no_upf_fail(tmp_path):
    (tmp_path / "design.v").write_text("module top(); endmodule")

    result = usc.audit_upf(tmp_path)
    assert result.passed is False
    assert result.summary["files_found"] == 0


# ---------------------------------------------------------------------------
# FAIL: UPF without create_power_domain
# ---------------------------------------------------------------------------
def test_no_power_domain_fail(tmp_path):
    upf = tmp_path / "power.upf"
    upf.write_text(
        "set_scope /top\n"
        "create_supply_net VDD\n"
        "create_supply_net VSS\n"
        "set_domain_supply_net PD_TOP -primary_power_net VDD\n"
    )

    result = usc.audit_upf(tmp_path)
    assert result.passed is False
    assert result.summary["has_power_domain"] is False
    assert result.summary["has_supply_def"] is True


# ---------------------------------------------------------------------------
# FAIL: UPF with power domain but no supply
# ---------------------------------------------------------------------------
def test_no_supply_fail(tmp_path):
    upf = tmp_path / "power.upf"
    upf.write_text(
        "set_scope /top\n"
        "create_power_domain PD_TOP -include_scope\n"
        "set_domain_supply_net PD_TOP\n"
        "# TODO: add supply nets\n"
    )

    result = usc.audit_upf(tmp_path)
    assert result.passed is False
    assert result.summary["has_power_domain"] is True
    assert result.summary["has_supply_def"] is False


# ---------------------------------------------------------------------------
# FAIL: Stub UPF (< 3 non-empty, non-comment lines)
# ---------------------------------------------------------------------------
def test_stub_upf_fail(tmp_path):
    upf = tmp_path / "power.upf"
    upf.write_text("# stub\nset_scope /top\n")

    result = usc.audit_upf(tmp_path)
    assert result.passed is False
    # File found but it's a stub
    assert result.summary["files_found"] == 1
    assert len(result.summary["valid_files"]) == 0


# ---------------------------------------------------------------------------
# FAIL: Empty directory (non-existent path)
# ---------------------------------------------------------------------------
def test_empty_dir_fail(tmp_path):
    nonexistent = tmp_path / "does_not_exist"

    result = usc.audit_upf(nonexistent)
    assert result.passed is False
    assert result.summary["files_found"] == 0


# ---------------------------------------------------------------------------
# CLI exit codes
# ---------------------------------------------------------------------------
def test_cli_pass(tmp_path):
    (tmp_path / "chip.upf").write_text(VALID_UPF)
    rc = usc.main([str(tmp_path)])
    assert rc == 0


def test_cli_fail(tmp_path):
    rc = usc.main([str(tmp_path)])
    assert rc == 1
