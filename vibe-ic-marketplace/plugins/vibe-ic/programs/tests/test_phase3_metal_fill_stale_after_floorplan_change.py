#!/usr/bin/env python3
"""Regression — Step 34 metal fill must not reuse a previous round's output
after the floorplan changed.

Bug
---
The Step-34 call site gated the fill emitter on output EXISTENCE alone:

    filled_def = pnr_out / "filled.def"
    if primary_def.is_file() and not filled_def.is_file():
        _emit_metal_fill(...)

`filled.def` — and its siblings `metal_fill.{log,done}` and
`reports/density.{rpt,json}` — are computed FROM the routed DEF. So on a
re-run with a changed die/util, PnR correctly invalidated its own cache and
rewrote `<top>.def` for the new geometry, while the fill stage saw
`filled.def` present and skipped entirely.

Measured on a real re-run (die grew, core area grew ~59%, cell area
unchanged):

  routed.def / <top>.def / floorplan.def   rewritten for the new die
  filled.def / metal_fill.log / density.json   previous round's mtime, ~4h old
  density.json still reported the OLD core's utilization to four significant
  figures, and 0 filler instances

Step 34 therefore reported a superseded layout's numbers as this round's, and
every downstream consumer of `filled.def` read the old layout. Nothing in the
run disclosed that the fill had not re-run — it degraded silently.

Fix
---
`_fill_output_needs_rerun(filled_def, primary_def)`: run when the output is
absent OR older than the routed DEF it derives from. Unprovable freshness
(stat failure) re-runs rather than reuses.

NEG cases (load-bearing — the fix must not become "always re-run")
------------------------------------------------------------------
  * NEG-1 a filled.def NEWER than the routed DEF is still reused (no
          gratuitous re-run on every invocation — the caching this guard
          refines must survive).
  * NEG-2 equal mtimes are reused (not strictly older -> not stale).
  * NEG-3 absent output still runs, exactly as before.

chip-AGNOSTIC: pure mtime comparison on synthetic paths; no design, vendor,
SKU, process-node or PDK literal.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase3_one_shot_runner as R  # noqa: E402


def _mk(tmp_path: Path, filled_age: float | None, primary_age: float):
    """Create <top>.def and (optionally) filled.def with explicit mtimes.

    `*_age` is seconds BEFORE a fixed reference instant — larger age = older.
    """
    ref = 1_700_000_000.0
    pnr = tmp_path / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    primary = pnr / "top.def"
    primary.write_text("DIEAREA ( 0 0 ) ( 1000 1000 ) ;\n")
    os.utime(primary, (ref - primary_age, ref - primary_age))
    filled = pnr / "filled.def"
    if filled_age is not None:
        filled.write_text("DIEAREA ( 0 0 ) ( 1000 1000 ) ;\n")
        os.utime(filled, (ref - filled_age, ref - filled_age))
    return filled, primary


def test_stale_fill_after_floorplan_change_is_rerun(tmp_path):
    """THE DEFECT — filled.def older than the routed DEF must re-run.

    Pre-fix the call site skipped on existence alone, so this layout's fill
    was never recomputed and its density report described a superseded die.
    """
    filled, primary = _mk(tmp_path, filled_age=14_400.0, primary_age=0.0)
    assert R._fill_output_needs_rerun(filled, primary) is True, (
        "a filled.def older than the routed DEF it derives from was treated "
        "as current; Step 34 would report the superseded floorplan's numbers"
    )


def test_neg1_fresh_fill_is_reused(tmp_path):
    """NEG-1 — a fill NEWER than the routed DEF is still reused."""
    filled, primary = _mk(tmp_path, filled_age=0.0, primary_age=600.0)
    assert R._fill_output_needs_rerun(filled, primary) is False, (
        "the guard degenerated into 'always re-run' and destroyed the caching "
        "it was meant to refine"
    )


def test_neg2_equal_mtime_is_reused(tmp_path):
    """NEG-2 — equal mtimes are not 'older', so the fill is reused."""
    filled, primary = _mk(tmp_path, filled_age=100.0, primary_age=100.0)
    assert R._fill_output_needs_rerun(filled, primary) is False


def test_neg3_absent_fill_runs(tmp_path):
    """NEG-3 — absent output runs, byte-identical to pre-fix behaviour."""
    filled, primary = _mk(tmp_path, filled_age=None, primary_age=0.0)
    assert R._fill_output_needs_rerun(filled, primary) is True


def test_unstattable_primary_reruns(tmp_path):
    """Freshness that cannot be established re-runs rather than reuses."""
    filled, primary = _mk(tmp_path, filled_age=0.0, primary_age=600.0)
    primary.unlink()
    assert R._fill_output_needs_rerun(filled, primary) is True


def test_pre_fix_predicate_would_have_reused_the_stale_fill(tmp_path):
    """States the BEHAVIOURAL delta, not merely that a new symbol exists.

    Every other test here fails pre-fix with AttributeError, which proves the
    helper is new — not that behaviour changed. This one spells out the escape
    using the pre-fix gate expression verbatim (`not filled_def.is_file()`) on
    the measured case, so the delta is visible without the new symbol.
    """
    filled, primary = _mk(tmp_path, filled_age=14_400.0, primary_age=0.0)

    pre_fix_would_run = not filled.is_file()
    assert pre_fix_would_run is False, (
        "pre-fix gate should reuse the existing filled.def — that IS the bug"
    )

    assert R._fill_output_needs_rerun(filled, primary) is True, (
        "post-fix gate must re-run the same case the pre-fix gate reused"
    )


@pytest.mark.parametrize("filled_age,primary_age,expected", [
    (14_400.0, 0.0, True),    # 4h-stale fill, the measured case
    (1.0, 0.0, True),         # one second stale is still stale
    (0.0, 1.0, False),        # fresh
    (0.0, 0.0, False),        # simultaneous
])
def test_polarity_table(tmp_path, filled_age, primary_age, expected):
    filled, primary = _mk(tmp_path, filled_age, primary_age)
    assert R._fill_output_needs_rerun(filled, primary) is expected
