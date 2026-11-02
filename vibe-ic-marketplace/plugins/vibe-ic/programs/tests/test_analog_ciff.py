"""CIFF contracts through the ordinary A1 -> A2 -> A3 producers.

Study numbers appear only as independent regression expectations / state
scaling inputs. Production synthesis contains no ADC-specific coefficients.
"""
import json
from itertools import product
import re
import subprocess

import numpy as np
import pytest

import analog_a3_netlist_emit as a3
from _analog_producer_fixture import A1, A2, A3, block, make_project, run_prog, bdir, read_json, stage_custom_pdk
from test_analog_a3_netlist_emit import DS_SPEC, DS_PDK_RECORD
from test_incremental_reset_phase_alignment import fanin, logic


def _assert_phi2_or_reset_pair(devices, name, left, right):
    """Reset prepares the passive sum before the first phi1 return."""
    for prefix in ("mn_", "mp_"):
        assert devices[prefix+name]["nets"][::2] == [left, right]
    for reset, phi2 in product((0, 1), repeat=2):
        known = {"nall": reset, "nph2": phi2}
        expected = int(reset or phi2)
        assert logic(devices, devices["mn_"+name]["nets"][1], known) == expected
        assert logic(devices, devices["mp_"+name]["nets"][1], known) == 1-expected


def _project(tmp_path, order=3, window=512, **values):
    specs = [dict(row) for row in DS_SPEC]
    next(r for r in specs if r["name"] == "order")["target"] = order
    next(r for r in specs if r["name"] == "osr")["target"] = window
    values = {"ciff": 1, "ntf_hinf": 1.4,
              **{f"a{i}": .25 for i in range(1, order+1)}, **values}
    specs.extend({"name": k, "target": v, "unit": ""} for k, v in values.items())
    p = make_project(tmp_path, [block("mod_alpha", "delta_sigma", specs)])
    stage_custom_pdk(p, a3.DEFAULT_PDK)
    rec = p / "analog/_pdk_char/analog_device_params.json"
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(json.dumps(DS_PDK_RECORD))
    assert run_prog(A1, p).returncode == 0
    return p


@pytest.mark.parametrize("family", [0, 1])
def test_designed_unequal_coefficients_and_consumer_contract(tmp_path, family):
    b = [.12, -.08, .03] if family == 0 else [.12, 0., 0.]
    values = {"ciff": family, "designed_coefficients": 1, "feedback_delay": 1,
              "a1": .21, "a2": -.34, "a3": .18,
              "b1": b[0], "b2": b[1], "b3": b[2],
              "c1": 1.5, "c2": -.8, "c3": .7, "c0": .6, "k0": .2}
    p, ir = _emit(tmp_path, **values)
    loop = ir["loop_declaration"]
    assert loop["family"] == ("CIFF" if family else "CIFB")
    assert loop["order"] == 3 and loop["quantizer_levels"] == 2 and loop["D"] == 1
    assert loop["a"] == pytest.approx([.21, -.34, .18])
    assert loop["b"] == pytest.approx(b)
    assert loop["c"] == pytest.approx([1.5, -.8, .7])
    assert loop["dac_stages"] == ([1] if family else [1, 2, 3])
    assert loop["k0_path"]["gain"] == -.2
    assert loop["k0_path"]["capacitor"] == "cffk0"
    devices = {d["name"]: d for d in ir["devices"]}
    assert devices["mn_cstc2"]["nets"][2] == loop["state_nets"][0]
    if family == 0:
        assert devices["mn_dacs2"]["nets"][2] == "ndacb"
    cp = run_prog(A3, p)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    text = (bdir(p, "mod_alpha") / "mod_alpha.sp").read_text()
    assert f"DAC stages={loop['dac_stages']}" in text
    # Recover the actual rendered capacitor values, summing PDK unit arrays.
    # This catches a producer that publishes the requested coefficients but
    # leaves the netlist at its old equal-gain geometry.
    def cap(base):
        total = 0.
        for line in text.splitlines():
            name = line.split()[0] if line.split() else ""
            if name != "x"+base and not name.startswith("x"+base+"_u"):
                continue
            w = float(re.search(r"\bw=([0-9.eE+-]+)", line)[1])
            length = float(re.search(r"\bl=([0-9.eE+-]+)", line)[1])
            params = ir["pdk_measured_params"]
            total += params["cap_area_ff_per_um2"]*w*length + 2*params.get("cap_perim_ff_per_um", 0)*(w+length)
        assert total > 0, base
        return total
    for i, gain in enumerate(loop["a"], 1):
        assert cap(f"cs{i}")/cap(f"ci{i}") == pytest.approx(abs(gain), rel=1e-5)
        if b[i-1]:
            assert cap(f"cf{i}")/cap(f"ci{i}") == pytest.approx(abs(b[i-1]), rel=1e-5)
    assert cap("cff2")/cap("cff3") == pytest.approx(.8/.7, rel=1e-5)
    assert devices["mn_ffr2"]["nets"][1] == "nph1"


@pytest.mark.parametrize("ciff", [0, 1])
def test_declared_startup_reset_reaches_counter_and_all_integrators(tmp_path, ciff):
    p, ir = _emit(tmp_path, 2, ciff=ciff, startup_reset=1,
                  startup_reset_tau_ns=100, startup_reset_cap_ff=1000)
    por = ir["startup_reset"]
    assert por["kind"] == "RC_Schmitt" and por["tau_ns"] == 100
    assert set(por["clears"]) == {"window_counter", "all_integrators",
                                  "decision_latch", "sc_sampling_plates"}
    devs = {d["name"]: d for d in ir["devices"]}
    assert devs["mn_cki1"]["nets"][1] == por["counter_clock_net"]
    assert devs["mp_por_clear1_0"]["nets"][0] == "nm1"
    assert devs["mp_por_clear1_1"]["nets"][0] == "ns1"
    control = ir["incremental_startup"]
    window, boot = control["window_reset_net"], control["bootstrap_net"]
    assert {window, boot, "npor_runb"} <= fanin(devs, por["reset_net"])
    storage = devs["mn_rout"]["nets"][1]
    assert devs["mn_rout"]["nets"][0] == window
    assert any(d["role"] == "pmos" and d["nets"][:3] ==
               [storage, "npor_run", "vdd"] for d in devs.values())
    for terminal, boot_held, running in product((0, 1), repeat=3):
        known = {window: terminal, boot: boot_held, "npor_runb": 1-running}
        assert logic(devs, por["reset_net"], known) == int(terminal or boot_held or not running)
    known = {"nall": 1, "nrstb": 0, "nq_n": 0, "nq_p": 0}
    assert logic(devs, devs["mn_n1a"]["nets"][1], known) == 1
    assert logic(devs, devs["mn_n2a"]["nets"][1], known) == 0
    plates = {n for d in devs.values() if d["role"] == "cap"
              and re.fullmatch(r"(?:cs|cf|czero)\d+(?:_u\d+)?", d["name"])
              for n in d["nets"]}
    assert plates
    for plate in plates:
        for role, gate in (("nmos", "nall"), ("pmos", "nrstb")):
            assert any(d["role"] == role and d["nets"][1] == gate
                       and {d["nets"][0], d["nets"][2]} == {plate, "vcm"}
                       for d in devs.values()), (plate, role)
    for i in (1, 2):
        assert devs[f"mn_rsti{i}"]["nets"][1] == por["reset_net"]
    assert run_prog(A3, p).returncode == 0
    assert "startup reset: RC_Schmitt" in (bdir(p, "mod_alpha") / "mod_alpha.sp").read_text()


def test_legacy_cifb_publishes_the_same_loop_contract(tmp_path):
    _, ir = _emit(tmp_path, 2, ciff=0)
    loop = ir["loop_declaration"]
    assert loop["family"] == "CIFB" and loop["dac_stages"] == [1, 2]
    assert loop["c"] == [0., 1.]
    assert loop["D"] == 1 and loop["k0_path"] is None
    assert "startup_reset" not in ir


def test_startup_reset_clears_counter_and_releases_on_a_clock_edge_in_spice(tmp_path):
    p, ir = _emit(tmp_path, 2, startup_reset=1,
                  startup_reset_tau_ns=100, startup_reset_cap_ff=1000)
    import analog_a2_topology_emit as a2
    counter = a2.LIBRARY["delta_sigma"]["stage"][1]
    count = len(ir["startup_reset"]["counter_state_on_reset"])
    counter_names = {d["name"].format(i=i, i1=i+1) for d in counter["devices"] for i in range(1, count+1)}
    sv = a3.spec_values(read_json(bdir(p, "mod_alpha") / "spec.json"))
    overrides, _, _, env = a3._resolve_params(ir, sv)
    cards = ["Startup reset and counter from the emitted IR",
             ".model n nmos level=1 vto=.2 kp=200u",
             ".model p pmos level=1 vto=-.3 kp=80u",
             "Vdd vdd 0 PWL(0 0 5n 1.2)", "Vss vss 0 0",
             "Vclk clk 0 PULSE(0 1.2 25n .2n .2n 124.8n 250n)",
             "Vwindow nwindow_reset 0 0"]
    for d in ir["devices"]:
        if d["name"] not in counter_names and "por" not in d["name"] and d["nets"][0] != "nclkb":
            continue
        param = {k: overrides.get(d["name"], {}).get(k, d.get(k)) for k in ("w", "l")}
        w, length = param["w"], param["l"]
        name, nets = d["name"], ["0" if n == "vss" else n for n in d["nets"]]
        if d["role"] in ("nmos", "pmos"):
            cards.append(f"M{name} {' '.join(nets)} {'n' if d['role']=='nmos' else 'p'} w={w}u l={length}u")
        elif d["role"] == "cap":
            ff = env["cap_area_ff_per_um2"]*w*length + 2*env.get("cap_perim_ff_per_um", 0)*(w+length)
            cards.append(f"C{name} {' '.join(nets[:2])} {ff*1e-15}")
        elif d["role"] == "res":
            cards.append(f"R{name} {' '.join(nets[:2])} {env['rsheet_ohm_per_sq']*length/w}")
    cards += [".control", "set wr_singlescale", "set wr_vecnames",
              "tran .2n 1.5u 0 .2n uic", "wrdata por.dat v(npor) v(npor_run) v(npor_clk) v(clk) v(q1)",
              "quit", ".endc", ".end"]
    (tmp_path / "por.sp").write_text("\n".join(cards))
    cp = subprocess.run(["ngspice", "-b", "por.sp"], cwd=tmp_path, text=True, capture_output=True)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    wave = np.loadtxt(tmp_path / "por.dat", skiprows=1)
    t, por, run, gated, clock, q1 = wave.T
    held = (t > 20e-9) & (run < .2)
    assert held.sum() > 10 and np.max(q1[held]) < .15
    assert np.max(por[t < 20e-9]) > 1.0 and np.max(run) > 1.0
    assert np.max(q1[t > .5e-6]) > 1.0
    edges = np.flatnonzero((gated[1:] > .6) & (gated[:-1] <= .6)) + 1
    clock_edges = np.flatnonzero((clock[1:] > .6) & (clock[:-1] <= .6)) + 1
    assert len(edges) > 2
    assert all(np.min(abs(t[e]-t[clock_edges])) < 3e-9 for e in edges)


def _emit(tmp_path, order=3, **values):
    p = _project(tmp_path, order, **values)
    cp = run_prog(A2, p)
    gap = bdir(p, "mod_alpha") / "topology_gap.json"
    assert cp.returncode == 0, cp.stdout + cp.stderr + (gap.read_text() if gap.exists() else "")
    return p, read_json(bdir(p, "mod_alpha") / "topology.json")


@pytest.mark.parametrize("delay,a,k,c", [
    (0, [.19164823008849652, .3587301587302853, .25449354235259564],
     [.6668447509766403, .20462778018567096, .02759084217906796],
     [3.479524703508686, 2.9764040754268764, 1.5769411556631048]),
    (1, [.19693081667831636, .40740780898751794, .12416161258686594],
     [.8714725311623095, .23221862236473584, .027590842179067696],
     [4.425272518855428, 2.8943697678328464, 2.769711801593367]),
])
def test_ciff3_hinf14_matches_independent_study(tmp_path, delay, a, k, c):
    _, ir = _emit(tmp_path, feedback_delay=delay, **{f"a{i}": v for i, v in enumerate(a, 1)})
    loop = ir["ciff"]
    assert loop["a"] == pytest.approx(a)
    assert loop["k"] == pytest.approx(k, rel=1e-7)
    assert loop["c"] == pytest.approx(c, rel=1e-7)
    assert loop["k0"] == pytest.approx(.6668447509766395 if delay else 0, abs=1e-8)
    assert loop["ntf_hinf"] == pytest.approx(1.4, rel=1e-7)


@pytest.mark.parametrize("order", [1, 2, 3])
@pytest.mark.parametrize("delay", [0, 1])
def test_template_emits_passive_summer_and_only_first_stage_dac(tmp_path, order, delay):
    p, ir = _emit(tmp_path, order, feedback_delay=delay)
    # Ordinary A3 CLI consumes A2's flat IR, including its capacitor arrays.
    cp = run_prog(A3, p)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    text = (bdir(p, "mod_alpha") / "mod_alpha.sp").read_text()
    assert "CIFF" in text
    devices = {d["name"]: d for d in ir["devices"]}
    if delay:
        assert devices["mn_sum_hold"]["nets"][:3] == ["nsum", "nph1", "nqz"]
    else:
        assert "mn_sum_hold" not in devices
        _assert_phi2_or_reset_pair(devices, "sum_reset", "nqz", "vcm")
    for i in range(order+1):
        assert any(n == f"cff{i}" or n.startswith(f"cff{i}_u") for n in devices)
    assert "mn_dacs1" in devices
    assert not any(f"mn_dacs{i}" in devices for i in range(2, order+1))
    assert devices["mn_qdly1"]["nets"][1] == ("clk" if delay == 0 else "nclkb")
    assert any(n.startswith("cffk0") for n in devices) == bool(delay)
    # Every new SC device reaches the actual netlist, not just a sidecar.
    for name in devices:
        assert f"x{name} " in text


@pytest.mark.parametrize("order", [1, 2, 3])
@pytest.mark.parametrize("delay", [0, 1])
def test_optimized_zeros_realize_the_requested_ntf(tmp_path, order, delay):
    _, ir = _emit(tmp_path, order, window=16, feedback_delay=delay, ntf_optimize_zeros=1)
    loop = ir["ciff"]
    A, b, c = np.array(loop["A"]), np.array(loop["b"]), np.array(loop["c"])
    for z in 1.1*np.exp(1j*np.linspace(.01, np.pi, 41)):
        h = c @ np.linalg.solve(z*np.eye(order)-A, b)
        actual = 1/(1 + z**(-delay)*h + loop["k0"]/z)
        wanted = np.polyval(loop["ntf_num"], z)/np.polyval(loop["ntf_den"], z)
        assert actual == pytest.approx(wanted, rel=1e-8, abs=1e-10)
    if order > 1:
        assert any(abs(z[1]) > 0 for z in loop["zeros"])
        assert any(d["name"].startswith("czero") for d in ir["devices"])


def test_ciff_order2_coefficient_changes_from_cifb_on_base(tmp_path):
    # Substantive pre-fix control: main emits an actual, wrong CIFB coefficient,
    # not merely an absent new API. It must disagree with the CIFF NTF gain.
    _, ir = _emit(tmp_path, 2, a1=.31, a2=.47)
    assert ir["stage_expansion"]["coefficients"] == pytest.approx([.31, .47])


def test_explicit_cifb_and_legacy_default_have_identical_devices(tmp_path):
    _, default = _emit(tmp_path / "default", 2, ciff=0)
    p = _project(tmp_path / "legacy", 2, ciff=0)
    spec = bdir(p, "mod_alpha") / "spec.json"
    data = read_json(spec)
    data["specs"] = [r for r in data["specs"] if r["name"] not in ("ciff", "ntf_hinf")]
    spec.write_text(json.dumps(data))
    assert run_prog(A2, p).returncode == 0
    legacy = read_json(bdir(p, "mod_alpha") / "topology.json")
    for key in ("devices", "internal_nets", "device_param_exprs", "stage_expansion"):
        assert default[key] == legacy[key]


@pytest.mark.parametrize("values", [{"feedback_delay": 2}, {"a1": 0}, {"ntf_hinf": 1},
                                  {"c1": 9}, {"k0": 1}, {"ciff": 2}])
def test_invalid_ciff_is_an_explicit_gap(tmp_path, values):
    p = _project(tmp_path, **values)
    cp = run_prog(A2, p)
    assert cp.returncode == 2, cp.stdout + cp.stderr
    assert read_json(bdir(p, "mod_alpha") / "topology_gap.json")["status"] == "CIFF_SPEC_INVALID"
