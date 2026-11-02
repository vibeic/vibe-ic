"""Phase and polarity contracts from the measured native timing arrangement."""
from itertools import product

import analog_a2_topology_emit as a2
from test_analog_ciff import _emit, _assert_phi2_or_reset_pair
from test_incremental_reset_phase_alignment import logic


def test_d1_strobe_preserves_the_native_measured_wiring(tmp_path):
    _, ir = _emit(tmp_path, 2, feedback_delay=1)
    devs = {d["name"]: d for d in ir["devices"]}
    native = {d["name"]: d for d in a2.LIBRARY["delta_sigma"]["devices"]}
    # Two inverters preserve the SOURCE polarity. nph2b is not nclkb.
    for name in ("mn_qdly1", "mp_qdly1"):
        assert devs[name]["nets"] == native[name]["nets"]
        assert devs[name]["nets"][1] == "nclkb"
    for name in ("mn_qdly2", "mp_qdly2", "mn_qin", "mn_qref"):
        assert devs[name]["nets"] == native[name]["nets"]
    for name in ("mn_qtail", "mp_qrst1", "mp_qrst2", "mp_qrsti1", "mp_qrsti2"):
        assert devs[name]["nets"][::2] == native[name]["nets"][::2]
        assert devs[name]["nets"][3] == native[name]["nets"][3]
        assert (devs[name]["w"], devs[name]["l"]) == (native[name]["w"], native[name]["l"])
        assert devs[name]["nets"][1] == devs["mn_qtail"]["nets"][1]
    for reset, strobe, phi2 in product((0, 1), repeat=3):
        known = {"nrstb": 1-reset, "nqstb": strobe, "nph2": phi2}
        assert logic(devs, devs["mn_qtail"]["nets"][1], known) == int(not reset and strobe and phi2)
    assert ir["loop_declaration"]["D"] == 1
    assert ir["loop_declaration"]["k0_path"]["delay_clocks"] == 1


def test_default_d0_latches_at_integration_end_and_dac_samples_next_phase(tmp_path):
    _, ir = _emit(tmp_path)
    timing = ir["loop_declaration"]["timing"]
    assert ir["loop_declaration"]["D"] == 0
    assert timing["latch_event"] == "end_of_integration"
    assert timing["strobe_source"] == "clk"
    assert timing["dac_sample_phase"] == "nph1"
    assert timing["dac_transfer_phase"] == "nph2"
    devs = {d["name"]: d for d in ir["devices"]}
    # Native ciff5: two-inverter strobe driven by clk, AZ during phi2,
    # passive summer sampling in phi2 and returning in the next phi1.
    for name in ("mn_qdly1", "mp_qdly1"):
        assert devs[name]["nets"][1] == "clk"
    _assert_phi2_or_reset_pair(devs, "sum_reset", "nqz", "vcm")
    _assert_phi2_or_reset_pair(devs, "ff0", "nff0", "vin")
    assert devs["mn_ffr0"]["nets"][:3] == ["nff0", "nph1", "vcm"]
    assert devs["mn_qin"]["nets"][1] == "vcm"
    assert devs["mn_qref"]["nets"][1] == "nqz"
    assert devs["mn_ndac1"]["nets"][1] == "nph1"
    assert devs["mn_dacs1"]["nets"][1] == "nckdac"
    assert devs["mn_cftv1"]["nets"][::2] == ["ncft1", "vsum1"]
    assert devs["mp_cftv1"]["nets"][::2] == ["ncft1", "vsum1"]
    ready = ir["incremental_startup"]["transfer_ready_net"]
    for reset, accepted, phi2 in product((0, 1), repeat=3):
        known = {"nrstb": 1-reset, ready: accepted, "nph2": phi2}
        expected = int(not reset and accepted and phi2)
        assert logic(devs, devs["mn_cftv1"]["nets"][1], known) == expected
        assert logic(devs, devs["mp_cftv1"]["nets"][1], known) == 1-expected
    assert "caz" not in devs and "csum_hold" not in devs


def test_nonoverlap_and_latch_delay_remain_declared_parameters(tmp_path):
    _, ir = _emit(tmp_path, 2, quantizer_latch_delay_cap_ff=47.,
                  sc_nonoverlap_nmos_w_um=2.5, sc_nonoverlap_pmos_w_um=5., sc_nonoverlap_l_um=.6)
    timing = ir["loop_declaration"]["timing"]
    assert timing["latch_delay_cap_ff"] == 47.
    assert timing["nonoverlap_parameters"] == {"w_nmos": 2.5, "w_pmos": 5., "l": .6}
    # No ns target is fabricated: only supplied physical parameters change.
    assert "latch_delay_ns" not in timing
    assert any(e["device"] == "c_qdly" and e.get("ff_expr") == "quantizer_latch_delay_cap_ff"
               for e in ir["device_param_exprs"])
