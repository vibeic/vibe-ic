"""`slew_margin` cannot fail on a design's numbers, and the clock mismatch is
somewhere else.

MEASURED (round 33, v1.16.88 / 626809984241). Round 31 found a settling bound
evaluated at `fclk` (the 1.0 MHz target) while the emitted testbench runs at
`fclk_max` (10 MHz), and listed `slew_margin` as having the same shape. It does
read `fclk` -- and changing it to `fclk_max` changes NOTHING, because the bound
is identically `slew_design_margin` for every declaration:

    fclk   r_ib_l_um   I_tail      C_load     slew_margin
     0.1    150.889     9.81 uA   12.267 pF     2.0000
     1.0     15.089    98.14      12.267        2.0000
    10.0      1.509   981.37      12.267        2.0000

`fclk` appears once in the time available (1/fclk) and once inside the bias
length this entry derives FROM the slew requirement (v1.16.10), so
I_tail proportional-to fclk cancels it exactly.

The mismatch is real but it is in the BIAS derivation, not here: the entry
binds fclk_max, builds every testbench time from fclk_max, and sizes the
circuit from fclk. That is recorded beside `bias_resistor_l_um` and is
deliberately not changed -- it multiplies the tail current by ten and lands on
an open design decision.
"""
import re
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


def _spec(n):
    for s in _entry()["requires_derived"]:
        if s["name"] == n:
            return s
    raise AssertionError(n)


def _env(**kw):
    e = {"order": 2, "osr": 64, "vref": 1.0, "vdd": 1.2, "enob": 14,
         "fclk": 1.0, "fclk_max": 10.0}
    e.update(_entry()["constants"])
    e.update({"kt_j_300k": 4.141947e-21, "cap_area_ff_per_um2": 2.00009,
              "rsheet_ohm_per_sq": 260.0, "vth_n_extracted_v": 0.5})
    e.update(kw)
    return e


def _v(expr, **kw):
    return eval(expr, {"__builtins__": {}}, _env(**kw))


def test_slew_margin_is_the_design_margin_constant_at_every_clock():
    """FORWARD control: the value at the clock the testbench really uses."""
    e = _spec("slew_margin")["expr"]
    k = _entry()["constants"]["slew_design_margin"]
    for f in (0.1, 1.0, 10.0):
        assert abs(_v(e, fclk=f) - k) < 1e-9, (f, _v(e, fclk=f))


def test_reading_fclk_max_instead_changes_nothing():
    """REVERSE control, and the reason the obvious fix is not made: swapping
    the symbol must reproduce the SAME number, which proves the change would
    not change the judgement."""
    e = _spec("slew_margin")["expr"]
    swapped = e.replace("fclk", "fclk_max")
    assert abs(_v(e) - _v(swapped)) < 1e-9
    assert abs(_v(swapped, fclk_max=10.0) - _v(e, fclk=1.0)) < 1e-9


def test_it_admits_every_declaration_which_is_the_defect_not_a_pass():
    """THIRD control, inverted from the usual one. The worry with a bound is
    that it refuses everything; this one ACCEPTS everything, at any clock,
    order, osr, vref or supply. A bound whose value no declaration can move is
    not measuring the declaration."""
    lo = _spec("slew_margin")["min"]
    e = _spec("slew_margin")["expr"]
    for kw in ({"fclk": 10.0}, {"osr": 512}, {"order": 1}, {"vref": 0.8},
               {"vdd": 1.3}, {"enob": 10}, {"fclk": 0.1, "osr": 64}):
        assert _v(e, **kw) >= lo, kw
        assert abs(_v(e, **kw) - _v(e)) < 1e-9, (kw, _v(e, **kw))


def test_it_still_catches_the_regression_it_is_kept_for():
    """It is not deleted because it DOES move when the load expression and the
    bias derivation are edited APART -- which is a real regression.

    The load expression appears TWICE in this bound: once as the load being
    slewed, and once inside the bias length derived from it. Scaling BOTH
    cancels (measured: 2.0 -> 2.0), which is exactly the invariance that makes
    the bound a constant. Scaling ONE is the drift it can still see."""
    e = _spec("slew_margin")["expr"]
    both = e.replace(m._LOAD_F_EXPR, "(" + m._LOAD_F_EXPR + ") * 3.0")
    assert abs(_v(both) - _v(e)) < 1e-9, "a common change must cancel"
    i = e.rfind(m._LOAD_F_EXPR)
    assert i >= 0
    one = e[:i] + "(" + m._LOAD_F_EXPR + ") * 3.0" + e[i + len(m._LOAD_F_EXPR):]
    assert abs(_v(one) - _v(e)) > 1e-6, "a divergent change must be visible"
    assert _v(one) < _spec("slew_margin")["min"], (
        "and it must actually breach the bound, or the check is decorative")


def test_the_testbench_and_the_circuit_read_different_clocks():
    """The mismatch this round was sent to find, pinned where it really is."""
    tb = _entry()["testbench"]
    times = {k: v for k, v in (tb.get("values") or tb).items()
             if isinstance(v, str) and ("tper_ns" in k or "tstop_ns" in k
                                        or "tmeas_ns" in k or "thigh_ns" in k)}
    if not times:
        src = Path(m.__file__).read_text()
        times = {k: v for k, v in
                 re.findall(r'"(t(?:per|high|stop|meas)_ns)":\s*"([^"]+)"', src)}
    assert times, "no testbench time parameters found"
    for k, v in times.items():
        assert "fclk_max" in v, (k, v)
    # ...while the circuit is sized from `fclk`
    assert "fclk_max" not in m._R_IB_L_UM_EXPR
    assert "fclk" in m._R_IB_L_UM_EXPR
    # and the entry BINDS fclk_max, so the two are not even the same declared row
    assert "fclk_max" in _entry()["requires_bound"]


def test_the_shipped_library_still_holds_its_own_invariants():
    assert m.library_invariants() == []
