"""A clocked regenerative latch has no state until something defines one.

MEASURED (round 22, the repaired quantiser on its own bench with ideal
differential sources, 349 ns, four evaluate phases in):

    vid = -40 mV, `tran ... uic`   -> decides POSITIVE   (wrong)
    vid = -40 mV, `tran ...`       -> decides NEGATIVE   (right)

With `uic` the transient starts from UNSOLVED node voltages, the latch
regenerates on them, and the set-reset latch downstream HOLDS that decision
into every following cycle. The apparent 42.5 mV input-referred offset that
round 21 left open is that artefact, not the circuit: bisected, the `uic`
trip point sits between -40 and -45 mV while the solved-start deck decides
correctly at -40 mV.

Checked by run before the change: the full 260-device loop converges its own
`.op` with zero convergence errors, so dropping `uic` costs nothing.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analog_a2_topology_emit as m  # noqa: E402


def _entry():
    for name in dir(m):
        v = getattr(m, name)
        if isinstance(v, dict) and "delta_sigma" in v:
            c = v["delta_sigma"]
            if isinstance(c, dict) and "circuit_class_citation" in c:
                return c
    raise AssertionError("delta_sigma entry not found")


def _tb_control():
    tb = _entry().get("testbench") or {}
    ctl = tb.get("control")
    if ctl is None:
        for v in _entry().values():
            if isinstance(v, dict) and "control" in v:
                ctl = v["control"]
                break
    assert ctl, "no testbench control found"
    return list(ctl)


def test_the_transient_does_not_start_from_an_unsolved_state():
    tran = [c for c in _tb_control() if c.lstrip().startswith("tran")]
    assert tran, "no tran card"
    for c in tran:
        assert "uic" not in c.split("#")[0], (
            f"`uic` is back in {c!r}: the quantiser latch will resolve on "
            f"unsolved initial voltages and the SR latch will hold it")


def test_the_transient_card_still_exists_and_is_parameterised():
    # the control that keeps this from passing by deleting the card
    tran = [c for c in _tb_control() if c.lstrip().startswith("tran")]
    assert len(tran) == 1, tran
    assert "{tstep_ns}" in tran[0] and "{tstop_ns}" in tran[0]


def test_the_measurement_window_is_still_the_second_one():
    # an incremental converter's first window is not a conversion; dropping
    # uic must not have disturbed which window is graded
    ctl = " ".join(_tb_control())
    assert "{tmeas_ns}" in ctl and "{twin2_ns}" in ctl
