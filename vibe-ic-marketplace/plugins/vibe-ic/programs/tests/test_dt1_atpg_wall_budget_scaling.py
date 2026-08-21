"""Size-scaled at-speed (DT1 transition) ATPG wall budget.

REGRESSION for the DFT at-speed ATPG docker-command TIMEOUT that blocked large
designs (measured: subservient×GF180MCU, 1272 scan flops) from a real DT1
verdict. The old producer used a FIXED wall (1800 s) for BOTH the calibration
probe and the real batch, which on a large design:

  (a) right-sized the graded sample down to a small strided slice (~57 of the
      400-fault disclosed sample) — a starved sample; and
  (b) under host contention let the fixed calibration ceiling kill the one-time
      miter flatten before it emitted the setup marker → yosys exit 124,
      setup_done=False → a false hard ERROR (a timeout, not a coverage number).

The fix makes the wall AND the calibration setup-allowance SCALE with the
design's OWN measured scale (the scan-flop count the cut exposed), chip/PDK/
vendor-AGNOSTICally (keyed only on flop count, never on a chip/SKU/library
literal). These tests pin the scaling helpers, the measured 1272-flop case, and
the wiring into run_tdf_atpg.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
SCRIPT = PROG / "transition_fault_atpg_run.py"
assert SCRIPT.exists()

sys.path.insert(0, str(PROG))
import transition_fault_atpg_run as tdf  # noqa: E402

_SRC = SCRIPT.read_text()

# The measured reference design (kept as a bare number, NOT a chip name — the
# logic is chip-agnostic; this constant is only the scale we measured against).
_MEASURED_SCAN_FLOPS = 1272
_OLD_FIXED_WALL = 1800


# ── _scaled_wall_budget ──────────────────────────────────────────────────────

def test_wall_zero_or_negative_flops_is_floor():
    assert tdf._scaled_wall_budget(1800, 0) == 1800
    assert tdf._scaled_wall_budget(1800, -5) == 1800


def test_wall_never_below_floor():
    for flops in (0, 1, 10, 65, 500, 1272, 10_000):
        assert tdf._scaled_wall_budget(1800, flops) >= 1800


def test_wall_monotonic_non_decreasing_in_flops():
    prev = -1
    for flops in range(0, 6000, 137):
        w = tdf._scaled_wall_budget(1800, flops)
        assert w >= prev
        prev = w


def test_wall_capped_at_max():
    # a very large design cannot run away — the wall saturates at the ceiling.
    assert tdf._scaled_wall_budget(1800, 1_000_000) == tdf.WALL_BUDGET_MAX
    assert tdf._scaled_wall_budget(1800, 10_000) <= tdf.WALL_BUDGET_MAX


def test_wall_scales_with_measured_1272_flop_case():
    w = tdf._scaled_wall_budget(_OLD_FIXED_WALL, _MEASURED_SCAN_FLOPS)
    # materially larger than the old fixed wall (the starved-sample failure (a))
    assert w > _OLD_FIXED_WALL * 1.5
    # and exactly floor + per-flop term while still under the cap
    expected = min(tdf.WALL_BUDGET_MAX,
                   _OLD_FIXED_WALL + tdf.WALL_PER_SCAN_FLOP * _MEASURED_SCAN_FLOPS)
    assert w == int(expected)


def test_wall_floor_is_honoured_when_caller_raises_timeout():
    # --timeout is the FLOOR: a caller-raised floor is never lowered by scaling.
    assert tdf._scaled_wall_budget(6000, 0) == 6000
    assert tdf._scaled_wall_budget(6000, 100) >= 6000


# ── _scaled_setup_allowance ──────────────────────────────────────────────────

def test_setup_allowance_floor_and_growth():
    assert tdf._scaled_setup_allowance(0) == tdf.SETUP_ALLOWANCE_FLOOR
    assert tdf._scaled_setup_allowance(-3) == tdf.SETUP_ALLOWANCE_FLOOR
    # grows with flops
    assert (tdf._scaled_setup_allowance(2000)
            > tdf._scaled_setup_allowance(200)
            > tdf._scaled_setup_allowance(0))


def test_setup_allowance_covers_a_large_miter_flatten():
    # The fixed 60 s allowance was what let a large flatten get SIGTERM'd
    # (exit 124, setup_done=False). For the measured 1272-flop design the scaled
    # allowance must clear a realistic large-miter flatten by a wide margin.
    allow = tdf._scaled_setup_allowance(_MEASURED_SCAN_FLOPS)
    assert allow > 300
    assert allow == int(tdf.SETUP_ALLOWANCE_FLOOR
                        + tdf.SETUP_ALLOWANCE_PER_SCAN_FLOP * _MEASURED_SCAN_FLOPS)


# ── behavioural: the scaled wall un-starves the graded sample ────────────────

def test_scaled_wall_grades_more_faults_than_fixed_wall():
    # measured on subservient×GF180MCU: per-fault SAT ~25 s, setup ~8 s.
    per_fault, setup = 25.0, 8.0
    hard_cap, total = 400, 20_000
    fixed_wall = _OLD_FIXED_WALL
    scaled_wall = tdf._scaled_wall_budget(_OLD_FIXED_WALL, _MEASURED_SCAN_FLOPS)

    n_fixed = tdf._rightsize_sample(per_fault, setup, fixed_wall, hard_cap, total)
    n_scaled = tdf._rightsize_sample(per_fault, setup, scaled_wall, hard_cap, total)

    # the fixed wall starved the sample (a small slice); the scaled wall grades
    # materially more — the whole point of the fix.
    assert n_fixed < 80          # the old ~57-fault slice regime
    assert n_scaled >= 2 * n_fixed
    assert n_scaled <= hard_cap  # still bounded by the disclosed --max-faults


def test_small_design_is_unchanged_no_regression():
    # A small design keeps (essentially) the floor wall and grades its full
    # affordable sample exactly as before — no behavioural regression.
    assert tdf._scaled_wall_budget(1800, 40) - 1800 <= tdf.WALL_PER_SCAN_FLOP * 40 + 1
    per_fault, setup = 2.0, 1.0
    n = tdf._rightsize_sample(per_fault, setup,
                              tdf._scaled_wall_budget(1800, 40), 400, 300)
    assert n == 300  # tiny design → full sample fits well within the wall


# ── wiring: run_tdf_atpg must use the scaled wall / setup-allowance ──────────

def test_source_wires_scaled_wall_into_producer():
    assert "_scaled_wall_budget(timeout, scan_flops)" in _SRC
    # calibration wall uses the scaled setup-allowance, not a bare fixed 60 s
    assert "_scaled_setup_allowance(scan_flops)" in _SRC
    # the real-batch budget is the scaled wall, not the raw --timeout
    assert "remaining = wall - cal_elapsed" in _SRC
    # and the old fixed-ceiling forms are gone
    assert "cal_wall = min(timeout // 3, 60 + cal_n * sat_timeout)" not in _SRC
    assert "remaining = timeout - cal_elapsed" not in _SRC


# ── partial-output SALVAGE on docker wall (the exit-124 ERROR root cause) ─────

def test_as_text_coerces_bytes_str_none():
    assert tdf._as_text(None) == ""
    assert tdf._as_text("abc") == "abc"
    assert tdf._as_text(b"ab\xffc") == "ab�c"  # replace undecodable byte


def test_run_in_docker_salvages_partial_stdout_on_timeout(monkeypatch, tmp_path):
    # The OLD code returned (124, "", "docker command timed out") on the wall,
    # DISCARDING the completed-fault prefix yosys had already printed → the
    # false "ATPG produced no gradeable verdicts (yosys exit 124,
    # setup_done=False)" ERROR that blocked large designs. The fix must return
    # the partial stdout so the completed prefix can still be graded.
    partial = ("VIBEICTDF_SETUP_DONE\n"
               "VIBEICTDF _001_ STR\nsat: model found: FAIL!\n"
               "VIBEICTDF _002_ STF\n")  # 2nd fault cut mid-solve
    calls = {"n": 0}

    def fake_run(cmd, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            # the `docker run` invocation → wall fires with partial output
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout", 1),
                                            output=partial, stderr="")
        # the `docker rm -f` reap invocation → succeeds
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(tdf.subprocess, "run", fake_run)
    ec, out, err = tdf._run_in_docker(tmp_path, "yosys /work/x.ys", timeout=1)
    assert ec == 124
    assert "VIBEICTDF_SETUP_DONE" in out          # setup marker survives
    assert "VIBEICTDF _001_ STR" in out           # completed fault survives
    assert "docker command timed out" in err
    # the container was reaped (a second subprocess.run call for `docker rm -f`)
    assert calls["n"] == 2


def test_salvaged_partial_log_grades_completed_prefix():
    # Given a SALVAGED partial batch log (setup done, 1 fault detected, 1 cut
    # mid-solve, 2 never reached), the parser must grade the completed prefix
    # and mark the rest ABORT/UNREACHED — never crash, never lose the graded
    # faults. This is what converts the exit-124 ERROR into a real verdict.
    log = ("VIBEICTDF_SETUP_DONE\n"
           "VIBEICTDF _001_ STR\nsat: model found: FAIL!\n"
           "VIBEICTDF _002_ STF\n")  # marker printed, solve truncated
    faults = [("\\_001_", "STR", "1'b0", "1'b0"),
              ("\\_002_", "STF", "1'b1", "1'b0"),
              ("\\_003_", "STR", "1'b0", "1'b0"),
              ("\\_004_", "STF", "1'b1", "1'b0")]
    results, _example, setup_done = tdf._parse_batch_log(log, faults, [])
    assert setup_done is True
    verdicts = {n: v for n, _k, v in results}
    assert verdicts["_001_"] == "DET"        # completed + detected
    assert verdicts["_002_"] == "ABORT"      # marker present, solve truncated
    assert verdicts["_003_"] == "UNREACHED"  # never reached → excluded by caller
    assert verdicts["_004_"] == "UNREACHED"
    # the graded (non-UNREACHED) prefix is non-empty → NOT a false-ERROR
    graded = [v for v in verdicts.values() if v != "UNREACHED"]
    assert graded and "DET" in graded
