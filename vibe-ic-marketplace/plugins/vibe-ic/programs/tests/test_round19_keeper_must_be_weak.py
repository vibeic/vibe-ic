"""ROUND 19 — a latch keeper must be WEAK against the path that writes it.

MEASURED (u_hawaii_adc / ihp-sg13g2). The counter's master and slave keepers
were drawn at the forward inverter's own geometry — a SYMMETRIC back-to-back
latch. It could not be written. Over 254 clocks the master node tracked the
CLOCK rather than the data, reverting to the keeper's state each time the pass
gate closed; the slave therefore sampled the same value on every edge and `q1`
never toggled once. With the counter frozen at all-ones the decode was
satisfied permanently, `nall` averaged 1.19999 V of a 1.2 V supply, and both
integrators sat in unity gain for the whole of every conversion window
(`vsum1` and `vo1` agreed to 0.35 mV). The modulator produced a DC bitstream
at every input because its loop was never let out of reset.

The entry's own comment already said what it wanted — "(W/L) 1 against the
pass gate's 13", "five to ten times weaker" — and the shipped numbers gave
3.3x. This pins the RULE the comment states, not the particular widths, so a
later resize is free to move the geometry and is not free to close the margin.
"""
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
a2 = importlib.import_module("analog_a2_topology_emit")

#: A keeper is overridden by the pass gate that writes its node. Below this
#: the write does not take. The entry's own comment says "five to ten".
MIN_MARGIN = 4.0


def _by_name():
    found = {}
    def walk(o):
        if isinstance(o, dict):
            n = o.get("name")
            if isinstance(n, str) and "w" in o and "l" in o:
                found[n] = (float(o["w"]), float(o["l"]))
            for v in o.values():
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)
    walk(a2.LIBRARY)
    return found


def test_the_library_really_declares_these_devices():
    # Guard the arm: a test that finds nothing must fail, not pass silently.
    d = _by_name()
    for n in ("mp_mkp{i}", "mn_mkp{i}", "mp_skp{i}", "mn_skp{i}",
              "mn_mtg{i}", "mn_stg{i}"):
        assert n in d, f"{n} not found in the topology library"


def test_the_master_keeper_is_weaker_than_its_pass_gate_by_the_stated_margin():
    d = _by_name()
    wl = lambda k: d[k][0] / d[k][1]
    margin = wl("mn_mtg{i}") / wl("mn_mkp{i}")
    assert margin >= MIN_MARGIN, (
        f"master keeper is only {margin:.1f}x weaker than the pass gate that "
        f"must write it; measured on silicon, 3.3x froze the counter")


def test_the_slave_keeper_is_weaker_than_its_pass_gate_by_the_stated_margin():
    d = _by_name()
    wl = lambda k: d[k][0] / d[k][1]
    margin = wl("mn_stg{i}") / wl("mn_skp{i}")
    assert margin >= MIN_MARGIN, (
        f"slave keeper is only {margin:.1f}x weaker than its pass gate")


def test_a_keeper_at_the_forward_inverters_own_size_is_refused():
    # The exact shape that shipped: keeper == forward inverter == a symmetric
    # latch. This is the negative control, stated as the rule it violates.
    d = _by_name()
    for keeper, inv in (("mn_mkp{i}", "mn_minv{i}"), ("mn_skp{i}", "mn_sinv{i}")):
        if inv in d:
            assert d[keeper] != d[inv], (
                f"{keeper} is drawn at {inv}'s exact geometry — a symmetric "
                f"back-to-back latch, which measured as unwritable")


def test_the_keeper_length_stays_one_the_block_already_draws():
    # A5's layout generator refused this very device at l=2.0 um ("no leg tap
    # level"), so the margin is bought with WIDTH, not length.
    d = _by_name()
    for k in ("mp_mkp{i}", "mn_mkp{i}", "mp_skp{i}", "mn_skp{i}"):
        assert d[k][1] == 0.5, (
            f"{k} length moved to {d[k][1]} um; A5 has refused this device at "
            f"a length no other device in the block draws")
