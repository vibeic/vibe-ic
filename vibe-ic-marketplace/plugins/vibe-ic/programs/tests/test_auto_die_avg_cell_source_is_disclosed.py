#!/usr/bin/env python3
"""`--die-um auto` reported a FALLBACK CONSTANT in the format of a measurement.

MEASURED DEFECT
===============
`_resolve_auto_die` estimates an average standard-cell area from the PDK's site
size, and falls back to `_AUTO_DIE_FALLBACK_CELL_UM2` when the site cannot be
read. Both branches then printed through the SAME format:

    die-um=auto -> 2000x2000 (cells=175525, avg_cell=7.50um2, target_util=0.25 ...)

Nothing in that line distinguishes "measured from this PDK" from "a constant,
because the read failed". And the read fails on every containerised run:
`pdk.cell_lef` is an IN-CONTAINER path (the PDK ships inside the EDA image, not
on the host), so the host-side `Path(...).read_text()` raises FileNotFoundError
and the bare `except` swallows it.

Measured consequence on one real cell:

    host read of the in-container cell LEF -> FileNotFoundError
    fallback avg cell area                 -> 7.500 um2
    the design's OWN post-synthesis report -> chip_area 249283.23 um2
                                              cell_count 175525
                                           -> 1.420 um2 measured
    over-estimate                          -> x5.28

so `--die-um auto` chose a die 5.3x too large in area and OpenROAD reported
`[INFO IFP-0104] Effective utilization: 0.064` against the 0.25 target.

SCOPE OF THIS CHANGE
====================
DISCLOSURE ONLY. No number changes; every die produced today is byte-identical.
The estimate now names which of its two sources it came from, so a mis-sized
die is attributable instead of invisible. Choosing a better estimate (the run's
own measured `chip_area / cell_count` is right there in the synthesis report)
moves physical results for every design and needs its own corpus sweep — it is
deliberately NOT bundled here.

chip-, PDK- and vendor-AGNOSTIC.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import phase3_one_shot_runner as R  # noqa: E402


def test_fallback_is_labelled_as_a_fallback():
    """The site-parse-failed branch must SAY the die was not sized from the
    PDK. Without this, the operator sees a number and assumes a measurement."""
    src = pathlib.Path(R.__file__).read_text()
    assert "FALLBACK CONSTANT" in src, (
        "the fallback branch must label itself in the emitted line")
    assert "_avg_cell_src" in src


def test_the_emitted_line_carries_the_source():
    """The `avg_cell=` field must be followed by its provenance in the SAME
    line the operator reads, not buried elsewhere."""
    src = pathlib.Path(R.__file__).read_text()
    assert 'avg_cell={avg_cell:.2f}µm² [{_avg_cell_src}]' in src


def test_the_fallback_constant_itself_is_unchanged():
    """Disclosure only — this change must not move any die. If the constant
    ever changes, that is a physical-results change and belongs in its own
    swept PR, not in a logging fix."""
    assert R._AUTO_DIE_FALLBACK_CELL_UM2 == 7.5
    assert R._AUTO_DIE_AVG_SITES_PER_CELL == 6.0
    assert R._AUTO_DIE_TARGET_UTIL == 0.25


def test_die_sizing_math_is_unchanged():
    """The sizing function is untouched: same inputs, same side."""
    # measured against the shipped implementation, not guessed
    assert R._auto_die_side_um(175525, 0.25, 7.5) == R._DEFAULT_DIE_MAX_UM
    assert R._auto_die_side_um(1, 0.25, 7.5) == R._AUTO_DIE_MIN_SIDE_UM
    assert R._auto_die_side_um(10000, 0.25, 1.42) == 239
    # a zero/negative avg area still routes to the fallback constant
    assert R._auto_die_side_um(10000, 0.25, 0) == R._auto_die_side_um(
        10000, 0.25, R._AUTO_DIE_FALLBACK_CELL_UM2)
