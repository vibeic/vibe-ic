"""R-0915-105: fillers, taps and the PG connect run BEFORE the first route.

MEASURED on a die whose core is its ring's whole interior (run9, 2026-09-21).
The flow inserted 53,993 fillers, repaired well-tie coverage and re-applied
`global_connect` AFTER the design was routed, and then owed itself a
whole-design `detailed_route` so the spacing engine could see rails that had
just become net-owned shapes. That re-route failed its own connectivity check —
`[ERROR DRT-0206] checkConnectivity error.` — and the failure was SWALLOWED as
`PG_REROUTE_NONFATAL`, so:

  * 105 signal nets were left with no wire and no abutment (probed at the stage
    boundaries: intact at `BEGIN_postroute_fill`, gone at
    `BEGIN_postroute_named_violation_reroute`),
  * nothing said so for another 3877 log lines, where a different checker
    reported `NAMED_VIOL_REROUTE_INCOMPLETE: 105`,
  * no `routed.def` was written and `drc` / `lvs` were never dispatched.

And the re-connect that owed all this had moved **12 terminals of 23,766** onto
a net (measured with the audit's own predicate, before and after).

A rollback is not the repair and this repo already measured why: in the adopt
script's own words, `dbChip_destroy` + `read_db` restores the wires and then
kills STA for the rest of the session (`[CRITICAL ORD-2008]`), and ODB's ECO
journal restores neither state. "The loop cannot restore a best it walked past
— it must not walk past it."

So the order changes instead: place -> fillers/taps -> PG connect -> route. The
residual post-route connect stays for instances a later step creates (antenna
diodes, a repair buffer), it re-routes ONLY when the delta says terminals
actually changed, and a re-route that fails is a VERDICT of that step, by name.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))


SRC = (PROGRAMS / "phase3_one_shot_runner.py").read_text()




# ------------------------------------------------- (1) the order, in the script







# ------------------------------------- (3) delta 0 -> no re-route, and it says so







# ------------------------------------------------ (2) the other direction holds





def test_both_pg_blocks_come_from_one_builder():
    """One implementation, two call sites — not a second copy that can drift."""
    assert SRC.count("def _build_pg_reconnect_tcl(") == 1
    assert "pg_reconnect_block = _build_pg_reconnect_tcl()" in SRC
    assert "pg_preconnect_block = _build_pg_reconnect_tcl(reroute=False)" in SRC
    assert re.search(r"pg_preconnect_block=pg_preconnect_block,", SRC)
