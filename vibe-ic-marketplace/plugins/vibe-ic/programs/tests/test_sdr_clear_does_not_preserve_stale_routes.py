#!/usr/bin/env python3
"""R-0915-71 — the SDR clear preserved wires it was about to invalidate.

MEASURED (opentitan_aes x sky130A, 2026-09-16). Pass 4 of the post-route DRV
loop died on

    Error: spare_tielo_spare_inverter_107 1 pin not visited #guides = 7
    Error: checkConnectivity break, net spare_tielo_spare_inverter_107
    [ERROR DRT-0206] checkConnectivity error.

ONE net -- `checkConnectivity` stops at the first failure -- and it cost a
5.4-hour route, `route_ok=0`, and the whole repaired candidate.

v1.8.43 had already diagnosed this exact failure (spm x sky130A) and removed
the `*spare*` NAME filter from the routing clear, because TritonRoute cannot
reconcile a stale detailed route against fresh global-route guides. It left the
`isDoNotTouch` filter alone -- and on a design with spare cells the two
predicates select THE SAME NETS. From this run's own `pre_repair.odb`:

    PG=2  PROTECTED=604 (spare-named=604  other=0)  UNROUTED=703  CLEARABLE=39780

All 604 are `spare_tielo_*` and all 604 are WIRED, so the deleted filter was
still in force under another name, at 604x the scale of the single net that
produced the v1.8.42 failure.

The site-specific fact that decides it: the SDR clear is followed by
`global_route` + `detailed_route`, which regenerates every guide. A preserved
wire there has nothing left to be reconciled against. A caller that does NOT
re-route must still keep those wires, which is why the choice is an argument
and not a new rule inside the proc.

These tests read the EMITTED Tcl, because that is what OpenROAD executes.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))

_CALL = "_vibeic_spare_safe_clear_net $_net"




# ───────────────── the argument exists and both ways are real ──────────────







def test_power_and_ground_are_never_reachable_through_the_argument():
    """The PG skip is not optional. `drop_protected` must not be a way to
    destroy supply wiring -- the proc returns PG before it ever looks at the
    dont_touch flag, and this pins that ordering in the emitted text."""
    proc = R._spare_safe_clear_net_proc_tcl()
    pg = proc.index('return PG')
    # The GUARD, not the parameter declaration -- the parameter is named in the
    # proc's signature on line 1 and would make this comparison meaningless.
    guard = proc.index('if {!$_drop_protected}')
    assert pg < guard, (
        "the POWER/GROUND skip no longer precedes the drop_protected branch; "
        "a caller could reach supply wiring through it")
    assert proc.index('odb::dbWire_destroy') > pg, (
        "a wire can now be destroyed before the POWER/GROUND check runs")


# ─────────────────── the SDR site is the one that drops ────────────────────







# ─────────────────────────── it still runs ─────────────────────────────────
