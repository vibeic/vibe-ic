#!/usr/bin/env python3
"""The remaining `eda_report_audit` wrappers that discarded the caller's argv.

THE DEFECT. `sta_report_check` and `em_report_check` were fixed in PR #473;
`drc_report_check`, `ir_drop_report_check` and `antenna_report_check` were left
as `main([sys.argv[1], "--mode", <fixed>])`, which discards every token past
`sys.argv[1]` — including the `--json <path>` the flow yaml declares for steps
21, 24, 26 and 31. Measured on a project holding real reports::

    ir_drop_report_check  proj --mode ir_drop --json <path>   rc=0  no file
    antenna_report_check  proj --mode antenna --json <path>   rc=0  no file
    drc_report_check      proj --mode drc     --json <path>   rc=1  no file

and on the real completed run `campaign_pr427/spm/converge_ihp-sg13g2`,
`find reports/phase3 -iname '*drc*'` returns only `.rpt` files — the declared
`drc_router.json` / `drc_signoff.json` audit trail was never written by anything.

TWO THINGS THE DROPPED FLAG WAS HIDING, both fixed in the same change:

(1) OUTPUT-PATH COLLISION. Steps 24 and 26 declared their audit output at
    `reports/phase3/ir_drop.json` / `reports/phase3/antenna.json` — the
    PRODUCER's measurement files, which `phase3_one_shot_runner._read_verdict`
    reads back as those steps' evidence and which step 24 also lists in its own
    `required_outputs`. Honouring the flag without moving the path would have
    destroyed the measurement being audited. This is the same collision PR #473
    found at step 25.

(2) SELF-CONSUMPTION. `eda_report_audit`'s antenna mode globs `*antenna*.json`
    and its ir_drop mode globs `*ir_drop*`, so the audit's own verdict document
    would be re-discovered as an input report on the next run. Measured before
    the guard, on a project with exactly one real antenna.rpt: run 1
    `files_found=1`, run 2 (after writing `antenna_signoff.json`)
    `files_found=2`. `_discover` now skips documents carrying this program's own
    `"program": "eda_report_audit:<mode>"` field.

WHAT IT COSTS. Nothing in the gate verdicts: `program_exit_zero` reads the
subprocess rc, and forwarding argv does not change the rc of any call shape in
the repo (the direction-1 guards below pin that). It costs three more files
written per phase-3 run, and it makes a mis-declared `--mode` visible as an
argparse error instead of being silently absorbed — which is the point.

DIRECTION-1 GUARDS (`test_d1_*`) hold on the pre-fix tree as well.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent
_FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
_RUNNER_SRC = _PROGRAMS / "phase3_one_shot_runner.py"

sys.path.insert(0, str(_PROGRAMS))

_PAD = "# " + ("=" * 78 + "\n") * 40  # ~3.2 KB, clears MIN_REPORT_BYTES

_DRC_RPT = (
    "[INFO DRT-0012] OpenROAD detailed_route started\n"
    "Layer M1 spacing violation at (1.2, 3.4): 0.12 um\n"
    "Layer M2 width violation at (5.0, 2.1): 0.15 um\n"
    "Layer M3 via enclosure error at (3.0, 4.5)\n"
    "Total: 0 violations (3 waived)\nDRC clean\n" + _PAD
)
_IR_RPT = (
    "OpenROAD PSM IR drop analysis\n"
    "power grid mesh nodes: 12458\n"
    "worst voltage drop: 6.8 mV (0.2% Vdd) static IR\n"
    "worst dynamic IR: 9.1 mV (0.3% Vdd)\n" + _PAD
)
_ANT_RPT = (
    "OpenROAD check_antennas (ANT) gate-oxide protection\n"
    "antenna check: 0 net violations, 0 pin violations\n"
    "antenna clean: YES\n"
    "gate oxide ratio 12.0 antenna ratio\n" + _PAD
)

# The PRODUCER payloads the runner reads back as step 24/26 evidence.
_IR_MEASUREMENT = {
    "tool": "openroad-psm", "mode": "static_ir_drop",
    "worst_ir_uv": 6800.0, "budget_uv": 180000.0, "verdict": "PASS",
}
_ANT_MEASUREMENT = {
    "tool": "openroad", "mode": "antenna_check_in_session_post_repair",
    "net_violations": 0, "pin_violations": 0, "clean": True, "verdict": "PASS",
}

_WRAPPERS = {
    "drc_report_check.py": "drc",
    "ir_drop_report_check.py": "ir_drop",
    "antenna_report_check.py": "antenna",
}


def _run(prog: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(_PROGRAMS / prog), *args],
                          capture_output=True, text=True, timeout=60)


def _project(tmp: Path) -> Path:
    rp = tmp / "reports" / "phase3"
    rp.mkdir(parents=True, exist_ok=True)
    (rp / "drc_router.rpt").write_text(_DRC_RPT)
    (rp / "ir_drop.rpt").write_text(_IR_RPT)
    (rp / "antenna.rpt").write_text(_ANT_RPT)
    (rp / "ir_drop.json").write_text(json.dumps(_IR_MEASUREMENT))
    (rp / "antenna.json").write_text(json.dumps(_ANT_MEASUREMENT))
    return tmp


def _flow_invocations(program: str):
    """Every `<program> ...` command string declared in the flow yaml."""
    return re.findall(rf'"({re.escape(program)} [^"]*)"',
                      _FLOW.read_text(errors="replace"))


def _flow_json_target(program: str) -> str:
    """The `--json <path>` THE FLOW declares for `program`, read from the yaml.

    Every behavioural test below drives the wrapper with THIS, never with a
    path repeated in the test body: a test that hardcodes the post-fix path is
    green on the colliding yaml too, which is exactly how the collision escaped
    being executed in the first place.
    """
    cmds = _flow_invocations(program)
    assert cmds, f"{program} is no longer declared in the flow"
    targets = set()
    for cmd in cmds:
        toks = cmd.split()
        assert "--json" in toks, cmd
        targets.add(toks[toks.index("--json") + 1])
    assert len(targets) == 1, (
        f"{program} is declared with {len(targets)} different --json targets "
        f"{sorted(targets)}; this test drives one")
    return targets.pop()


# ===========================================================================
# The wrappers honour the output flag the flow declares
# ===========================================================================
@pytest.mark.parametrize("wrapper,mode", sorted(_WRAPPERS.items()))
def test_wrapper_writes_the_json_the_caller_asked_for(tmp_path, wrapper, mode):
    """Pre-fix each of these returned without writing anything at all."""
    proj = _project(tmp_path)
    out = proj / "reports" / "phase3" / f"probe_{mode}.json"
    r = _run(wrapper, str(proj), "--mode", mode, "--json", str(out))
    assert out.is_file(), (
        f"{wrapper} discarded --json: the audit trail step declares has no "
        f"producer (rc={r.returncode})\n{r.stdout}\n{r.stderr}")
    doc = json.loads(out.read_text())
    assert doc["program"] == f"eda_report_audit:{mode}", doc


@pytest.mark.parametrize("wrapper,mode", sorted(_WRAPPERS.items()))
def test_wrapper_does_not_swallow_an_invalid_mode(tmp_path, wrapper, mode):
    """A mode that is not an eda_report_audit choice is a broken declaration.
    It must NOT be silently replaced by the wrapper's own hardcoded mode.

    UPDATED with #490. This asserted rc 2, i.e. "let argparse reject it".
    That was right about the intent and wrong about the exit code:
    `flow_compliance_check._check_program_exit_zero` credits rc 2 as a
    VACUOUS_PASS and `return True`s unconditionally, so a command line
    argparse itself rejected turned the step GREEN. The wrappers now REFUSE
    an unpinnable mode themselves and exit 1. The requirement the test exists
    for — the wrapper must not absorb it — is unchanged and still asserted."""
    r = _run(wrapper, str(_project(tmp_path)), "--mode", "phase3/stage3/sta")
    blob = (r.stderr + r.stdout).lower()

    src = (_PROGRAMS / wrapper).read_text()
    adopted = "_report_check_argv" in src

    if adopted:
        # drc (#490) / lvs (#489) / power: the wrapper refuses it itself and
        # exits 1, because rc 2 is credited as a vacuous PASS by the gate
        # runner and a refusal must never spend that credit.
        assert r.returncode == 1, (
            f"{wrapper} adopted the shared splitter but did not refuse: "
            f"rc={r.returncode}")
        assert "refused" in blob, blob
    else:
        # antenna / ir_drop have NOT adopted it — #490 measured that their
        # declared --json paths are already written by phase3_one_shot_runner
        # under a DIFFERENT schema, so honouring --json there would clobber a
        # real sign-off artefact. Each needs a path decision before an argv
        # fix. Until then the old behaviour stands: argparse rejects it (rc 2).
        # This arm is a LEDGER of what has not been converted, and it flips to
        # the arm above the moment one of them adopts the helper.
        assert r.returncode == 2, (
            f"{wrapper} neither adopted the splitter nor let argparse reject "
            f"the mode: rc={r.returncode}")
        assert "invalid choice" in blob, blob


# ===========================================================================
# (1) The declared audit path must not be the PRODUCER's measurement
# ===========================================================================
@pytest.mark.parametrize("program,producer_path", [
    ("ir_drop_report_check", "reports/phase3/ir_drop.json"),
    ("antenna_report_check", "reports/phase3/antenna.json"),
    ("em_report_check", "reports/phase3/em.json"),
])
def test_flow_audit_json_does_not_clobber_the_producers_measurement(
        program, producer_path):
    invocations = _flow_invocations(program)
    assert invocations, f"{program} is no longer declared in the flow"
    for cmd in invocations:
        toks = cmd.split()
        assert "--json" in toks, cmd
        target = toks[toks.index("--json") + 1]
        assert target != producer_path, (
            f"{program}'s audit verdict would overwrite {producer_path}, the "
            f"measurement it audits")
    runner = _RUNNER_SRC.read_text(errors="replace")
    assert f'"{producer_path}"' in runner, (
        f"the producer's measurement path moved — re-check the collision "
        f"for {producer_path}")


@pytest.mark.parametrize("wrapper,program,producer_rel", [
    ("ir_drop_report_check.py", "ir_drop_report_check",
     "reports/phase3/ir_drop.json"),
    ("antenna_report_check.py", "antenna_report_check",
     "reports/phase3/antenna.json"),
])
def test_the_collision_is_executed_not_just_pattern_matched(
        tmp_path, wrapper, program, producer_rel):
    """THE EXECUTING GUARD. Drive the step exactly as the FLOW declares it —
    the `--json` target is READ FROM THE YAML, never repeated here — and assert
    the producer's measurement survives byte-identical.

    This is what makes the collision a reddening regression rather than a
    documented one: point the yaml back at the producer's own path and this
    test goes RED, because the wrapper now honours the flag and really does
    overwrite `<producer_rel>`. The two sibling yaml-regex tests cannot detect
    that, and neither can a version of this test that spells the post-fix path
    in its own body.
    """
    proj = _project(tmp_path)
    producer = proj / producer_rel
    before = producer.read_bytes()

    declared = _flow_json_target(program)          # <- from the flow, not here
    mode = _WRAPPERS[wrapper]
    r = _run(wrapper, str(proj), "--mode", mode, "--json",
             str(proj / declared))

    assert (proj / declared).is_file(), (
        f"{wrapper} did not write the audit trail the flow declares "
        f"({declared}); rc={r.returncode}\n{r.stdout}\n{r.stderr}")
    assert producer.read_bytes() == before, (
        f"step's audit verdict OVERWROTE {producer_rel}, the producer "
        f"measurement `phase3_one_shot_runner._read_verdict` reads back as "
        f"this step's evidence. The flow declares `--json {declared}`.")
    # And the surviving file is still the PRODUCER's document, not an audit
    # document that merely happens to be the same size.
    doc = json.loads(producer.read_text())
    assert not str(doc.get("program", "")).startswith("eda_report_audit:"), doc


def test_audit_run_leaves_the_producer_measurements_intact(tmp_path):
    """Both steps driven in one project, the way a real evaluation runs them:
    neither audit may disturb either measurement. Paths come from the flow."""
    proj = _project(tmp_path)
    rp = proj / "reports" / "phase3"
    before = {p.name: p.read_text() for p in
              (rp / "ir_drop.json", rp / "antenna.json")}
    for wrapper, program, mode in (
            ("ir_drop_report_check.py", "ir_drop_report_check", "ir_drop"),
            ("antenna_report_check.py", "antenna_report_check", "antenna")):
        _run(wrapper, str(proj), "--mode", mode,
             "--json", str(proj / _flow_json_target(program)))
    after = {p.name: p.read_text() for p in
             (rp / "ir_drop.json", rp / "antenna.json")}
    assert after == before, "an audit overwrote the measurement it audits"


@pytest.mark.parametrize("step_id,program", [
    ("24", "ir_drop_report_check"),
    ("26", "antenna_report_check"),
])
def test_the_new_audit_artefact_is_itself_declared(step_id, program):
    """The collision fix CREATES a new artefact. An artefact nothing declares
    is the defect this change is about, so the new one is declared too — and
    `flow_compliance_check` re-probes gate-produced entries after the gate so
    the declaration is satisfiable on the FIRST evaluation."""
    import yaml  # noqa: WPS433
    doc = yaml.safe_load(_FLOW.read_text(errors="replace"))
    step = next(s for s in doc["steps"] if str(s.get("id")) == step_id)
    declared = _flow_json_target(program)
    assert declared in (step.get("required_outputs") or []), (
        f"step {step_id}'s gate writes {declared} and no step declares it")


@pytest.mark.parametrize("step_id,program", [
    ("24", "ir_drop_report_check"),
    ("26", "antenna_report_check"),
])
def test_the_declaration_is_satisfiable_on_the_first_evaluation(
        tmp_path, step_id, program):
    """DRIVEN through `flow_compliance_check.check_step` with the REAL step
    from the flow yaml, on a project that does not yet contain the audit file.

    `missing_entries` is computed BEFORE the gate runs, so without the
    gate-produced re-probe this declaration would report MISSING on evaluation
    1 and PASS on evaluation 2 — a verdict that depends on how many times it
    has been run. Assert the artefact exists afterwards AND that the step's
    reasons never accuse it of being missing."""
    import yaml  # noqa: WPS433
    import flow_compliance_check as FCC  # noqa: WPS433
    doc = yaml.safe_load(_FLOW.read_text(errors="replace"))
    step = next(s for s in doc["steps"] if str(s.get("id")) == step_id)
    declared = _flow_json_target(program)

    proj = _project(tmp_path)
    assert not (proj / declared).exists(), "fixture must start without it"

    res = FCC.check_step(proj, step, {})

    assert (proj / declared).is_file(), (
        f"step {step_id}'s gate did not produce {declared} when driven through "
        f"check_step")
    blamed = [r for r in res.reasons
              if "required_outputs missing" in r and declared in r]
    assert not blamed, (
        f"step {step_id} reported its OWN gate's output as missing on the "
        f"first evaluation: {blamed}")


def test_gate_produced_reprobe_does_not_excuse_an_upstream_output(tmp_path):
    """DIRECTION check on the re-probe: it may only rescue entries this step's
    own gate names with `--json`. An absent artefact produced by anyone else
    must still report MISSING, or the ALL-of-N rule is gone."""
    import flow_compliance_check as FCC  # noqa: WPS433
    proj = _project(tmp_path)
    step = {
        "id": 900, "name": "synthetic", "stage": "stage3",
        "required_outputs": ["reports/phase3/antenna.rpt",
                             "reports/phase3/never_produced_by_anyone.json"],
        "gate": {"all_of": [
            {"program_exit_zero":
                "antenna_report_check . --mode antenna "
                "--json reports/phase3/antenna_signoff.json"}]},
    }
    res = FCC.check_step(proj, step, {})
    assert res.status == "MISSING", res.status
    assert any("never_produced_by_anyone.json" in r for r in res.reasons), \
        res.reasons


@pytest.mark.parametrize("program", sorted(
    w.replace(".py", "") for w in _WRAPPERS))
def test_flow_declares_a_real_report_mode(program):
    """Now that the mode reaches argparse, a mis-declared mode is an rc-2
    argparse error, which flow_compliance_check reads as VACUOUS_PASS — i.e. a
    broken declaration would buy PASS credit. Pin every declaration."""
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


# ===========================================================================
# (2) The audit must not ingest its own verdict document
# ===========================================================================
def test_audit_does_not_rediscover_its_own_verdict_document(tmp_path):
    """`*antenna*.json` matches the audit's own output. Measured pre-fix:
    files_found 1 -> 2 on a project holding exactly one real antenna report."""
    import eda_report_audit as A
    proj = tmp_path / "p"
    rp = proj / "reports" / "phase3"
    rp.mkdir(parents=True)
    (rp / "antenna.rpt").write_text(_ANT_RPT)

    first = A.main([str(proj), "--mode", "antenna",
                    "--json", str(rp / "antenna_signoff.json")])
    assert first == 0
    assert (rp / "antenna_signoff.json").is_file()

    found = A._discover(proj, ["*antenna*.rpt", "*antenna*.json", "*ANT*.rpt"])
    names = sorted(p.name for p in found)
    assert names == ["antenna.rpt"], (
        f"the audit re-discovered its own verdict document: {names}")


def test_self_document_guard_is_content_based_not_name_based(tmp_path):
    """A name rule would only move the landmine — the caller picks the path."""
    import eda_report_audit as A
    proj = tmp_path / "p"
    rp = proj / "reports" / "phase3"
    rp.mkdir(parents=True)
    (rp / "antenna.rpt").write_text(_ANT_RPT)
    # Same content, a name that shares nothing with the default.
    A.main([str(proj), "--mode", "antenna",
            "--json", str(rp / "zzz_step26_audit_trail.json")])
    found = A._discover(proj, ["*.json"])
    assert [p.name for p in found] == [], found


def test_a_real_tool_json_report_is_still_discovered(tmp_path):
    """Direction check on the guard itself: it must exclude ONLY this
    program's own documents, never a genuine tool report that happens to be
    JSON."""
    import eda_report_audit as A
    proj = tmp_path / "p"
    rp = proj / "reports" / "phase3"
    rp.mkdir(parents=True)
    (rp / "antenna.json").write_text(json.dumps(_ANT_MEASUREMENT))
    found = A._discover(proj, ["*antenna*.json"])
    assert [p.name for p in found] == ["antenna.json"], found


# ===========================================================================
# DIRECTION-1 GUARDS — these hold on the pre-fix tree too
# ===========================================================================
@pytest.mark.parametrize("wrapper", sorted(_WRAPPERS))
def test_d1_bare_wrapper_call_shape_still_works(tmp_path, wrapper):
    """`<wrapper> <project>` with no mode and no --json is the call shape
    test_report_wrappers.py drives. Forwarding argv must not break it."""
    proj = _project(tmp_path)
    assert _run(wrapper, str(proj)).returncode == 0
    assert _run(wrapper, str(tmp_path / "empty")).returncode == 1


@pytest.mark.parametrize("wrapper,mode", sorted(_WRAPPERS.items()))
def test_d1_explicit_mode_still_selects_that_mode(tmp_path, wrapper, mode):
    """The wrapper's own mode is what a declaration states, so stating it
    explicitly must behave identically to the bare call."""
    proj = _project(tmp_path)
    bare = _run(wrapper, str(proj))
    explicit = _run(wrapper, str(proj), "--mode", mode)
    assert bare.returncode == explicit.returncode == 0
    assert (json.loads(bare.stdout)["program"]
            == json.loads(explicit.stdout)["program"]
            == f"eda_report_audit:{mode}")


def test_no_argument_defaults_to_the_current_directory():
    """`main([])` must never happen — the wrapper substitutes ".".

    UPDATED with #490. This called `drc_report_check.build_argv`, an API that
    existed only in #485's version of the drc fix. #490's version landed
    instead (it adopts the shared splitter, pins the mode in both spellings,
    refuses any other, and maps argparse's own rc 2 to rc 1), so the assertion
    now goes through the shared helper — the thing that actually decides the
    project directory for every wrapper."""
    from _report_check_argv import split_and_pin
    proj, passthrough, rejected = split_and_pin([], mode="drc")
    assert proj == "."
    assert passthrough == []
    assert rejected is None
