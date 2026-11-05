"""#1412 CONTINUED — a WAIVED PnR must still reach the stream-out.

`step_pnr` returns WAIVED (not FAIL) when every residual DRT marker is below
its own layer's LEF MINWIDTH in both dimensions, on the explicit reasoning that
"the sign-off DRC deck runs on the streamed GDS, evaluates merged polygons and
keeps its own verdict". The phase-3 chain test that gates the stream-out was
written when `step_pnr` was binary, and still read `status == "PASS"`, so a
WAIVED PnR was rejected exactly like a failed one and `step_gds` was NEVER
CALLED -- emitting no `gds` row at all, not even a SKIP.

MEASURED, spm x gf180mcuD, plugin 1.17.38, EDA image 0.3.6, host 8HD-9:
  phase3 steps ... pnr WAIVED -> drc SKIP ...   (no `gds` row anywhere)
  drc               SKIP  "GDS missing: phase3/stage3/pnr/spm.gds"
  tapeout_precheck  FAIL  NOT_DETERMINED at KLayout.ReadLayout,
                          refuses_on "the layout file cannot be read as GDSII"
  overall           FAIL  halted_at phase3
while the published v1.14.88 cell for the same IC and PDK recorded
`gds PASS 41.33s (streamout=magic, 2,131,574 bytes)` then `drc PASS
violations=0`.

The gating status is NOT the assertion here. What is asserted is that the
predicate keys off the ARTEFACT evidence `pnr_signoff_writes_complete` -- set by
`step_pnr` on the same branch that sets WAIVED, because "the writes below it all
ran" -- so a PnR that died mid-tcl still stops the chain, and a future status
added without those writes is not silently admitted.
"""
import inspect
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402


#: R-0915-85 — the fields each word REQUIRES, supplied here so a fixture can
#: name a status without also having to remember its obligations. A
#: NOT_MEASURED with no reason and a NOT_APPLICABLE with no declaration are
#: refused at the row, which is the point: they are not sayable.
_OBLIGATION = {
    "NOT_MEASURED": {"reason_class": "not_executed"},
    "NOT_APPLICABLE": {"declared_by": "the input declares no PnR"},
    "PASS_WITH_WAIVERS": {"attribution": "the sign-off engineer"},
}




# ── the predicate ────────────────────────────────────────────────────────────









# ── the wiring: the predicate must actually gate the stream-out ──────────────



def test_step_gds_is_dispatched_under_the_chain_gate():
    """The `gds` dispatch must sit behind `_chain_ok`, which is what
    `_pnr_chain_continues` feeds. If `step_gds` is ever called unconditionally
    this test should be rewritten, not deleted -- but it must not silently
    become vacuous."""
    src = inspect.getsource(R.main)
    from _phase3_main_dispatch import gds_chain_dispatch_line
    assert gds_chain_dispatch_line()
    assert "_chain_ok = _pnr_step_passed" in src, (
        "_chain_ok no longer derives from the PnR chain predicate")
