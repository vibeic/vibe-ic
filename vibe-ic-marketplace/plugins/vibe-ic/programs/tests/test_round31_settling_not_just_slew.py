"""Slewing to the answer and settling on it are different questions.

MEASURED (round 31, on the emitted netlist at OSR 64, v1.16.72). The loop
filter's output moves 0.285 V within every clock and comes back to the SAME
range over eight consecutive clocks -- 0.4571..0.7427 in one clock and
0.4571..0.7427 across eight. No net accumulation. vsum2 and vint swing
together with their difference fixed at 0.011 V, so the integrating capacitor
never changes charge: the virtual ground is not a virtual ground, and the
charge cf2 commutates each clock lands on the summing node's own capacitance
instead of on ci.

    gm  = 697 uS   (at the operating point)
    ci  = 9.49 pF
    tau = 13.6 ns  against 25 ns of usable settling = 1.8 constants,
                   where settling to the declared resolution needs about 7

The incremental coefficient derivation grew ci about 90x (6.949 um -> 629 um)
and the amplifier that drives it did not grow with it. `slew_margin` already
guards the LARGE-signal case and passes at 2.0; it says nothing about whether
the loop then settles.

AND THE CHECK MUST BE EVALUATED AT THE CLOCK THE CIRCUIT RUNS AT. This entry's
own testbench runs the modulator at the fastest rate the declaration admits.
Checked at the 1.0 MHz `fclk` target the margin reads 13.3 and passes; at the
10 MHz `fclk_max` the simulation uses it reads 1.3, and the measurement agrees.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analog_a2_topology_emit as m  # noqa: E402

CONSTS_EXTRA = {"kt_j_300k": 4.141947e-21, "cap_area_ff_per_um2": 2.00009,
                "rsheet_ohm_per_sq": 260.0, "vth_n_extracted_v": 0.5}


def _entry():
    for name in dir(m):
        v = getattr(m, name)
        if isinstance(v, dict) and "delta_sigma" in v:
            c = v["delta_sigma"]
            if isinstance(c, dict) and "circuit_class_citation" in c:
                return c
    raise AssertionError("delta_sigma entry not found")


def _spec(name):
    for s in _entry()["requires_derived"]:
        if s["name"] == name:
            return s
    return None


def _env(**kw):
    e = {"order": 2, "osr": 64, "vref": 1.0, "vdd": 1.2, "enob": 14,
         "fclk": 1.0, "fclk_max": 10.0}
    e.update(_entry()["constants"])
    e.update(CONSTS_EXTRA)
    e.update(kw)
    return e


def _val(name, **kw):
    return eval(_spec(name)["expr"], {"__builtins__": {}}, _env(**kw))


def test_a_settling_bound_exists_at_all():
    s = _spec("settling_time_constants")
    assert s is not None, (
        "only slew is bounded; an amplifier can slew to the answer and never "
        "settle on it")
    assert s["min"] >= 7.0


def test_it_is_evaluated_at_the_clock_the_testbench_uses():
    """THE CONTROL that stops it being a check that cannot fail: at the 1.0
    MHz target it reads 13.3 and passes, at the 10 MHz the emitted testbench
    actually runs it reads 1.3."""
    expr = _spec("settling_time_constants")["expr"]
    assert "fclk_max" in expr, "evaluated at the target, not the worst case"
    assert _val("settling_time_constants") < 2.0
    # and the target-clock reading really would have passed
    slow = expr.replace("fclk_max", "fclk")
    assert eval(slow, {"__builtins__": {}}, _env()) > 7.0


def test_it_refuses_this_declaration_and_that_is_the_point():
    s = _spec("settling_time_constants")
    assert _val("settling_time_constants") < s["min"], (
        "the measured circuit does not settle -- 1.8 constants -- so a bound "
        "that admits it is not measuring anything")


def test_it_admits_a_declaration_that_can_settle():
    """The anti-vacuity control: a slower clock leaves time to settle, and the
    bound must then PASS. A bound that refuses everything refuses the bug."""
    assert _val("settling_time_constants", fclk_max=1.0) > 7.0


def test_slew_and_settling_disagree_here_which_is_why_both_are_needed():
    assert _val("slew_margin") >= _spec("slew_margin")["min"]
    assert _val("settling_time_constants") < _spec("settling_time_constants")["min"]


def test_the_shipped_library_still_holds_its_own_invariants():
    assert m.library_invariants() == []
