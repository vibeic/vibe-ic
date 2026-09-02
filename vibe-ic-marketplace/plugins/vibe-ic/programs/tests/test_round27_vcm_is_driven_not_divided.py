"""A reference loaded by switches needs a driver, not a bigger capacitor.

MEASURED (rounds 26-27). Decoupling alone took the decision-instant swing on
`vcm` from 0.1196 V to 0.0367 V and stopped: reaching a tenth of the signal
that way needs ~734 unit capacitors, about 0.10 mm^2, which closed that route
by extrapolation rather than by preference.

THE SPEC, back-derived from the switched charge:

    I_avg  = 4 * C_unit * dV_switch * f_clk
           = 4 * 277.97 fF * 0.5 V * 10 MHz = 5.56 uA
    R_out  < 0.0020 V / 5.56 uA = 360 ohm

against a divider that is 67.2 kohm (two 181 um rppd arms in parallel at the
registry's measured sheet resistance) -- 187x too high. Every term comes from
something the design already declares: the sampling capacitor the noise budget
fixed, half the declared reference span, the declared clock, and a tenth of
the measured signal variation.

THE TOPOLOGY IS NOT INVENTED: the design already contains two of the amplifier
this needs. The integrator OTA is instantiated a third time at the same
geometry, closed in unity gain, with the divider midpoint on its input.
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


def _stage_dev(n):
    for g in m._stage_groups(_entry()):
        for d in (g.get("devices") or []):
            if d.get("name") == n:
                return d
    return None


def test_the_divider_no_longer_drives_the_reference_node_directly():
    for r in ("r_cm1", "r_cm2"):
        nets = _dev(r)["nets"]
        assert "vcm" not in nets, (
            f"{r} still drives vcm directly; a 67.2 kohm divider cannot hold "
            f"a node ten switched terminals commutate onto")
    assert "nvcmr" in _dev("r_cm1")["nets"]
    assert "nvcmr" in _dev("r_cm2")["nets"]


def test_the_buffer_is_closed_in_unity_gain():
    # the feedback input must BE the output, or it is not a buffer
    assert _dev("mn_cmfb")["nets"][1] == "vcm"
    assert _dev("mp_cmo")["nets"][0] == "vcm"
    assert _dev("mn_cmo")["nets"][0] == "vcm"
    # and the reference input takes the divider midpoint
    assert _dev("mn_cmin")["nets"][1] == "nvcmr"


def test_the_feedback_is_on_the_INVERTING_input():
    """Taken from this OTA's own phase, not assumed. The diode side of the
    mirror is inverting; the mirror side is not. Wired the other way the loop
    is positive feedback -- MEASURED, the buffer drove vcm to 1.11 V against
    a 0.60 V divider midpoint, i.e. straight to the rail."""
    diode = _dev("mp_cmld1")["nets"][0]          # the diode-connected load
    assert _dev("mp_cmld1")["nets"][0] == _dev("mp_cmld1")["nets"][1]
    assert _dev("mn_cmfb")["nets"][0] == diode, (
        "feedback is on the mirror side: that is positive feedback")
    assert _dev("mn_cmin")["nets"][0] != diode


def test_the_buffer_reuses_the_integrator_OTA_geometry_not_new_numbers():
    """The control against inventing an amplifier: every width here must equal
    the integrator's own, which the design already ships two of."""
    for buf, integ in (("mn_cmtail", "mn_tail{i}"), ("mn_cmin", "mn_in{i}"),
                       ("mn_cmfb", "mn_ref{i}"), ("mp_cmld1", "mp_ld1_{i}"),
                       ("mp_cmld2", "mp_ld2_{i}"), ("mp_cmo", "mp_o{i}"),
                       ("mn_cmo", "mn_o{i}")):
        b, g = _dev(buf), _stage_dev(integ)
        assert b is not None and g is not None, (buf, integ)
        assert (b["w"], b["l"]) == (g["w"], g["l"]), (buf, integ, b, g)


def test_the_tail_hangs_off_the_already_derived_bias():
    assert _dev("mn_cmtail")["nets"][1] == "nbias"
    assert _dev("mn_cmo")["nets"][1] == "nbias"


def test_the_compensation_is_derived_not_a_number_that_was_once_right():
    exprs = {e["device"]: e for e in _entry()["device_param_exprs"]}
    assert "c_cmc" in exprs, "the buffer's compensation is hand-written"
    e = exprs["c_cmc"]["expr"]
    assert "miller_fraction_of_load" in e and "enob" in e and "osr" in e


def test_the_shipped_library_still_holds_its_own_invariants():
    assert m.library_invariants() == []
