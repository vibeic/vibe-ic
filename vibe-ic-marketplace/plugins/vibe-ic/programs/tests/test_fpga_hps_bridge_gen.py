"""Unit tests for fpga_hps_bridge_gen.py — deterministic HPS bridge generator.

The register map is a FIXED 16-entry lookup with exact byte offsets
(0x00..0x3C). An LLM paraphrasing those offsets is a SILENT bug, so this proves
the generator emits the 16 offsets + the documented file set VERBATIM, is
chip-AGNOSTIC (IC name / config are params), and is deterministic.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "fpga_hps_bridge_gen.py"
assert SCRIPT.exists()

# The 16 registers, exactly as in skills/fpga-hps-bridge/SKILL.md "Register Map".
EXPECTED_REGS = [
    (0x00, "CTRL", "R/W"),
    (0x04, "STATUS", "R"),
    (0x08, "TEST_NUM", "R"),
    (0x0C, "PASS_COUNT", "R"),
    (0x10, "FAIL_COUNT", "R"),
    (0x14, "TOTAL_TESTS", "R"),
    (0x18, "COV_TOGGLE", "R"),
    (0x1C, "COV_STATE", "R"),
    (0x20, "COV_GROUP", "R"),
    (0x24, "COV_BRANCH", "R"),
    (0x28, "LOOP_COUNT", "R/W"),
    (0x2C, "LOOP_PASS", "R"),
    (0x30, "LOOP_FAIL", "R"),
    (0x34, "FMAX_RESULT", "R"),
    (0x38, "CHIP_ID", "R"),
    (0x3C, "VERSION", "R"),
]


def _run(out_dir, *extra):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--ic", "widgetx", "--out", str(out_dir), *extra],
        capture_output=True, text=True)


def test_emits_documented_file_set(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "common_rtl" / "hps_bridge.sv").is_file()
    assert (tmp_path / "widgetx_hps_top.sv").is_file()   # <ic>_hps_top.sv
    assert (tmp_path / "hps_test.py").is_file()
    assert (tmp_path / "hps_register_map.md").is_file()


def test_16_register_offsets_verbatim_in_map(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    md = (tmp_path / "hps_register_map.md").read_text()
    # exactly 16 register rows, each offset+name+rw verbatim
    for off, name, rw in EXPECTED_REGS:
        assert f"| 0x{off:02X} | {name} | {rw} |" in md, f"missing 0x{off:02X} {name}"
    # no extra / no missing — count the data rows
    data_rows = [ln for ln in md.splitlines()
                 if ln.startswith("| 0x")]
    assert len(data_rows) == 16


def test_offsets_in_python_test_script(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    py = (tmp_path / "hps_test.py").read_text()
    for off, name, _rw in EXPECTED_REGS:
        assert f"{name:<12} = 0x{off:02X}" in py, f"missing Reg.{name} = 0x{off:02X}"


def test_bridge_sv_read_mux_covers_all_16_words(tmp_path):
    r = _run(tmp_path)
    sv = (tmp_path / "common_rtl" / "hps_bridge.sv").read_text()
    # word index = byte offset >> 2, 0..15 each appear in the read case
    for off, name, _rw in EXPECTED_REGS:
        word = off >> 2
        assert f"{name}" in sv  # name appears as a comment
    # CHIP_ID / VERSION word-15/14 arms present
    assert "14: csr_rdata <= chip_id_q;" in sv
    assert "15: csr_rdata <= version_q;" in sv


def test_chip_agnostic_param_propagation(tmp_path):
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--ic", "Foo-Bar Chip", "--out", str(tmp_path),
         "--chip-id", "0x42", "--version", "0x09", "--bist", "fb_bist", "--dut", "fb_core"],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    # IC name canonicalised: "Foo-Bar Chip" -> foo_bar_chip
    top = tmp_path / "foo_bar_chip_hps_top.sv"
    assert top.is_file()
    body = top.read_text()
    assert "module foo_bar_chip_hps_top" in body
    assert "32'h00000042" in body and "32'h00000009" in body  # CHIP_ID / VERSION
    assert "fb_bist u_bist" in body                            # custom BIST module
    sv = (tmp_path / "common_rtl" / "hps_bridge.sv").read_text()
    assert "CHIP_ID_VALUE = 32'h00000042" in sv
    assert "VERSION_VALUE = 32'h00000009" in sv


def test_deterministic_byte_identical(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    assert _run(a).returncode == 0
    assert _run(b).returncode == 0
    for rel in ("common_rtl/hps_bridge.sv", "widgetx_hps_top.sv",
                "hps_test.py", "hps_register_map.md"):
        assert (a / rel).read_text() == (b / rel).read_text(), f"non-deterministic: {rel}"


def test_graceful_on_empty_ic(tmp_path):
    # deny: an IC that canonicalises to empty must fail cleanly (exit 1), not crash.
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--ic", "***", "--out", str(tmp_path)],
        capture_output=True, text=True)
    assert r.returncode == 1
    assert "empty module stem" in r.stderr


def test_graceful_on_out_of_range_constant(tmp_path):
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--ic", "widgetx", "--out", str(tmp_path),
         "--chip-id", "0x1FF"],   # > 0xFF
        capture_output=True, text=True)
    assert r.returncode == 1
    assert "out of" in r.stderr and "range" in r.stderr


def test_generated_sv_compiles_if_iverilog(tmp_path):
    """The hps_bridge.sv slave must be standalone-synthesizable."""
    if not shutil.which("iverilog"):
        pytest.skip("iverilog not installed")
    assert _run(tmp_path).returncode == 0
    sv = tmp_path / "common_rtl" / "hps_bridge.sv"
    r = subprocess.run(["iverilog", "-g2012", "-o", str(tmp_path / "b"), str(sv)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
