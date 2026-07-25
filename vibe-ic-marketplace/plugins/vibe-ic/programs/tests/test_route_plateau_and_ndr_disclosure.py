"""ORGANIC (routing convergence, 2026-07-25) — two chip-AGNOSTIC defects that
share one root: the flow had NO honest account of what routing congestion cost.

CASE A — the SILENT clock-NDR trade (ibex + opentitan_aes, sky130A).
  OpenROAD's global-route congestion recovery DROPS the non-default rule off
  the CTS clock nets:
      [WARNING GRT-0273] Disabled NDR (to reduce congestion) for net: clknet_0_clk_regs
  and the flow said nothing, in EITHER outcome:
    * ibex   — the trade was made, congestion STILL lost (GRT-0116), and the
               step FAILed with a bare `rc=1 log_tail=<2000 chars>`: neither
               the trade nor the congestion root-cause was named.
    * aes    — the trade was made and the route then SUCCEEDED, so the run went
               GREEN with 2-5 clock nets routed at default width/spacing and
               nobody was told. This is the dangerous half.
  Fix: `_clock_ndr_disclosure` / `_clock_ndr_detail` surface the trade on EVERY
  pnr outcome (PASS included), `reports/route_congestion_trades.json` persists
  it, and GRT-0116 becomes the structured GLOBAL_ROUTE_CONGESTION finding.
  The verdict TIER is deliberately unchanged — disclosure, not a new failure.

CASE B — the detailed-route burn (edge_llm_matmul_accel), ~23.5 h of OpenROAD
CPU, no routed DEF, no GDS. TWO separate mechanisms, and the evidence supports
each of them to a DIFFERENT depth. Keeping that distinction is the point:

  B-1 the PLATEAU stop (a FLAT tail).
    `_drt_plateau_verdict` is the domain read ("violations stopped falling"),
    `_DrtPlateauProbe` evaluates it LIVE on the tee'd log, and
    `_watchdog.run_supervised(abort_probe=...)` stops the router with the new
    rc=RC_ABORTED so step_pnr reports ROUTE_PLATEAU instead of burning a day.
    The progress-stall watchdog cannot see this and is RIGHT not to (output +
    CPU advance every poll: the job is alive); the 24h ceiling is a
    pathological-loop backstop, not a convergence judgement.
    *** SCOPE OF THE CLAIM ***: the only RECORDED edge_llm trajectory is the 5
    samples in `benchmark-data/ic/edge_llm_matmul_accel/phase3/
    PHASE3_MILESTONE.md` (`MATMUL_RECORDED` below), and on those the predicate
    correctly returns None — at iteration 4 that route was still improving
    ~11%/iter and is, by any windowed-gain measure, INDISTINGUISHABLE from the
    real converging routes in `REAL_CONVERGING`. We do NOT claim this predicate
    would have stopped edge_llm at iteration 4, and no honest predicate could:
    see `test_recorded_matmul_prefix_is_not_yet_a_plateau`. What it covers is
    the FLAT tail, exercised by the clearly-labelled SYNTHETIC fixture.
    (The doc's "plateauing ~13 K/iter" is the last IMPROVEMENT, 129,304 ->
    116,677 = 12,627 — not a residual violation count. An earlier revision of
    this file encoded the other reading as a fabricated flat 13K tail and
    claimed the predicate fired on "the real wall". It did not. Fixture
    provenance is now asserted mechanically by
    `test_matmul_recorded_matches_the_milestone_record`.)

  B-2 the PRE-ROUTE disclosure (what the flow ALREADY knew, 23.5 h earlier).
    Global placement's routability phase reports its own congestion estimate
    and says out loud when it cannot reach target:
        [INFO GPL-0047] Routability iteration weighted routing congestion: 1.15
        [INFO GPL-0089] Routability finished. Reverting to minimal observed
                        routing congestion, could not reach target.
    edge_llm sat at 1.15-1.17 (>1.0 = local demand over capacity) at 36.1%
    global utilisation — the milestone doc calls this "the early congestion
    signal" — and the flow proceeded through CTS into a 23.5 h detailed route
    without ever surfacing it. `_placement_congestion_disclosure` makes it a
    first-class disclosure on EVERY pnr outcome, exactly like the CASE-A clock
    NDR trade. §4.05: disclosure ONLY, no verdict TIER change — 1.0 is the
    PHYSICAL unity point (demand/capacity), not a threshold fitted to make the
    corpus separate. It deliberately is not a predictor: opentitan_aes
    CONVERGED at a final 1.0805 with GPL-0089 set, and that run must still be
    disclosed and still PASS (`test_placement_disclosure_does_not_change_tier`).

NEGATIVE CONTROL: every `test_negctl_*` below FAILS on the pre-fix tree — the
symbol it exercises does not exist there (`AttributeError`/`TypeError`), which
is exactly the pre-fix behaviour: no disclosure, no live abort.
"""
import ast
import inspect
import json
import sys
import textwrap
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402
import _watchdog as W  # noqa: E402


# ── REAL fixtures, transcribed from live campaign OpenROAD logs ──────────────
# ibex / sky130A: the trade was made AND congestion still lost.
IBEX_TAIL = (
    "PG_CLEANUP_DEL: zero_ (GROUND)\n"
    "PG_CLEANUP_DONE: deleted=1 reclassified=0\n"
    "[WARNING GRT-0273] Disabled NDR (to reduce congestion) for net: "
    "clknet_0_clk_regs\n"
    "[WARNING GRT-0273] Disabled NDR (to reduce congestion) for net: clk_regs\n"
    "[ERROR GRT-0116] Global routing finished with congestion. Check the "
    "congestion regions in the DRC Viewer.\n"
    "Error: pnr.tcl, 989 GRT-0116\n"
)
# opentitan_aes / sky130A: the trade was made and the route SUCCEEDED — the
# silent-green case. The same net is re-reported by later reroute passes.
AES_TAIL = (
    "[WARNING GRT-0273] Disabled NDR (to reduce congestion) for net: "
    "clknet_2_2_0_clk_i\n"
    "[INFO DRT-0199] Number of violations = 18.\n"
    "[WARNING GRT-0273] Disabled NDR (to reduce congestion) for net: "
    "clknet_2_2_0_clk_i\n"
    "[WARNING GRT-0273] Disabled NDR (to reduce congestion) for net: "
    "clknet_2_3_0_clk_i\n"
    "[INFO DRT-0199] Number of violations = 0.\n"
)

# Every DRT-0199 trajectory in the local campaign corpus that CONVERGED
# (final 0). Provenance: campaign_v1520/1544/1551/1558/1560/1566/1569/1570/1578
# + benchmark-data caravel_user_project + sha256/aes/spm clean runs. These are
# the routes the live abort must NEVER touch.
REAL_CONVERGING = [
    [6983, 3048, 2541, 57, 0],
    [89708, 69402, 64501, 13921, 2508, 664, 261, 135, 81, 32, 18, 7, 7, 0],
    [8568, 5416, 5126, 849, 72, 20, 0],
    [111, 50, 43, 0],
    [6762, 4030, 3784, 661, 92, 12, 5, 3, 3, 0],
    [8139, 5080, 4844, 579, 101, 27, 4, 0],
    [6917, 4401, 3961, 478, 51, 0],
    [6571, 3592, 3413, 385, 35, 1, 1, 0],
    [6704, 3563, 3047, 449, 38, 0],
    [6572, 3820, 3248, 540, 14, 2, 2, 0],
]

# edge_llm_matmul_accel — the ONLY recorded trajectory, transcribed verbatim
# from benchmark-data/ic/edge_llm_matmul_accel/phase3/PHASE3_MILESTONE.md
# ("violations 409,554 -> 332,073 -> 312,639 -> 129,304 -> ~116,677 (iter
# 1->4)"). The run then burned ~23.5 h with NO further numbers written down,
# so the tail of this route is simply NOT IN EVIDENCE. Nothing below may
# extrapolate it. Its own deltas are [77481, 19434, 183335, 12627] — the last
# one is the doc's "plateauing ~13 K/iter".
MATMUL_RECORDED = [409554, 332073, 312639, 129304, 116677]
MILESTONE_DOC = (Path(__file__).resolve().parents[5] / "benchmark-data" / "ic"
                 / "edge_llm_matmul_accel" / "phase3" / "PHASE3_MILESTONE.md")

# SYNTHETIC — NOT from any log. A hand-written FLAT tail, the shape the
# plateau predicate exists to stop. Labelled so it can never be mistaken for
# campaign evidence.
SYNTHETIC_FLAT_TAIL = [409554, 332073, 312639, 129304, 116677,
                       13421, 13208, 13150, 13102, 13094]


# ── CASE B: the plateau predicate ────────────────────────────────────────────

def test_matmul_recorded_matches_the_milestone_record():
    """PROVENANCE GUARD. `MATMUL_RECORDED` must be transcribable from the
    checked-in milestone doc, digit for digit. This is the test that would
    have caught the fabricated flat-13K fixture: a plateau fixture nobody can
    trace back to a report is not evidence, and a fix verified against it is
    verified against itself."""
    if not MILESTONE_DOC.is_file():          # pragma: no cover - repo layout
        pytest.skip(f"milestone record not present: {MILESTONE_DOC}")
    text = MILESTONE_DOC.read_text(errors="ignore")
    for n in MATMUL_RECORDED:
        assert f"{n:,}" in text, f"{n:,} is not in {MILESTONE_DOC.name}"
    # ...and the doc's "~13 K/iter" is the last IMPROVEMENT, not a residue.
    assert MATMUL_RECORDED[-2] - MATMUL_RECORDED[-1] == 12627
    # The synthetic fixture must stay honestly labelled as NOT from the doc.
    assert f"{SYNTHETIC_FLAT_TAIL[-1]:,}" not in text


def test_recorded_matmul_prefix_is_not_yet_a_plateau():
    """THE HONESTY BOUND on CASE B-1. At every prefix of the only recorded
    edge_llm trajectory the predicate abstains — that route was still taking
    ~11%/iter off the violation count when the record stops. We therefore do
    NOT claim the plateau stop would have saved the 23.5 h at iteration 4;
    the pre-route disclosure (CASE B-2) is what speaks to that window."""
    for i in range(2, len(MATMUL_RECORDED) + 1):
        assert R._drt_plateau_verdict(MATMUL_RECORDED[:i]) is None, i


def test_negctl_plateau_predicate_fires_on_a_flat_tail():
    """NEG-CTL: pre-fix `_drt_plateau_verdict` does not exist, so a flat tail
    had no representation at all and the router ran on. Exercised on the
    SYNTHETIC fixture — see `test_recorded_matmul_prefix_is_not_yet_a_plateau`
    for why the recorded trajectory cannot carry this assertion."""
    rec = R._drt_plateau_verdict(SYNTHETIC_FLAT_TAIL)
    assert rec is not None
    assert rec["finding"] == "ROUTE_PLATEAU"
    assert rec["window_to"] == 13094
    assert rec["window_rel_gain"] < R._DRT_PLATEAU_MIN_REL_GAIN
    assert rec["iterations_seen"] == len(SYNTHETIC_FLAT_TAIL)


def test_plateau_reason_names_the_numbers_it_acted_on():
    reason = R._drt_plateau_reason(R._drt_plateau_verdict(SYNTHETIC_FLAT_TAIL))
    assert "ROUTE_PLATEAU" in reason
    assert "13094" in reason and "13421" in reason
    # The honesty clause: a plateau is a congestion result, not "needs more
    # router iterations" — the wording must not send the user down that path.
    assert "not a router-iteration shortfall" in reason


def test_plateau_never_fires_on_a_converged_route():
    for traj in REAL_CONVERGING:
        assert R._drt_plateau_verdict(traj) is None, traj


def test_real_corpus_no_false_positive_on_any_prefix():
    """The LIVE abort sees PREFIXES of a trajectory, not the finished one. No
    prefix of any real converging route may ever look like a plateau — this is
    the no-downstream-regression proof for the abort."""
    for traj in REAL_CONVERGING:
        for n in range(1, len(traj) + 1):
            rec = R._drt_plateau_verdict(traj[:n])
            assert rec is None, f"false abort on {traj[:n]} (from {traj})"


def test_real_corpus_keeps_a_wide_margin_to_the_threshold():
    """Report the SMALLEST real converging window gain, so the calibration
    margin is a measured number in the suite rather than a claim in a comment.
    The tightest real window must stay comfortably above the threshold."""
    worst = 1.0
    w = R._DRT_PLATEAU_WINDOW
    for traj in REAL_CONVERGING:
        for i in range(w, len(traj)):
            head, tail = traj[i - w], traj[i]
            if head <= 0 or tail < R._DRT_PLATEAU_MIN_VIOLATIONS:
                continue
            worst = min(worst, (head - tail) / float(head))
    assert worst > 4 * R._DRT_PLATEAU_MIN_REL_GAIN, (
        f"real converging routes come within {worst:.3f} of the "
        f"{R._DRT_PLATEAU_MIN_REL_GAIN} plateau threshold — recalibrate")


def test_plateau_needs_a_full_window_of_evidence():
    """One or two flat iterations are normal mid-route; the abort must wait
    for a full window before it is allowed to kill anything."""
    flat = [50000] * R._DRT_PLATEAU_WINDOW      # window+1 samples required
    assert R._drt_plateau_verdict(flat) is None
    assert R._drt_plateau_verdict(flat + [50000]) is not None


def test_plateau_ignores_small_residue():
    """A flat tail at a handful of violations is the antenna / SPEF-repair
    reroute working on its own residue — a different mechanism's business."""
    residue = [7] * (R._DRT_PLATEAU_WINDOW + 1)
    assert R._drt_plateau_verdict(residue) is None
    assert R._DRT_PLATEAU_MIN_VIOLATIONS > max(residue)


def test_plateau_catches_a_climbing_route():
    climbing = [5000, 5200, 5400, 5600, 5800]
    rec = R._drt_plateau_verdict(climbing)
    assert rec is not None and rec["window_rel_gain"] < 0


def test_plateau_never_fires_on_a_clean_finish():
    assert R._drt_plateau_verdict([90000, 500, 40, 3, 0]) is None


# ── CASE B: the live probe over a growing log ────────────────────────────────

def _log_with(counts):
    return "".join(
        f"[INFO DRT-0195] Start {i}th optimization iteration.\n"
        f"[INFO DRT-0199] Number of violations = {c}.\n"
        for i, c in enumerate(counts, 1))


def test_negctl_live_probe_aborts_only_once_the_wall_is_proven(tmp_path):
    """NEG-CTL: pre-fix there is no probe, so a plateaued router was never
    stopped. Here the probe stays silent while the log still shows progress
    and fires the moment the window closes on a flat tail."""
    log = tmp_path / "openroad.log"
    probe = R._DrtPlateauProbe(log)
    assert probe() is None                       # no log yet ⇒ no opinion
    log.write_text(_log_with(SYNTHETIC_FLAT_TAIL[:5]))
    assert probe() is None                       # still improving fast
    log.write_text(_log_with(SYNTHETIC_FLAT_TAIL))
    reason = probe()
    assert reason is not None and "ROUTE_PLATEAU" in reason
    assert probe.record["window_to"] == 13094


def test_live_probe_is_sticky_and_reports_what_it_acted_on(tmp_path):
    """Once fired, the probe must keep reporting the SAME evidence: the run is
    already being killed, and a re-read of a still-growing log would report a
    state that never triggered anything."""
    log = tmp_path / "openroad.log"
    probe = R._DrtPlateauProbe(log)
    log.write_text(_log_with(SYNTHETIC_FLAT_TAIL))
    first = probe()
    fired_on = dict(probe.record)
    log.write_text(_log_with(SYNTHETIC_FLAT_TAIL + [1, 0]))
    assert probe() == first
    assert probe.record == fired_on


def test_the_retry_loop_clears_the_previous_transcript_before_relaunching():
    """The retry loop re-runs `... | tee openroad.log`, so at the instant a new
    attempt starts the file still holds the OLD attempt's plateaued log. A
    probe that read it would abort the fresh attempt on its first poll —
    killing the looser retry the loosen ladder just paid for. The loop must
    therefore clear the log BEFORE constructing the probe (an mtime heuristic
    cannot do this job: the two writes are milliseconds apart)."""
    src = inspect.getsource(R.step_pnr)
    body = src[src.index("for _retry_i in _pnr_loop:"):]
    body = body[:body.index("_docker_exec(")]
    assert "_pnr_logp.unlink()" in body
    assert body.index("_pnr_logp.unlink()") < body.index("_DrtPlateauProbe(")


def test_live_probe_never_aborts_a_converging_route(tmp_path):
    log = tmp_path / "openroad.log"
    for traj in REAL_CONVERGING:
        probe = R._DrtPlateauProbe(log)
        for n in range(1, len(traj) + 1):
            log.write_text(_log_with(traj[:n]))
            assert probe() is None, f"{traj[:n]} aborted"


# ── CASE B: the watchdog abort hook ──────────────────────────────────────────

class _FakeProc:
    """A process that never exits on its own and always looks busy."""

    def __init__(self):
        self.killed = False

    def wait(self, timeout=None):
        raise _Timeout()

    def kill(self):
        self.killed = True


class _Timeout(Exception):
    pass


def _wait_never(proc, timeout):
    return None


def test_negctl_supervise_kills_a_progressing_job_that_goes_nowhere():
    """NEG-CTL: pre-fix `supervise` has no `abort_probe` (TypeError). A job
    that keeps PROGRESSING is never killed — which is the whole 23.5h bug: the
    stall grace and the ceiling both correctly decline, and nothing else looks."""
    proc = _FakeProc()
    killed_with = []
    ticks = iter(range(100))
    polls = {"n": 0}

    def progress():
        polls["n"] += 1
        return polls["n"]          # ALWAYS progressing → stall never trips

    def abort():
        return "gone nowhere" if polls["n"] >= 3 else None

    outcome, rc = W.supervise(
        proc, progress, lambda p, why: killed_with.append(why),
        poll_s=0, stall_grace_s=10_000, hard_ceiling_s=10_000,
        wait_fn=_wait_never, clock=lambda: next(ticks),
        abort_probe=abort)
    assert outcome == "aborted"
    assert rc is None
    assert killed_with == ["aborted"]


def test_supervise_without_abort_probe_is_unchanged():
    """§4.05: the hook is opt-in. With no probe the job runs until the stall
    grace, exactly as before."""
    proc = _FakeProc()
    killed_with = []
    ticks = iter(range(100))
    outcome, _ = W.supervise(
        proc, lambda: 1, lambda p, why: killed_with.append(why),
        poll_s=0, stall_grace_s=3, hard_ceiling_s=10_000,
        wait_fn=_wait_never, clock=lambda: next(ticks))
    assert outcome == "stalled"
    assert killed_with == ["stalled"]


def test_abort_is_checked_last_so_a_finished_run_wins():
    """A job that exits inside the poll window must be reported 'natural' even
    if the probe would have aborted — an abort may never steal a real result."""
    proc = _FakeProc()
    outcome, rc = W.supervise(
        proc, lambda: 1, lambda p, why: None,
        poll_s=0, stall_grace_s=10_000, hard_ceiling_s=10_000,
        wait_fn=lambda p, t: 0, clock=lambda: 0.0,
        abort_probe=lambda: "would abort")
    assert outcome == "natural" and rc == 0


def test_a_probe_that_raises_never_kills_the_job():
    proc = _FakeProc()
    ticks = iter(range(100))

    def boom():
        raise RuntimeError("probe bug")

    outcome, _ = W.supervise(
        proc, lambda: 1, lambda p, why: None,
        poll_s=0, stall_grace_s=3, hard_ceiling_s=10_000,
        wait_fn=_wait_never, clock=lambda: next(ticks),
        abort_probe=boom)
    assert outcome == "stalled"          # the stall grace, not the probe


def test_negctl_run_supervised_reports_the_abort_distinctly():
    """NEG-CTL: pre-fix `run_supervised` has no `abort_probe` (TypeError) and
    no RC_ABORTED. The abort must NOT be dressed up as a hang or a natural rc."""
    reasons = iter([None, "ROUTE_PLATEAU: nowhere"])
    res = W.run_supervised(
        ["/bin/sh", "-c", "sleep 30"],
        poll_s=0, stall_grace_s=10_000, hard_ceiling_s=10_000,
        abort_probe=lambda: next(reasons, "ROUTE_PLATEAU: nowhere"))
    assert res.rc == W.RC_ABORTED
    assert res.outcome == "aborted"
    assert res.aborted is True
    assert res.stalled is False          # an abort is NOT a hang
    assert "ROUTE_PLATEAU: nowhere" in res.abort_reason
    assert "WATCHDOG_ABORTED" in res.err


def test_rc_aborted_is_distinct_from_the_other_kills():
    assert len({W.RC_ABORTED, W.RC_STALLED, W.RC_CEILING}) == 3


# ── CASE A: the clock-NDR disclosure ─────────────────────────────────────────

def test_negctl_clock_ndr_trade_is_disclosed_on_the_ibex_log():
    """NEG-CTL: pre-fix `_clock_ndr_disclosure` does not exist — the trade
    appeared nowhere in the verdict, only inside a 2000-char log tail."""
    disc = R._clock_ndr_disclosure(IBEX_TAIL)
    assert disc is not None
    assert disc["finding"] == "CLOCK_NDR_DISABLED_FOR_CONGESTION"
    assert disc["nets"] == ["clknet_0_clk_regs", "clk_regs"]
    assert disc["net_count"] == 2
    assert disc["clock_tree_nets"] == ["clknet_0_clk_regs"]
    assert disc["congestion_error"] is True


def test_negctl_silent_green_run_still_discloses_the_trade():
    """The dangerous half: aes traded the clock NDR and the route SUCCEEDED
    (no GRT-0116). Pre-fix that run was simply green with a degraded clock
    tree. The disclosure must be present with congestion_error False."""
    disc = R._clock_ndr_disclosure(AES_TAIL)
    assert disc is not None
    assert disc["congestion_error"] is False
    # A net re-reported by later reroute passes is ONE degraded net.
    assert disc["nets"] == ["clknet_2_2_0_clk_i", "clknet_2_3_0_clk_i"]
    assert disc["clock_tree_net_count"] == 2


def test_no_disclosure_when_the_trade_was_never_made():
    assert R._clock_ndr_disclosure("[INFO GRT-0018] Total wirelength: 1\n") is None
    assert R._clock_ndr_detail(None) == ""
    assert R._grt_ndr_disabled_nets("") == []


def test_disclosure_text_names_the_cost_not_just_the_event():
    detail = R._clock_ndr_detail(R._clock_ndr_disclosure(IBEX_TAIL))
    assert "clock-NDR TRADED" in detail
    assert "clknet_0_clk_regs" in detail
    assert "default width/spacing" in detail
    assert "skew" in detail


def test_disclosure_text_truncates_a_long_net_list():
    log = "".join(
        f"[WARNING GRT-0273] Disabled NDR (to reduce congestion) for net: "
        f"clknet_{i}_clk\n" for i in range(9))
    disc = R._clock_ndr_disclosure(log)
    detail = R._clock_ndr_detail(disc)
    assert disc["net_count"] == 9
    assert "…" in detail
    assert "clknet_8_clk" not in detail       # truncated, count still honest
    assert "9 net(s)" in detail


def test_grt_congestion_error_is_recognised():
    assert R._grt_congestion_failed(IBEX_TAIL) is True
    assert R._grt_congestion_failed(AES_TAIL) is False
    assert R._grt_congestion_failed("") is False


# ── CASE B-2: the PRE-ROUTE congestion read the flow already had ─────────────
# REAL fixtures, transcribed from the campaign OpenROAD logs named below.
# ibex/sky130A (campaign_v1560) — placement could NOT reach target, and the
# route then died on GRT-0116.
IBEX_PLACE = (
    "[INFO GPL-0047] Routability iteration weighted routing congestion: 1.4879\n"
    "[INFO GPL-0047] Routability iteration weighted routing congestion: 1.3255\n"
    "[INFO GPL-0089] Routability finished. Reverting to minimal observed "
    "routing congestion, could not reach target.\n"
)
# opentitan_aes/sky130A (campaign_v1560) — placement ALSO could not reach
# target and ended over unity, and the route CONVERGED anyway. This fixture is
# the reason the disclosure is not allowed to be a verdict.
AES_PLACE = (
    "[INFO GPL-0047] Routability iteration weighted routing congestion: 1.4606\n"
    "[INFO GPL-0047] Routability iteration weighted routing congestion: 1.1581\n"
    "[INFO GPL-0047] Routability iteration weighted routing congestion: 1.0757\n"
    "[INFO GPL-0047] Routability iteration weighted routing congestion: 1.0805\n"
    "[INFO GPL-0089] Routability finished. Reverting to minimal observed "
    "routing congestion, could not reach target.\n"
)
# sha256/sky130A (campaign_v1544) — comfortable: reached target, ended UNDER
# unity. Nothing to disclose; a disclosure here would be pure noise.
SHA256_PLACE = (
    "[INFO GPL-0047] Routability iteration weighted routing congestion: 1.082\n"
    "[INFO GPL-0047] Routability iteration weighted routing congestion: 0.9057\n"
)


def test_negctl_placement_congestion_is_disclosed_on_the_real_ibex_log():
    """NEG-CTL: pre-fix `_placement_congestion_disclosure` does not exist, so
    the placer's own "could not reach target" at 1.3255 — available BEFORE the
    route was even attempted — reached no report and no verdict."""
    disc = R._placement_congestion_disclosure(IBEX_PLACE)
    assert disc is not None
    assert disc["finding"] == "PLACEMENT_CONGESTION_RESIDUAL"
    assert disc["final_weighted_congestion"] == 1.3255
    assert disc["over_capacity"] is True
    assert disc["routability_gave_up"] is True
    assert disc["routability_iterations"] == 2


def test_negctl_placement_disclosure_fires_on_the_converged_aes_run():
    """NEG-CTL + the honest half: opentitan_aes went over capacity, the placer
    gave up, and the route STILL converged. It must be disclosed anyway — the
    margin a green run passed on is worth the same sentence as the margin a
    red one failed on."""
    disc = R._placement_congestion_disclosure(AES_PLACE)
    assert disc is not None
    assert disc["final_weighted_congestion"] == 1.0805
    assert disc["min_weighted_congestion"] == 1.0757   # not the final one
    assert disc["over_capacity"] is True
    assert disc["routability_gave_up"] is True


def test_placement_disclosure_is_silent_on_a_comfortable_placement():
    """A design that reached target and ended UNDER unity has nothing to
    disclose. Guarding this keeps the disclosure from degrading into noise
    that gets filtered out and therefore stops being read."""
    assert R._placement_congestion_disclosure(SHA256_PLACE) is None
    assert R._placement_congestion_disclosure("") is None
    assert R._placement_congestion_detail(None) == ""


def test_placement_over_capacity_threshold_is_physical_unity():
    """The one number here that must NOT be tuned. 1.0 is where routing demand
    equals capacity; anything fitted to make the local corpus separate would
    be a predictor dressed up as physics — and the corpus does NOT separate
    (aes converged at 1.0805, ibex failed at 1.3255)."""
    assert R._GPL_CONGESTION_OVER_CAPACITY == 1.0
    just_over = "[INFO GPL-0047] Routability iteration weighted routing " \
                "congestion: 1.0\n"
    just_under = "[INFO GPL-0047] Routability iteration weighted routing " \
                 "congestion: 0.9999\n"
    assert R._placement_congestion_disclosure(just_over) is not None
    assert R._placement_congestion_disclosure(just_under) is None


def test_placement_disclosure_does_not_change_tier():
    """§4.05. The disclosure is text + extras on whatever outcome the route
    actually had. It must not introduce a new FAIL: no verdict word appears in
    the detail, and the wording explicitly refuses to predict."""
    detail = R._placement_congestion_detail(
        R._placement_congestion_disclosure(AES_PLACE))
    assert detail.startswith(" | PRE-ROUTE CONGESTION:")
    assert "not a verdict" in detail
    assert "converged from here and have also failed from here" in detail
    for verdict_word in ("FAIL", "PASS", "unroutable", "cannot be routed"):
        assert verdict_word not in detail


def test_placement_detail_never_claims_a_clock_ndr_trade():
    """WIRING GUARD. `_place_detail` is a SEPARATE variable from `_ndr_detail`
    because the GRT-0116 branch appends 'and it was NOT enough: the rule was
    given up' whenever `_ndr_detail` is non-empty. Folding the two together
    would make a run that dropped NO clock NDR claim it had."""
    detail = R._placement_congestion_detail(
        R._placement_congestion_disclosure(IBEX_PLACE))
    assert "NDR" not in detail and "non-default" not in detail
    src = inspect.getsource(R.step_pnr)
    assert "_place_detail = _placement_congestion_detail(" in src
    # the two must never be summed into the flag the GRT-0116 clause tests
    assert "_ndr_detail = _clock_ndr_detail(_ndr_disc)" in src
    grt = src[src.index("GLOBAL_ROUTE_CONGESTION: global routing finished"):]
    grt = grt[:grt.index("extras=")]
    assert 'if _ndr_detail else ""' in grt


def test_negctl_trades_report_carries_the_pre_route_read(tmp_path):
    """NEG-CTL: pre-fix the side-file had no placement section at all, so a
    downstream gate could not tell "placement was comfortable" from "nobody
    looked". schema/2 states it positively in BOTH directions."""
    hot = R._write_route_congestion_trades(
        tmp_path / "hot", None, IBEX_PLACE)
    body = json.loads(hot.read_text())
    assert body["schema"] == "route_congestion_trades/2"
    assert body["placement_congestion"] is True
    assert body["placement_detail"]["final_weighted_congestion"] == 1.3255
    # ...and the clock-NDR half is untouched by the new section.
    assert body["clock_ndr_disabled"] is False

    cool = R._write_route_congestion_trades(
        tmp_path / "cool", None, SHA256_PLACE)
    cool_body = json.loads(cool.read_text())
    assert cool_body["placement_congestion"] is False
    assert cool_body["placement_detail"] == {}


def test_negctl_every_pnr_outcome_carries_the_pre_route_read():
    """NEG-CTL + wiring: the pre-route read must reach every routing outcome,
    exactly like the clock-NDR trade. The PASS paths matter most — that is
    where a design routed on borrowed margin used to go out silent."""
    src = inspect.getsource(R.step_pnr)
    tail = src[src.index('detail += f" | pdn:'):]
    assert "detail += _ndr_detail + _place_detail" in tail
    assert src.count("_place_detail") >= 7   # 1 definition + >=6 outcomes


# ── CASE A: the durable disclosure side-file ─────────────────────────────────

def test_negctl_trades_report_is_written_for_both_outcomes(tmp_path):
    """NEG-CTL: pre-fix no such report existed. It must be written even when
    the trade was NOT made, so the file's absence never needs interpreting."""
    traded = R._write_route_congestion_trades(
        tmp_path / "traded", R._clock_ndr_disclosure(IBEX_TAIL), IBEX_TAIL)
    body = json.loads(traded.read_text())
    assert traded.name == "route_congestion_trades.json"
    assert body["clock_ndr_disabled"] is True
    assert body["global_route_congestion_error"] is True
    assert body["detail"]["clock_tree_nets"] == ["clknet_0_clk_regs"]

    clean = R._write_route_congestion_trades(tmp_path / "clean", None, "")
    clean_body = json.loads(clean.read_text())
    assert clean_body["clock_ndr_disabled"] is False
    assert clean_body["detail"] == {}


# ── Wiring: the disclosure must reach EVERY routing outcome ──────────────────

def _step_pnr_ast():
    return ast.parse(textwrap.dedent(inspect.getsource(R.step_pnr)))


def test_negctl_every_pnr_outcome_after_the_route_carries_the_disclosure():
    """NEG-CTL: pre-fix NO pnr return mentioned the trade — least of all the
    PASS ones. Parsing the real source is what makes this a wiring guard and
    not just another parser unit test: a future edit that adds a routing
    outcome without the disclosure fails here."""
    tree = _step_pnr_ast()
    seen = 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Return)
                and isinstance(node.value, ast.Call)):
            continue
        call = node.value
        fn = call.func
        if not (isinstance(fn, ast.Name) and fn.id == "StepResult"):
            continue
        args = call.args
        if not (args and isinstance(args[0], ast.Constant)
                and args[0].value == "pnr"):
            continue
        rendered = ast.dump(call)
        if "_ndr_detail" not in rendered and "_ndr_extras" not in rendered:
            continue
        seen += 1
    # plateau, GRT-0116, generic rc!=0, ROUTE_NOT_CONVERGED, PDN BLOCKED,
    # PASS-with-resize, PASS — every outcome downstream of the route.
    assert seen >= 7, f"only {seen} pnr outcomes carry the disclosure"


def test_negctl_both_pass_returns_carry_the_disclosure():
    """The green path is the one that used to hide the trade. Guard it by
    itself so a refactor cannot quietly drop it from PASS while leaving the
    FAIL paths (which nobody was going to miss) intact."""
    src = inspect.getsource(R.step_pnr)
    tail = src[src.index('detail += f" | pdn:'):]
    assert tail.count('StepResult("pnr", "PASS"') == 2
    assert "detail += _ndr_detail" in tail


def test_pnr_route_runs_under_the_plateau_probe():
    """The abort only saves CPU if it is actually wired to the router call."""
    src = inspect.getsource(R.step_pnr)
    assert "_DrtPlateauProbe(_pnr_logp)" in src
    assert "abort_probe=_plateau_probe" in src
    assert "if rc == _RC_ABORTED:" in src


def test_plateau_abort_isolates_the_partial_def_then_loosens_or_stops():
    """A killed router leaves a mid-iteration DEF, which must be isolated like
    the hang path. The geometry is then loosened one ladder rung and retried;
    when the ladder is exhausted the loop stops. It must NEVER re-run the
    IDENTICAL geometry — that would replay the identical plateau."""
    src = inspect.getsource(R.step_pnr)
    body = src[src.index("if rc == _RC_ABORTED:"):]
    body = body[:body.index("if rc in (_RC_STALLED, 124):")]
    assert "_docker_timeout_isolate" in body
    assert "_route_feedback_loosen" in body
    assert "_rewrite_pnr_floorplan_die" in body    # geometry actually changes
    # the retry is guarded by the loosen returning dims; otherwise: stop
    assert body.index("continue") < body.rindex("break")


@pytest.mark.parametrize("finding", ["ROUTE_PLATEAU", "GLOBAL_ROUTE_CONGESTION"])
def test_new_findings_are_structured_not_log_tails(finding):
    src = inspect.getsource(R.step_pnr)
    assert f'"finding": "{finding}"' in src


# ── CASE A root cause: the loosen ladder was blind, then mis-stepped ─────────

def test_negctl_global_route_congestion_now_reaches_the_loosen_ladder():
    """NEG-CTL: pre-fix `_route_feedback_loosen` returned None whenever the
    route did not COMPLETE — and GRT-0116 aborts the OpenROAD script, so no
    routed DEF ever exists. The loudest congestion signal OpenROAD emits was
    the one that bought ZERO geometry relief; ibex burned 8036 s and got
    nothing. It must now loosen, exactly like a non-converged route."""
    out = R._route_feedback_loosen(
        459, 459, IBEX_TAIL, loosen_idx=0, auto_die_requested=True,
        route_completed=False, ladder=R._route_loosen_ladder(0.5))
    assert out is not None
    _w, _h, rec = out
    assert rec["trigger"] == "global_route_congestion"
    assert rec["direction"] == "loosen"
    # No detailed route ran, so there is no violation count to report.
    assert rec["final_violations"] is None
    assert rec["violation_trajectory"] == []


def test_negctl_loosen_ladder_is_anchored_to_the_die_that_was_built():
    """NEG-CTL: pre-fix the ladder head was hard-coded `_AUTO_DIE_TARGET_UTIL`
    (0.25) no matter what util the die was sized to. ibex adopts ORFS
    CORE_UTILIZATION=50 → the die is built at 0.5, so the first relief step was
    computed as 0.25→0.18 (1.18x) for a die that needed 0.5→0.25 (1.41x)."""
    assert R._route_loosen_ladder(0.5) == (0.5, 0.25, 0.18, 0.12)
    anchored = R._compute_loosened_die(459, 459, 0.5, 0.25)
    unanchored = R._compute_loosened_die(459, 459, 0.25, 0.18)
    assert anchored == (650, 650)
    assert unanchored == (541, 541)
    assert anchored[0] > unanchored[0]


def test_anchored_ladder_is_a_no_op_for_a_default_sized_die():
    """§4.05 no-drift: a die sized at the routing-headroom default must get
    BYTE-IDENTICALLY the ladder it got before anchoring."""
    assert R._route_loosen_ladder(R._AUTO_DIE_TARGET_UTIL) == \
        R._ROUTE_LOOSEN_UTIL_LADDER
    assert R._route_loosen_ladder(None) == R._ROUTE_LOOSEN_UTIL_LADDER
    assert R._route_loosen_ladder(0.0) == R._ROUTE_LOOSEN_UTIL_LADDER
    assert R._route_loosen_ladder(1.5) == R._ROUTE_LOOSEN_UTIL_LADDER


def test_anchored_ladder_never_breaches_the_floor():
    """A die already looser than the floor has nothing left to give: the
    ladder collapses to one rung, and one rung means no loosen at all."""
    ladder = R._route_loosen_ladder(0.10)
    assert ladder == (0.10,)
    assert R._route_feedback_loosen(
        900, 900, IBEX_TAIL, loosen_idx=0, auto_die_requested=True,
        route_completed=False, ladder=ladder) is None


def test_loosen_still_refuses_an_explicit_die_and_a_converging_route():
    """The guards that predate this change must still hold."""
    assert R._route_feedback_loosen(
        459, 459, IBEX_TAIL, loosen_idx=0, auto_die_requested=False,
        route_completed=False, ladder=R._route_loosen_ladder(0.5)) is None
    converging = _log_with([9000, 5000, 2000, 900])
    assert R._route_feedback_loosen(
        900, 900, converging, loosen_idx=0, auto_die_requested=True,
        route_completed=True, ladder=R._ROUTE_LOOSEN_UTIL_LADDER) is None


def test_negctl_plateau_abort_still_gets_its_looser_retry():
    """NEG-CTL (regression guard on the OTHER fix): a live abort that just
    `break`s would REGRESS the ladder — a run that used to complete, be judged
    non-converging and get a looser retry would now be killed and get nothing.
    The saving must come from truncating each attempt, not from dropping the
    recovery."""
    out = R._route_feedback_loosen(
        900, 900, _log_with(SYNTHETIC_FLAT_TAIL), loosen_idx=0,
        auto_die_requested=True, route_completed=False,
        ladder=R._ROUTE_LOOSEN_UTIL_LADDER, plateau_aborted=True)
    assert out is not None
    assert out[2]["trigger"] == "route_plateau_aborted"
    src = inspect.getsource(R.step_pnr)
    body = src[src.index("if rc == _RC_ABORTED:"):]
    body = body[:body.index("if rc in (_RC_STALLED, 124):")]
    assert "plateau_aborted=True" in body
    assert "_loosen_idx += 1" in body and "continue" in body


def test_die_target_util_has_one_resolver():
    """The sizer and the ladder must read the SAME precedence. Two copies is
    how they came to disagree (sizer 0.5 vs ladder 0.25) in the first place."""
    sizer = ast.parse(textwrap.dedent(
        inspect.getsource(R._resolve_auto_die_um)))
    called = {n.func.id for n in ast.walk(sizer)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_resolve_die_target_util" in called
    # the precedence itself must live in ONE place, not be re-implemented here
    assert "_l9_declared_die_util" not in called
    assert "_reference_flow_declared_die_util" not in called
    assert R._resolve_die_target_util(None) == (
        R._AUTO_DIE_TARGET_UTIL, "routing-headroom-default")


def test_retry_budget_still_bounds_the_anchored_ladder():
    """The anchored ladder can carry one extra rung; the loop's hard cap must
    still cover every mutation path."""
    longest = len(R._route_loosen_ladder(0.99))
    assert longest == len(R._ROUTE_LOOSEN_UTIL_LADDER) + 1
    assert R._PNR_RETRY_ITERS >= 1 + R._PNR_UPSIZE_RETRIES + 1 + (longest - 1)
