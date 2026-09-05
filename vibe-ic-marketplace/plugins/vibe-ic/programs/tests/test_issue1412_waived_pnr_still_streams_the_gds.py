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


def _row(status, **extras):
    return R.StepResult("pnr", status, 1.0, "detail", [], dict(extras))


# ── the predicate ────────────────────────────────────────────────────────────

def test_passing_pnr_continues_the_chain():
    assert R._pnr_chain_continues(_row("PASS")) is True


def test_waived_pnr_with_completed_signoff_writes_continues_the_chain():
    """The #1412 shape. This is the case that was silently dropping the GDS."""
    assert R._pnr_chain_continues(
        _row("WAIVED", pnr_signoff_writes_complete=True,
             route_residual_waiver={"ticket": "vibe-ic#1412"})) is True


def test_waived_pnr_without_completed_writes_does_NOT_continue():
    """A PnR that died mid-tcl must still stop the chain: WAIVED is not a
    password, the completed writes are."""
    assert R._pnr_chain_continues(_row("WAIVED")) is False
    assert R._pnr_chain_continues(
        _row("WAIVED", pnr_signoff_writes_complete=False)) is False


def test_failed_blocked_and_absent_pnr_do_not_continue():
    for st in ("FAIL", "BLOCKED", "SKIP", "ENV_UNAVAILABLE"):
        assert R._pnr_chain_continues(_row(st)) is False, st
    # even with the flag: a FAILed PnR is not admitted by carrying the key
    assert R._pnr_chain_continues(
        _row("FAIL", pnr_signoff_writes_complete=True)) is False
    assert R._pnr_chain_continues(None) is False


# ── the wiring: the predicate must actually gate the stream-out ──────────────

def test_the_chain_gate_is_wired_to_the_predicate():
    """A predicate nothing calls is not a fix."""
    src = inspect.getsource(R.main)
    assert "_pnr_chain_continues(_pnr_row)" in src, (
        "main() no longer derives the phase-3 chain from _pnr_chain_continues; "
        "the stream-out gate is not wired to it")
    assert '_pnr_row.status == "PASS"' not in src, (
        "main() still tests the PnR row's status literally against PASS -- "
        "that is the exact test that dropped the WAIVED stream-out")


def test_step_gds_is_dispatched_under_the_chain_gate():
    """The `gds` dispatch must sit behind `_chain_ok`, which is what
    `_pnr_chain_continues` feeds. If `step_gds` is ever called unconditionally
    this test should be rewritten, not deleted -- but it must not silently
    become vacuous."""
    src = inspect.getsource(R.main)
    assert "step_gds, project, effective_top, pdk, args.container" in src, (
        "step_gds is no longer dispatched from main() at all")
    head = src.split("step_gds, project, effective_top, pdk, args.container")[0]
    assert "_chain_ok" in head, "the gds dispatch is not gated by _chain_ok"
    assert "_chain_ok = _pnr_step_passed" in src, (
        "_chain_ok no longer derives from the PnR chain predicate")


def test_step_pnr_sets_the_evidence_this_predicate_reads():
    """Both halves in one place: the producer must still write the key the
    consumer reads. This is the producer/consumer contract that, broken
    elsewhere in this same file family, is why LVS sign-off metrics are
    permanently NOT_MEASURED."""
    src = inspect.getsource(R.step_pnr)
    assert '_status = "WAIVED"' in src
    assert '"pnr_signoff_writes_complete"' in src, (
        "step_pnr no longer records pnr_signoff_writes_complete, so "
        "_pnr_chain_continues can never admit a WAIVED PnR")
