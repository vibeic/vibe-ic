"""Shared input/DAC and conversion-synchronous three-location chopping."""
import pytest
import subprocess
import numpy as np
import analog_a3_netlist_emit as a3
from _analog_producer_fixture import A2, A3, run_prog, bdir, read_json
from test_analog_ciff import _emit, _project
from test_analog_ota1_options import _case


def _caps(project, ir):
    sv = a3.spec_values(read_json(bdir(project, "mod_alpha") / "spec.json"))
    overrides, _, _, env = a3._resolve_params(ir, sv)
    def value(base):
        total = 0.
        for d in ir["devices"]:
            if d["role"] != "cap" or (d["name"] != base and not d["name"].startswith(base+"_u")):
                continue
            w, length = [overrides.get(d["name"], {}).get(k, d[k]) for k in ("w", "l")]
            total += env["cap_area_ff_per_um2"]*w*length+2*env.get("cap_perim_ff_per_um", 0)*(w+length)
        return total
    return value


@pytest.mark.parametrize("decision", [-1, 1])
def test_shared_cs_uses_both_reference_polarities_and_preserves_total_feedback(tmp_path, decision):
    p, ir = _emit(tmp_path, shared_input_dac=1, ciff_dac_ratio=1.4,
                  cs1_ff=960., cs2_ff=180., cs3_ff=120., ciff_summer_cap_ff=31.)
    loop = ir["loop_declaration"]
    sharing = loop["sharing"]
    devs = {d["name"]: d for d in ir["devices"]}
    assert sharing["stage"] == 1 and sharing["total_dac_over_input_cap"] == pytest.approx(1.4)
    assert devs["mn_smpb1"]["nets"][:3] == ["nsmp1", "nph2", "ndacb"]
    assert devs["mp_smpb1"]["nets"][:3] == ["nsmp1", "nph2b", "ndacb"]
    assert devs["mn_dacs1"]["nets"][2] == "ndac"
    assert devs["mn_dacb1"]["nets"][1:3] == ["bit_out", "vrefp"]
    assert devs["mn_dacb0"]["nets"][1:3] == ["nqb", "vrefn"]
    cap = _caps(p, ir)
    cs, cf, ci = cap("cs1"), cap("cf1"), cap("ci1")
    assert cs == pytest.approx(960.) and cf == pytest.approx(384.)
    assert cap("cs2") == pytest.approx(180.) and cap("cs3") == pytest.approx(120.)
    assert (cs+cf)/cs == pytest.approx(1.4)
    # Independent charge oracle: shared Cs transfers Vin - selected Vref,
    # whereas the separate Cf samples the opposite reference then returns.
    u, reference, scale = .17, .5, 1.4*.5
    physical_update = (cs*(u*scale-decision*reference)-cf*decision*reference)/ci/scale
    assert physical_update == pytest.approx(loop["a"][0]*u-loop["b"][0]*decision)
    paths = [x for x in loop["paths"] if x["kind"] in ("dac", "dac_shared")]
    assert sum(x["gain"] for x in paths) == pytest.approx(-loop["b"][0])
    assert run_prog(A3, p).returncode == 0


def test_sharing_off_has_identical_circuit_devices_and_expressions(tmp_path):
    _, default = _emit(tmp_path / "default", 2)
    _, off = _emit(tmp_path / "off", 2, shared_input_dac=0)
    for key in ("devices", "device_param_exprs", "loop_declaration"):
        assert default[key] == off[key]


@pytest.mark.parametrize("values", [{"feedback_delay": 1}, {"ciff_dac_ratio": .8},
                                  {"cs1_ff": 960., "cf1_ff": 960.}])
def test_inconsistent_sharing_is_a_named_gap(tmp_path, values):
    p = _project(tmp_path, **{"shared_input_dac": 1, "ciff_dac_ratio": 1.3, **values})
    assert run_prog(A2, p).returncode == 2
    gap = read_json(bdir(p, "mod_alpha") / "topology_gap.json")
    assert gap["status"] == "CIFF_SPEC_INVALID"


@pytest.mark.parametrize("polarity", [0, 1])
def test_three_choppers_have_fold_and_nmos_mirror_nodes_and_reset_phase(tmp_path, polarity):
    p, ir = _case(tmp_path, 1, 1, phase=1, ratio=2, stages=3, remove_cc=1, polarity=polarity)
    devs = {d["name"]: d for d in ir["devices"]}
    chop = ir["ota1_options"]["chopper"]
    assert set(chop["switch_locations"]) == {"CH1", "CH2", "CH3"}
    assert chop["switch_locations"]["CH2"]["kind"] == "folding_cascode_sources"
    assert chop["switch_locations"]["CH3"]["kind"] == "nmos_current_mirror"
    assert chop["ratio"] == 2 and chop["update_event"] == "start_of_phi1"
    assert chop["static_phase"] == "nph2" and chop["reset_net"] == "nall"
    assert chop["conversion_start_phase"] == ("positive" if polarity == 0 else "negative")
    assert devs["ota1_mp_no1a"]["nets"][0] != devs["mp_no1a"]["nets"][0]
    assert devs["ota1_mp_no2a"]["nets"][0] != devs["mp_no2a"]["nets"][0]
    assert devs["ota1_ch_mn_stg1"]["nets"][1] == chop["divider_clock_net"]
    assert devs["ota1_ch_mn_mtg1"]["nets"][1] == "nph2"
    assert devs["mn_ota1_ch_gate1"]["nets"][1] == "nph1"
    assert devs["mn_ota1_ch_run_tg"]["nets"][1] == "nph1b"
    assert devs["mn_ota1_ch_run_reset"]["nets"][1] == "nall"
    for node in ("nm1", "ns1"):
        assert devs["mp_ota1_ch_clear_"+node]["nets"][:3] == ["ota1_ch_"+node, "nrstb", "vdd"]
    for i, suffix in enumerate(("in1", "ref1"), 1):
        assert devs["ota1_mn_fc_load_"+suffix]["nets"][0] == f"ota1_ch_mraw{i}"
        assert devs[f"mn_ota1_ch_mirror{i}p"]["nets"][1] == chop["positive_phase"]
        assert devs[f"mn_ota1_ch_mirror{i}n"]["nets"][1] == chop["negative_phase"]
    assert "cc1" not in devs and "rz_cc1" not in devs
    assert run_prog(A3, p).returncode == 0


def test_fully_shared_stage_omits_an_unnecessary_dac_only_branch(tmp_path):
    p, ir = _emit(tmp_path, 2, shared_input_dac=1)
    assert ir["loop_declaration"]["sharing"]["dac_only_capacitor"] is None
    assert "mn_dacs1" not in {d["name"] for d in ir["devices"]}
    assert [p["kind"] for p in ir["loop_declaration"]["paths"] if p["kind"].startswith("dac")] == ["dac_shared"]
    assert run_prog(A3, p).returncode == 0


def test_absolute_capacitances_remain_explicit_parameters(tmp_path):
    p, ir = _emit(tmp_path, 2, cs1_ff=900., ci1_ff=3600., cf1_ff=900., cc1_ff=77.,
                  cff0_ff=31.)
    cap = _caps(p, ir)
    assert cap("cs1") == pytest.approx(900.)
    assert cap("ci1") == pytest.approx(3600.)
    assert cap("cc1") == pytest.approx(77.)
    assert cap("cff0") == pytest.approx(31.)


def test_optimized_zero_capacitors_follow_the_explicit_first_stage_scale(tmp_path):
    p, ir = _emit(tmp_path, window=16, ntf_optimize_zeros=1, cs1_ff=900.)
    cap = _caps(p, ir)
    for j, gain in enumerate(ir["loop_declaration"]["A"][0]):
        correction = gain-(1. if j == 0 else 0.)
        if abs(correction) > 1e-12:
            assert cap(f"czero{j+1}")/cap("ci1") == pytest.approx(abs(correction), rel=1e-7)


def test_chop_clock_restarts_same_phase_and_only_changes_during_phi1(tmp_path):
    _, ir = _case(tmp_path, 1, 1, phase=1, ratio=2, stages=3, remove_cc=1)
    allowed = {"vdd", "vss", "nph1", "nph1b", "nph2", "nph2b", "nall", "nrstb"}
    digital = [d for d in ir["devices"] if d["role"] in ("nmos", "pmos")
               and all(n in allowed or n.startswith("ota1_ch_") for n in d["nets"])]
    cards = ["Chopper clock and conversion reset from the emitted graph",
             ".model n nmos level=1 vto=.2 kp=200u", ".model p pmos level=1 vto=-.3 kp=80u",
             "Vdd vdd 0 PWL(0 0 2n 1.2)", "Vss vss 0 0",
             "Vphi nph1 0 PULSE(0 1.2 20n .1n .1n 44.9n 100n)",
             "Vphib nph1b 0 PULSE(1.2 0 20n .1n .1n 44.9n 100n)",
             "Vphi2 nph2 0 PULSE(0 1.2 67n .1n .1n 50.9n 100n)",
             "Vphi2b nph2b 0 PULSE(1.2 0 67n .1n .1n 50.9n 100n)",
             "Vreset nall 0 PWL(0 1.2 90n 1.2 90.1n 0 420n 0 420.1n 1.2 520n 1.2 520.1n 0)",
             "Vresetb nrstb 0 PWL(0 0 90n 0 90.1n 1.2 420n 1.2 420.1n 0 520n 0 520.1n 1.2)"]
    for d in digital:
        nets = ["0" if n == "vss" else n for n in d["nets"]]
        cards.append(f"M{d['name']} {' '.join(nets)} {'n' if d['role']=='nmos' else 'p'} w={d['w']}u l={d['l']}u")
    cards += [".control", "set wr_singlescale", "set wr_vecnames", "tran .1n 900n 0 .1n uic",
              "wrdata chop.dat v(nph1) v(nph2) v(nall) v(ota1_ch_q1) v(ota1_ch_p) v(ota1_ch_n)", "quit", ".endc", ".end"]
    (tmp_path / "chop.sp").write_text("\n".join(cards))
    cp = subprocess.run(["ngspice", "-b", "chop.sp"], cwd=tmp_path, capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout+cp.stderr
    t, phi, phi2, reset, q, pos, neg = np.loadtxt(tmp_path / "chop.dat", skiprows=1).T
    for when in (130e-9, 630e-9):
        i = np.argmin(abs(t-when))
        assert q[i] > 1.0 and pos[i] > 1.0 and neg[i] < .2
    for when in (230e-9, 730e-9):
        i = np.argmin(abs(t-when))
        assert q[i] < .2 and neg[i] > 1.0 and pos[i] < .2
    edges = np.flatnonzero((q[1:] > .6) != (q[:-1] > .6)) + 1
    edges = edges[t[edges] > 30e-9]
    assert len(edges) >= 5
    starts = np.flatnonzero((phi[1:] > .6) & (phi[:-1] <= .6)) + 1
    assert all(min(abs(t[e]-t[starts])) < 2e-9 for e in edges), "a chop transition missed the start of phi1"
    assert np.all(phi2[edges] < .2), "a chop transition entered phi2"
    assert not np.any((pos > .8) & (neg > .8)), "chop phases overlap"
