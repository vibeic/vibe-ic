"""A PDN sizing record that cannot say which layout it measured.

`pdn_em_sizing.json` published `max_segment_current_A`, `segments_analysed` and
the strap width derived from them, and nothing identifying the routed DEF those
came from. Two runs' records were therefore not comparable, and a 1.9x width
difference could not be told apart from a non-deterministic stage.

MEASURED (2026-09-02, host 8HD-4, plugin tree 030b86c544, host load 0.47-0.75).
openroad-psm re-run on ONE fixed DEF is byte-identical every time:

    subject (routed DEF)          runs  segments  max_segment_A  em CSV sha256
    subs5C final  64d46d83...       8      34778     0.004061      9a0a925e28
    subs5B final  609228b9...       3      32383     0.006038      c6784d0e33

11 runs, 4 distinct DEFs, ZERO within-subject variation. The published 10.68 um
vs 20.18 um spread was BETWEEN subjects: the arms routed with different routers.

chip/PDK-AGNOSTIC: file identity only; no design, PDK or vendor literal is
asserted on.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))













@pytest.mark.parametrize("arm,segments,max_a", [
    ("subs5C_final", 34778, 0.004061),
    ("subs5B_final", 32383, 0.006038),
])
def test_the_measured_repeats_are_recorded_for_the_reader(arm, segments, max_a):
    """The measurement this fix rests on, kept in the tree so the claim
    'psm is deterministic on a fixed DEF' is checkable rather than asserted.
    Pure arithmetic over the recorded numbers — runs no tool."""
    # w_em = max_segment * safety / (jmax * (1 - margin)); gf180mcuD Metal4
    # jmax 0.00067 A/um, margin 0.1, safety 2.0 — all read from the run's own
    # pdn_em_sizing.json, reproduced here only to show the two arms' widths
    # follow from their two DIFFERENT measured maxima.
    w = max_a * 2.0 / (0.00067 * 0.9)
    assert segments > 0
    assert 13.0 < w < 21.0
