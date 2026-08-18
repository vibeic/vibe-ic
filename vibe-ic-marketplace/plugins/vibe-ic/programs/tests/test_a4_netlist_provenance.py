"""test_a4_netlist_provenance.py — A4 must not substitute for an absent A3.

MEASURED FAILURE THIS COMES FROM (an internal Phase-3 round, reproduced here on
a synthetic project):

    A1/A2/A3 were WAIVED for all ten declared analog blocks — 28-53 ms each,
    zero output files, and A3's declared output `phase3/analog/<block>/<block>.sp`
    existed for NONE of them. A4 nevertheless ran real ngspice over all ten
    blocks × nine PVT corners and wrote `_provenance: "real_ngspice"` for each;
    the A4 gate certified seven. Every deck ngspice consumed came from the
    built-in table `T[block_type]` inside `analog_real_corner_sweep.py` — a pure
    function of (canonical block type, PDK section, one sweep knob), byte-for-byte
    identical to the previous round's for all 126 decks, with no design content.
    `_provenance` was true about the SIMULATOR and silent about the SUBJECT.

    The three blocks whose sweep failed did so because the TEMPLATE cannot meet
    the hardcoded target (a voltage doubler reading 5e-15 V), not because
    anything of the design was wrong — nothing of the design had been netlisted.

THE RULE UNDER TEST: a step must not consume a substitute for an upstream step's
declared output while that output is absent, and an artefact must say which
circuit it measured.

Every fixture here is synthetic: generic block names (`vreg`, `ref`), an open
PDK selector, no design content.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
GATE = PROGRAMS / "analog_a4_corner_sweep_check.py"
RUNNER = PROGRAMS / "analog_one_shot_runner.py"

sys.path.insert(0, str(PROGRAMS))


# ───────────────────────────── synthetic fixture ───────────────────────────

def _project(tmp_path: Path, blocks, *, with_netlist=()) -> Path:
    """A minimal analog project. `blocks` is [(name, type)]; `with_netlist`
    names the blocks for which A3's declared output exists."""
    root = tmp_path / "proj"
    adir = root / "phase3" / "analog"
    adir.mkdir(parents=True, exist_ok=True)
    (adir / "analog_block_list.json").write_text(json.dumps(
        {"blocks": [{"name": n, "type": t} for n, t in blocks]}, indent=2))
    for name, _t in blocks:
        (adir / name).mkdir(parents=True, exist_ok=True)
    for name in with_netlist:
        # A plausible A3 output: a `.subckt` with real device cards, over the
        # 200-byte substance floor the A3 gate applies. Generic, no design.
        (adir / name / f"{name}.sp").write_text(
            f"* {name} — synthetic block netlist for provenance tests\n"
            f"* (stand-in for the analog-netlist-gen skill's output)\n"
            f".subckt {name} vdd vss vin vout\n"
            f"xm1 vout vin vss vss nch w=8 l=1\n"
            f"xm2 vout vin vdd vdd pch w=16 l=1\n"
            f"r1 vout vss 100k\n"
            f".ends {name}\n")
    return root


def _corners(project: Path, block: str, doc: dict) -> None:
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / "corner_results.json").write_text(json.dumps(doc, indent=2))


def _real_sim_doc(**extra) -> dict:
    """A corner_results.json shaped exactly like the one the sweep writes on a
    clean 9-corner run: nothing about it is wrong except, possibly, what it
    measured."""
    doc = {
        "block": "vreg", "block_type": "ldo",
        "_provenance": "real_ngspice",
        "simulator": "ngspice (docker)",
        "corners_executed": 2, "corners_derived": 0,
        "full_pvt_sweep_executed": True,
        "corners": [
            {"name": "tt_27c", "process": "tt", "temp_c": 27,
             "vout_v": 1.80, "simulator_run": True},
            {"name": "ss_m40c", "process": "ss", "temp_c": -40,
             "vout_v": 1.79, "simulator_run": True},
        ],
        "best_corner": {"name": "tt_27c", "value": 1.80},
        "spec_results": [
            {"name": "vout", "status": "PASS", "raw_sim_verdict": "PASS",
             "value": 1.80, "target": 1.8, "tolerance_pct": 0.05},
        ],
    }
    doc.update(extra)
    return doc


def _run_gate(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GATE), str(project),
         "--json", str(project / "report.json"), *args],
        capture_output=True, text=True)


def _rules(project: Path) -> list:
    rpt = json.loads((project / "report.json").read_text())
    return [f.get("rule") for f in (rpt.get("findings") or [])]


# ── SHAPE 1 — the producer refuses, and does not reach for the simulator ────

def test_sweep_refuses_when_a3_netlist_absent_and_never_touches_simulator(
        tmp_path: Path, monkeypatch) -> None:
    """A4's producer must not manufacture a deck in place of A3's output.

    The assertion that matters is `docker_calls == []`: pre-fix the sweep
    probed ngspice, resolved the PDK lib, wrote four decks of its own from
    `T["ldo"]` and invoked the simulator on them — all for a block that has no
    netlist. Refusing has to happen BEFORE the simulator, or the run still
    spends its 82-222 s per block measuring the template library."""
    import analog_real_corner_sweep as S

    project = _project(tmp_path, [("vreg", "ldo")])           # no vreg.sp
    calls: list = []

    def fake_docker(container, cmd, timeout=120):
        calls.append(cmd)
        if "command -v ngspice" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "/usr/bin/ngspice\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(S, "_docker", fake_docker)
    S._NGSPICE_CACHE.clear()
    S._CONTAINER_PATH_CACHE.clear()

    rc = S.run_block(project, "vreg", "fake-container", "sky130", "auto")

    bdir = project / "phase3" / "analog" / "vreg"
    assert calls == [], (
        f"A4 reached the simulator for a block with no A3 netlist: {calls[:4]}")
    assert not list((bdir / "sizing_loop").glob("*.sp")) \
        if (bdir / "sizing_loop").is_dir() else True, \
        "A4 wrote decks of its own in place of the absent A3 netlist"
    assert rc == 2

    cr = bdir / "corner_results.json"
    assert cr.is_file(), (
        "A4 must record WHY it produced nothing — a silent absence becomes an "
        "anonymous MISSING that names no blocker")
    doc = json.loads(cr.read_text())
    assert doc["_provenance"] == "upstream_netlist_missing"
    assert doc["status"] == "BLOCKED"
    assert doc["blocked_on"] == "A3_netlist_gen"
    assert doc["required_input"].endswith("vreg.sp")
    assert doc["required_skill"] == "analog-netlist-gen"
    assert doc["corners"] == [] and doc["spec_results"] == []
    assert doc["simulator_run"] is False


def test_sweep_records_deck_origin_when_it_does_run(
        tmp_path: Path, monkeypatch) -> None:
    """When the sweep DOES run, the artefact must say what circuit it ran on.

    UPDATED CONTRACT. This test used to assert that a netlist on disk was
    simulated as `builtin_template` anyway — the quiet half of the same
    substitution the loud half of this file forbids. A delivered artefact is
    now the subject of measurement, and half a delivered pair (a netlist with
    no stimulus, which is what this fixture writes) is refused rather than
    improvised over. The INTENT is unchanged and is what is checked here: the
    artefact must say which circuit it ran on, whatever the outcome.

    The consumption path itself is covered in
    `test_a4_consumes_design_netlist.py`."""
    import analog_real_corner_sweep as S

    project = _project(tmp_path, [("vreg", "ldo")], with_netlist=("vreg",))

    calls: list = []

    def fake_docker(container, cmd, timeout=120):
        calls.append(cmd)
        if "command -v ngspice" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "/usr/bin/ngspice\n", "")
        if "-b " in cmd and ".sp" in cmd:                 # the ngspice run
            return subprocess.CompletedProcess(
                cmd, 0, "MEAS vout=1.800000e+00\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(S, "_docker", fake_docker)
    S._NGSPICE_CACHE.clear()
    S._CONTAINER_PATH_CACHE.clear()

    # PRECONDITION — A3's declared netlist really is on disk, so this exercises
    # the "output present" path and not the already-covered absent one.
    assert (project / "phase3" / "analog" / "vreg" / "vreg.sp").is_file()

    rc = S.run_block(project, "vreg", "fake-container", "sky130", "auto")
    assert rc == 2, (
        "a netlist with no stimulus deck cannot be simulated without inventing "
        "its operating conditions")
    assert calls == [], f"the simulator was reached anyway: {calls[:3]}"
    assert not sorted((project / "phase3" / "analog" / "vreg"
                       / "sizing_loop").glob("*.sp")) \
        if (project / "phase3" / "analog" / "vreg" / "sizing_loop").is_dir() \
        else True

    doc = json.loads((project / "phase3" / "analog" / "vreg"
                      / "corner_results.json").read_text())
    assert doc.get("status") == "BLOCKED"
    assert doc.get("design_traceable") is False
    assert doc.get("netlist_present_but_unusable") == \
        "phase3/analog/vreg/vreg.sp", (
        "the record must say the netlist EXISTS and could not be used — a "
        "different fix from 'it was never produced'")
    assert doc.get("netlist_sha256"), (
        "the bytes that could not be used must still be identified")
    assert "tb_vreg.sp" in doc.get("reason", "")


# ── SHAPE 2 — the gate refuses to certify a self-authored circuit ───────────

def test_gate_fails_disclosed_builtin_deck(tmp_path: Path) -> None:
    """Nine real corners on the producer's own template is a self-test."""
    project = _project(tmp_path, [("vreg", "ldo")], with_netlist=("vreg",))
    _corners(project, "vreg", _real_sim_doc(
        netlist_provenance="builtin_template",
        netlist_source="phase3/analog/vreg/vreg.sp",
        deck_authored_by="analog_real_corner_sweep.T[block_type]"))

    r = _run_gate(project)
    assert r.returncode == 1, (
        f"gate certified a sweep of its own template deck (rc={r.returncode})")
    assert "A4_NETLIST_NOT_FROM_A3" in _rules(project)


def test_gate_fails_undisclosed_sweep_with_no_a3_netlist_on_disk(
        tmp_path: Path) -> None:
    """The measured round's exact shape: a perfectly-formed real_ngspice
    artefact, no `netlist_provenance` field at all, and no `<block>.sp`
    anywhere. Decided by the filesystem, so omitting the field evades
    nothing."""
    project = _project(tmp_path, [("vreg", "ldo")])           # no vreg.sp
    _corners(project, "vreg", _real_sim_doc())

    r = _run_gate(project)
    assert r.returncode == 1, (
        f"gate certified a sweep with no design netlist behind it "
        f"(rc={r.returncode})")
    assert "A4_NETLIST_ABSENT" in _rules(project)


def test_gate_fails_producer_blocked_record(tmp_path: Path) -> None:
    """The BLOCKED artefact the producer now writes must land as a NAMED FAIL
    that names A3 — not as `A4_NO_CORNERS`, which would describe the symptom
    and hide the cause."""
    project = _project(tmp_path, [("vreg", "ldo")])
    _corners(project, "vreg", {
        "block": "vreg", "block_type": "ldo", "status": "BLOCKED",
        "_provenance": "upstream_netlist_missing",
        "blocked_on": "A3_netlist_gen",
        "required_input": "phase3/analog/vreg/vreg.sp",
        "required_skill": "analog-netlist-gen",
        "corners": [], "spec_results": [], "simulator_run": False,
    })

    r = _run_gate(project)
    assert r.returncode == 1
    assert _rules(project) == ["A4_NETLIST_ABSENT"], (
        "a block blocked on A3 must be reported as blocked on A3")


def test_gate_passes_a3_derived_sweep(tmp_path: Path) -> None:
    """The negative control for the two rules above: an artefact whose deck IS
    derived from A3's output still passes. The fix is a provenance requirement,
    not a blanket refusal."""
    project = _project(tmp_path, [("vreg", "ldo")], with_netlist=("vreg",))
    # The design_content field joined the shape the sweep writes when the
    # record of WHERE a deck came from stopped being allowed to stand in for
    # the record of WHAT IS IN IT. An artefact that claims a3-derived and
    # stays silent on its content is now its own finding
    # (A4_DESIGN_CONTENT_UNDECLARED), so this negative control states the
    # content it is a control for.
    #
    # `netlist_sha256` used to be `"0" * 64` here — a placeholder, because
    # nothing re-computed it. That made this control assert something it never
    # meant to: that a corner artefact may record a hash of the netlist it
    # measured which is not that netlist's hash. Now that the recorded digest
    # is verified against the bytes on disk, the control records the REAL one.
    # Its subject is unchanged — an a3-derived deck still passes — and it no
    # longer doubles as a shipped statement that a fabricated digest certifies.
    netlist = project / "phase3" / "analog" / "vreg" / "vreg.sp"
    _corners(project, "vreg", _real_sim_doc(
        netlist_provenance="a3_netlist",
        netlist_source="phase3/analog/vreg/vreg.sp",
        design_content="structure_and_geometry",
        netlist_sha256=hashlib.sha256(netlist.read_bytes()).hexdigest()))

    r = _run_gate(project)
    assert r.returncode == 0, r.stdout + r.stderr
    rpt = json.loads((project / "report.json").read_text())
    assert rpt["verdict"] == "PASS"


def test_gate_leaves_derived_only_artefact_to_the_value_rules(
        tmp_path: Path) -> None:
    """An artefact that claims NO simulation is not accused of faking one — it
    still falls to the pre-existing `simulator_run: false` rule, so the new
    rules cannot mask the old ones."""
    project = _project(tmp_path, [("vreg", "ldo")])
    doc = _real_sim_doc()
    for c in doc["corners"]:
        c["simulator_run"] = False
    _corners(project, "vreg", doc)

    r = _run_gate(project)
    assert r.returncode == 1
    assert "A4_NO_SIMULATOR_RUN" in _rules(project)


# ── SHAPE 3 — the A1-A9 matrix must not read A4 as done on presence alone ──

def _matrix(project: Path) -> dict:
    prog = PROGRAMS / "analog_flow_compliance_check.py"
    subprocess.run(
        [sys.executable, str(prog), str(project),
         "--json", str(project / "afcc.json")],
        capture_output=True, text=True)
    rpt = json.loads((project / "afcc.json").read_text())
    return (rpt.get("summary") or {}).get("matrix") or {}


def test_matrix_does_not_read_a4_done_without_a_netlist(
        tmp_path: Path) -> None:
    """The measured round's matrix said, for the same block and in the same
    table, `A3: MISSING` and `A4: PASS` — a corner sweep certified over a
    netlist the run never produced. A cell that can read PASS while its own
    declared input reads MISSING is a presence probe wearing a verdict's
    clothes."""
    project = _project(tmp_path, [("vreg", "ldo")])           # no vreg.sp
    _corners(project, "vreg", _real_sim_doc())

    row = _matrix(project)["vreg"]
    assert row["A3"] == "MISSING", row
    assert row["A4"] != "PASS", (
        f"A1-A9 matrix reports A4 done while A3 is {row['A3']}: {row}")


def test_matrix_does_not_read_a4_done_on_a_blocked_record(
        tmp_path: Path) -> None:
    """The refusal record is A4 saying it produced nothing. A consumer that
    keys on the filename alone would read it as A4 done — the fix must not
    hand anyone a new false clean."""
    project = _project(tmp_path, [("vreg", "ldo")])
    _corners(project, "vreg", {
        "block": "vreg", "status": "BLOCKED",
        "_provenance": "upstream_netlist_missing",
        "blocked_on": "A3_netlist_gen",
        "required_input": "phase3/analog/vreg/vreg.sp",
        "corners": [], "spec_results": [], "simulator_run": False,
    })
    row = _matrix(project)["vreg"]
    assert row["A4"] != "PASS", row


def test_matrix_still_reads_a4_done_for_an_a3_derived_sweep(
        tmp_path: Path) -> None:
    """Negative control: a sweep with A3's netlist behind it still counts.

    Carries `design_content` for the same reason the sibling gate control
    above does: the matrix cell delegates to the gate's certification
    predicates, and an artefact that claims an upstream-derived deck while
    saying nothing about what is IN it is not one of them. Without the field
    this control would be asserting that the cell may sign off what the gate
    refuses."""
    project = _project(tmp_path, [("vreg", "ldo")], with_netlist=("vreg",))
    _corners(project, "vreg", _real_sim_doc(
        netlist_provenance="a3_netlist",
        design_content="structure_and_geometry",
        netlist_source="phase3/analog/vreg/vreg.sp"))
    row = _matrix(project)["vreg"]
    assert row["A3"] == "PASS", row
    assert row["A4"] == "PASS", row


# ── SHAPE 4 — the runner's record must agree with what is on disk ───────────

def test_runner_records_blocked_block_as_fail_not_waived(
        tmp_path: Path, monkeypatch) -> None:
    """WAIVED means "artefact not yet emitted". Once the sweep has written a
    BLOCKED corner_results.json that names its missing upstream, WAIVED is
    false about the filesystem — and a deferral is a bucket other steps can
    inherit, where a FAIL is not."""
    import analog_one_shot_runner as R

    project = _project(tmp_path, [("vreg", "ldo")])           # no vreg.sp

    class Args:
        allow_deterministic_stubs = False
        container = "no-such-container-for-tests"

    monkeypatch.setenv("VIBEIC_ANALOG_CONTAINER",
                       "no-such-container-for-tests")
    res = R.step_for_block(project, {"name": "vreg", "type": "ldo"},
                           "A4_corner_sweep", Args())

    assert res.status == "FAIL", (
        f"runner reported {res.status!r} for a block the sweep refused; the "
        f"artefact on disk states a named blocker")
    assert "A4_NETLIST_ABSENT" in (res.detail or "") \
        or "A3" in (res.detail or ""), res.detail


if __name__ == "__main__":                                    # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
