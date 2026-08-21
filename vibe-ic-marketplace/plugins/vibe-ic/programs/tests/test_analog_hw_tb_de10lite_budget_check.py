"""Unit tests for analog_hw_tb_de10lite_budget_check.py.

Extracted from the `analog-hw-testbench-gen` skill's "Do not exceed DE10-Lite
GPIO count (36 GPIO + 10 Arduino header)" rule.

Tests:
  1. Valid DE10-Lite QSF (real corpus pin pattern)  — clean PASS (exit 0)
  2. 47 header pins, all physically real            — PASS (#693 regression:
     the withdrawn external-io-budget rule FAILed this legal map)
  3. Pin double-assignment (board short)            — FAIL pin-double-assignment
  4. Empty DE10-Lite QSF / no pin map               — FAIL no-pin-assignments (vacuous guard)
  5. Missing file                                   — NO_DATA exit 2 (honesty)
  6. Many header pins used                          — PASS (no false-fire)
  7. Directory scan finds nested .qsf
  8. Non-DE10-Lite (DE10-Nano Cyclone V) QSF        — NO_DATA out-of-scope (no false-fire)
  9. Real corpus DE10-Lite QSF (if present)         — PASS (regression: no false-fire)
 10. Pin-map .qsf + settings-only .qsf in one dir   — PASS (#693 regression:
     `no-pin-assignments` used to fire per FILE and turn a normal Quartus
     project split into a project-wide FAIL)
 11. `--json <path>` writes the report to that path (#693 regression: `--json`
     was `store_true`, so the house-style invocation died in argparse with
     exit 2 — which flow_compliance_check records as a pass)
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
# 2. #693 — 47 physically-real header pins is a LEGAL map, not a finding.
#
# This test used to assert the opposite (`external-io-budget`, exit 1). The
# ceiling it asserted against, 46, is a prose bullet in the skill; this file's
# own §3.6 Arduino table has 17 entries, so the board offers 36 + 17 = 53
# external-I/O pins on its two user headers. Every pin below is on the board
# and none is assigned twice. The rule could only ever fire on maps like this
# one, and could never fire on a genuinely over-budget design, whose surplus
# pins fall outside the catalogue the rule counts from — so it was withdrawn.
# ---------------------------------------------------------------------------

def test_47_real_header_pins_is_not_a_finding(tmp_path):
    lines = []
    # all 36 GPIO_0 header pins + 11 Arduino digital I/Os = 47 real board pins
    for i, pin in enumerate(chk._GPIO0_PINS.values()):
        lines.append(f"set_location_assignment {pin} -to dut_g{i}")
    for j, pin in enumerate(list(chk._ARDUINO_PINS.values())[:11]):
        lines.append(f"set_location_assignment {pin} -to dut_a{j}")
    qsf = _write(tmp_path, "wide.qsf", lines)
    code, rep = _run(qsf)
    assert code == 0, rep
    assert rep["status"] == "PASS"
    assert rep["total_findings"] == 0
    # The count is still MEASURED — it is disclosed, just not judged.
    assert rep["external_io_pins_used"] == 47
    assert rep["external_io_pins_available"] == 53
    assert "external_io_budget" not in rep


def test_external_io_budget_rule_is_gone():
    # A withdrawn rule must not come back by accident: nothing may re-introduce
    # a threshold whose ceiling sits below the catalogue it counts from.
    assert not hasattr(chk, "_EXTERNAL_IO_BUDGET")
    assert not hasattr(chk, "check_external_io_budget")
    assert len(chk._EXTERNAL_IO_PINS) == 53


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
# 6. Many header pins used — no false-fire
# ---------------------------------------------------------------------------

def test_46_header_pins_pass(tmp_path):
    lines = []
    # 36 GPIO_0 + 10 Arduino = 46 external-I/O pins
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
# 10. #693 — a normal Quartus split (pin map + settings-only) is not a FAIL.
#
# `no-pin-assignments` used to be evaluated PER FILE. Wired at project scope —
# which is how the P0 structural umbrella and the A9 gate both drive it — that
# turned every settings-only .qsf beside a real pin map into a project-wide
# red. It is now a TARGET-level rule: the finding is "no pin map ANYWHERE".
# ---------------------------------------------------------------------------

def test_settings_only_qsf_beside_pin_map_is_not_a_finding(tmp_path):
    _write(tmp_path, "pinmap.qsf", [
        "set_location_assignment PIN_V10 -to sig_a",
        "set_location_assignment PIN_W10 -to sig_b",
    ])
    _write(tmp_path, "settings_only.qsf", [
        "set_global_assignment -name TOP_LEVEL_ENTITY top",
    ])
    code, rep = _run(tmp_path)
    assert code == 0, rep
    assert rep["status"] == "PASS"
    assert rep["in_scope_files"] == 2
    assert rep["total_assignments"] == 2


def test_no_pin_map_anywhere_still_fails(tmp_path):
    _write(tmp_path, "a.qsf", ["set_global_assignment -name TOP_LEVEL_ENTITY t"])
    _write(tmp_path, "b.qsf", ["set_global_assignment -name NUM_PARALLEL_PROCESSORS 4"])
    code, rep = _run(tmp_path)
    assert code == 1, rep
    assert {f["rule"] for f in rep["findings"]} == {"no-pin-assignments"}


# ---------------------------------------------------------------------------
# 11. #693 — `--json <path>` must WRITE, not die in argparse.
#
# `--json` was `action="store_true"`, so the flow-YAML house style
# `... . --json reports/.../de10.json` exited 2 — and exit 2 is this repo's
# disclosed cannot-judge tier, which `flow_compliance_check` records as a pass.
# One token of drift bought a permanent, undisclosed pass.
# ---------------------------------------------------------------------------

def test_json_path_argument_writes_report(tmp_path):
    qsf = _write(tmp_path, "good.qsf", [
        "set_location_assignment PIN_V10 -to ID_BUS",
    ])
    out = tmp_path / "nested" / "de10.json"
    res = subprocess.run(
        [sys.executable, str(SCRIPT), str(qsf), "--json", str(out)],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stderr
    assert out.is_file(), res.stderr
    assert json.loads(out.read_text())["status"] == "PASS"


def test_json_path_argument_preserves_fail_exit(tmp_path):
    qsf = _write(tmp_path, "dbl.qsf", [
        "set_location_assignment PIN_V10 -to sig_a",
        "set_location_assignment PIN_V10 -to sig_b",
    ])
    out = tmp_path / "de10.json"
    res = subprocess.run(
        [sys.executable, str(SCRIPT), str(qsf), "--json", str(out)],
        capture_output=True, text=True,
    )
    assert res.returncode == 1, res.stdout + res.stderr
    assert json.loads(out.read_text())["status"] == "FAIL"


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
