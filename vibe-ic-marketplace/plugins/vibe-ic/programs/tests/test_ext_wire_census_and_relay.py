"""R-0915-25 — the extension-net census, and the half of it that may relay.

MEASURED (sha256 x sky130A, run9's own checkpoint, decoded opcode by opcode):
the two nets `detailed_route` refused with DRT-1010 each carry exactly one
POINT_EXT op, and the coordinate drt calls the non-orthogonal END is that op's
point — paired with the BEGIN of a different path. Each path is orthogonal; the
database holds no diagonal, and neither does any DEF on either side of the
restore. The defect is in the router's wire reader, so until it is fixed the
flow must not hand a restored session a wire the reader mis-pairs.

R-0915-33 — THE RELAY IS RETIRED; THE CENSUS STAYS.

Five cases in this file used to pin the relay's behaviour. They are replaced,
not deleted, by the cases that pin its retirement, and the IDs that went are
named in the commit. What retired it, MEASURED on `subservient` x gf180mcuD
(lane icsub2, r14, on the tree that shipped the relay):

  * DRT-1010 IS COSMETIC. `DRT-0702 Post-route verification: 0 violation(s)` in
    every session that ran one (5 of 5); the gates' own `routed_router.drc.rpt`
    is 0 BYTES; and NO GATE READS DRT-1010 — the only file that mentions it is
    the raw transcript copied to `reports/phase3/drc_router.rpt`, on which
    `drc_report_check` PASSES. sha256 run7 is the same shape.
  * RELAYING DOES NOT CURE IT. r14's failing net `o_sram_addr[7]` was IN the
    first child's 31-net census, WAS relaid, and came back still tripping
    DRT-1010.
  * AND IT COSTS REAL TIMING. Same RTL, same SDC, same input, `SHIP_WNS_BEFORE`
    -3.0296530586256614 (no relay) -> -3.636286041864957 (relay live), the
    convergence plateauing with pass2 worse than pass1, and `sta_corner` SS
    +0.03 (closed) -> -0.50 (VIOLATED).

So every restore deck censuses and names the nets, and NO deck drops a wire.

The negative controls are unchanged: a net with no extension op is never
touched, a census of 0 says so, PG is refused by the shared helper, and the
census asks the decoder for nothing that could segfault.
"""
import shutil
import sys
from pathlib import Path


PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402

tclsh = shutil.which("tclsh")

SPARE_PLAN = {"instances": [{"name": "spare_inverter_0", "cell": "inv_2"},
                            {"name": "spare_dff_0", "cell": "dfxtp_2"}]}






# --------------------------------------------------------------- the census













# ---------------------------------------------------------------- the relay









def test_the_shared_helper_still_refuses_pg():
    proc = R._spare_safe_clear_net_proc_tcl()
    assert 'if {$_st eq "POWER" || $_st eq "GROUND"} { return PG }' in proc


# ------------------------------------------------------- shape of the decks





def test_every_restore_site_goes_through_the_one_composer():
    src = (PROG / "phase3_one_shot_runner.py").read_text()
    assert src.count("_after_restore_tcl(") >= 4  # def + three call sites
