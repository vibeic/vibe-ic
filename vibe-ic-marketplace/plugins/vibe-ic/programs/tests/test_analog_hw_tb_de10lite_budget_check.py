"""Unit tests for analog_hw_tb_de10lite_budget_check.py.

Extracted from the `analog-hw-testbench-gen` skill's "Do not exceed DE10-Lite
GPIO count (36 GPIO + 10 Arduino header)" rule.

Tests:
  1. Valid DE10-Lite QSF (real corpus pin pattern)  — clean PASS (exit 0)
  2. Over-budget (47 external-I/O pins)             — FAIL external-io-budget
  3. Pin double-assignment (board short)            — FAIL pin-double-assignment
  4. Empty DE10-Lite QSF / no pin map               — FAIL no-pin-assignments (vacuous guard)
  5. Missing file                                   — NO_DATA exit 2 (honesty)
  6. At-budget (exactly 46 external pins)           — PASS (boundary, no false-fire)
  7. Directory scan finds nested .qsf
  8. Non-DE10-Lite (DE10-Nano Cyclone V) QSF        — NO_DATA out-of-scope (no false-fire)
  9. Real corpus DE10-Lite QSF (if present)         — PASS (regression: no false-fire)
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from _hostpaths import corpus_path

SCRIPT = Path(__file__).parent.parent / "analog_hw_tb_de10lite_budget_check.py"
assert SCRIPT.exists(), f"program not found at {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import analog_hw_tb_de10lite_budget_check as chk  # noqa: E402

# Header that puts a fixture QSF IN SCOPE (declares the DE10-Lite part).
_DE10LITE_HEADER = [
    'set_global_assignment -name FAMILY "MAX 10"',
    "set_global_assignment -name DEVICE 10M50DAF484C7G",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(tmp_path: Path, name: str, body_lines, in_scope: bool = True) -> Path:
    lines = (_DE10LITE_HEADER if in_scope else []) + list(body_lines)
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _run(target: Path):
    """Run via subprocess; return (exit_code, parsed_json_report)."""
    res = subprocess.run(
        [sys.executable, str(SCRIPT), str(target), "--json"],
        capture_output=True, text=True,
    )
    return res.returncode, json.loads(res.stdout)


# ---------------------------------------------------------------------------
# 1. Valid QSF — clean PASS (mirrors real as3616 corpus pattern)
# ---------------------------------------------------------------------------

def test_valid_corpus_pattern_pass(tmp_path):
    qsf = _write(tmp_path, "good.qsf", [
        "set_location_assignment PIN_P11 -to CLOCK_50",
        "set_location_assignment PIN_B8 -to RESET_N",
        "set_location_assignment PIN_V10 -to ID_BUS",   # GPIO_0[0]
        "set_location_assignment PIN_W10 -to CC_IN",     # GPIO_0[1]
        "set_location_assignment PIN_A8 -to LEDR[0]",
        "set_location_assignment PIN_A9 -to LEDR[1]",
    ])
    code, rep = _run(qsf)
    assert code == 0
    assert rep["status"] == "PASS"
    assert rep["total_findings"] == 0


# ---------------------------------------------------------------------------
# 2. Over-budget — the real FAIL this gate exists for
# ---------------------------------------------------------------------------

def test_over_budget_fail(tmp_path):
    lines = []
    # all 36 GPIO_0 header pins + 11 Arduino pins = 47 external-I/O pins
    for i, pin in enumerate(chk._GPIO0_PINS.values()):
        lines.append(f"set_location_assignment {pin} -to dut_g{i}")
    for j, pin in enumerate(list(chk._ARDUINO_PINS.values())[:11]):
        lines.append(f"set_location_assignment {pin} -to dut_a{j}")
    qsf = _write(tmp_path, "over.qsf", lines)
    code, rep = _run(qsf)
    assert code == 1
    assert rep["status"] == "FAIL"
    rules = {f["rule"] for f in rep["findings"]}
    assert "external-io-budget" in rules
    bud = next(f for f in rep["findings"] if f["rule"] == "external-io-budget")
    assert bud["external_io_pins_used"] == 47
    assert bud["budget"] == 46


# ---------------------------------------------------------------------------
# 3. Pin double-assignment — board short
# ---------------------------------------------------------------------------

def test_pin_double_assignment_fail(tmp_path):
    qsf = _write(tmp_path, "dbl.qsf", [
        "set_location_assignment PIN_V10 -to sig_a",
        "set_location_assignment PIN_V10 -to sig_b",
    ])
    code, rep = _run(qsf)
    assert code == 1
    assert rep["status"] == "FAIL"
    rules = {f["rule"] for f in rep["findings"]}
    assert "pin-double-assignment" in rules


# ---------------------------------------------------------------------------
# 4. Empty QSF / no pin map — vacuous-pass guard
# ---------------------------------------------------------------------------

def test_no_pin_assignments_fail(tmp_path):
    # in-scope (DE10-Lite header present) but no pin assignments
    qsf = _write(tmp_path, "empty.qsf", [
        'set_global_assignment -name TOP_LEVEL_ENTITY chip_top',
    ])
    code, rep = _run(qsf)
    assert code == 1
    assert rep["status"] == "FAIL"
    rules = {f["rule"] for f in rep["findings"]}
    assert "no-pin-assignments" in rules


# ---------------------------------------------------------------------------
# 5. Missing file — honesty: NO_DATA, never vacuous PASS
# ---------------------------------------------------------------------------

def test_missing_file_no_data(tmp_path):
    target = tmp_path / "does_not_exist.qsf"
    code, rep = _run(target)
    assert code == 2
    assert rep["status"] == "NO_DATA"


# ---------------------------------------------------------------------------
# 6. Exactly-at-budget — boundary, no false-fire
# ---------------------------------------------------------------------------

def test_at_budget_pass(tmp_path):
    lines = []
    # 36 GPIO_0 + 10 Arduino = exactly 46 external-I/O pins (the ceiling)
    for i, pin in enumerate(chk._GPIO0_PINS.values()):
        lines.append(f"set_location_assignment {pin} -to dut_g{i}")
    for j, pin in enumerate(list(chk._ARDUINO_PINS.values())[:10]):
        lines.append(f"set_location_assignment {pin} -to dut_a{j}")
    qsf = _write(tmp_path, "atbudget.qsf", lines)
    code, rep = _run(qsf)
    assert code == 0
    assert rep["status"] == "PASS"
    assert rep["total_findings"] == 0


# ---------------------------------------------------------------------------
# 7. Directory scan finds nested .qsf
# ---------------------------------------------------------------------------

def test_directory_scan(tmp_path):
    nested = tmp_path / "fpga"
    nested.mkdir()
    _write(nested, "top.qsf", [
        "set_location_assignment PIN_P11 -to CLOCK_50",
        "set_location_assignment PIN_V10 -to ID_BUS",
    ])
    code, rep = _run(tmp_path)
    assert code == 0
    assert rep["status"] == "PASS"
    assert rep["in_scope_files"] == 1


# ---------------------------------------------------------------------------
# 8. Non-DE10-Lite (DE10-Nano Cyclone V) — out of scope, NO false-fire
# ---------------------------------------------------------------------------

def test_non_de10lite_out_of_scope(tmp_path):
    # A Cyclone V (DE10-Nano) QSF — its pins are NOT DE10-Lite pins, but that
    # is correct for its board. Must be reported NO_DATA, never FAIL.
    p = tmp_path / "de10nano.qsf"
    p.write_text("\n".join([
        'set_global_assignment -name FAMILY "Cyclone V"',
        "set_global_assignment -name DEVICE 5CSEBA6U23I7",
        "set_location_assignment PIN_V11 -to CLOCK_50",
        "set_location_assignment PIN_AH17 -to KEY[0]",
    ]) + "\n", encoding="utf-8")
    code, rep = _run(p)
    assert code == 2
    assert rep["status"] == "NO_DATA"


# ---------------------------------------------------------------------------
# 9. Real corpus DE10-Lite QSF — regression: must NOT false-fire
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("corpus_rel", [
    "phase2+3_v052/fpga/as3616_fpga.qsf",
    "spm_benchmark_v0211/phase2/stage1/fpga/spm_fpga_bist.qsf",
])
def test_real_corpus_de10lite_pass(corpus_rel):
    p = corpus_path(corpus_rel)
    if not p.exists():
        pytest.skip("external benchmark corpus not available: set "
                    f"$VIBEIC_CORPUS_ROOT to a directory containing {corpus_rel}")
    code, rep = _run(p)
    assert code == 0, rep
    assert rep["status"] == "PASS"
