"""A pin's CLASS must not depend on how its designer spelled it.

`analog_interface_classify._CLK_RE` listed `clk`/`clock` and their prefixed
variants but not `ck<N>` or `phi<N>` — the standard switched-capacitor clock
spellings. Measured before the fix, with only the spelling changed:

    ck1,  ck2   -> digital_data_input   has_digital_clock_input=False
    clk1, clk2  -> digital_clk_input    has_digital_clock_input=True

It was an INTERNAL inconsistency too: `harness_exact_selfverify._CLOCK_NAME_RE`
in the SAME plugin version already matched `ck`/`ck1`/`ck4`. Two regexes in one
plugin disagreed about what a clock is, and the analog track got the losing one.

Chip-AGNOSTIC: pin-name conventions only; no design, PDK or vendor involved.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))


def _mod(name: str):
    spec = importlib.util.spec_from_file_location(name, PROGRAMS / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.mark.parametrize("name", [
    "ck", "ck1", "ck2", "ck4", "ck5", "ck6",     # SC modulator convention
    "phi", "phi1", "phi2",                        # two-phase non-overlapping
    "clk", "clk1", "clock", "sclk", "refclk",     # must keep working
])
def test_a_clock_is_recognised_however_it_is_spelled(name):
    assert _mod("analog_interface_classify")._CLK_RE.match(name), name


@pytest.mark.parametrize("name", [
    "ckt", "checksum", "check_en", "phase_out", "phy_data",
    "data", "din", "dout", "ack", "clocked_data", "block_ready",
])
def test_a_non_clock_is_not_swept_in(name):
    """The polarity control. A regex that answered True to everything would
    satisfy the test above and misclassify every data pin as a clock — a worse
    defect than the one being fixed, and invisible without this half."""
    assert not _mod("analog_interface_classify")._CLK_RE.match(name), name


#: `phi` is DELIBERATELY absent from this list, and the reason is worth stating
#: rather than leaving as a silent gap. `harness_exact_selfverify._CLOCK_NAME_RE`
#: guards a §4.05 latch-detection gate, and its own comment records that a
#: PRIOR, wider version "laundered a real inferred latch by merely renaming its
#: data-enable guard" (#813 r2). Adding `phi` there to make two regexes match
#: would widen a gate that was deliberately narrowed after a real escape — a
#: cosmetic symmetry bought with a live safety property. `phi` is correct for
#: the ANALOG classifier (two-phase non-overlapping SC clocks) and is added
#: there only. The asymmetry is intentional, documented, and pinned by
#: `test_phi_is_analog_only_and_that_is_deliberate` below.
@pytest.mark.parametrize("name", ["ck", "ck1", "ck4", "clk", "clock"])
def test_the_two_clock_regexes_in_this_plugin_agree(name):
    """The defect was not just an omission — it was two components of one
    plugin holding different definitions of 'clock'. Pin them together so they
    cannot drift apart again, for the family the defect was actually about."""
    a = _mod("analog_interface_classify")._CLK_RE.match(name)
    b = _mod("harness_exact_selfverify")._CLOCK_NAME_RE.match(name)
    assert bool(a) == bool(b), f"{name}: analog={bool(a)} harness={bool(b)}"


def test_phi_is_analog_only_and_that_is_deliberate():
    """Pins the intentional asymmetry so a later reader cannot mistake it for
    the same oversight that was just fixed. If someone decides the harness
    SHOULD know `phi`, that is a separate change against a §4.05 gate and must
    be argued on its own evidence — not slipped in for tidiness."""
    a = _mod("analog_interface_classify")._CLK_RE
    h = _mod("harness_exact_selfverify")._CLOCK_NAME_RE
    assert a.match("phi1"), "the analog classifier must know SC phase clocks"
    assert not h.match("phi1"), (
        "the harness latch gate now matches phi1 — if that was intended, "
        "update this test WITH the §4.05 argument for widening it")
