import os,sys
from pathlib import Path
PROGRAMS=Path(os.environ.get("VIBE_PROGRAMS",str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0,str(PROGRAMS))
import spec_coverage_check as S
def test_reset_heading_with_negated_body_not_derived():
    assert S._has_reset("## Reset\nNo explicit reset port is provided in the template.") is False
def test_real_reset_in_body_still_derived():
    assert S._has_reset("## Reset\nThe reset rst_n is active-low and clears all registers.") is True
def test_heading_only_no_body_still_derived():
    assert S._has_reset("## Reset\n") is True
def test_plain_affirmative_still_derived():
    assert S._has_reset("On reset, all counters clear to zero.") is True
def test_fully_negated_not_derived():
    assert S._has_reset("The module has no clock or reset inputs; purely combinational.") is False

# --- §4.05 round-2 (Step-2.7): an INCIDENTAL negation in the body must NOT drop
# a genuine reset — only an EXISTENCE-DENIAL negation vetoes the heading. ---
def test_heading_reset_with_incidental_negation_still_derived():
    # "not optional" is an incidental negation, NOT a denial of the reset's
    # existence — the genuine reset requirement must still derive.
    assert S._has_reset(
        "## Reset\nA power-on reset is not optional and must drive por_n low "
        "for at least 10 us.") is True
def test_heading_reset_never_deasserted_still_derived():
    assert S._has_reset(
        "## Reset\nThe reset is never deasserted until the PLL locks.") is True
def test_heading_reset_no_outstanding_on_reset_still_derived():
    assert S._has_reset(
        "## Reset\nOn reset there are no outstanding transactions; rst_n "
        "clears the FIFO.") is True
def test_heading_reset_existence_denial_still_not_derived():
    # a genuine existence-denial body ("no explicit reset port") still suppresses.
    assert S._has_reset(
        "## Reset\nNo explicit reset port is provided; purely clocked.") is False


def test_heading_reset_no_glitch_constraint_still_derived():
    # "no glitch on the reset" negates the GLITCH, not the reset's existence.
    assert S._has_reset(
        "## Reset\nThere must be no glitch on the reset during power-up.") is True
def test_heading_does_not_use_reset_not_derived():
    assert S._has_reset(
        "## Reset\nThis design does not use a reset of any kind.") is False
def test_heading_without_any_reset_not_derived():
    assert S._has_reset(
        "## Reset\nThe block operates without any reset signal.") is False


def test_heading_no_separate_reset_shares_still_derived():
    # "no separate reset (it shares the bus reset)" denies a KIND; reset exists.
    assert S._has_reset(
        "## Reset\nThere is no separate reset (it shares the bus reset).") is True
def test_heading_no_dedicated_reset_derived_still_derived():
    assert S._has_reset(
        "## Reset\nNo dedicated reset (derived from the global reset).") is True
def test_heading_reset_intentionally_omitted_not_derived():
    assert S._has_reset(
        "## Reset\nReset functionality is intentionally omitted.") is False
def test_heading_no_reset_logic_not_derived():
    assert S._has_reset(
        "## Reset\nThe core contains no reset logic whatsoever.") is False


def test_heading_reset_never_disabled_double_negative_derived():
    # "the reset is never disabled" is a double negative reaffirming presence.
    assert S._has_reset("## Reset\nThe reset is never disabled.") is True
def test_heading_reset_not_omitted_double_negative_derived():
    assert S._has_reset("## Reset\nThe reset is not omitted.") is True
def test_heading_reset_is_disabled_not_derived():
    assert S._has_reset("## Reset\nThe reset is disabled.") is False


def test_heading_reset_cannot_be_disabled_derived():
    assert S._has_reset("## Reset\nThe reset cannot be disabled.") is True
def test_heading_reset_not_to_be_disabled_derived():
    assert S._has_reset("## Reset\nThe reset is not to be disabled.") is True
def test_heading_at_no_point_reset_omitted_derived():
    assert S._has_reset("## Reset\nAt no point is the reset omitted.") is True
def test_heading_clock_cannot_be_disabled_derived():
    assert S._has_clock("## Clock\nThe clock cannot be disabled.") is True

if __name__=="__main__":
    import pytest; raise SystemExit(pytest.main([__file__,"-v"]))
