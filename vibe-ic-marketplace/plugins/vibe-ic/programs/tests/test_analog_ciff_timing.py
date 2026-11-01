"""Phase and polarity contracts from the measured native timing arrangement."""
import analog_a2_topology_emit as a2
from test_analog_ciff import _emit


def test_d1_strobe_preserves_the_native_measured_wiring(tmp_path):
    _, ir = _emit(tmp_path, 2, feedback_delay=1)
    devs = {d["name"]: d for d in ir["devices"]}
    native = {d["name"]: d for d in a2.LIBRARY["delta_sigma"]["devices"]}
    # Two inverters preserve the SOURCE polarity. nph2b is not nclkb.
    for name in ("mn_qdly1", "mp_qdly1"):
        assert devs[name]["nets"] == native[name]["nets"]
        assert devs[name]["nets"][1] == "nclkb"
    for name in ("mn_qdly2", "mp_qdly2", "mn_qtail", "mn_qin", "mn_qref"):
        assert devs[name]["nets"] == native[name]["nets"]
    assert ir["loop_declaration"]["D"] == 1
    assert ir["loop_declaration"]["k0_path"]["delay_clocks"] == 1
