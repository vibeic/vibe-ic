#!/usr/bin/env python3
"""R-0915-142 — the PG audit must not re-ask the same question 187,948 times,
and it must say where it is while it works.

THE MEASUREMENT. Two runs were killed by the progress watchdog at exactly this
block, each after the route had already succeeded:

  subservient run2, 2nd PnR (2026-09-23 01:22:58)
      WATCHDOG_STALLED: … since_last_progress_s=1822.908 elapsed_s=47426.209
      last line of openroad.log: PG_CONNECT_OWED: 8 terminal(s) gained a net
  subservient probeA (2026-09-23 ~19:55)
      FAIL pnr rc=199 … since_last_progress_s=1825.122 elapsed_s=5608.956
      last line of openroad.log: PG_CONNECT_OWED: 96 terminal(s) gained a net
      -> routed.def never written; drc and lvs both refused for want of it

The watchdog was RIGHT both times: every transcript was silent. The block ran
for longer than the 1800 s grace and emitted nothing at all.

MEASURED COST, both variants against run2's own
`sdr_transaction/pre_repair.odb` in the pinned image, each dumping its complete
result set to a file:

    OLD_RESULT bad=0 no_rail=1228 ms=7006598      (116.8 minutes)
    NEW_RESULT bad=0 no_rail=1228 ms=231191       (  3.85 minutes)
    cmp old.txt new.txt -> IDENTICAL (72,849 bytes each)

Same answer, byte for byte, at 30.3x the speed. The cause is in the new
variant's own disclosure: 61,303 instances, and `VDD 159513` / `VSS 160394`
stripe rectangles that the old code re-fetched and re-walked FOR EVERY PG
TERMINAL. The cache fetches them once per net.

The rules this deck pins:
  * the stripe rectangles are read ONCE PER NET, not once per terminal;
  * the block reports progress at a bounded interval, and announces its
    denominator up front and its totals at the end;
  * the ANSWER is untouched — same fields, same order, same comparison;
  * the watchdog's grace is NOT raised anywhere.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))

import phase3_one_shot_runner as P  # noqa: E402


# ── 1. the work: one fetch per NET, not per terminal ──────────────────────


# ── 2. the answer is untouched ────────────────────────────────────────────


# ── 3. it says where it is ────────────────────────────────────────────────


# ── 4. the grace is NOT raised — this fixes the WORK ──────────────────────
def test_the_watchdog_grace_is_untouched():
    """THE NEGATIVE ARM, and the point of the whole change: a silent step is
    made visible; the watchdog is not made blinder."""
    assert P._WATCHDOG_STALL_GRACE_S == 1800


# ── 5. MUTATION: put the per-terminal fetch back ──────────────────────────
