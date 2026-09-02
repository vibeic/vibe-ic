"""The quantiser must be a LATCH, not a cross-coupled-load amplifier.

MEASURED (round 21, u_hawaii_adc / ihp-sg13g2). The entry cites the StrongARM
/ sense-amplifier latch and emitted only TWO of its four latch devices: the
input pair drained straight onto the regenerative nodes and there was no
cross-coupled NMOS pair. Extracted and driven by ideal sources, the result did
not resolve at any input:

    |vid|      output separation      what it is
    200 mV        0.7718 V
     20 mV        0.0255 V            ~1.3 V/V, LINEAR in the input
      2 mV        0.0025 V
      0           0.0000 V

with both outputs clamped at 0.1605 V by a static vdd->vss path (both
cross-coupled PMOS in saturation, both input devices and the tail in triode).
With the nmos half and the intermediate-node pre-charge added, the same
testbench resolves to FULL RAILS (1.2000 V separation) at every input down to
2 mV, in 1.13-1.47 ns.
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


def test_the_latch_has_BOTH_cross_coupled_pairs():
    # the defect: a cited StrongARM emitting only its pmos half
    for n in ("mp_qlat1", "mp_qlat2", "mn_qlat1", "mn_qlat2"):
        assert _dev(n) is not None, f"{n} missing — this is not a latch"


def test_the_cross_couple_is_actually_cross_coupled():
    # each latch device's GATE must be the OPPOSITE output node
    for n, out, gate in (("mp_qlat1", "nq_p", "nq_n"),
                         ("mp_qlat2", "nq_n", "nq_p"),
                         ("mn_qlat1", "nq_n", "nq_p"),
                         ("mn_qlat2", "nq_p", "nq_n")):
        d = _dev(n)
        assert d["nets"][0] == out and d["nets"][1] == gate, (n, d["nets"])


def test_the_input_pair_drains_to_intermediate_nodes_not_the_latch_nodes():
    # THE mechanism. Drain the input pair onto the regenerative nodes and the
    # input devices hold a DC path through them for the whole evaluate phase.
    assert _dev("mn_qin")["nets"][0] == "ndi_n"
    assert _dev("mn_qref")["nets"][0] == "ndi_p"
    # and the nmos latch pair sources FROM those intermediate nodes
    assert _dev("mn_qlat1")["nets"][2] == "ndi_n"
    assert _dev("mn_qlat2")["nets"][2] == "ndi_p"


def test_every_precharged_node_including_the_intermediate_ones():
    # an intermediate node with no pre-charge carries the previous decision
    pre = {d["nets"][0] for d in _entry()["devices"]
           if d.get("name", "").startswith("mp_qrst")}
    assert {"nq_p", "nq_n", "ndi_p", "ndi_n"} <= pre, pre


def test_the_precharge_and_the_tail_are_opposite_phase_BY_DEVICE_TYPE():
    """They share a gate net ON PURPOSE — an NMOS tail and a PMOS pre-charge
    driven from one net are already opposite phase, and that is the standard
    StrongARM clocking. I first asserted the nets must DIFFER; the producer
    proved that wrong, so the invariant is the one that is actually true:
    every pre-charge device is a PMOS, the tail is an NMOS, and they take the
    same net."""
    tail = _dev("mn_qtail")
    assert tail["role"] == "nmos"
    pre = [d for d in _entry()["devices"]
           if d.get("name", "").startswith("mp_qrst")]
    assert pre, "no pre-charge devices"
    for d in pre:
        assert d["role"] == "pmos", d["name"]
        assert d["nets"][1] == tail["nets"][1], (d["name"], d["nets"][1])


def test_the_shipped_library_still_holds_its_own_invariants():
    assert m.library_invariants() == []
