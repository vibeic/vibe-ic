"""A fix made anywhere but the producer is a fix that was never made.

This lane paid for that shape twice. Round 20 measured a phase overlap and a
ripple-decode hazard, fixed BOTH in a hand-edited netlist, and neither reached
this file: round 25 rediscovered the phase overlap, and round 29 found the
decode hazard still there -- `nallc` appeared 0 times in the emitted netlist
and 0 times in the emitter.

MEASURED (round 29, v1.16.60): `nallc` is a combinational AND over an
ASYNCHRONOUS ripple counter, so it glitches on every carry -- 5 to 6 pulses of
about 0.6 ns per conversion window, at 2, 4, 8 and 16 clocks after each reset.
Wired straight to the integrator shorts and the auto-zero clamp, each glitch
closes them for 0.6 ns, far too short for the clamp to pull nqz to vcm: the
reset left nqz - vcm = +0.0261 V where it should leave 0, and the quantiser
carried that as a standing offset for the whole window.

The counter advances on the RISING edge, so the ripple settles during the LOW
phase. A transparent-LOW latch samples there and holds through the HIGH phase.
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


def _dev(n):
    for d in _entry()["devices"]:
        if d.get("name") == n:
            return d
    return None


def test_the_combinational_decode_no_longer_IS_the_reset():
    """The counter group's accumulator must terminate on a net that is not
    the one driving the resets."""
    groups = [g for g in m._stage_groups(_entry())
              if g.get("last_out2") or g.get("inner_out2")]
    assert groups, "no accumulator chain found"
    for g in groups:
        assert g.get("last_out2") != "nall", (
            "the ripple decode drives the resets directly; every carry "
            "glitch is a reset pulse")
    assert any(g.get("last_out2") == "nallc" for g in groups)


def test_the_register_exists_and_is_a_latch_not_a_wire():
    for n in ("mn_rtg", "mp_rtg", "mp_rinv", "mn_rinv",
              "mp_rkp", "mn_rkp", "mp_rout", "mn_rout"):
        assert _dev(n) is not None, n
    # the pass gate takes the COMBINATIONAL decode, the output drives `nall`
    assert _dev("mn_rtg")["nets"][0] == "nallc"
    assert _dev("mp_rout")["nets"][0] == "nall"


def test_the_latch_is_transparent_on_the_phase_the_ripple_has_settled():
    """The counter advances on the rising edge, so the ripple lands in the
    HIGH phase; the latch must be transparent on the LOW one."""
    assert _dev("mn_rtg")["nets"][1] == "nclkb"   # n-side opens on clk LOW
    assert _dev("mp_rtg")["nets"][1] == "clk"     # p-side, same phase


def test_the_keeper_is_weak_against_the_pass_gate():
    """Round 19 measured what a keeper drawn at the forward inverter's own
    geometry does: the pass gate cannot overwrite it and the latch never
    changes state. The counter stayed in reset for every window."""
    kp, inv = _dev("mp_rkp"), _dev("mp_rinv")
    assert kp["w"] < inv["w"], (kp["w"], inv["w"])
    assert _dev("mn_rkp")["w"] < _dev("mn_rinv")["w"]


def test_everything_the_reset_drives_takes_the_REGISTERED_net():
    """The point of the register is lost if any consumer still reads the
    combinational net."""
    consumers = []
    for d in _entry()["devices"]:
        if d.get("name", "").startswith(("mn_rst", "mp_rst", "mn_azq",
                                         "mp_azq")):
            consumers.append(d)
    for g in m._stage_groups(_entry()):
        for d in (g.get("devices") or []):
            if d.get("name", "").startswith(("mn_rsti", "mp_rsti")):
                consumers.append(d)
    assert consumers, "no reset consumers found"
    for d in consumers:
        assert "nallc" not in d["nets"], (
            f"{d['name']} still reads the combinational decode")


def test_the_shipped_library_still_holds_its_own_invariants():
    assert m.library_invariants() == []
