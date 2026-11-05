"""R-0915-74 — a refused antenna repair shipped an unverified route.

MEASURED, sha256 x sky130A, lane icsha2 run15 (main 385445351), front door.
The post-route antenna loop inserted 4 diodes (`[INFO GRT-0015] Inserted 4
diodes.`), the incremental `detailed_route` that must re-route their nets RAISED
(`REPAIR_ANTENNA_REROUTE_NONFATAL: DRT-1010`) and the loop broke.  What that
aborted call had already written stayed in the database, was written to
`routed.def`, and NOTHING verified it again: the router's last
`[INFO DRT-0702] Post-route verification:` is at log line 1530 and the refusals
are at 1957 / 1987 / 2427 / 2457.

It was not cosmetic.  Traced across this run's own checkpoints, `net4772` does
not exist at all in `routed_preantenna.def`, exists in the SDR `candidate.def`
WITHOUT its y = 417.450 um met1 segment, and carries that segment in
`routed.def` — and that segment is the conductor magic's extractor then reported
as 22 illegal overlaps across three flip-flops.

THE SHAPE OF THE FIX is the one this repo already proved.  A mid-session
rollback is measured to be unavailable — this deck's own
`ANTENNA_LOOP_BEST_NOT_RESTORED` note records that `dbChip_destroy` + `read_db`
restores the routing and then kills the STA network the rest of the session runs
on (ORD-2008), against a control that survives without it.  So the session
CHECKPOINTS the verified route with `write_db` before it touches anything, and
on a refusal it asks the parent to re-enter the post-route tail from that
checkpoint in a FRESH session with both antenna stages omitted.
"""
from __future__ import annotations

from pathlib import Path


import phase3_one_shot_runner as R








# --------------------------------------------------------------------------
# (a) the session checkpoints BEFORE it mutates, and asks rather than restores
# --------------------------------------------------------------------------






# The window is per-marker and is the LENGTH OF THAT EXIT'S OWN MESSAGE, not a
# loosening: every marker below still has to set `_ant_refused` in the same
# breath as it prints. Only ANTENNA_DIODE_ROLLED_BACK needs more than 260
# characters, because its message names the nets, the diode count and why no
# route is run. R-0915-121 lengthened it again -- it now also reports the two
# damage modes separately (lost entirely / lost in part), names the checkpoint
# the parent is asked to restore from, and cites ORD-2008 for why this session
# does not restore in place. The measured distance is 644, and it is the
# message's own length and nothing else: the uncapped membership-file write
# that R-0915-121(b) adds at that exit is emitted AFTER the assignment, so no
# optional IO sits between an exit's report and the refusal it records. This
# test is what forced that ordering. The number tracks the message; the
# PROPERTY it guards has not moved.












# --------------------------------------------------------------------------
# the request parser — pure, and it reads the marker the refusal prints
# --------------------------------------------------------------------------
_REQ = ("ANTENNA_REPAIR_REFUSED_ROLLBACK_REQUEST: "
        "checkpoint=/w/pnr/antenna_pre_repair.odb "
        "reason=REPAIR_ANTENNA_REROUTE_NONFATAL: DRT-1010")












# --------------------------------------------------------------------------
# the parent: what it does, and what it refuses to do
# --------------------------------------------------------------------------














# --------------------------------------------------------------------------
# (b) the invariant at ship
# --------------------------------------------------------------------------
_VERIFIED = "[INFO DRT-0702] Post-route verification: 0 violation(s).\n"












# --------------------------------------------------------------------------
# the seam
# --------------------------------------------------------------------------
def test_the_rollback_runs_after_the_sdr_adopt():
    """The adopt tail RE-RUNS the antenna stage, so its refusal is the one that
    decides what ships; rolling back first would undo a route the adopt is
    about to replace."""
    src = Path(R.__file__).read_text()
    i_adopt = src.index("_sdr_adopt = _pnr_adopt_sdr_candidates(")
    i_roll = src.index("_ant_roll = _pnr_rollback_refused_antenna_repair(")
    assert i_adopt < i_roll


# --------------------------------------------------------------------------
# a design that never needed a repair
# --------------------------------------------------------------------------




# --------------------------------------------------------------------------
# (b) the invariant keys on ANY modification, not only a refused one
# --------------------------------------------------------------------------
