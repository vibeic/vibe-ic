"""The normal ENOB consumer must give weight zero to the first real update.

Neutral controller-only Level-1 simulation; ideal resolved comparator and
controlled counter decode. This proves timing integration, not ADC ENOB/PDK.
"""
from pathlib import Path
import subprocess

import numpy as np
import pytest

import analog_a2_topology_emit as a2
import analog_adc_enob_corner_check as enob
import analog_incremental_decimator as dec
import analog_resolution_stimulus as stimulus
from test_declared_load_bias_branches import _emit


def _control_wave(tmp_path):
    ir, _, _, env, _ = _emit(tmp_path, order=2, values={"osr": 8., "startup_reset": 0.})
    exact = {"ckb", "rtg", "rinv", "rkp", "rout", "rstinv", "qdly1", "qdly2",
             "n1a", "n1b", "n2a", "n2b", "obuf", "bbuf"}
    rows = [d for d in ir["devices"] if
            (d["name"][3:] in exact or d["name"].startswith("c_qdly") or
             d["name"][3:].startswith(("conversion_", "no1", "no2", "nph1", "nph2")))
            and not any(x in d["name"] for x in ("clear_n", "summer_prepare", "sum_clear", "k0_"))]
    qgate = next(d["nets"][1] for d in ir["devices"] if d["name"] == "mn_qtail")
    cards = ["Neutral emitted controller integration probe",
             ".model n nmos level=1 vto=.2 kp=200u",
             ".model p pmos level=1 vto=-.3 kp=80u",
             "Vdd vdd 0 PWL(0 0 5n 1.2)", "Vss vss 0 0",
             "Vclk clk 0 PULSE(0 1.2 25n .2n .2n 124.8n 250n)",
             "Bplus nq_p 0 V=1.2", f"Bminus nq_n 0 V=V({qgate})>.6 ? 0 : 1.2",
             "Vdecode nallc 0 PULSE(1.2 0 200n .2n .2n 1749.8n 2000n)"]
    exprs = {(e["device"], e["param"]): e["expr"] for e in ir["device_param_exprs"]}
    for d in rows:
        w, length = [a2._safe_eval(exprs[(d["name"], k)], env) if (d["name"], k) in exprs
                     else d[k] for k in ("w", "l")]
        nets = ["0" if n == "vss" else n for n in d["nets"]]
        if d["role"] in ("nmos", "pmos"):
            cards.append(f"M{d['name']} {' '.join(nets)} {d['role'][0]} w={w}u l={length}u")
        elif d["role"] == "cap":
            ff = env["cap_area_ff_per_um2"]*w*length + 2*env.get("cap_perim_ff_per_um", 0)*(w+length)
            cards.append(f"C{d['name']} {' '.join(nets[:2])} {ff*1e-15}")
    drains = {d["nets"][0] for d in rows if d["role"] in ("nmos", "pmos")}
    for i, node in enumerate(sorted(drains - {"vdd", "vss", "clk", "nq_n", "nq_p"})):
        cards.append(f"Charness{i} {node} 0 1f")
    reset = (ir.get("incremental_startup") or {}).get("reset_bar_net", "nrstb")
    cards += [".control", "set wr_singlescale", "set wr_vecnames", "tran .2n 8u 0 .2n uic",
              f"wrdata wave.dat v(bit_out) v({reset}) v(clk) v(nph2)", "quit", ".endc", ".end"]
    (tmp_path / "probe.sp").write_text("\n".join(cards) + "\n")
    run = subprocess.run(["ngspice", "-b", "probe.sp"], cwd=tmp_path, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    data = np.loadtxt(tmp_path / "wave.dat", skiprows=1)
    assert data[-1, 0] >= 7.999e-6, "ngspice may return zero on truncated TRAN"
    return ir, data


def _consumer_decode(monkeypatch, deck, dump):
    seen = []
    original = dec.decimate
    def observe(*args, **kwargs):
        result = original(*args, **kwargs)
        seen.append(result)
        return result
    monkeypatch.setattr(dec, "decimate", observe)
    enob.sndr_db_incremental(deck, dump)
    assert seen, "normal consumer never reached its declared decoder"
    return seen[0][0]


def test_native_fresh_decisions_occupy_the_consumers_first_weight(tmp_path, monkeypatch):
    ir, wave = _control_wave(tmp_path)
    times, values = wave[:, 0].tolist(), wave[:, 1].tolist()
    reset = wave[:, 2] > .6
    releases = np.flatnonzero(~reset[:-1] & reset[1:]) + 1
    transfers = np.flatnonzero((wave[:-1, 4] <= .6) & (wave[1:, 4] > .6)) + 1
    assert all(wave[r, 3] > .6 for r in releases), "release must be in phi1"
    for left, right in zip(releases, releases[1:]):
        assert sum((transfers >= left) & (transfers < right)) == 7
    assert not any((wave[:, 4] > .6) & ~reset)
    old_bits, _ = dec.sample_decisions(times, values, 25e-9, 250e-9, .6)
    old, _ = dec.decimate(old_bits, 8, order=2, topology="ciff")
    assert old[1:] == pytest.approx([.5, .5, .5]), "explicit one-weight-shift counterexample"
    node = (ir.get("incremental_startup") or {}).get("reset_bar_net", "nrstb")
    deck = (dec.stamp("incremental", 8, 2, .25, 0, "ciff") +
            f" reset_release_node={node} active_transfers=7\n" +
            "v_clk clk 0 pulse(0 1.2 25n .2n .2n 124.8n 250n)\n" +
            "v_in ain 0 sin(.6 .1 10000)\n")
    dump = f"time v(bit_out) v({node})\n" + "\n".join(
        f"{t} {v} {r}" for t, v, r in wave[:, :3])
    decoded = _consumer_decode(monkeypatch, deck, dump)
    assert decoded == pytest.approx([1., 1., 1.]), (decoded, old)


def test_controller_deck_exports_its_own_reset_release(tmp_path):
    ir, *_ = _emit(tmp_path, order=2, values={"osr": 8.})
    from test_analog_resolution_stimulus import _deck, _spec
    deck = _deck(stop_ns=496100, clk_per_ns=1000).replace("ain", "vin").replace("dout", "bit_out")
    # Testbench signal port is explicitly declared; instance name is arbitrary.
    ir["testbench"] = {"signal_input_port": "vin"}
    deck = deck.replace("xdut", "xconverter")
    produced, record = stimulus.apply(deck, _spec(osr=8.), ir, "resolution.dat")
    assert record["applied"], record
    declaration, why = dec.read_stamp(produced)
    assert declaration is not None, why
    assert declaration["reset_release_node"] == "xconverter." + ir["incremental_startup"]["reset_bar_net"]
    assert declaration["active_transfers"] == 7
    assert "v(" + declaration["reset_release_node"] + ")" in produced.split("wrdata", 1)[1]
    assert "set wr_singlescale" in produced and "set wr_vecnames" in produced


@pytest.mark.parametrize("offset", [0., .11, .43])
def test_raw_delay_cannot_shift_observed_release_slots(offset):
    times = [i / 100 for i in range(3300)]
    reset = [float(.25 <= (t-offset) % 8 < 7.25) for t in times]
    values = [1.2 * r for r in reset]
    bits, meta = dec.sample_decisions(times, values, -99., 1., .6,
                                     reset_release_values=reset, window_clocks=8)
    assert bits and all(v == 1. for v in bits)
    assert len(bits) % 7 == 0
    assert meta["alignment"] == "observed_phi1_reset_release"
