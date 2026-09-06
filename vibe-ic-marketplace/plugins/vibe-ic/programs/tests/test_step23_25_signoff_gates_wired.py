#!/usr/bin/env python3
"""Steps 23 / 25 — the sign-off gates the flow DECLARED that nothing ran.

THE DEFECT, in two layers.

(1) NOT WIRED. `flow/phase1_phase2_phase3.yaml` declares four checkers across
    the two post-route sign-off steps — `sta_report_check`,
    `post_route_signoff_corner_check`, `sta_corner_record_completeness_check`
    (step 23) and `em_report_check` (step 25). No runner ever invoked any of
    them. The phase-3 orchestrators never load the flow yaml, and the only
    `flow_compliance_check` call in the runner chain is `design_one_shot_runner`
    at `--phase 2 --strict-structural`, whose verdict is filtered to `r.id ==
    'P0'` and never reaches stage3. The plugin's own
    `flow_gate_enforcement_audit` classified them AUDIT_ONLY.

(2) THE PRODUCER DROPPED ITS OUTPUT FLAG. `sta_report_check` and
    `em_report_check` rebuilt argv as `main([sys.argv[1], "--mode", <mode>])`,
    discarding the `--json <path>` the flow declares. Measured on the real
    completed run `campaign_pr427/spm/converge_ihp-sg13g2`:

        $ sta_report_check . --mode phase3/stage3/sta \
              --json reports/phase3/sta/post_route_summary.json
        rc=0        # and no file written

    `reports/phase3/sta/post_route_summary.json` is step 23's own
    `required_outputs` entry and this wrapper is its ONLY declared producer
    anywhere in the plugin, so a declared sign-off output had no producer at
    all. The same held for step 10's `pre_pnr_summary.json`.

    The dropped flag also hid an output-path COLLISION: step 25 declared its
    audit output at `reports/phase3/em.json`, which is where the PRODUCER
    (`step_canonicalize_artefacts` → `_emit_ir_em_reports`) writes the
    measurement the runner reads back as EM evidence. Honouring the flag
    without moving the path would have destroyed the measurement.

WHAT THIS COSTS — measured over the 14 published phase-3 run-roots under
`benchmark-data/ic` BEFORE wiring anything, the same corpus and evidence bar
#306 used:

    sta_report_check                      FAILs  9/14
    sta_corner_record_completeness_check  FAILs  6/14
    em_report_check                       FAILs  6/14
    post_route_signoff_corner_check       FAILs  2/14

Those are real findings. The sharpest: `sha256/clean_run_v1422_20260715`, a run
published as CLEAN, reports `setup worst-slack -1.710 ns at the sign-off
(max-RC) corner is VIOLATED` — verbatim the #147 defect step 23's gate comment
was written about, sitting in the corpus undetected because the gate that
detects it had no caller. On the real completed run all four return rc 0.

DIRECTION-1 GUARDS (`test_d1_*`) assert the behaviour that must NOT change and
hold on the pre-fix tree as well: the bare `<wrapper> <project>` call shape, the
NOT_APPLICABLE self-skips that make unconditional wiring safe, and the producer's
`reports/phase3/em.json` measurement staying untouched.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent
_FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
_RUNNER_SRC = _PROGRAMS / "phase3_one_shot_runner.py"

sys.path.insert(0, str(_PROGRAMS))

# Padding to clear eda_report_audit's MIN_REPORT_BYTES anti-fabrication floor.
_PAD = "# " + ("=" * 78 + "\n") * 40  # ~3.2 KB

_STA_RPT = (
    "OpenSTA 2.4.0 report_checks\n"
    "Startpoint: reg_a (rising edge-triggered flip-flop clocked by clk)\n"
    "Endpoint: reg_b (rising edge-triggered flip-flop clocked by clk)\n"
    "Path Type: max\n"
    "WNS = 0.15 ns\nTNS = 0.0 ns\n"
    "slack (MET)\nsetup check: PASS\nhold check: PASS\n"
    "data arrival time: 2.34 ns\n" + _PAD
)

_EM_RPT = (
    "OpenROAD Electromigration Analysis\n"
    "EM lifetime: 10 years worst-case\n"
    "Javg = 2.5 mA/um  current density\n"
    "Jpeak = 8.1 mA/um  peak current\n"
    "RMS current: 3.2 mA/um\n" + _PAD
)

# The #147 shape: nominal-clean, sign-off corner violated.
_MULTICORNER_VIOLATED = (
    "# Multi-corner SPEF STA (TAPEOUT-SIGNOFF P1)\n"
    "# SETUP corner: max-RC   HOLD corner: min-RC\n"
    "=== SETUP (max-RC corner, SPEF=max) ===\n"
    "worst slack max -1.71\n"
    "=== HOLD (min-RC corner, SPEF=min) ===\n"
    "worst slack min 0.54\n"
)


#: CZT2-16 — THE INNER BOUND IS GONE, and the reasoning that justified it is
#: what removed it. It read: "every gate driven here is a pure report reader
#: that returns in well under a second (measured over the whole published
#: corpus: 70 invocations, none slower than a few hundred ms), so a small bound
#: is honest." A bound chosen because the work is short is a bound that only
#: ever fires when the HOST is slow, which is not a fact about the gate.
#: `_run_declared_signoff_gate` now supervises the child's own forward progress
#: and takes no `timeout` at all, so there is no argument left to pass.
#:
#: The concern the constant also served -- staying BELOW CI's `--timeout=180`
#: harness bound (#542), so a wedged test fails as one test instead of killing
#: the whole subset -- is unaffected: the harness bound is the harness's, and a
#: genuinely wedged gate is now stopped by the supervisor as a STALL, which is
#: a finding about the child rather than a number about the host.

#: The verdicts `phase3_one_shot_runner.main` treats as a releasing run.
_RELEASING = ("PASS", "PASS_WITH_WAIVERS", "PASS_WITH_OPEN_SOURCE_CONSTRAINTS")


def _run(prog: str, *args: str) -> subprocess.CompletedProcess:
    return _pr.run([sys.executable, str(_PROGRAMS / prog), *args],
                          capture_output=True, text=True)


def _project(tmp: Path) -> Path:
    """A minimal but tool-authentic post-route project."""
    sta = tmp / "phase3" / "stage3" / "sta"
    sta.mkdir(parents=True)
    (sta / "post_route_timing.rpt").write_text(_STA_RPT)
    rpt = tmp / "reports" / "phase3"
    rpt.mkdir(parents=True)
    (rpt / "em.rpt").write_text(_EM_RPT)
    # A DECLARED DELIVERY ROUTE. The sixth declared sign-off gate
    # (`tapeout_precheck`, wired 2026-09-04) reads it to decide whether a
    # tape-out precheck applies at all, and a project with NO route is left
    # NOT_DETERMINED on purpose — 0.5ic failing is when a chip most needs that
    # step. The IP terminal keeps this a STA/EM fixture: no die, so no die to
    # check.
    st = tmp / "input" / "submission_template"
    st.mkdir(parents=True, exist_ok=True)
    (st / "NO_TEMPLATE.txt").write_text(
        "# submission_template_ingest: no template record\n"
        "STATUS: ABSENT — this fixture delivers an IP, not a die.\n")
    return tmp


# ===========================================================================
# (2) The producer honours the output flag the flow declares
# ===========================================================================
def test_sta_report_check_writes_the_json_the_caller_asked_for(tmp_path):
    """Step 23's `required_outputs` entry, produced by its only declared
    producer. Pre-fix this returned rc 0 and wrote nothing at all."""
    proj = _project(tmp_path)
    out = proj / "reports" / "phase3" / "sta" / "post_route_summary.json"
    r = _run("sta_report_check.py", str(proj), "--mode", "sta",
             "--json", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    assert out.is_file(), (
        "sta_report_check discarded --json: step 23's declared "
        "required_outputs entry has no producer")
    doc = json.loads(out.read_text())
    assert doc["program"] == "eda_report_audit:sta", doc
    assert doc["passed"] is True, doc


def test_em_report_check_writes_the_json_the_caller_asked_for(tmp_path):
    proj = _project(tmp_path)
    out = proj / "reports" / "phase3" / "em_signoff.json"
    r = _run("em_report_check.py", str(proj), "--mode", "em",
             "--json", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    assert out.is_file(), "em_report_check discarded --json"
    assert json.loads(out.read_text())["program"] == "eda_report_audit:em"


def test_wrapper_does_not_swallow_an_invalid_mode(tmp_path):
    """The stale declaration `--mode phase3/stage3/sta` is a PATH, not one of
    eda_report_audit's seven report classes. It only ever "worked" because the
    wrapper rebuilt argv and threw it away — a broken declaration that could
    not be seen. It must now reach argparse."""
    proj = _project(tmp_path)
    r = _run("sta_report_check.py", str(proj), "--mode", "phase3/stage3/sta")
    assert r.returncode == 2, (
        "an invalid --mode is still being absorbed by the wrapper")
    assert "invalid choice" in (r.stderr + r.stdout)


# ===========================================================================
# The DECLARATIONS the wrappers are driven by
# ===========================================================================
def _flow_invocations(program: str):
    """Every `<program> ...` command string declared in the flow yaml."""
    return re.findall(rf'"({re.escape(program)} [^"]*)"',
                      _FLOW.read_text(errors="replace"))


@pytest.mark.parametrize("program", ["sta_report_check", "em_report_check"])
def test_flow_declares_a_real_report_mode(program):
    """A `--mode` that is not an eda_report_audit choice is an argparse error
    (rc 2), which `flow_compliance_check` reads as VACUOUS_PASS — i.e. a
    broken declaration would buy PASS credit. Pin every declaration to a real
    mode so it cannot drift back."""
    import eda_report_audit  # noqa: WPS433
    valid = set(eda_report_audit.MODE_MAP)
    invocations = _flow_invocations(program)
    assert invocations, f"{program} is no longer declared in the flow"
    for cmd in invocations:
        toks = cmd.split()
        assert "--mode" in toks, cmd
        mode = toks[toks.index("--mode") + 1]
        assert mode in valid, (
            f"flow declares `--mode {mode}` for {program}; valid modes are "
            f"{sorted(valid)}")


def test_step25_audit_json_does_not_clobber_the_em_measurement():
    """`reports/phase3/em.json` is the PRODUCER's file — the measurement
    (`verdict: MEASURED`, max_segment_current_A) that phase3_one_shot_runner
    reads back as step 25's evidence. The audit verdict must go elsewhere or
    the checker destroys what it audits."""
    for cmd in _flow_invocations("em_report_check"):
        toks = cmd.split()
        assert "--json" in toks, cmd
        target = toks[toks.index("--json") + 1]
        assert target != "reports/phase3/em.json", (
            "step 25's audit would overwrite the EM measurement it audits")
    runner = _RUNNER_SRC.read_text(errors="replace")
    assert '"reports/phase3/em.json"' in runner, (
        "the producer's measurement path moved — re-check the collision")


# ===========================================================================
# (1) The gates are WIRED — a runner invokes them, so they can block
# ===========================================================================
def test_runner_exposes_every_declared_signoff_gate():
    """MEMBERS, not a count — and the name carries no size for the same reason.

    A set equality is the right shape here: swapping one gate for another
    leaves any count unchanged, and this must notice. The name used to say
    "all_four"; a set whose size is written into its own test name goes stale
    the moment a member is added, which is what happened when `tapeout_precheck`
    was wired in on 2026-09-04.
    """
    import phase3_one_shot_runner as R
    wired = {g[1] for g in R._DECLARED_SIGNOFF_GATES}
    assert wired == {
        "sta_report_check.py",
        "post_route_signoff_corner_check.py",
        "sta_corner_record_completeness_check.py",
        "em_report_check.py",
        # Step 37.5ic. Both tape-out ladders existed and neither ran until this
        # entry: no runner invoked the gate, so a phase-3 verdict was reached
        # with no authority having read the GDS.
        "tapeout_precheck.py",
    }, wired


def test_runner_actually_calls_the_gates_in_its_plan():
    """Defining the step is not wiring it. The verdict must land in `plan`,
    which is what `_aggregate_verdict` reads."""
    # Pinned on the CALL, not on its exact argument list: FP-20 added the run's
    # own PDK (`step_declared_signoff_gates(project, pdk.name)`) because the
    # gate resolved the FAMILY and every metal layer came back UNCHECKED. The
    # property this test exists for is "the verdict lands in `plan`", which an
    # added argument does not touch — so it is asserted over the parsed call,
    # and the argument itself is pinned by
    # test_the_signoff_gate_is_told_which_pdk_the_run_built.
    import ast
    src = _RUNNER_SRC.read_text(errors="replace")
    calls = [n for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "extend"
             and n.args and isinstance(n.args[0], ast.Call)
             and isinstance(n.args[0].func, ast.Name)
             and n.args[0].func.id == "step_declared_signoff_gates"]
    assert len(calls) == 1, (
        "the sign-off gates are defined but never appended to `plan` "
        "(or are appended more than once)")
    assert ast.unparse(calls[0].func.value) == "plan", ast.unparse(calls[0])


def test_blast_radius_is_stated_where_the_wiring_is():
    """The repo's own rule for a gate wired blocking (#306): the measured blast
    radius belongs beside the wiring, not rediscovered when main turns red.
    Four gates that never ran now block every phase-3 run; that is not free and
    the source must say so."""
    prose = " ".join(_RUNNER_SRC.read_text(errors="replace")
                     .replace("#", " ").split())
    assert "14 published phase-3 run-roots" in prose, (
        "the corpus the blast radius was measured over is not recorded")
    for gate, n in (("sta_report_check", "9/14"),
                    ("sta_corner_record_completeness_check", "6/14"),
                    ("em_report_check", "6/14"),
                    ("post_route_signoff_corner_check", "2/14")):
        assert gate in prose and n in prose, (
            f"the measured blast radius for {gate} is not stated")
    assert "-1.710 ns" in prose, (
        "the concrete finding that justified the blocking slot is not recorded")


def test_enforcement_audit_sees_the_gates_as_enforced():
    """The plugin's own register, in its own terms: ENFORCED means a runner
    invokes it inline so it can stop the step it guards."""
    import flow_gate_enforcement_audit as AUDIT
    rep = AUDIT.audit(_FLOW, _PROGRAMS)
    rows = {r["gate"].replace(".py", ""): r for r in rep["gates"]}
    for gate in ("sta_report_check", "em_report_check",
                 "sta_corner_record_completeness_check"):
        assert rows[gate]["enforcement"] == "ENFORCED", rows[gate]
    assert not rep["contradictions"], rep["contradictions"]


def test_signoff_gates_pass_a_clean_project(tmp_path):
    import phase3_one_shot_runner as R
    results = R.step_declared_signoff_gates(_project(tmp_path))
    # DERIVED FROM THE TABLE, not written down. A literal here goes stale the
    # moment a gate is added — which is exactly what happened when step 37.5ic
    # was wired in — and a stale count fails a test for the one reason that is
    # never a defect: the sign-off population grew.
    import phase3_one_shot_runner as _R
    assert len(results) == len(_R._DECLARED_SIGNOFF_GATES)
    assert [r.status for r in results] == ["PASS"] * len(results), [
        (r.name, r.status, r.detail) for r in results]


def test_signoff_gates_block_a_violated_signoff_corner(tmp_path):
    """The two-sided control. A gate that never fires is wiring for its own
    sake — this drives the #147 shape (nominal clean, sign-off corner at
    -1.71 ns) through the wiring that now carries it."""
    import phase3_one_shot_runner as R
    proj = _project(tmp_path)
    (proj / "phase3" / "stage3" / "sta"
     / "sta_spef_multicorner.rpt").write_text(_MULTICORNER_VIOLATED)
    results = {r.name: r for r in R.step_declared_signoff_gates(proj)}
    corner = results["sta_corner"]
    assert corner.status == "FAIL", corner
    assert "-1.710" in corner.detail or "-1.71" in corner.detail, corner.detail


def test_a_blocked_signoff_gate_fails_the_whole_run(tmp_path):
    """`_aggregate_verdict` is what turns a step FAIL into a non-zero exit.
    Without this the wiring could land in `plan` and still be cosmetic."""
    import phase3_one_shot_runner as R
    proj = _project(tmp_path)
    (proj / "phase3" / "stage3" / "sta"
     / "sta_spef_multicorner.rpt").write_text(_MULTICORNER_VIOLATED)
    plan = R.step_declared_signoff_gates(proj)
    assert R._aggregate_verdict(plan) == "FAIL"


def test_a_checker_fault_is_not_a_design_failure_and_is_not_neutral_either(
        tmp_path):
    """rc 2 means the gate could not read its inputs or was mis-invoked. That
    is inconclusive, not a verdict about the design — a blocking gate that
    fails runs over its own I/O errors is breakage, not enforcement.

    REVERSED BY #544, deliberately. This test used to assert `SKIP` and
    `_aggregate_verdict(...) != "FAIL"`, and that second half was the defect:
    for a gate the flow DECLARES as sign-off, "inconclusive" is not neutral.
    The distinction the original was protecting is kept — the step is
    `BLOCKED`, never `FAIL`, so triage can still tell "nothing is known" from
    "the design did not pass" — but it no longer releases.
    """
    import phase3_one_shot_runner as R
    # A mis-invocation: argparse exits 2.
    r = R._run_declared_signoff_gate(
        _project(tmp_path), "sta_signoff", "sta_report_check.py",
        "reports/phase3/sta/post_route_summary.json", ("--mode", "bogus"))
    assert r.status == "BLOCKED", r
    assert r.status != "FAIL", "a checker fault is not a verdict on the design"
    assert "rc=2" in r.detail, r.detail
    assert R._aggregate_verdict([r]) not in _RELEASING, r


def test_a_missing_project_is_not_fabricated_into_existence(tmp_path):
    """Creating the report directory would also create the PROJECT directory,
    and every checker keys its rc-2 "cannot read my inputs" branch on
    `project.is_dir()`. Fabricating the tree would convert that fault into a
    NOT_APPLICABLE rc 0 — a green verdict about a project that is not there."""
    import phase3_one_shot_runner as R
    missing = tmp_path / "does_not_exist"
    r = R._run_declared_signoff_gate(
        missing, "sta_corner", "post_route_signoff_corner_check.py",
        "reports/phase3/sta/post_route_signoff_corner.json")
    # #544: a project that is not there is not a project that passed.
    assert r.status == "BLOCKED", r
    assert not missing.exists(), (
        "the gate helper created the project directory it was asked to audit")


def test_signoff_gate_writes_its_verdict_json(tmp_path):
    import phase3_one_shot_runner as R
    proj = _project(tmp_path)
    R.step_declared_signoff_gates(proj)
    for rel in ("reports/phase3/sta/post_route_summary.json",
                "reports/phase3/sta/post_route_signoff_corner.json",
                "reports/phase3/sta/sta_corner_record_completeness.json",
                "reports/phase3/em_signoff.json"):
        assert (proj / rel).is_file(), f"{rel} was not written"


# ===========================================================================
# DIRECTION-1 GUARDS — must hold on the pre-fix tree too
# ===========================================================================
def test_d1_bare_wrapper_call_shape_still_works(tmp_path):
    """`<wrapper> <project>` with no mode and no --json is the call shape
    test_report_wrappers.py and test_sta_report_check.py drive. Forwarding
    argv must not break it."""
    proj = _project(tmp_path)
    assert _run("sta_report_check.py", str(proj)).returncode == 0
    assert _run("em_report_check.py", str(proj)).returncode == 0
    assert _run("sta_report_check.py", str(tmp_path / "empty")).returncode == 1
    assert _run("em_report_check.py", str(tmp_path / "empty")).returncode == 1


def test_d1_signoff_corner_check_self_skips_without_a_multicorner_report(tmp_path):
    """Why wiring it UNCONDITIONALLY is safe even though the yaml declares it
    under `condition_files_exist: [sta_spef_multicorner.rpt]`: on the
    condition's false branch the checker self-reports NOT_APPLICABLE and exits
    0, which is exactly what the unrun conditional gate produced."""
    proj = _project(tmp_path)
    r = _run("post_route_signoff_corner_check.py", str(proj))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "NOT_APPLICABLE" in r.stdout


def test_d1_corner_record_check_self_skips_with_no_declared_corner(tmp_path):
    """Pre-phase3 and analog runs declare no sign-off corner; that must stay a
    rc 0 self-skip, not a FAIL invented out of an absent declaration."""
    r = _run("sta_corner_record_completeness_check.py", str(_project(tmp_path)))
    assert r.returncode == 0, r.stdout + r.stderr


def test_d1_audit_never_writes_the_producers_em_measurement(tmp_path):
    """The measurement must survive its own checker."""
    proj = _project(tmp_path)
    measurement = {"tool": "openroad-psm", "verdict": "MEASURED",
                   "max_segment_current_A": 0.0002532,
                   "segments_analysed": 3362}
    em_json = proj / "reports" / "phase3" / "em.json"
    em_json.write_text(json.dumps(measurement))
    _run("em_report_check.py", str(proj), "--mode", "em",
         "--json", str(proj / "reports" / "phase3" / "em_signoff.json"))
    assert json.loads(em_json.read_text()) == measurement, (
        "the EM audit overwrote the measurement it was auditing")
