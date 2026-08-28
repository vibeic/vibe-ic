"""The runner must actually CALL the A1-A3 producers.

A producer nothing invokes is the disease, not the cure: the A8 GDS emitter's
own docstring records that `magic_port_extract_emit.build_gds_write_tcl` sat
"documented and unit-tested, for many releases" and was "referenced only by
its own unit test and by the skill's prose", so A8 declared a layout nothing
produced.

These tests assert the DISPATCHED argv and the resulting StepResult — the same
shape `test_analog_hardmacro_gds_emit` uses — never a grep of the runner
source, which would pass on a call site that is dead.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import _plugin_tree  # noqa: F401  — puts programs/ on sys.path

import analog_one_shot_runner as R
from _analog_producer_fixture import block, make_project, bdir, read_json


STEPS = [
    ("A1_spec_extract", "analog_a1_spec_emit.py", "PASS_WITH_REAL_EXTRACT",
     "spec.json"),
    ("A2_topology_select", "analog_a2_topology_emit.py",
     "PASS_WITH_DERIVED_TOPOLOGY", "topology.md"),
    ("A3_netlist_gen", "analog_a3_netlist_emit.py", "PASS_WITH_REAL_NETLIST",
     "vreg_alpha.sp"),
]


@pytest.mark.parametrize("step,program,status,artefact", STEPS)
def test_the_runner_dispatches_the_producer_at_its_own_step(
        tmp_path, monkeypatch, step, program, status, artefact):
    """The gate says rc 2; the producer must be invoked BEFORE the runner
    falls through to WAIVED, and the step must come back with the producer's
    own status once the gate re-runs clean."""
    p = make_project(tmp_path, [block("vreg_alpha", "ldo",
                                      [{"name": "Vout", "target": 1.8,
                                        "unit": "V"},
                                       {"name": "Vref", "target": 0.9,
                                        "unit": "V"}])])
    blk = {"name": "vreg_alpha", "type": "ldo"}
    # The steps are a CHAIN — A3 renders the IR A2 writes, from the spec A1
    # binds — so the ones before the step under test have to have run.
    for earlier in ("A1_spec_extract", "A2_topology_select",
                    "A3_netlist_gen"):
        if earlier == step:
            break
        R.step_for_block(p, blk, earlier)

    seen = []
    # The runner launches producers through TWO seams: `_pr.run` (progress
    # supervised) and, at the three sites the timeout census classified
    # NOT_MEASURED rather than verdict-bearing, still `subprocess.run`. A spy on
    # one of them answers "the producer was never dispatched" for a run that
    # dispatched it through the other, so both are watched.
    real_pr, real_sp = R._pr.run, R.subprocess.run

    def _spy(real):
        def spy(cmd, *a, **kw):
            seen.append(list(cmd))
            return real(cmd, *a, **kw)
        return spy

    monkeypatch.setattr(R._pr, "run", _spy(real_pr))
    monkeypatch.setattr(R.subprocess, "run", _spy(real_sp))
    res = R.step_for_block(p, blk, step)

    dispatched = [c for c in seen if any(program in str(t) for t in c)]
    assert dispatched, (
        f"{step} never invoked `{program}`; the producer exists and nothing "
        f"calls it. argv seen: {seen}")
    argv = dispatched[0]
    assert str(p) in argv and "--block" in argv
    assert argv[argv.index("--block") + 1] == "vreg_alpha"

    if step == "A3_netlist_gen":
        # A3 must be simulated INSIDE the flow, not only when someone
        # remembers the flag. Safe by the producer's contract: an unreachable
        # container is recorded, never turned into a FAIL.
        assert "--verify-sim" in argv, argv
        assert "--container" in argv, argv

    assert res.status == status, res.detail
    assert res.extras.get("producer") == program
    assert res.extras.get("low_confidence") is False
    assert any(artefact in f for f in res.output_files), (
        f"the runner's own record must NAME what the step produced; "
        f"output_files={res.output_files}")
    assert (bdir(p, "vreg_alpha") / artefact).is_file()


def test_a_declining_producer_leaves_the_step_WAIVED_and_names_the_gap(
        tmp_path):
    """Producing is not a verdict. A block the deterministic track cannot do
    must stay WAIVED — never become a FAIL the gate has not itself found —
    and the runner must surface WHERE the reason was written."""
    p = make_project(tmp_path, [block("keeper_x", "pull", specs=None)])
    res = R.step_for_block(p, {"name": "keeper_x", "type": "pull"},
                           "A1_spec_extract")
    assert res.status == "WAIVED", res.detail
    assert res.extras.get("gap_path", "").endswith("spec_gap.json"), res.extras
    assert "analog-spec-extract" in res.detail
    assert not (bdir(p, "keeper_x") / "spec.json").exists()
    gap = read_json(bdir(p, "keeper_x") / "spec_gap.json")
    assert gap["status"] == "NO_SPEC_IN_DOCS"


def test_a_crashing_producer_does_not_turn_a_step_into_a_FAIL(
        tmp_path, monkeypatch):
    p = make_project(tmp_path, [block("keeper_x", "pull", specs=None)])
    # Both launch seams, for the reason given at the spy above: the producer
    # this test crashes is dispatched through `subprocess.run`, not `_pr.run`.
    real_pr, real_sp = R._pr.run, R.subprocess.run
    exploded = []

    def _boom(real):
        def boom(cmd, *a, **kw):
            if any("analog_a1_spec_emit" in str(t) for t in cmd):
                exploded.append(list(cmd))
                raise OSError("simulated producer crash")
            return real(cmd, *a, **kw)
        return boom

    monkeypatch.setattr(R._pr, "run", _boom(real_pr))
    monkeypatch.setattr(R.subprocess, "run", _boom(real_sp))
    res = R.step_for_block(p, {"name": "keeper_x", "type": "pull"},
                           "A1_spec_extract")
    # PRECONDITION: WAIVED is also what a runner that never dispatches a
    # producer returns, so without this the test passes on a tree where the
    # crash never happened.
    assert exploded, (
        "the producer was never dispatched, so nothing crashed and the "
        "WAIVED below would prove nothing")
    assert res.status == "WAIVED", (
        f"a producer crash must leave the step where the GATE left it, not "
        f"invent a failure: {res.status} / {res.detail}")


def test_the_full_analog_chain_produces_what_each_step_declares(tmp_path):
    """A1 -> A2 -> A3 in order, on one block that can be done and one that
    cannot. The chain must produce for the first and defer for the second,
    and the deferral must not be quiet."""
    p = make_project(tmp_path, [
        block("vreg_alpha", "ldo", [{"name": "Vout", "target": 1.8,
                                     "unit": "V"},
                                    {"name": "Vref", "target": 0.9,
                                     "unit": "V"}]),
        block("widget_q", "charge_pump", specs=None),
    ])
    got = {}
    for blk in ("vreg_alpha", "widget_q"):
        for step in ("A1_spec_extract", "A2_topology_select",
                     "A3_netlist_gen"):
            got[(blk, step)] = R.step_for_block(
                p, {"name": blk, "type": ("ldo" if blk == "vreg_alpha"
                                          else "charge_pump")}, step)

    for step in ("A1_spec_extract", "A2_topology_select", "A3_netlist_gen"):
        r = got[("vreg_alpha", step)]
        assert r.status.startswith("PASS"), (step, r.status, r.detail)
        assert r.output_files, (step, "produced nothing it can name")
        r2 = got[("widget_q", step)]
        assert r2.status == "WAIVED", (step, r2.status)
        assert r2.extras.get("gap_path"), (
            f"{step} deferred on widget_q without recording where it said "
            f"why")

    assert not list((bdir(p, "widget_q")).glob("*.sp")), (
        "a block the deterministic track deferred on must not have acquired "
        "a netlist along the way")


# ── A4: the RUN RECORD must name the circuit, not only the simulator ────────

def test_the_run_record_names_the_circuit_a4_measured(tmp_path, monkeypatch):
    """`real ngspice` with `output_files: []` names the tool and not the work.

    The whole failure this round comes from is a record that was true about the
    simulator and silent about the subject. Fixing it only inside the artefact
    leaves the run log — the thing a reviewer actually reads first — saying
    exactly as little as before.

    Driven through the runner with a stubbed simulator, so the assertion is on
    the StepResult the runner really returns, not on the runner's source.
    """
    p = make_project(tmp_path, [block("vreg_alpha", "ldo",
                                      [{"name": "Vout", "target": 1.8,
                                        "unit": "V"}])])
    blk = {"name": "vreg_alpha", "type": "ldo"}
    for earlier in ("A1_spec_extract", "A2_topology_select", "A3_netlist_gen"):
        R.step_for_block(p, blk, earlier)
    # PRECONDITION — A3 really delivered the pair A4 is supposed to consume.
    assert (bdir(p, "vreg_alpha") / "vreg_alpha.sp").is_file()
    assert (bdir(p, "vreg_alpha") / "tb_vreg_alpha.sp").is_file()

    import analog_real_corner_sweep as S

    def fake_docker(container, cmd, timeout=120):
        if "command -v ngspice" in cmd or "ls /foss/tools" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "/usr/bin/ngspice\n", "")
        if "--json-measure" in cmd and " -v " in cmd:
            return subprocess.CompletedProcess(cmd, 0, "unrecognized option", "")
        if cmd.startswith("grep -ioE") and ".lib" in cmd:
            return subprocess.CompletedProcess(
                cmd, 0, ".lib ss\n.lib tt\n.lib ff\n", "")
        if " -b " in cmd and ".sp" in cmd:
            return subprocess.CompletedProcess(
                cmd, 0, "MEAS vout=1.800000e+00\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(S, "_docker", fake_docker)
    S._NGSPICE_CACHE.clear()
    S._CONTAINER_PATH_CACHE.clear()
    S._JSON_MEASURE_SUPPORT.clear()
    S._PDK_SECTION_CACHE.clear()
    # The runner shells out; keep the sweep in-process so the stub applies.
    real = subprocess.run

    def spy(cmd, *a, **kw):
        if any("analog_real_corner_sweep" in str(t) for t in cmd):
            argv = [str(t) for t in cmd]
            rc = S.run_block(Path(argv[2]),
                             argv[argv.index("--block") + 1],
                             "fake", "sky130", "auto")
            return subprocess.CompletedProcess(cmd, rc, "", "")
        return real(cmd, *a, **kw)

    monkeypatch.setattr(R._pr, "run", spy)
    res = R.step_for_block(p, blk, "A4_corner_sweep")

    # The deterministic A3 producer resolves this block's netlist from a
    # topology library — the project's documents bound no quantity that reaches
    # a device parameter — and RECORDS that. The sweep republishes it and the
    # gate discloses it, so the runner's own disposition for this step is the
    # structure-only tier rather than a plain real-sim pass. "PASS_WITH_REAL_SIM"
    # here would be the original defect in the run log: a status that is true
    # about the SIMULATOR and silent about the SUBJECT.
    assert res.status == "PASS_STRUCTURE_ONLY", res.detail
    assert res.extras.get("design_content") == "structure_only", res.extras
    assert (res.extras.get("design_content_source") or "").endswith(
        "corner_results.json"), res.extras
    assert res.extras.get("design_traceable") is True, res.extras
    assert res.extras.get("deck_source") == "a3_netlist", res.extras
    assert (res.extras.get("netlist_source") or "").endswith(
        "vreg_alpha.sp"), res.extras
    assert any("corner_results.json" in f for f in res.output_files), (
        f"the run record must NAME the artefact: {res.output_files}")
    # BOTH halves on the one line a reviewer reads: which circuit, and what is
    # in it. Neither replaces the other.
    assert "vreg_alpha.sp" in res.detail, (
        f"the one line a reviewer reads must say which circuit: {res.detail!r}")
    assert "STRUCTURE_ONLY" in res.detail, (
        f"...and what was in it: {res.detail!r}")
