#!/usr/bin/env python3
"""M1-d4 — the PRODUCER of the evidence M1's verdict depends on was declared
nowhere and driven by nobody.

The audited defect
------------------
``mixed_signal_merge_check`` (M1's gate) only returns PASS when
``reports/analog/mixed_signal/top_lvs.json`` carries ``verdict == "PASS"``.
The one writer of that file — and of ``phase3/mixed_signal/top_merged.gds``,
M1's own declared ``required_output`` — is ``mixed_signal_top_lvs_run``.  It
appeared in no ``programs:`` list, in no gate, and in no runner.

Measured on a synthetic A+D fixture holding every input the producer needs
(digital sign-off GDS, A8 hardmacro GDS + Verilog stub, gate netlist)::

    M1 programs:       ['mixed_signal_merge_check']
    M1 gate commands:  ['mixed_signal_merge_check . --json .../merge.json']
    top_lvs.json produced by M1's declared execution? -> False

and through ``flow_compliance_check.check_step`` on a fresh A+D project::

    status: MISSING
    reason: no required_outputs found (expected:
            ['phase3/mixed_signal/top_merged.gds',
             'reports/analog/mixed_signal/merge.json'])

i.e. the artefact check short-circuits before the gate, so wiring the producer
into the gate ALONE could never make M1 reachable — the flow has to drive it.

What these tests pin
--------------------
The PROPERTY, not one particular spelling of the fix: M1 must declare a
program that really writes ``top_lvs.json`` (proved by RUNNING it against a
faked toolchain, never by grepping source), and the orchestrator must dispatch
one of those declared producers.  Any producer name satisfies them.

The direction-1 guards pin what must NOT move: M1 still FAILs on a merged GDS
with no / non-PASS top-level LVS, M1's ``required_outputs`` gains nothing, and
a digital-only run dispatches no mixed-signal merge at all.

chip-AGNOSTIC: synthetic fixtures + a monkeypatched container.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROGRAMS = Path(__file__).resolve().parent.parent
FLOW = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
sys.path.insert(0, str(PROGRAMS))

_TOP_LVS_REL = "reports/analog/mixed_signal/top_lvs.json"


# ── helpers ────────────────────────────────────────────────────────────────

def _m1_step() -> dict:
    doc = yaml.safe_load(FLOW.read_text())
    for st in doc["steps"]:
        if st.get("id") == "M1":
            return st
    raise AssertionError("step M1 not found in the flow yaml")


def _gate_commands(gate) -> list[str]:
    """Every program command line reachable from a step's gate tree."""
    out: list[str] = []
    if not isinstance(gate, dict):
        return out
    for key in ("program_exit_zero", "optional_program_exit_zero",
                "advisory_program_exit_zero"):
        spec = gate.get(key)
        if isinstance(spec, str):
            out.append(spec)
        elif isinstance(spec, dict) and isinstance(spec.get("command"), str):
            out.append(spec["command"])
    for sub in (gate.get("all_of") or []) + (gate.get("any_of") or []):
        out += _gate_commands(sub)
    return out


def _ad_fixture(root: Path) -> Path:
    """A mixed-signal project holding every input the top-level merge needs."""
    (root / "phase3/stage4/gds").mkdir(parents=True)
    (root / "phase3/stage4/gds/chip_top.gds").write_bytes(b"\x00\x06digital")
    hm = root / "phase3/analog/hardmacro/ldo"
    hm.mkdir(parents=True)
    (hm / "ldo.gds").write_bytes(b"\x00\x06macro")
    (hm / "ldo.v").write_text("module ldo(input en, output vout);\nendmodule\n")
    sy = root / "phase2/stage2/synth"
    sy.mkdir(parents=True)
    (sy / "chip_top_synth.v").write_text("module chip_top();\nendmodule\n")
    (root / "phase1/analog").mkdir(parents=True)
    (root / "phase1/analog/analog_block_list.json").write_text(
        json.dumps({"blocks": [{"name": "ldo"}]}))
    return root


def _fake_toolchain(lvs_text: str):
    """Stand in for `docker exec <container> …`: KLayout writes the merged
    GDS, Magic writes the extracted netlist, netgen writes an LVS report with
    `lvs_text`.  No real tool, no container, no PDK."""
    def fake(container, cmd, timeout=600, **_):
        if cmd.startswith("command -v") or cmd.startswith("test -f"):
            return 0, "", ""
        if "klayout" in cmd:
            m = re.search(r"MERGED_OUT=(\S+)", cmd)
            Path(m.group(1)).parent.mkdir(parents=True, exist_ok=True)
            Path(m.group(1)).write_bytes(b"\x00\x06merged")
            return 0, "KLAYOUT_MERGE_DONE", ""
        if "magic" in cmd:
            m = re.search(r"SPICE_OUT=(\S+)", cmd)
            Path(m.group(1)).write_text(".subckt chip_top a b\n.ends\n")
            return 0, "MAGIC_EXT2SPICE_DONE", ""
        if "netgen" in cmd:
            # The report path used to sit on the command line. It now lives in
            # the Tcl script netgen is told to `source`, because netgen's `lvs`
            # takes a two-element {file cell} list per side and the schematic
            # side is always several files -- they have to be read into one
            # netlist first, which needs a script. So the fake reads the script
            # the program actually wrote, exactly as netgen would.
            m = re.search(r"source\s+(\S+\.tcl)", cmd)
            assert m, f"netgen invoked without a script to source: {cmd}"
            tcl = Path(m.group(1)).read_text()
            rpt = re.search(r"(\S+/top_lvs\.rpt)", tcl.replace("{", " ")
                            .replace("}", " "))
            assert rpt, f"the netgen script names no report file:\n{tcl}"
            Path(rpt.group(1)).parent.mkdir(parents=True, exist_ok=True)
            Path(rpt.group(1)).write_text("Netgen 1.5\n" + lvs_text)
            return 0, lvs_text, ""
        return 0, "", ""
    return fake


def _declared_producers_of_top_lvs(tmp_path, monkeypatch) -> set[str]:
    """RUN every program M1 declares against an A+D fixture with a faked
    toolchain and return the names of those that actually wrote top_lvs.json.

    Deliberately execution-based: a source-substring search would miss a
    producer reached by any indirection, and would count a mention inside a
    comment as a write.  Each candidate gets its own project copy so one
    program's side effects cannot be credited to another.
    """
    step = _m1_step()
    tokens = set(step.get("programs") or [])
    for cmd in _gate_commands(step.get("gate")):
        tokens.add(cmd.split()[0])

    producers: set[str] = set()
    for tok in sorted(tokens):
        mod_path = PROGRAMS / f"{tok}.py"
        assert mod_path.is_file(), f"M1 declares {tok!r}, which does not exist"
        proj = _ad_fixture(tmp_path / f"run_{tok}")
        mod = __import__(tok)
        if hasattr(mod, "_docker_exec"):
            monkeypatch.setattr(
                mod, "_docker_exec",
                _fake_toolchain("Final result: Circuits match uniquely.\n"),
                raising=True)
        try:
            mod.main([str(proj)])
        except SystemExit:
            pass
        if (proj / _TOP_LVS_REL).is_file():
            producers.add(tok)
    return producers


# ── the defect ─────────────────────────────────────────────────────────────

def test_m1_declares_a_program_that_really_writes_its_verdict_evidence(
        tmp_path, monkeypatch):
    """M1's PASS is gated on top_lvs.json, so M1 must declare something that
    writes it.  Proved by execution, so the test does not care WHICH program
    is the producer nor how it is spelled."""
    producers = _declared_producers_of_top_lvs(tmp_path, monkeypatch)
    assert producers, (
        "M1's declared execution wrote no "
        f"{_TOP_LVS_REL} — mixed_signal_merge_check demands it for a PASS, so "
        "as declared M1 can only ever reach FAIL/SKIP. Declare (and invoke) "
        "the producer.")


def test_orchestrator_dispatches_one_of_m1s_declared_producers(
        tmp_path, monkeypatch):
    """`check_step` returns MISSING on absent required_outputs BEFORE it
    evaluates the gate, so a producer wired only into the gate is unreachable
    on a fresh project.  The flow itself has to drive it."""
    producers = _declared_producers_of_top_lvs(tmp_path, monkeypatch)
    assert producers, "no declared producer to dispatch (see sibling test)"

    import vibe_ic_one_shot_runner as ORCH

    proj = tmp_path / "orch"
    (proj / "phase3/analog").mkdir(parents=True)
    (proj / "phase3/analog/analog_block_list.json").write_text(
        json.dumps({"blocks": [{"name": "ldo"}]}))
    (proj / "phase2/stage1/rtl").mkdir(parents=True)
    (proj / "phase2/stage1/rtl/chip_top.v").write_text(
        "module chip_top(); endmodule\n")

    dispatched: list[str] = []

    def _record(label, runner, args, env=None):
        dispatched.append(Path(runner).stem)
        return 0

    monkeypatch.setattr(ORCH, "_run_phase", _record)
    monkeypatch.setattr(sys, "argv",
                        ["vibe_ic_one_shot_runner", str(proj),
                         "--skip-phase1", "--no-dashboard"])
    ORCH.main()

    assert producers & set(dispatched), (
        f"the orchestrator dispatched {dispatched} — none of them is a "
        f"declared M1 producer ({sorted(producers)}), so nothing in the flow "
        "ever writes the merged GDS or the top-level LVS result and M1 stays "
        "MISSING on every automated run.")


def test_mixed_signal_dispatch_cannot_drag_the_digital_verdict_down(
        tmp_path, monkeypatch):
    """The merge is driven for its ARTEFACTS; the verdict belongs to the M1
    gate.  A producer failure must be recorded, not turned into a digital
    sign-off failure — the same contract the A-track already has."""
    import vibe_ic_one_shot_runner as ORCH

    proj = tmp_path / "orch_fail"
    (proj / "phase3/analog").mkdir(parents=True)
    (proj / "phase3/analog/analog_block_list.json").write_text(
        json.dumps({"blocks": [{"name": "ldo"}]}))
    (proj / "phase2/stage1/rtl").mkdir(parents=True)
    (proj / "phase2/stage1/rtl/chip_top.v").write_text(
        "module chip_top(); endmodule\n")

    producers = _declared_producers_of_top_lvs(tmp_path, monkeypatch)

    def _record(label, runner, args, env=None):
        return 1 if Path(runner).stem in producers else 0

    monkeypatch.setattr(ORCH, "_run_phase", _record)
    monkeypatch.setattr(sys, "argv",
                        ["vibe_ic_one_shot_runner", str(proj),
                         "--skip-phase1", "--no-dashboard"])
    ORCH.main()

    rep = json.loads(
        (proj / "reports/orchestrator/vibe_ic_one_shot.json").read_text())
    phases = {p["name"]: p for p in rep["phases"]}
    assert "mixed_signal" in phases, (
        f"no mixed-signal phase in the run record: {sorted(phases)}")
    assert phases["mixed_signal"]["rc"] == 1, "producer failure not recorded"
    assert rep["verdict"] != "FAIL", (
        "a mixed-signal merge failure dragged the digital verdict to FAIL; it "
        "must be recorded and left to the M1 gate, like the A-track")


# ── direction-1 guards: what must NOT change ───────────────────────────────

def test_every_program_m1_declares_is_invoked_by_m1(tmp_path):
    """The flow yaml's own contract. A declaration nothing runs is the orphan
    this whole class of defect is made of — adding one to fix another would
    be no fix at all."""
    step = _m1_step()
    invoked = {c.split()[0] for c in _gate_commands(step.get("gate"))}
    declared = set(step.get("programs") or [])
    assert declared, "M1 declares no programs at all"
    assert declared <= invoked, (
        f"M1 declares {sorted(declared - invoked)} under `programs:` but no "
        f"gate member invokes them (gate invokes: {sorted(invoked)})")


def test_m1_required_outputs_stay_the_two_design_artefacts():
    """Guards against paying for the wiring with a manufactured MISSING, and
    against declaring the producer's own run record: top_lvs_run.json exists
    even on the producer's honest rc=2 skip, so declaring it would let the
    gate's own side effect satisfy M1's artefact check."""
    assert _m1_step().get("required_outputs") == [
        "phase3/mixed_signal/top_merged.gds",
        "reports/analog/mixed_signal/merge.json",
    ]


def test_m1_still_fails_on_a_merged_gds_with_no_top_level_lvs(tmp_path):
    """Presence is not substance — unchanged by the wiring."""
    import mixed_signal_merge_check as M1
    ms = tmp_path / "phase3" / "mixed_signal"
    ms.mkdir(parents=True)
    (ms / "top_merged.gds").write_bytes(b"\x00\x06merged")
    out = tmp_path / "m1.json"
    assert M1.main([str(tmp_path), "--json", str(out)]) == 1
    rep = json.loads(out.read_text())
    assert any(f["rule"] == "MERGE_NOT_LVS_SUBSTANTIATED"
               for f in rep["findings"])


def test_m1_still_fails_when_the_top_level_lvs_did_not_match(tmp_path):
    """A produced-but-FAILing LVS must stay a FAIL. Wiring a producer must
    never become a way to satisfy the gate by merely having run."""
    import mixed_signal_merge_check as M1
    ms = tmp_path / "phase3" / "mixed_signal"
    ms.mkdir(parents=True)
    (ms / "top_merged.gds").write_bytes(b"\x00\x06merged")
    rpt = tmp_path / "reports" / "analog" / "mixed_signal"
    rpt.mkdir(parents=True)
    (rpt / "top_lvs.json").write_text(json.dumps({"verdict": "FAIL"}))
    assert M1.main([str(tmp_path)]) == 1


def test_digital_only_run_dispatches_no_mixed_signal_merge(tmp_path,
                                                           monkeypatch):
    """A project with no analog blocks is the overwhelming majority and the
    one the reference run (spm x ihp-sg13g2) exercises: it must not gain a
    merge step, a container call, or a new phase verdict."""
    import vibe_ic_one_shot_runner as ORCH

    proj = tmp_path / "digital_only"
    (proj / "phase2/stage1/rtl").mkdir(parents=True)
    (proj / "phase2/stage1/rtl/chip_top.v").write_text(
        "module chip_top(); endmodule\n")

    dispatched: list[str] = []

    def _record(label, runner, args, env=None):
        dispatched.append(Path(runner).stem)
        return 0

    monkeypatch.setattr(ORCH, "_run_phase", _record)
    monkeypatch.setattr(sys, "argv",
                        ["vibe_ic_one_shot_runner", str(proj),
                         "--skip-phase1", "--no-dashboard"])
    ORCH.main()

    assert "mixed_signal_top_lvs_run" not in dispatched
    assert not (proj / "phase3" / "mixed_signal").exists()
    rep = json.loads(
        (proj / "reports/orchestrator/vibe_ic_one_shot.json").read_text())
    for ph in rep["phases"]:
        if ph["name"] == "mixed_signal":
            assert ph["verdict"] == "SKIPPED"


def test_producer_skips_honestly_when_it_cannot_run(tmp_path):
    """The disclosed capability-gap skip the advisory gate slot relies on:
    absent inputs are rc=2 with a NAMED reason, never a silent 0."""
    import mixed_signal_top_lvs_run as TL
    rep = TL.run(tmp_path, "chip_top", "no-such-container", "sky130A")
    assert rep["rc"] == 2
    assert rep["verdict"] == "SKIP"
    assert rep.get("reason"), "an rc=2 skip with no reason discloses nothing"
    assert not (tmp_path / _TOP_LVS_REL).exists(), (
        "a skipped producer must not leave a top_lvs.json behind — the M1 "
        "gate would read it as a real LVS result")
