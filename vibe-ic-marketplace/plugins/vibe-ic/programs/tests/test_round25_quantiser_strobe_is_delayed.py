"""The latch must not begin evaluating on the edge the switches fire on.

MEASURED (round 25, OSR 64, five inputs, one full conversion window each).
A StrongARM commits within ~1.5 ns of its tail turning on. Strobed directly
by `nclkb` it began evaluating on the very edge the sampling and DAC switches
fire on, and at that instant the differential it was handed was a
clock-injection transient rather than the signal:

    offset from the tail turning on    nqz - vcm, window mean
      1.5 ns    +0.098 .. +0.153 V at EVERY input, sign 63/63
     40   ns    -0.033 .. +0.033 V, and it varies with the input

The transient is 3-5x the signal and identical at every input, so the
decision carried no information about the input at all. The loop filter was
never the problem: vint's window mean is monotone in the input, 0.5668 ->
0.6122 V over vin 0.30 -> 0.70, about 11.4 mV per 100 mV.

PHASE, not settling budget: the signal is present before the edge and present
again after it, and only the 1-3 ns around the edge is corrupted.
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


def _dev(name):
    for d in _entry()["devices"]:
        if d.get("name") == name:
            return d
    return None


def test_the_tail_is_not_strobed_by_the_raw_clock_phase():
    tail = _dev("mn_qtail")
    assert tail is not None
    assert tail["nets"][1] not in ("clk", "nclkb"), (
        "the latch would commit inside the clock edge's own injection "
        "transient")


def test_the_delay_exists_and_is_a_real_load_not_a_bare_inverter_pair():
    # two minimum inverters are ~100 ps; the measured transient decays over
    # nanoseconds, so the delay has to be a LOAD someone sized
    for n in ("mp_qdly1", "mn_qdly1", "mp_qdly2", "mn_qdly2", "c_qdly"):
        assert _dev(n) is not None, n
    cap = _dev("c_qdly")
    assert cap["role"] == "cap"
    assert cap["nets"][0] == _dev("mp_qdly1")["nets"][0], (
        "the delay capacitor must load the FIRST stage's output")


def test_the_delay_chain_restores_the_phase_it_was_given():
    # an odd number of inversions would strobe on the sampling phase instead
    s1_out = _dev("mp_qdly1")["nets"][0]
    assert _dev("mp_qdly2")["nets"][1] == s1_out
    assert _dev("mn_qtail")["nets"][1] == _dev("mp_qdly2")["nets"][0]


def test_the_first_stage_is_weak_and_the_second_is_not():
    # the delay comes from a weak stage driving a big load; a strong first
    # stage would make the capacitor decorative
    w1 = _dev("mp_qdly1")["w"]
    w2 = _dev("mp_qdly2")["w"]
    assert w1 < w2, (w1, w2)


def test_the_shipped_library_still_holds_its_own_invariants():
    assert m.library_invariants() == []
