"""Unit tests for fpga_qsf_lint.py.

Each test creates a small QSF + RTL fixture and verifies the lint catches
(or correctly ignores) the specific pattern.

Tests:
  1. Valid QSF — clean PASS
  2. Missing RTL file — FAIL with missing-verilog-file
  3. Pin conflict — FAIL with pin-conflict
  4. Missing top entity — FAIL with missing-top-entity
  5. Missing IO standard — FAIL with missing-io-standard
  6. Empty QSF — FAIL with missing-top-entity
  7. Top entity mismatch — FAIL with top-entity-mismatch
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "fpga_qsf_lint.py"
assert SCRIPT.exists(), f"fpga_qsf_lint.py not found at {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import fpga_qsf_lint as fql  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_rtl(rtl_dir: Path, module_name: str = "my_top", filename: str = "top.v"):
    """Write a minimal Verilog file that declares a module."""
    rtl_dir.mkdir(parents=True, exist_ok=True)
    (rtl_dir / filename).write_text(
        f"module {module_name}(input clk, output led);\n"
        f"  assign led = clk;\n"
        f"endmodule\n"
    )


def _write_qsf(qsf_path: Path, lines: list[str]):
    """Write a QSF file from a list of lines."""
    qsf_path.write_text("\n".join(lines) + "\n")


def run_cli(tmp_path, qsf_lines: list[str], rtl_module: str | None = "my_top",
            rtl_filename: str = "top.v"):
    """Run fpga_qsf_lint.py via subprocess and return (result, report_dict)."""
    qsf_path = tmp_path / "project.qsf"
    rtl_dir = tmp_path / "phase2" / "stage1" / "rtl"
    out_dir = tmp_path / "out"

    _write_qsf(qsf_path, qsf_lines)
    if rtl_module is not None:
        _write_rtl(rtl_dir, module_name=rtl_module, filename=rtl_filename)
    else:
        rtl_dir.mkdir(parents=True, exist_ok=True)

    res = subprocess.run(
        [sys.executable, str(SCRIPT),
         "--qsf-file", str(qsf_path),
         "--rtl-dir", str(rtl_dir),
         "--out-dir", str(out_dir)],
        capture_output=True, text=True,
    )
    report = json.loads((out_dir / "fpga_qsf_lint.json").read_text())
    return res, report


# ---------------------------------------------------------------------------
# Test 1: Valid QSF — all checks pass
# ---------------------------------------------------------------------------

class TestValidQSF:
    def test_clean_qsf_passes(self, tmp_path):
        rtl_dir = tmp_path / "phase2" / "stage1" / "rtl"
        _write_rtl(rtl_dir, "my_top", "top.v")
        qsf_lines = [
            'set_global_assignment -name TOP_LEVEL_ENTITY my_top',
            f'set_global_assignment -name VERILOG_FILE "{rtl_dir}/top.v"',
            'set_location_assignment PIN_A1 -to clk',
            'set_location_assignment PIN_B2 -to led',
            'set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to clk',
            'set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to led',
        ]
        res, report = run_cli(tmp_path, qsf_lines, "my_top")
        assert res.returncode == 0
        assert report["status"] == "PASS"
        assert report["total_findings"] == 0


# ---------------------------------------------------------------------------
# Test 2: Missing RTL file
# ---------------------------------------------------------------------------

class TestMissingRTLFile:
    def test_missing_verilog_file_detected(self, tmp_path):
        qsf_lines = [
            'set_global_assignment -name TOP_LEVEL_ENTITY my_top',
            'set_global_assignment -name VERILOG_FILE "nonexistent.v"',
        ]
        res, report = run_cli(tmp_path, qsf_lines, "my_top")
        assert res.returncode == 1
        rules = [f["rule"] for f in report["findings"]]
        assert "missing-verilog-file" in rules


# ---------------------------------------------------------------------------
# Test 3: Pin conflict
# ---------------------------------------------------------------------------

class TestPinConflict:
    def test_two_signals_on_same_pin(self, tmp_path):
        qsf_lines = [
            'set_global_assignment -name TOP_LEVEL_ENTITY my_top',
            'set_location_assignment PIN_A1 -to clk',
            'set_location_assignment PIN_A1 -to led',
            'set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to clk',
            'set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to led',
        ]
        res, report = run_cli(tmp_path, qsf_lines, "my_top")
        assert res.returncode == 1
        rules = [f["rule"] for f in report["findings"]]
        assert "pin-conflict" in rules
        conflict = [f for f in report["findings"] if f["rule"] == "pin-conflict"][0]
        assert "clk" in conflict["signals"]
        assert "led" in conflict["signals"]


# ---------------------------------------------------------------------------
# Test 4: Missing top entity
# ---------------------------------------------------------------------------

class TestMissingTopEntity:
    def test_no_top_entity_set(self, tmp_path):
        qsf_lines = [
            '# No TOP_LEVEL_ENTITY line',
            'set_location_assignment PIN_A1 -to clk',
            'set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to clk',
        ]
        res, report = run_cli(tmp_path, qsf_lines, "my_top")
        assert res.returncode == 1
        rules = [f["rule"] for f in report["findings"]]
        assert "missing-top-entity" in rules


# ---------------------------------------------------------------------------
# Test 5: Missing IO standard
# ---------------------------------------------------------------------------

class TestMissingIOStandard:
    def test_pin_without_io_standard(self, tmp_path):
        qsf_lines = [
            'set_global_assignment -name TOP_LEVEL_ENTITY my_top',
            'set_location_assignment PIN_A1 -to clk',
            'set_location_assignment PIN_B2 -to led',
            # Only clk has IO_STANDARD, led does not
            'set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to clk',
        ]
        res, report = run_cli(tmp_path, qsf_lines, "my_top")
        assert res.returncode == 1
        rules = [f["rule"] for f in report["findings"]]
        assert "missing-io-standard" in rules
        missing = [f for f in report["findings"] if f["rule"] == "missing-io-standard"]
        assert any(f["signal"] == "led" for f in missing)


# ---------------------------------------------------------------------------
# Test 6: Empty QSF
# ---------------------------------------------------------------------------

class TestEmptyQSF:
    def test_empty_file_fails(self, tmp_path):
        qsf_lines = [
            "# Empty QSF file",
        ]
        res, report = run_cli(tmp_path, qsf_lines, "my_top")
        assert res.returncode == 1
        rules = [f["rule"] for f in report["findings"]]
        assert "missing-top-entity" in rules


# ---------------------------------------------------------------------------
# Test 7: Top entity mismatch
# ---------------------------------------------------------------------------

class TestTopEntityMismatch:
    def test_top_entity_not_in_rtl(self, tmp_path):
        qsf_lines = [
            'set_global_assignment -name TOP_LEVEL_ENTITY wrong_module',
        ]
        res, report = run_cli(tmp_path, qsf_lines, "my_top")
        assert res.returncode == 1
        rules = [f["rule"] for f in report["findings"]]
        assert "top-entity-mismatch" in rules
        mismatch = [f for f in report["findings"] if f["rule"] == "top-entity-mismatch"][0]
        assert mismatch["entity"] == "wrong_module"
        assert "my_top" in mismatch["available_modules"]


# ---------------------------------------------------------------------------
# Unit tests for parse_qsf
# ---------------------------------------------------------------------------

class TestParseQSF:
    def test_parses_all_fields(self, tmp_path):
        qsf = tmp_path / "test.qsf"
        qsf.write_text(
            'set_global_assignment -name TOP_LEVEL_ENTITY soc_top\n'
            'set_global_assignment -name VERILOG_FILE "rtl/core.v"\n'
            'set_global_assignment -name SYSTEMVERILOG_FILE "rtl/pkg.sv"\n'
            'set_location_assignment PIN_C3 -to spi_mosi\n'
            'set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to spi_mosi\n'
        )
        parsed = fql.parse_qsf(qsf)
        assert parsed["top_level_entity"] == "soc_top"
        assert "rtl/core.v" in parsed["verilog_files"]
        assert "rtl/pkg.sv" in parsed["verilog_files"]
        assert ("spi_mosi", "PIN_C3") in parsed["pin_assignments"]
        assert parsed["io_standards"]["spi_mosi"] == "3.3-V LVTTL"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
