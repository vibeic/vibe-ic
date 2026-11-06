#!/usr/bin/env python3
"""A9's producer runs the scenarios L22 declares, and the gate counts L22's.

Two halves of one fix (q5):

  * `analog_a9_cosim_emit` reads `L22.verification_plan.cosim_scenarios`,
    runs exactly those ids, stamps the L22 sha256 into every row, and never
    adds one of its own. A row it cannot run is NOT_MEASURED with its reason;
    an UNBOUNDED_IN_INPUT row is UNBOUNDED whatever it measured.
  * `mixed_signal_cosim_check` takes its denominator from the same L22 ids:
    a declared id with no result FAILs, a stale plan FAILs, an extra result is
    INFO, and NOT_MEASURED / UNBOUNDED / zero declared rows are rc 2.

The simulator is faked only where it writes: `FakeEngine.ngspice` returns the
measure values a transient would print, and `loadable` answers the libvvp
dlopen. Everything else is the programs' own code path. The observer log
excerpt is real: ngspice d_cosim + Icarus (libvvp) output from the A9 deck
this producer wrote, run on a real delta-sigma netlist.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import analog_a9_cosim_emit as A9  # noqa: E402
import l22_analog_verification_plan_emit as L22  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "a9_cosim_scenarios"
OBSERVER_LOG = FIXTURE / "a9_observer_ngspice_dcosim.txt"

# Minimal A3-shaped artefacts: the netlist's .subckt line and a testbench in
# the shape `analog_a3_netlist_emit` writes. No device content is needed —
# the engine is faked — but the pin/node structure is the real one.
_NETLISTS = {
    "delta_sigma": (
        ".subckt delta_sigma vdd vss vin vrefp vrefn clk bit_out\n"
        ".ends delta_sigma\n",
        "* tb\n.include delta_sigma.sp\n"
        "v_vdd vdd 0 pwl(0n 0 100n 1.2 28673000n 1.2)\n"
        "v_vrefp vrefp 0 1.1\nv_vrefn vrefn 0 0.1\n"
        "v_clk clk 0 pulse(0 1.2 1000n 1n 1n 499n 1000n)\n"
        "v_in vin 0 0.7\n"
        "xdut vdd 0 vin vrefp vrefn clk bit_out delta_sigma\n"
        ".options trtol=1\n.control\ntran 5n 28673000n\n.endc\n.end\n"),
    "ldo": (
        ".subckt ldo vin vss vref vout\n.ends ldo\n",
        "* tb\n.include ldo.sp\nv_vdd vin 0 1.8\nv_vref vref 0 0.6\n"
        "xdut vin 0 vref vout ldo\nr_load vout 0 1k\n"
        ".control\nop\n.endc\n.end\n"),
}


class FakeEngine:
    """Fakes only what the simulator writes."""

    def __init__(self, meas=None, vvp=False):
        self.container = "fake"
        self.meas = meas or {}
        self.vvp = vvp
        self.probed = []
        self.decks = []

    def loadable(self, library):
        self.probed.append(library)
        return (self.vvp, "" if self.vvp else
                f"OSError: {library}: cannot open shared object file")

    def ngspice(self, deck):
        self.decks.append(deck)
        return True, dict(self.meas), "fake ngspice log\n"

    def run(self, cmd, deadline_s=0):
        import subprocess
        self.commands = getattr(self, "commands", []) + [cmd]
        return subprocess.CompletedProcess(cmd, 1, stdout="fake: no compiler",
                                           stderr="")


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    shutil.copytree(FIXTURE, project)
    assert L22.run(project)["status"] == "OK"
    for block, (netlist, bench) in _NETLISTS.items():
        bdir = project / "phase3/analog" / block
        bdir.mkdir(parents=True)
        (bdir / f"{block}.sp").write_text(netlist)
        (bdir / f"tb_{block}.sp").write_text(bench)
        (bdir / "spec.json").write_text("{}")
    return project


def _results(project: Path) -> dict:
    return json.loads((project / "phase3/mixed_signal/cosim/"
                       "mixed_signal_results.json").read_text())


def _run(project, engine):
    return A9.run(project, engine=engine, libvvp=A9.LIBVVP_DEFAULT)


_IN_BOUNDS = {"a9_0_min": 1.15, "a9_0_max": 1.25,
              "a9_1_min": 1.15, "a9_1_max": 1.25}


# ── the producer ────────────────────────────────────────────────────────────
def test_it_runs_exactly_the_declared_ids_and_stamps_the_plan(tmp_path):
    project = _project(tmp_path)
    rc, report = _run(project, FakeEngine(meas=_IN_BOUNDS))
    _path, sha, plan = A9.load_plan(project)
    declared = [r["id"] for r in plan["cosim_scenarios"]]
    assert declared == ["S1", "S2", "S3", "S4", "S5"]
    assert [r["id"] for r in report["scenarios"]] == declared
    assert report["declared_ids"] == declared
    assert all(r["l22_sha256"] == sha for r in report["scenarios"])
    assert _results(project)["l22_sha256"] == sha
    assert rc == A9._pc.EX_ENV_REFUSED


def test_the_analog_arm_grades_the_declared_bounds(tmp_path):
    project = _project(tmp_path)
    _rc, report = _run(project, FakeEngine(meas=_IN_BOUNDS))
    s3 = {r["id"]: r for r in report["scenarios"]}["S3"]
    assert s3["arm"] == "ngspice"
    assert s3["verdict"] == "PASS"
    assert [c["verdict"] for c in s3["criteria"]] == ["PASS", "PASS"]


def test_a_supply_measured_outside_its_bound_fails(tmp_path):
    project = _project(tmp_path)
    low = dict(_IN_BOUNDS, a9_0_min=1.07277, a9_1_min=1.07277)
    _rc, report = _run(project, FakeEngine(meas=low))
    s3 = {r["id"]: r for r in report["scenarios"]}["S3"]
    assert s3["verdict"] == "FAIL"
    assert s3["criteria"][0]["measured"]["min"] == pytest.approx(1.07277)


def test_the_connection_replaces_the_consumers_supply(tmp_path):
    project = _project(tmp_path)
    _run(project, FakeEngine(meas=_IN_BOUNDS))
    deck = (project / "phase3/mixed_signal/cosim/S3/deck.sp").read_text()
    # The consumer's supply pin sits on the supplier's output node ...
    assert "xdelta_sigma ldo_vout 0 " in deck
    # ... and the testbench elements that drove or loaded that pin are gone.
    assert "v_vdd__delta_sigma" not in deck
    assert "r_load__ldo" not in deck
    assert "v_vdd__ldo ldo_vin 0 1.8" in deck
    # Every measure reaches the A4 reader through its MEAS echo summary.
    for i in (0, 1):
        assert f'echo "MEAS a9_{i}_min=" $&a9_{i}_min' in deck


def test_without_libvvp_every_dcosim_row_is_not_measured(tmp_path):
    project = _project(tmp_path)
    engine = FakeEngine(meas=_IN_BOUNDS, vvp=False)
    rc, report = _run(project, engine)
    assert engine.probed == [A9.LIBVVP_DEFAULT]
    rows = {r["id"]: r for r in report["scenarios"]}
    for sid in ("S1", "S2", "S4", "S5"):
        assert rows[sid]["arm"] == "d_cosim"
        assert rows[sid]["verdict"] == "NOT_MEASURED"
        assert rows[sid]["reason"].startswith("ENV_REFUSED:")
    assert rc == A9._pc.EX_ENV_REFUSED
    # The decks are still written, with the absolute libvvp path.
    deck = (project / "phase3/mixed_signal/cosim/S5/deck_held.sp").read_text()
    assert f'lib_args=["{A9.LIBVVP_DEFAULT}"]' in deck
    assert "d_cosim simulation=\"ivlng\"" in deck


def test_the_clock_bridge_has_no_unknown_band(tmp_path):
    """MEASURED: with an X band on the clock, 0->X and X->1 are each a Verilog
    posedge, and a real d_cosim run printed six 8-clock windows for 24 clocks.
    """
    import re
    project = _project(tmp_path)
    _run(project, FakeEngine(meas=_IN_BOUNDS))
    deck = (project / "phase3/mixed_signal/cosim/S5/deck_held.sp").read_text()
    clk_model = re.search(r"^a9_clk \[\S+\] \[a9_dclk\] (\S+)$", deck,
                          re.MULTILINE).group(1)
    m = re.search(rf"^\.model {clk_model} adc_bridge in_low=(\S+) "
                  rf"in_high=(\S+)$", deck, re.MULTILINE)
    assert m.group(1) == m.group(2)
    bit = re.search(r"^\.model a9_adc adc_bridge in_low=(\S+) in_high=(\S+)$",
                    deck, re.MULTILINE)
    assert float(bit.group(1)) < float(bit.group(2))


def test_the_sweep_is_run_against_the_reference(tmp_path):
    project = _project(tmp_path)
    _run(project, FakeEngine(meas=_IN_BOUNDS))
    d = project / "phase3/mixed_signal/cosim/S2"
    volts = [float(next(ln for ln in (d / f"deck_u{i}.sp").read_text()
                        .splitlines() if ln.startswith("v_a9_in")).split()[-1])
             for i in range(5)]
    # low reference 0.1, span 1.0: u = 0 .. 1 is 0.1 .. 1.1 V, never past it.
    assert volts == pytest.approx([0.1, 0.35, 0.6, 0.85, 1.1])


def test_resolution_is_never_graded_at_transistor_level(tmp_path):
    project = _project(tmp_path)
    _rc, report = _run(project, FakeEngine(meas=_IN_BOUNDS, vvp=True))
    s1 = {r["id"]: r for r in report["scenarios"]}["S1"]
    # libvvp loads and the (faked) compile fails: the ENOB criterion was
    # decided before any launch, and it is not a PASS.
    assert s1["criteria"][0]["verdict"] == "NOT_MEASURED"
    assert "sine fit" in s1["criteria"][0]["reason"]


def test_an_unbounded_row_never_passes():
    row = {"id": "S9", "grading": "UNBOUNDED_IN_INPUT"}
    assert A9.row_verdict(row, [{"verdict": "PASS"}]) == "UNBOUNDED"
    assert A9.row_verdict({"grading": "STRUCTURAL"}, []) == "UNBOUNDED"
    assert A9.row_verdict({"grading": "BOUNDED"},
                          [{"verdict": "PASS"}, {"verdict": "NOT_MEASURED"}]
                          ) == "NOT_MEASURED"


def test_no_declared_scenario_is_an_honest_gap(tmp_path):
    project = _project(tmp_path)
    path = project / "phase1/generated_docs/L22_VERIFICATION_PLAN.json"
    doc = json.loads(path.read_text())
    doc["fields"]["verification_plan"]["cosim_scenarios"] = []
    doc["fields"]["verification_plan"]["cosim_status"] = "NO_DERIVABLE_SCENARIOS"
    path.write_text(json.dumps(doc))
    rc, gap = _run(project, FakeEngine())
    assert rc == A9._pc.RC_HONEST_GAP
    assert gap["cosim_status"] == "NO_DERIVABLE_SCENARIOS"
    cosim = project / "phase3/mixed_signal/cosim"
    assert (cosim / A9.GAP_FILE).is_file()
    assert not (cosim / A9.RESULTS).exists()


# ── the observer's grammar, on real tool output ─────────────────────────────
def test_the_observer_lines_are_read_from_a_real_dcosim_log():
    windows = A9.observer_windows(OBSERVER_LOG.read_text())
    assert [(w["window"], w["ones"], w["code"], w["x"], w["n"])
            for w in windows] == [(0, 3, 13, 0, 8), (1, 5, 21, 0, 8),
                                  (2, 4, 14, 0, 8)]
    # 24 clocks, 8-clock windows: three, not six (the X-band double count).
    # The count and the member set together: three entries AND three distinct
    # window ids, so a double-counted window cannot hide behind either one.
    assert len(windows) == 3
    assert {w["window"] for w in windows} == {0, 1, 2}


def test_a_log_without_observer_lines_yields_no_window():
    assert A9.observer_windows("Circuit: x\nInitial Transient Solution\n") == []


def _w(*ones, x=0, n=8):
    return [{"window": i, "ones": o, "code": o, "x": x, "n": n}
            for i, o in enumerate(ones)]


@pytest.mark.parametrize("kind,points,want", [
    ("polarity", [(0, _w(0, 1)), (1, _w(0, 6))], "PASS"),
    ("polarity", [(0, _w(0, 6)), (1, _w(0, 1))], "FAIL"),
    ("monotonic", [(0, _w(0, 1)), (1, _w(0, 3)), (2, _w(0, 5))], "PASS"),
    ("monotonic", [(0, _w(0, 1)), (1, _w(0, 5)), (2, _w(0, 3))], "FAIL"),
    ("in_range", [(0, _w(0, 8))], "PASS"),
    ("in_range", [(0, _w(0, 9))], "FAIL"),
    ("logic_level", [(0, _w(0, 4))], "PASS"),
    ("logic_level", [(0, _w(0, 4, x=2))], "FAIL"),
    ("window_independent", [(0, _w(1, 4, 4))], "PASS"),
    ("window_independent", [(0, _w(1, 4, 5))], "FAIL"),
    ("window_independent", [(0, _w(4))], "NOT_MEASURED"),
])
def test_structural_graders_both_directions(kind, points, want):
    assert A9.grade_structural(kind, points)[0] == want


# ── the gate ────────────────────────────────────────────────────────────────
def _write_results(project, scenarios, sha=None):
    _p, cur, _plan = A9.load_plan(project)
    sha = cur if sha is None else sha
    out = project / "phase3/mixed_signal/cosim/mixed_signal_results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"l22_sha256": sha, "scenarios": [
        {"l22_sha256": sha, **s} for s in scenarios]}))




_ALL = ["S1", "S2", "S3", "S4", "S5"]


















# ── the runner reads the producer's tier from its exit code ─────────────────
def test_the_runner_records_an_env_refusal_as_env_unavailable(monkeypatch,
                                                              tmp_path):
    import subprocess
    import analog_one_shot_runner as R
    seen = {}

    def fake_run(argv, **_kw):
        seen["argv"] = argv
        return subprocess.CompletedProcess(
            argv, A9._pc.EX_ENV_REFUSED, stdout="S1 d_cosim NOT_MEASURED\n",
            stderr="ENV_REFUSED: libvvp is not loadable\n")
    monkeypatch.setattr(R._pr, "run", fake_run)
    rec = R._a9_cosim(tmp_path)
    assert rec["tier"] == "ENV_UNAVAILABLE"
    assert rec["detail"].startswith("ENV_REFUSED:")
    assert Path(seen["argv"][1]).name == "analog_a9_cosim_emit.py"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
