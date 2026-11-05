#!/usr/bin/env python3
"""R-0915-68 — the child offers its BEST pass, not the pass it happened to end on.

MEASURED (opentitan_aes x sky130A, 2026-09-16). The child's bounded DRV loop
drove DRV 41,956 -> 19,013 -> 2,647, and its PASS-1 route closed at **0 router
violations** — strictly better than the `before=2` the transaction judges
against. Passes 2 and 3 then re-degraded the route to 11 and 39. The child
wrote `candidate.odb` from whatever state it ENDED in, so a pass that had
already reached clean was discarded because a later pass spoiled it, and the
parent refused a candidate that had been worth accepting two passes earlier.

The fix is NOT an in-session rollback. The same deck's antenna loop already
records the measurement that forbids one: `odb::dbChip_destroy` + `read_db`
restores the routing and then `report_worst_slack -max` dies with
`[CRITICAL ORD-2008] unknown master term type`, and the ECO journal rolls
instances back while leaving the re-routed wires, so `check_antennas` reads a
third state that never existed. The child therefore never walks back — it
writes one ODB per pass and CHOOSES WHICH FILE becomes `candidate.odb`. The
parent restores it in a fresh adopt session, which is where a restore is safe.

These tests drive the REAL emitted deck under tclsh with the shared stub, so
they pin behaviour rather than text: a fixture makes the router's DRC report
say different things on successive passes, and the assertions are on what the
deck DID.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))

# NO `skipif(tclsh is None)` HERE, DELIBERATELY. A tool-absent skip turns a
# test that COULD NOT RUN into a green line on the very host doing the
# measuring, and nothing downstream can tell it from a test that ran and
# passed. `_tcl_walk.walk` resolves tclsh the way the RUNNER does -- host
# first, then the pinned EDA container through the runner's own exec seam --
# and raises `TclNotMeasured` (an AssertionError, so pytest reports a FAILURE)
# naming both routes when neither answers.

SITE = "postroute_drv_repair"

# The deck IS the deck: the walker's only job is to source it, so the text
# under test travels as `deck_text` and the container route gets it through
# the helper's heredoc rather than through a mount that does not exist.
_WALKER = "source [lindex $argv 0]\n"








# ────────────────── the deck still parses and still stops ──────────────────



# ───────────────────────── the ledger is written ───────────────────────────



# ─────────────── a later pass that REGRESSES does not displace ─────────────





# ───────────────── a pass that IMPROVES is kept (both directions) ───────────



# ───────────────────────── clean stops the loop early ──────────────────────



# ─────────── no clean pass: the best count is still what is offered ────────



# ───────────────────── the selection is a COPY, never a restore ────────────

def test_the_child_never_restores_over_itself():
    """The one thing this change must NOT do.

    The antenna loop in this same deck measured that `dbChip_destroy`+`read_db`
    kills the STA network (ORD-2008) and that the ECO journal leaves a third
    state. Selection is therefore a file copy. Asserted on the emitted source
    so no future edit can quietly turn it into a rollback.
    """
    import inspect
    src = inspect.getsource(R._sdr_transaction_block_tcl) if hasattr(
        R, "_sdr_transaction_block_tcl") else inspect.getsource(R)
    i = src.find("SDR_CANDIDATE_FROM_BEST_PASS")
    assert i > 0, "the best-pass selection is gone"
    window = src[max(0, i - 3000):i + 3000]
    assert "file copy -force" in window, (
        "the best pass is no longer selected by copying its ODB")
    assert "dbChip_destroy" not in window, (
        "an in-session rollback appeared in the selection path — the antenna "
        "loop already measured that it kills the STA network (ORD-2008)")
    assert "undoEco" not in window, (
        "the ECO journal appeared in the selection path — measured to leave a "
        "state that is neither the before nor the after")
