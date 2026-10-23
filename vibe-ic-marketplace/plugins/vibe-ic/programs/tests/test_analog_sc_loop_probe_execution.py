"""Bounded native execution and consumed-input reuse for the existing probe."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analog_sc_loop_probe as probe


def test_probe_threads_reach_actual_interpreter_without_changing_circuit():
    template = "* probe\nv_in vin 0 .7\nv_vdd vdd 0 1.2\n.end\n"
    deck = probe.build_deck(template, input_port="vin", vin=.6, inst="xdut", nets=["state"],
        tstop=9e-6, tstep=5e-9, out_file="wave.txt", threads=1)
    assert "v_vdd vdd 0 1.2" in deck and "v_in vin 0 0.600000" in deck
    assert "set num_threads=1\nset numdgt=15" in deck
    assert deck.index("set num_threads=1") < deck.index("tran ")


def test_probe_batches_two_workers_under_one_supervisor_and_sets_native_env(tmp_path, monkeypatch):
    output = tmp_path / "records"; output.mkdir()
    decks = {name: output / (name + ".sp") for name in ("a", "b", "c", "d")}
    calls = []
    def supervise(container, script, **kwargs):
        calls.append((container, script, kwargs))
        for deck in decks.values():
            deck.with_suffix(".rc").write_text("0\n")
        return type("Result", (), {"returncode": 0})()
    monkeypatch.setattr(probe._ce, "run_in_container_supervised", supervise)
    assert set(probe._run_decks(decks, "container", 10, workers=2, threads=1,
        wait_policy="PASSIVE", working_dir=tmp_path).values()) == {0}
    assert len(calls) == 1
    lines = calls[0][1].splitlines()
    assert lines.count("wait") == 2
    first_wait = lines.index("wait")
    assert sum(line.endswith(") &") for line in lines[:first_wait]) == 2
    assert "OMP_NUM_THREADS=1 OMP_WAIT_POLICY=PASSIVE GOMP_SPINCOUNT=0 ngspice" in calls[0][1]
    assert calls[0][2]["ceiling_s"] == 10


@pytest.mark.parametrize("kwargs", [{"workers": 0}, {"threads": True}, {"wait_policy": "PASSIVE; unsafe"}])
def test_invalid_resource_settings_cannot_launch_native(tmp_path, monkeypatch, kwargs):
    monkeypatch.setattr(probe._ce, "run_in_container_supervised", lambda *args, **kw: pytest.fail("native launched"))
    with pytest.raises(ValueError):
        probe._run_decks({"a": tmp_path / "a.sp"}, "container", 10, **kwargs)


def _project(tmp_path):
    bdir = tmp_path / "phase3/analog/cell"; bdir.mkdir(parents=True)
    (bdir / "cell.sp").write_text(".subckt cell vdd vss vin vrefp vrefn clk out\nr1 vin out 1k\n.ends cell\n")
    (bdir / "tb_cell.sp").write_text("* probe template\n.include cell.sp\n"
        "v_vdd vdd 0 1.2\nv_vrefp vrefp 0 1.1\nv_vrefn vrefn 0 .1\nv_in vin 0 .7\n"
        "v_clk clk 0 pulse(0 1.2 1u 1n 1n 499n 1u)\nxdut vdd 0 vin vrefp vrefn clk out cell\n.end\n")
    ir = {"loop_probe": {"input_port": "vin", "clock_port": "clk", "reference_ports": ["vrefp", "vrefn"],
        "common_mode_net": "cm", "feedback_net": "fb", "reset_net": "reset"},
        "stage_expansion": {"role": "cascade", "chain": ["vin", "state"]}, "devices": []}
    (bdir / "topology.json").write_text(json.dumps(ir))
    (bdir / "spec.json").write_text(json.dumps({"specs": [{"name": "vdd", "target": 1.2}]}))
    return bdir


def test_reuse_cannot_stamp_current_models_around_old_native_records(tmp_path, monkeypatch):
    bdir = _project(tmp_path)
    monkeypatch.setattr(probe, "_run_decks", lambda decks, *args: {tag: 0 for tag in decks})
    probe.probe(tmp_path, "cell", "container", workers=2, threads=1, wait_policy="PASSIVE")
    wdir = bdir / "loop_probe"
    before = (wdir / "native-inputs.json").read_bytes()
    for tag in probe.FIT_LEVELS:
        (wdir / f"w_fit_{tag:+.2f}.txt").write_text("old native capture\n")
    netlist = bdir / "cell.sp"
    netlist.write_text(netlist.read_text().replace("1k", "2k"))
    monkeypatch.setattr(probe, "_run_decks", lambda *args: pytest.fail("reuse unexpectedly reran native"))
    rc, record = probe.probe(tmp_path, "cell", "container", reuse_records=True,
        workers=2, threads=1, wait_policy="PASSIVE")
    assert rc == probe.RC_NO_RECORD and record["status"] == "NOT_MEASURED"
    assert "input closure" in record["reason"]
    assert (wdir / "native-inputs.json").read_bytes() == before
    assert all(path.read_text() == "old native capture\n" for path in wdir.glob("w_*.txt"))


def test_reuse_refuses_changed_native_capture_bytes(tmp_path, monkeypatch):
    bdir = _project(tmp_path)
    def completed(decks, *args):
        for tag, deck in decks.items():
            deck.with_suffix(".rc").write_text("0\n")
            deck.with_suffix(".log").write_text("native fixture completed\n")
            (deck.parent / f"w_{tag}.txt").write_text("time state cm fb reset\n")
        return {tag: 0 for tag in decks}
    monkeypatch.setattr(probe, "_run_decks", completed)
    probe.probe(tmp_path, "cell", "container", workers=2, threads=1)
    wdir = bdir / "loop_probe"
    before = (wdir / "native-outputs.json").read_bytes()
    next(wdir.glob("w_*.txt")).write_text("different native capture\n")
    monkeypatch.setattr(probe, "_run_decks", lambda *args: pytest.fail("reuse reran native"))
    rc, record = probe.probe(tmp_path, "cell", "container", reuse_records=True, workers=2, threads=1)
    assert rc == probe.RC_NO_RECORD and "output bytes differ" in record["reason"]
    assert (wdir / "native-outputs.json").read_bytes() == before
