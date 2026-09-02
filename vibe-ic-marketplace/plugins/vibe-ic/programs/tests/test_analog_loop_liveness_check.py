"""A null over a dead loop must not be reported as a null.

Rounds 18-20 closed TWO mechanisms on nulls measured over windows in which the
loop never closed, and both had to be reopened. These tests pin the shape that
stops it: the gate is fail-closed on liveness, it names WHICH condition failed,
and — the control that matters — it still reports the trend when the loop IS
live, because a gate that refuses everything is not a gate.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analog_loop_liveness_check import assess  # noqa: E402

PROG = Path(__file__).resolve().parents[1] / "analog_loop_liveness_check.py"
N = 400


def _t():
    return [i * 1e-9 for i in range(N)]


def _square(period, lo=0.0, hi=1.2, n=N):
    return [hi if (i // period) % 2 else lo for i in range(n)]


def _pinned(v=1.1, n=N):
    return [v] * n


def _released(n=N):
    # reset asserted for the first 5%, released after
    return [1.2 if i < n // 20 else 0.0 for i in range(n)]


def _ramp(a, b, n=N):
    return [a + (b - a) * i / (n - 1) for i in range(n)]


def _base(dac, decision, reset=None, measure=None):
    s = {"t": _t(), "rst": reset or _released(), "dac": dac, "dec": decision}
    s["m"] = measure if measure is not None else _ramp(0.0, 0.1)
    return s


def _run(s, **kw):
    return assess(s, reset="rst", dac="dac", decision="dec", measure="m", **kw)


def test_a_pinned_dac_is_NOT_MEASURED_and_says_so():
    # round 19's circuit: the loop looks closed on the schematic and the DAC
    # never moves, so nothing it does depends on the loop's state
    out = _run(_base(_pinned(), _square(4)))
    assert out["result"] == "NOT_MEASURED"
    assert "feedback_switching=DEAD" in out["reason"]
    assert "certifies nothing" in out["reason"]


def test_the_withheld_measurement_is_not_reported():
    # THE POINT. A number here would be the vacuous pass.
    out = _run(_base(_pinned(), _square(4), measure=_ramp(0.0, 0.5)))
    assert "measure" not in out
    assert "measurement_withheld" in out


def test_a_reset_never_released_is_NOT_MEASURED():
    out = _run(_base(_square(8), _square(4), reset=[1.2] * N))
    assert out["result"] == "NOT_MEASURED"
    assert "reset_released=DEAD" in out["reason"]


def test_a_quantiser_that_never_leaves_precharge_is_NOT_MEASURED():
    out = _run(_base(_square(8), _pinned(1.2)))
    assert out["result"] == "NOT_MEASURED"
    assert "decision_resolving=DEAD" in out["reason"]


def test_a_live_loop_IS_measured_and_the_trend_comes_back():
    # THE ANTI-VACUITY CONTROL. Everything above is a refusal; if the gate
    # cannot pass a live window it has not distinguished anything.
    out = _run(_base(_square(8), _square(4), measure=_ramp(0.0, 0.1)))
    assert out["result"] == "LIVE"
    assert out["measure"]["net_drift"] > 0.05
    assert out["measure"]["node"] == "m"


def test_a_live_loop_with_no_trend_reports_the_flat_null_honestly():
    # a null IS evidence once the loop is live — the gate must not suppress it
    out = _run(_base(_square(8), _square(4), measure=[0.03] * N))
    assert out["result"] == "LIVE"
    assert abs(out["measure"]["net_drift"]) < 1e-9


def test_every_failing_condition_is_named_not_just_the_first():
    out = _run(_base(_pinned(), _pinned(1.2), reset=[1.2] * N))
    for c in ("reset_released", "feedback_switching", "decision_resolving"):
        assert f"{c}=DEAD" in out["reason"], out["reason"]


def test_an_undeclared_node_cannot_establish_liveness():
    # silence is not liveness: a condition nobody named is NOT_DECLARED
    out = assess(_base(_square(8), _square(4)), reset="rst", dac="dac",
                 measure="m")
    assert out["result"] == "NOT_MEASURED"
    assert "decision_resolving=NOT_DECLARED" in out["reason"]


def test_a_named_but_absent_node_is_ABSENT_not_live():
    out = assess(_base(_square(8), _square(4)), reset="rst", dac="dac",
                 decision="nope", measure="m")
    assert "decision_resolving=ABSENT" in out["reason"]


def test_the_cli_exit_codes_separate_dead_from_live(tmp_path):
    for samples, want in ((_base(_pinned(), _square(4)), 2),
                          (_base(_square(8), _square(4)), 0)):
        p = tmp_path / "s.json"
        p.write_text(json.dumps(samples))
        cp = subprocess.run(
            [sys.executable, str(PROG), "--samples-json", str(p),
             "--reset-node", "rst", "--dac-node", "dac",
             "--decision-node", "dec", "--measure-node", "m"],
            capture_output=True, text=True)
        assert cp.returncode == want, cp.stdout


def test_an_active_low_reset_is_read_the_right_way_round():
    # rounds 18/19 read a reset node with the polarity reversed and reported
    # a duty of 1/256 for a signal asserted 255/256 of the time
    lo_active = [0.0 if i < N // 20 else 1.2 for i in range(N)]
    out = assess(_base(_square(8), _square(4), reset=lo_active),
                 reset="rst", dac="dac", decision="dec", measure="m",
                 reset_active_high=False)
    assert out["result"] == "LIVE"
    out2 = _run(_base(_square(8), _square(4), reset=[0.0] * N))
    assert out2["result"] == "LIVE"          # active-high, never asserted


def test_the_feedback_occupancy_is_reported_so_a_near_pinned_window_is_visible():
    # MEASURED: a real window whose DAC sat at one reference 98.6% of the
    # time passed on edges and span alone. It is still LIVE — a converter
    # near full scale looks the same — but a reader must be able to SEE it.
    rare = [0.0] * (N - 6) + [1.2] * 6          # ~1.5% in the high state
    out = _run(_base(rare, _square(4)))
    assert out["result"] == "LIVE"
    fb = [c for c in out["conditions"]
          if c["condition"] == "feedback_switching"][0]
    assert fb["low_state_fraction"] > 0.95


def test_occupancy_is_not_a_threshold():
    # the control: a near-pinned-but-switching window must NOT be refused,
    # because a legitimate near-full-scale input produces exactly that
    for hi_n in (2, 6, 40, N // 2, N - 6):
        v = [0.0] * (N - hi_n) + [1.2] * hi_n
        assert _run(_base(v, _square(4)))["result"] == "LIVE", hi_n
