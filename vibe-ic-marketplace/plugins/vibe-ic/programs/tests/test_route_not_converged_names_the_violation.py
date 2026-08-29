#!/usr/bin/env python3
"""`ROUTE_NOT_CONVERGED` asserted a CAUSE it never read.

The verdict said, for every residual count:

    The design is congestion-limited at die WxHum / requested util U:
    increase --die-um, lower --util, or raise the router's end iteration.

It named no violation TYPE because nothing parsed one -- and TritonRoute prints
the type/layer breakdown on the line DIRECTLY BELOW the `[INFO DRT-0199] Number
of violations = N` count the branch already reads:

    [INFO DRT-0199]   Number of violations = 55.
    Viol/Layer      Metal1 Metal2
    Metal Spacing        5      6
    NS Metal             1      0
    Short               32     11

MEASURED 2026-08-29, spm x gf180mcuD on v1.12.65 (fixture below is that run's
own log, verbatim): the single residual violation was `NS Metal` on `Metal1` --
TritonRoute's name for a MINIMUM-AREA violation, one metal stub below the
layer's MINIMUMAREA rule. That is a geometry rule about a single shape; die
area does not appear in it. The run had ALREADY measured all three prescribed
remedies useless:

  * the auto-loosen ladder ran to util 0.08 on a 412x412um die and reported
    `ROUTE_LOOSEN_DECLINED reason=loosen_ladder_stalled ...
     residual_series=[1, 4, 1] still_improving=False`
  * the DRT-0199 trajectory was 49 iterations long and held the final value 1
    for the last 42 of them

Same shape as the DRT-0701 defect fixed in v1.12.54: the tool published the
discriminating fact in its own log and nothing parsed it.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402

_LOG = (Path(__file__).resolve().parent / "fixtures" /
        "drt_residual_types" / "openroad_tail.txt").read_text()


def test_reads_the_final_single_layer_table_from_the_real_log():
    """SUBJECT: the run's real residual is named, not guessed."""
    assert R._drt_violation_types(_LOG) == [("NS Metal", "Metal1", 1)]


def test_reads_a_multi_layer_table_with_a_spaced_type_name():
    """CONTROL -- the input the fix must keep answering fully.

    A type name may contain spaces ("Metal Spacing"), and a table may span
    several layers. Parsing must not degrade to the first column or drop the
    spaced name; a parser that returned only the final table's shape would
    still pass the subject test."""
    early = _LOG[:_LOG.index("Number of violations = 1.")]
    assert R._drt_violation_types(early) == [
        ("Metal Spacing", "Metal1", 5),
        ("Metal Spacing", "Metal2", 6),
        ("NS Metal", "Metal1", 1),
        ("Short", "Metal1", 32),
        ("Short", "Metal2", 11),
    ]


def test_type_counts_reconcile_with_the_drt_0199_count():
    """The breakdown must ADD UP to the count the verdict already reports.

    This is the property that makes the two readings one fact rather than two.
    Both real tables are checked: 5+6+1+32+11 == 55, and 1 == 1."""
    for block, expected in ((_LOG[:_LOG.index("Number of violations = 1.")], 55),
                            (_LOG, 1)):
        assert sum(c for _, _, c in R._drt_violation_types(block)) == expected
        assert R._drt_final_violations(block) == expected


def test_no_table_is_empty_not_an_exception():
    assert R._drt_violation_types("") == []
    assert R._drt_violation_types("[INFO DRT-0199]   Number of violations = 3.\n") == []


def test_a_truncated_table_stops_cleanly():
    """A header with no rows under it yields nothing, never a partial row."""
    assert R._drt_violation_types(
        "[INFO DRT-0199]   Number of violations = 3.\n"
        "Viol/Layer      Metal1\n"
        "[INFO DRT-0267] cpu time = 00:00:00\n") == []


def test_flat_tail_counts_only_the_trailing_run():
    assert R._drt_flat_tail([]) == 0
    assert R._drt_flat_tail([5]) == 1
    assert R._drt_flat_tail([9, 4, 1, 1, 1]) == 3
    # CONTROL: a still-improving tail is not a plateau.
    assert R._drt_flat_tail([9, 4, 2, 1]) == 1
    # a count that RETURNS to an earlier value does not extend the run
    assert R._drt_flat_tail([1, 4, 1]) == 1


def test_verdict_consults_the_type_table_and_the_tail():
    """WIRING: reading the table is worthless if the verdict never calls it.

    Same convention as test_v0_3_41_issue585_route_convergence's wiring test."""
    src = inspect.getsource(R.step_pnr)
    assert "_drt_violation_types" in src
    assert "_drt_flat_tail" in src
    # and the assertion the evidence did not support is gone
    assert "design is congestion-limited" not in src
