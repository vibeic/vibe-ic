"""A refused antenna pass stops the deck, and nothing may destroy its evidence.

Two holes in R-0915-121 as landed (#2462), both confirmed on int11's own
artefacts before a line was changed.

(2) THE RECONVERGE SLOT HAD NO SENTINELS. The parent's rollback re-drives the
post-route tail with both antenna stages omitted, and it derives that tail by
finding each omitted stage's BEGIN marker. `postroute_antenna_repair` is
wrapped in `_pnr_stage_begin`/`_pnr_stage_end` (#2253);
`postroute_antenna_reconverge` had only a `puts` breadcrumb. So the derivation
raised and int9, int10 and int11 all printed

    rollback tail could not be derived: pnr.tcl carries no stage
    'postroute_antenna_reconverge' begin marker -- it was written by a pnr.tcl
    emitter that predates resume support

-- the rollback R-0915-121(a) asks for could not be built at all. The slot now
carries its own pair. That does NOT make it omittable on a fatal-signal
resume: that path gates on `_PNR_NONFATAL_STAGES`, which holds only
postroute_drv_repair, postroute_drv_reconverge and
postroute_setup_repair_estimate -- measured, not assumed.

(3) THE REFUSAL WAS A `puts`, SO THE DECK CARRIED ON AND ATE ITS OWN RESTORE
POINT. On int11 the FIRST antenna pass refused with a clean
`antenna_pass_pre.odb` behind it; the deck continued; the SECOND antenna slot
then rewrote BOTH checkpoints. MEASURED on the shipped artefacts:

    antenna_pass_pre.odb   26984114 bytes  20:27
    antenna_pre_repair.odb 26984114 bytes  20:27
    cmp -> IDENTICAL, and both already carry the 1437 unrouted nets the first
    pass created

so the parent was asked to restore from a file that no longer held anything to
restore. A refusal means this session's route is not the one the router
verified; everything after it is work on a wrecked database and the one thing
it reliably destroys is the means to undo it. The first refusal now STOPS the
deck. The parent's rollback reads the marker out of the LOG and runs whether
or not the deck exited 0, so stopping costs nothing and is what makes the
restore possible.

The success path's `file delete` is guarded by the same fact for the same
reason: the two antenna slots are separate emissions with separate local
variables, and only a deck-global flag can see across them.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

tclsh = shutil.which("tclsh")
needs_tclsh = pytest.mark.skipif(tclsh is None, reason="tclsh not installed")








# ── (2) the reconverge slot is bracketed like the repair slot ───────────────







# ── (3) the first refusal stops, and nothing sweeps its evidence ────────────









@needs_tclsh
def test_driven_a_refused_pass_stops_and_leaves_its_checkpoint():
    """Executed, not grepped: the deck must not reach its own terminal
    marker after a refusal, and it must have asked first."""
    from test_r0915_121_a_pass_answers_for_every_wire_it_took import (  # noqa
        _H, _tcl as _ant)
    script = (_H % {"seq": "5 5 5", "inserts": "d1", "unwire": "nX",
                    "shrink": ""}) + _ant()
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "ant.tcl"
        p.write_text(script)
        r = subprocess.run([tclsh, str(p)], capture_output=True, text=True,
                           cwd=td)
    assert "ANTENNA_REPAIR_REFUSED_ROLLBACK_REQUEST:" in r.stdout
    assert "checkpoint=./antenna_pass_pre.odb" in r.stdout
    assert "ANTENNA_POSTROUTE_DONE" not in r.stdout, (
        "the deck reached its terminal marker after a refusal -- everything "
        "between is work on a wrecked database")
    assert r.returncode != 0, "a refusal must not look like a clean session"
    assert "ANTENNA_REPAIR_REFUSED_STOP" in r.stdout + r.stderr


@needs_tclsh
def test_driven_a_clean_pass_still_reaches_the_end_and_sweeps():
    """THE REGRESSION GUARD: stopping on refusal must not stop anything
    else."""
    from test_r0915_121_a_pass_answers_for_every_wire_it_took import (  # noqa
        _H, _tcl as _ant)
    script = (_H % {"seq": "5 5 0", "inserts": "d1", "unwire": "",
                    "shrink": ""}) + _ant()
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "ant.tcl"
        p.write_text(script)
        r = subprocess.run([tclsh, str(p)], capture_output=True, text=True,
                           cwd=td)
    assert r.returncode == 0, r.stderr
    assert "ANTENNA_LOOP_CONVERGED" in r.stdout
    assert "ANTENNA_REPAIR_APPLIED" in r.stdout
    assert "ANTENNA_POSTROUTE_DONE" in r.stdout
    assert "ANTENNA_REPAIR_REFUSED_STOP" not in r.stdout + r.stderr
    assert "ANTENNA_CHECKPOINTS_KEPT" not in r.stdout




# ── (2) proved by BUILDING the thing that could not be built ────────────────
#
# The assertions above pin that the markers are emitted. This one pins the
# CONSEQUENCE: the parent's rollback tail is DERIVED from the pnr.tcl that ran,
# by finding each omitted stage's BEGIN marker, and that derivation is what
# int9, int10 and int11 all watched fail. Asserting the markers exist is not
# the same as asserting the tail builds.
