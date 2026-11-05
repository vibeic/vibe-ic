"""v1.3.48 — the SECOND face of the watchdog primitive (`loop_guard`) + the

Owner directive: "let watchdog be the common process for loop in the vibe-ic
plugin; force AI to use such watchdog for any loop." Two halves:

  * loop_guard — a bounded, no-progress-aware driver for an IN-PROCESS
    convergence / poll / retry loop. Proven here: converges-early,
    hits-max_iter, breaks-on-no-progress, single-shot, progress-keeps-alive,
    deterministic (injected clock → ms).
"""
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import _watchdog as W  # noqa: E402


# ── loop_guard behaviours ────────────────────────────────────────────────
def test_loop_guard_hits_max_iter():
    g = W.loop_guard("x", max_iter=5)
    seen = [i for i in g]
    assert seen == [0, 1, 2, 3, 4]
    assert g.reason == "max_iter"
    assert g.iterations == 5


def test_loop_guard_single_shot():
    g = W.loop_guard("once", max_iter=1)
    seen = [i for i in g]
    assert seen == [0]
    assert g.reason == "max_iter"
    assert g.iterations == 1


def test_loop_guard_converges_early_on_break():
    g = W.loop_guard("conv", max_iter=100)
    for i in g:
        if i == 2:
            break
    assert g.reason == "converged"
    assert g.iterations == 3          # yielded 0,1,2


def test_loop_guard_breaks_on_no_progress():
    """progress_fn plateaus → after `stall_iters` consecutive non-improving
    iterations the guard stops with reason 'stalled', well before max_iter."""
    g = W.loop_guard("stall", max_iter=50, stall_iters=3,
                     progress_fn=lambda: 7.0)     # never improves
    count = sum(1 for _ in g)
    assert g.reason == "stalled"
    # baseline primed at 7.0; iters 1,2,3 each fail to improve → stop after 3.
    assert count == 3
    assert g.iterations == 3


def test_loop_guard_progress_keeps_it_alive_to_max_iter():
    state = {"p": 0.0}

    def prog():
        state["p"] += 1.0            # strictly increasing → always progress
        return state["p"]

    g = W.loop_guard("live", max_iter=6, stall_iters=2, progress_fn=prog)
    count = sum(1 for _ in g)
    assert count == 6
    assert g.reason == "max_iter"    # never stalled — progress each iteration


def test_loop_guard_stalls_after_progress_then_plateau():
    seq = iter([1.0, 2.0, 3.0] + [3.0] * 20)   # improves 3x then plateaus

    def prog():
        return next(seq)

    g = W.loop_guard("mix", max_iter=50, stall_iters=2, progress_fn=prog)
    n = sum(1 for _ in g)
    assert g.reason == "stalled"
    # baseline primed at 1.0; loop improves at iters 0,1 (→2.0,3.0), then 2 flat
    # readings (iters 2,3) trip stall_iters=2 → stops after yielding 0,1,2,3.
    assert n == 4


def test_loop_guard_none_progress_carried_forward_not_progress():
    seq = iter([None, 5.0, None, 5.0, None, 5.0, None])

    def prog():
        return next(seq, 5.0)

    # after the first real reading (5.0) the value never improves; None must
    # NOT count as progress → it stalls.
    g = W.loop_guard("noneflap", max_iter=50, stall_iters=3, progress_fn=prog)
    for _ in g:
        pass
    assert g.reason == "stalled"


def test_loop_guard_injectable_clock_records_elapsed():
    ticks = iter([100.0, 137.0])
    g = W.loop_guard("clk", max_iter=2, clock=lambda: next(ticks))
    for _ in g:
        pass
    assert g.elapsed_s == 37.0


def test_loop_guard_rejects_bad_max_iter():
    with pytest.raises(ValueError):
        list(W.loop_guard("bad", max_iter=0))
    with pytest.raises(ValueError):
        list(W.loop_guard("bad", max_iter=3, stall_iters=0))


def test_loop_guard_stopped_early_property():
    g1 = W.loop_guard("a", max_iter=3)
    for i in g1:
        if i == 0:
            break
    assert g1.stopped_early is False          # caller converged
    g2 = W.loop_guard("b", max_iter=2)
    list(g2)
    assert g2.stopped_early is True           # hit the cap
