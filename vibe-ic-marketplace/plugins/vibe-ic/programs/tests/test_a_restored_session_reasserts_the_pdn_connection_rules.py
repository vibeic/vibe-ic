"""A checkpoint-restored session must re-assert the PDN's global CONNECTION
RULES, or everything it creates has power/ground terminals owned by no net.

R-0915-12. MEASURED 2026-09-15 (lane icsub2) on `subservient` x gf180mcuD —
same RTL (sha c6378fa74a…), same PDK, same container, same host, only main
moved::

    main 2f230524b   pnr PASS, GDS 8,142,856 B, 9 of 9 sign-off gates,
                     ZERO occurrences of PG_TERMINALS_ON_NO_NET
    main 7c3bab59c   pnr FAIL
                     PG_TERMINALS_ON_NO_NET: 30150 of 41498 power/ground
                     instance terminals (72.7%) are attached to no net after
                     routing (e.g. masters gf180mcu_fd_sc_mcu7t5v0__clkbuf_16)
                     -> no GDS -> drc SKIP, lvs SKIP, and
                        sta_signoff / sta_corner / sta_record FAIL

Every named master is a CTS buffer — an instance created AFTER the PDN step's
one-shot `global_connect`. The mechanism is visible in the run's own artefacts::

    phase3/stage3/pnr/pnr.tcl                                 6 add_global_connection
                                                              + global_connect (:432-438)
    phase3/stage3/pnr/sdr_child_postroute_drv_repair.tcl       0  +  0
    phase3/stage3/pnr/sdr_child_postroute_drv_reconverge.tcl   0  +  0

and it is the SAME CLASS OF LOSS #2255 found for the spare pool, stated in
`_spare_reassert_dont_touch_tcl`'s own docstring: a checkpoint-seeded deck
elides the floorplan..detailed_route region because the checkpoint contains its
RESULT; the INSTANCES come back with the DEF, the SESSION STATE does not.
`dont_touch` was one such invariant. `add_global_connection` / `global_connect`
is the other, and it was not re-asserted.

THE RULES ARE TAKEN FROM THE DECK, NEVER REBUILT. `_build_pdn_tcl` derives them
from the PDK's own LEFs, the macro LEFs and the IO library; a second derivation
here could disagree with the one the parent session actually ran. Re-running the
parent's own lines cannot.

ALL THREE RESTORE SEAMS, and a test that says so: `_write_sdr_child_decks`,
`_pnr_adopt_sdr_candidates` and `_pnr_resume_after_fatal_signal` all restore
from a checkpoint, and a fourth added later must not be able to forget — which
is why both invariants are assembled in one `_after_restore_tcl`.

chip-AGNOSTIC: the fixture deck's net names are `PWRNET` / `GNDNET`.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))




# The shape `_build_pdn_tcl` emits, reduced: the connection rules, then the
# one-shot apply, then the grid work a checkpoint DOES carry.
DECK_WITH_PDN = """\
puts "PNR_BEGIN"
if {[catch {
  add_global_connection -net PWRNET -pin_pattern "^PWRNET$" -power
  add_global_connection -net GNDNET -pin_pattern "^GNDNET$" -ground
  add_global_connection -net PWRNET -pin_pattern "^VNW$" -power
  global_connect
  set_voltage_domain -name CORE -power PWRNET -ground GNDNET
  define_pdn_grid -name grid
  pdngen
} err]} { puts "PDN_FAILED: $err" }
detailed_route
puts "PNR_END"
"""

DECK_WITHOUT_PDN = """\
puts "PNR_BEGIN"
detailed_route
puts "PNR_END"
"""




# ── the rules come back, verbatim and in order ────────────────────────────











# ── both invariants, and every seam ───────────────────────────────────────





def test_every_restore_seam_goes_through_the_one_assembler():
    """THE SEAM TEST. Three functions restore from a checkpoint; a fourth added
    later must not be able to re-assert one invariant and forget the other."""
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text(errors="replace")
    for fn in ("_write_sdr_child_decks", "_pnr_adopt_sdr_candidates",
               "_pnr_resume_after_fatal_signal"):
        body = src[src.index(f"def {fn}("):]
        body = body[:body.index("\ndef ", 10)]
        assert "_after_restore_tcl(" in body, (
            f"{fn} restores from a checkpoint and does not go through the "
            f"one place both restore invariants are assembled")
    # and nothing calls the spare half on its own any more
    assert src.count("_spare_reassert_dont_touch_tcl(spare_plan)") == 1, (
        "the spare re-assert is reachable only through _after_restore_tcl")


# ── end to end: the derived child deck actually carries them ──────────────
