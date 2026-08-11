"""Unit tests for sdc_syntax_check.py.

Tests verify correct detection of valid SDC files, missing SDC files,
missing create_clock, missing timing constraints, unreasonable clock
periods, and empty directories.
"""
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'sdc_syntax_check.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import sdc_syntax_check as ssc  # noqa: E402


# ---------------------------------------------------------------------------
# Test 1: Valid SDC → PASS
# ---------------------------------------------------------------------------
def test_valid_sdc_pass(tmp_path):
    sdc = """\
# Clock definition
create_clock -period 10 -name sys_clk [get_ports clk]

# Input/output delays
set_input_delay -clock sys_clk -max 2.0 [get_ports data_in]
set_output_delay -clock sys_clk -max 3.0 [get_ports data_out]
"""
    (tmp_path / "timing.sdc").write_text(sdc)

    result = ssc.audit(str(tmp_path))
    assert result.passed is True
    assert result.summary["valid_files"] >= 1
    assert result.summary["errors"] == 0


# ---------------------------------------------------------------------------
# Test 2: No .sdc files → FAIL
# ---------------------------------------------------------------------------
def test_no_sdc_fail(tmp_path):
    (tmp_path / "design.v").write_text("module top(); endmodule")

    result = ssc.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert any(f.rule == "NO_SDC_FILE" for f in errors)


# ---------------------------------------------------------------------------
# Test 3: SDC without create_clock → FAIL
# ---------------------------------------------------------------------------
def test_no_create_clock_fail(tmp_path):
    sdc = """\
# Timing constraints only, no clock definition
set_input_delay -clock sys_clk -max 2.0 [get_ports data_in]
set_output_delay -clock sys_clk -max 3.0 [get_ports data_out]
"""
    (tmp_path / "timing.sdc").write_text(sdc)

    result = ssc.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert any(f.rule == "NO_CREATE_CLOCK" for f in errors)


# ---------------------------------------------------------------------------
# Test 4: SDC with create_clock but no delay constraints → FAIL
# ---------------------------------------------------------------------------
def test_no_timing_constraint_fail(tmp_path):
    sdc = """\
# Clock only, no timing constraints
create_clock -period 10 -name sys_clk [get_ports clk]
"""
    (tmp_path / "timing.sdc").write_text(sdc)

    result = ssc.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert any(f.rule == "NO_TIMING_CONSTRAINT" for f in errors)


# ---------------------------------------------------------------------------
# Test 5: Unreasonable clock period (too small) → FAIL
# ---------------------------------------------------------------------------
def test_unreasonable_period_fail(tmp_path):
    sdc = """\
# Unreasonably small period (0.001 ns = 1 THz)
create_clock -period 0.001 -name fast_clk [get_ports clk]
set_input_delay -clock fast_clk -max 0.0001 [get_ports data_in]
"""
    (tmp_path / "timing.sdc").write_text(sdc)

    result = ssc.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert any(f.rule == "BAD_CLOCK_PERIOD" for f in errors)


# ---------------------------------------------------------------------------
# Test 6: Empty directory → FAIL
# ---------------------------------------------------------------------------
def test_empty_dir_fail(tmp_path):
    result = ssc.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert any(f.rule == "NO_SDC_FILE" for f in errors)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])


# ---------------------------------------------------------------------------
# Step 8's DECLARED scope decides the verdict (D9 blind-ruler campaign)
# ---------------------------------------------------------------------------
_GOOD_SDC = """\
create_clock -period 10 -name sys_clk [get_ports clk]
set_input_delay -clock sys_clk -max 2.0 [get_ports data_in]
set_output_delay -clock sys_clk -max 3.0 [get_ports data_out]
"""
#: Same content with the clock definition removed — a real constraint file
#: that no longer constrains anything.
_BROKEN_SDC = "\n".join(l for l in _GOOD_SDC.splitlines()
                        if "create_clock" not in l) + "\n"


def _two_scope_project(tmp_path, declared_text, other_text=_GOOD_SDC):
    """A project with one .sdc in step 8's declared scope and one outside it.

    The outside one is where every ERROR in the published corpus actually
    lives (`phase2/stage1/fpga/*.sdc`, an FPGA/Quartus constraint file), so a
    fixture with only one .sdc cannot tell the two rules apart.
    """
    d = tmp_path / "phase2" / "stage2" / "constraints"
    d.mkdir(parents=True)
    (d / "chip_top.sdc").write_text(declared_text)
    f = tmp_path / "phase2" / "stage1" / "fpga"
    f.mkdir(parents=True)
    (f / "board.sdc").write_text(other_text)
    return tmp_path


def test_broken_declared_sdc_is_not_rescued_by_a_valid_one_elsewhere(tmp_path):
    """ARM: mutate the file step 8 DECLARES; the verdict must move.

    MEASURED before the fix, by hand, on isolated copies of published runs:
    deleting every `create_clock` from `phase2/stage2/constraints/*.sdc` left
    rc=0 / PASS on caravel_user_project/v1.9.43_sky130A (valid_files 2 -> 1,
    errors 0 -> 1) and on phase1_parity/mdio (valid_files 2 -> 1, errors
    2 -> 3), because `passed = valid_files > 0` let any other .sdc in the tree
    stand in for the broken one.
    """
    proj = _two_scope_project(tmp_path, _BROKEN_SDC)
    base = ssc.audit(str(proj))
    assert base.passed is False
    assert base.summary["declared_scope_errors"] >= 1
    assert base.summary["valid_files"] >= 1, (
        "the control: a valid .sdc DOES exist outside the declared scope, so "
        "this failure is the scope talking and not an empty project")


def test_declared_scope_clean_passes_despite_errors_outside_it(tmp_path):
    """PRECISION, and the reason the rule is not a bare `errors == 0`.

    Of the 22 published run dirs that pass this gate, 10 carry at least one
    ERROR and every one of those errors is on an artefact step 8 does not own
    (`phase2/stage1/fpga/**`, `input/**`, `steps/7_*/**`). A bare `errors == 0`
    would turn 10 of 22 red on someone else's ruler.
    """
    proj = _two_scope_project(tmp_path, _GOOD_SDC, other_text=_BROKEN_SDC)
    r = ssc.audit(str(proj))
    assert r.passed is True
    assert r.summary["errors"] >= 1, "an out-of-scope ERROR must still be found"
    assert r.summary["declared_scope_errors"] == 0


def test_the_verdict_discloses_the_denominator_it_rests_on(tmp_path):
    """A PASS must say how much it looked at — and specifically how much of
    the population it actually DECIDED on, which is the smaller number."""
    proj = _two_scope_project(tmp_path, _GOOD_SDC)
    r = ssc.audit(str(proj))
    assert r.summary["declared_scope"] == ssc.DECLARED_SDC_SCOPE
    assert r.summary["declared_scope_files"] == [
        "phase2/stage2/constraints/chip_top.sdc"]
    assert r.summary["files_checked"] == 2


@pytest.mark.parametrize("mutation,expect_error", [
    ("create_clock -period 10 -name sys_clk [get_ports clk]", False),
    # Deletion is the cheapest probe, not the property: mutate the NUMBER.
    ("create_clock -period 99999999 -name sys_clk [get_ports clk]", True),
])
def test_a_mutated_period_in_the_declared_sdc_moves_the_verdict(
        tmp_path, mutation, expect_error):
    text = _GOOD_SDC.replace(
        "create_clock -period 10 -name sys_clk [get_ports clk]", mutation)
    proj = _two_scope_project(tmp_path, text)
    r = ssc.audit(str(proj))
    assert (r.summary["declared_scope_errors"] > 0) is expect_error
    assert r.passed is not expect_error
