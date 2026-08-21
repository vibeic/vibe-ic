"""A blank line inside a DRV table closed it, under-counting max_capacitance 24x.

`extract_drv()` walks `report_check_types -violators` output with an explicit
IDLE -> HEADER -> ROWS state machine, and ended a table at "the first line with
no digit in it". A BLANK line has no digit, so it ended the table too.

That is not a hypothetical. OpenSTA prints the three DRV tables with DIFFERENT
row spacing:

    max slew          rows contiguous
    max fanout        rows contiguous
    max capacitance   a BLANK LINE BETWEEN EVERY ROW

so the walk closed the capacitance table after its FIRST row, in every corner.

MEASURED on caravel_user_project x sky130A (plugin v1.10.18). The route is
deterministic to the byte -- `routed.def` md5 8dd2a0b7ab326390192d14c38ab8322a
on two independent hosts -- so these counts are reproducible, not a sample:

    report body            shipped walk      rows actually tagged (VIOLATED)
    max_slew                     473                473   <- contiguous, agreed
    max_fanout                     4                  4   <- contiguous, agreed
    max_capacitance                2                 48   <- 24x UNDER-count
    total                        479                525

The error is in the LENIENT direction: the sign-off record understated the
design's own DRV population, reporting `max_capacitance x2` for a report that
lists 24 violating capacitance pins per corner. `max_slew` and `max_fanout`
agreed exactly, which is why the defect stayed invisible -- the total looked
plausible and only the one blank-separated kind was wrong.

The fix defers the close by one line: a blank SUSPENDS the table (ROWS_BLANK)
and only a following non-data line actually closes it. Every real terminator (a
DRV title, a non-DRV title, an `=== SECTION ===` banner, the check-types
markers) is consumed earlier in the loop, so this can only stop a table ending
EARLY -- it can never hold one open across a title. The last two tests below are
the guards for that direction.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
PROG = _PROGRAMS / "sta_corner_record_completeness_check.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "sta_corner_record_completeness_probe_blank", PROG)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sta_corner_record_completeness_probe_blank"] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load()

#: Verbatim from the shipped
#: `_c12_caravel_user_project_sky130A/phase3/stage3/sta/sta_spef_multicorner.rpt`
#: -- note the blank line between every capacitance row, and NOT between the
#: slew rows. Trimmed to 4 cap rows / 3 slew rows; the spacing is the point.
_REAL_REPORT = """\
=== SETUP (max-RC corner, SPEF=max, liberty=sky130_fd_sc_hd__tt_025C_1v80.lib) ===

max slew

Pin                                    Limit    Slew   Slack
------------------------------------------------------------
ANTENNA_122/DIODE                       1.50   12.71  -11.21 (VIOLATED)
_171_/C_N                               1.50   12.71  -11.21 (VIOLATED)
_186_/C_N                               1.50    9.72   -8.22 (VIOLATED)

max fanout

Pin                                   Limit Fanout  Slack
---------------------------------------------------------
wire167/X                                16     26    -10 (VIOLATED)
wire170/X                                16     21     -5 (VIOLATED)

max capacitance

Pin                                    Limit     Cap   Slack
------------------------------------------------------------
wire163/X                               1.53    3.52   -1.99 (VIOLATED)

wire161/X                               1.53    3.52   -1.99 (VIOLATED)

wire160/X                               1.53    3.50   -1.97 (VIOLATED)

wire168/X                               1.53    3.45   -1.92 (VIOLATED)

SIGNOFF_CHECK_TYPES_REPORTED recovery removal max_slew min_pulse_width \
max_capacitance max_fanout
"""


def test_every_blank_separated_capacitance_row_is_counted():
    """The regression: 4 blank-separated cap rows must count 4, not 1."""
    drv = M.extract_drv(_REAL_REPORT)
    assert drv["violations"]["max_capacitance"] == 4, (
        "a blank line between capacitance rows must not close the table")


def test_contiguous_kinds_are_unchanged():
    """max_slew / max_fanout print contiguously and already counted right."""
    drv = M.extract_drv(_REAL_REPORT)
    assert drv["violations"]["max_slew"] == 3
    assert drv["violations"]["max_fanout"] == 2
    assert drv["total"] == 9


def test_rows_are_attributed_for_every_counted_row():
    """#582 attribution must keep pace with the count, not lag it."""
    drv = M.extract_drv(_REAL_REPORT)
    assert len(drv["rows"]["max_capacitance"]) == 4


def test_a_blank_does_not_carry_a_table_across_a_title():
    """Guard for the over-count direction: rows after the blank belong to the
    NEXT table's kind, never to the suspended one."""
    drv = M.extract_drv(_REAL_REPORT)
    # wire167/X and wire170/X sit under `max fanout`, which follows a blank
    # line ending the slew table. They must not be attributed to max_slew.
    assert drv["violations"]["max_slew"] == 3
    assert "wire167" not in " ".join(drv["rows"].get("max_slew", []))


def test_a_blank_then_prose_still_closes_the_table():
    """A blank followed by a non-data line closes the table, as before."""
    text = _REAL_REPORT + "\nthis trailing prose has no digits at all\n" \
        "stray/pin   1.50   9.99   -8.49 (VIOLATED)\n"
    drv = M.extract_drv(text)
    assert drv["violations"]["max_capacitance"] == 4, (
        "prose must close the table so a later stray row is not absorbed")
