#!/usr/bin/env python3
"""The two obstruction gates must be RUN by the flow, not merely exist.

`macro_obs_geometry_intersect_check` returns a blocking verdict (rc=1) and its
own header said what that was worth: "It is not registered in
flow/phase1_phase2_phase3.yaml and no runner invokes it; its only caller is
tools/ci/repo_hygiene_gates.sh".
It reproduces the defect in seconds on a routed DEF and nothing ever asked it
to. A gate no step runs enforces nothing on a real design.

`macro_obs_load_parity_check` is new and would have inherited exactly the same
fate if it were merely landed.

WHAT THIS TEST PINS, and why each half is needed:

  * DECLARATION — both gates appear in a gate leg of the step that owns their
    subject: LEF-load parity at the step that first READS the macro abstracts,
    geometry intersection at the step that PRODUCES routed.def. A test that
    only checked `programs:` membership would pass on an orphan, because that
    list executes nothing (this flow file says so in three places).

  * EXECUTABILITY — the wiring is conditioned on the gates' OWN precondition,
    a LEF to read, and the condition must be satisfiable by the thing it names.
    `condition_files_exist` skips only when NONE of its globs match, so the
    glob has to be the one that matches a staged LEF. A condition that can
    never match is an orphan with extra steps.

MEASURED end to end on the converged reference cell, which stages no LEF:
  * as-is                        -> both legs skipped, PASS=36 FAIL=0, exit 0
  * + one LEF whose OBS names an undeclared layer
                                 -> macro_obs_load_parity_check rc=1 FAIL,
                                    macro_obs_geometry_intersect_check ran,
                                    step 15 red
so the wiring both stays silent where it has nothing to read and blocks where
there is something to find.
"""
from __future__ import annotations

import os
import sys

import pytest

yaml = pytest.importorskip("yaml")

_HERE = os.path.dirname(os.path.abspath(__file__))
_PLUGIN = os.path.dirname(os.path.dirname(_HERE))
_FLOW = os.path.join(_PLUGIN, "vibe-ic", "flow", "phase1_phase2_phase3.yaml")
if not os.path.exists(_FLOW):
    _FLOW = os.path.join(os.path.dirname(os.path.dirname(_HERE)),
                         "flow", "phase1_phase2_phase3.yaml")

_LEF_GLOB = "**/*.lef"


def _steps():
    with open(_FLOW) as fh:
        doc = yaml.safe_load(fh)
    steps = doc.get("steps") or doc.get("flow") or []
    return {str(s.get("id")): s for s in steps if isinstance(s, dict)}


def _gate_legs(step):
    gate = step.get("gate") or {}
    legs = gate.get("all_of")
    if legs is None:
        legs = [gate] if gate else []
    return [l for l in legs if isinstance(l, dict)]


def _find_leg(step, program):
    for leg in _gate_legs(step):
        for key in ("program_exit_zero", "optional_program_exit_zero",
                    "advisory_program_exit_zero"):
            spec = leg.get(key)
            if spec is None:
                continue
            cmd = spec if isinstance(spec, str) else spec.get("command", "")
            if isinstance(cmd, str) and cmd.split()[:1] == [program]:
                return key, (spec if isinstance(spec, dict) else {"command": cmd})
    return None, None


@pytest.mark.parametrize("step_id,program", [
    ("15", "macro_obs_load_parity_check"),
    ("21", "macro_obs_geometry_intersect_check"),
])
def test_the_gate_is_wired_into_a_gate_leg(step_id, program):
    """REGRESSION. Membership of `programs:` executes nothing; only a gate leg
    does."""
    steps = _steps()
    assert step_id in steps, sorted(steps)
    key, spec = _find_leg(steps[step_id], program)
    assert key is not None, (
        f"{program} is not in any gate leg of step {step_id} — it would run "
        f"nowhere, which is the defect this pins")
    assert key != "advisory_program_exit_zero", (
        f"{program} returns rc=1 on a real defect and that verdict must decide "
        f"step {step_id}'s; the advisory slot RECORDS a finding and never "
        f"fails the step. The gate's own `ENFORCEMENT:` line is a DIFFERENT "
        f"axis — it answers whether a runner spawns it inline — so an "
        f"`advisory` declaration there is not a licence to move it here")


@pytest.mark.parametrize("step_id,program", [
    ("15", "macro_obs_load_parity_check"),
    ("21", "macro_obs_geometry_intersect_check"),
])
def test_the_condition_is_the_gates_own_precondition(step_id, program):
    """The condition must name the thing the gate needs — a LEF to read — and
    nothing narrower. A condition narrower than the gate's applicability is the
    invisible-skip antipattern; one that can never match is an orphan."""
    steps = _steps()
    key, spec = _find_leg(steps[step_id], program)
    if key == "program_exit_zero":
        return                     # unconditional is strictly stronger
    conds = spec.get("condition_files_exist")
    assert conds == [_LEF_GLOB], (
        f"{program} in step {step_id} is conditioned on {conds!r}; it must be "
        f"[{_LEF_GLOB!r}] — the gate's own precondition")


def test_the_condition_glob_matches_a_staged_lef(tmp_path):
    """EXECUTABILITY. `condition_files_exist` skips only when NONE of its globs
    match, so a glob that cannot match a real staged LEF would make both legs
    permanently invisible while still reading as wired."""
    assert list(tmp_path.glob(_LEF_GLOB)) == []
    nested = tmp_path / "input" / "pdk_local" / "vendor"
    nested.mkdir(parents=True)
    (nested / "some_macro.lef").write_text("MACRO m\nEND m\n")
    assert list(tmp_path.glob(_LEF_GLOB)), (
        "the condition glob does not match a staged LEF — the gates would "
        "never run")


def test_the_geometry_gate_header_no_longer_claims_to_be_unwired():
    """The header stated the defect as a fact about the repo. Landing the
    wiring without correcting it leaves a false statement in the file that a
    future reader would act on."""
    src = os.path.join(os.path.dirname(_HERE),
                       "macro_obs_geometry_intersect_check.py")
    text = open(src).read()
    head = text.split('"""')[1] if '"""' in text else text
    assert "It is not registered in" not in head, (
        "the header still says the gate is not registered in the flow")


# ── vibe-ic#2013: every refusal is TYPED, and the type is the flow's own ──
#
# Since #1978 `flow_compliance_check` classifies each rc=2 by the gate's
# `reason_class` and falls closed to EXECUTION_ERROR when none is published.
# Both obstruction gates published none, so on a real published run step 21
# read "INCOMPLETE: the gate reports its input was applicable and was NOT
# examined" for a design that integrates no macro (MEASURED, spm@1.15.55,
# ledger `rc=2 INCOMPLETE reason_class=EXECUTION_ERROR`). The gates now
# publish a class, and the one fact the LEF set cannot supply — does this
# design integrate a macro at all — is taken from the FLOW'S OWN declaration
# sites, the `condition_files_exist` triggers of step 15's
# `ip_integration_check` clause. The first test below pins the two copies of
# that list to each other; the rest run the gates and read the type back.

import json
import subprocess

_PROGRAMS = os.path.dirname(_HERE)
if _PROGRAMS not in sys.path:
    sys.path.insert(0, _PROGRAMS)


def _refusal(gate: str, project, *extra):
    """rc and the gate's own --json record, through a real subprocess."""
    out = project / f"{gate}.json"
    r = subprocess.run(
        [sys.executable, os.path.join(_PROGRAMS, gate + ".py"), str(project),
         "--json", str(out), *extra],
        capture_output=True, text=True, timeout=300)
    rec = json.loads(out.read_text()) if out.is_file() else None
    return r.returncode, rec, r.stderr


def test_the_declaration_sites_the_gates_consult_are_the_flows_own():
    """`_MACRO_DECLARATION_SITES` is a second copy of the yaml's list, and a
    second copy of one fact answers differently the day either moves."""
    import macro_obs_geometry_intersect_check as G
    key, spec = _find_leg(_steps()["15"], "ip_integration_check")
    assert key == "optional_program_exit_zero", key
    assert tuple(spec.get("condition_files_exist") or ()) == \
        tuple(G._MACRO_DECLARATION_SITES), (
        f"the flow declares a macro by {spec.get('condition_files_exist')}; "
        f"the obstruction gates consult {G._MACRO_DECLARATION_SITES}")


def test_a_project_with_nothing_to_read_and_no_declared_macro_is_the_designs_na(
        tmp_path):
    import _flow_reason_taxonomy as T
    rc, rec, err = _refusal("macro_obs_load_parity_check", tmp_path)
    assert rc == 2 and "CANNOT DETERMINE" in err, err
    assert rec["reason_class"] == T.DESIGN_DECLARED_NA, rec
    assert rec["verdict"] == T.record_verdict(T.DESIGN_DECLARED_NA), rec
    # the geometry gate refuses one step earlier: no routed DEF is the step's
    # own producer missing, which is blocked and never an N/A.
    rc, rec, err = _refusal("macro_obs_geometry_intersect_check", tmp_path)
    assert rc == 2 and "no routed DEF" in err, err
    assert rec["reason_class"] == T.BLOCKED_BY_UPSTREAM, rec


def test_a_declared_macro_with_no_abstract_is_blocked_not_na(tmp_path):
    """The self-disabling shape the step-15 wiring comment refuses: a design
    that DECLARES a macro must not get an N/A because its LEF is missing."""
    import _flow_reason_taxonomy as T
    import macro_obs_geometry_intersect_check as G
    (tmp_path / G._MACRO_DECLARATION_SITES[0]).mkdir(parents=True)
    rc, rec, err = _refusal("macro_obs_load_parity_check", tmp_path)
    assert rc == 2 and rec["reason_class"] == T.BLOCKED_BY_UPSTREAM, (rec, err)
    assert "DECLARES a macro" in err, err
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "routed.def").write_text(
        "VERSION 5.8 ;\nDESIGN top ;\nUNITS DISTANCE MICRONS 1000 ;\n"
        "COMPONENTS 0 ;\nEND COMPONENTS\nEND DESIGN\n")
    rc, rec, err = _refusal("macro_obs_geometry_intersect_check", tmp_path)
    assert rc == 2 and rec["reason_class"] == T.BLOCKED_BY_UPSTREAM, (rec, err)
    assert "no macro LEF" in err and "DECLARES a macro" in err, err


def test_an_abstract_that_declares_no_obs_is_the_designs_na(tmp_path):
    import _flow_reason_taxonomy as T
    (tmp_path / "tech.lef").write_text(
        "VERSION 5.8 ;\nLAYER metalA\n  TYPE ROUTING ;\nEND metalA\n"
        "END LIBRARY\n")
    (tmp_path / "macro.lef").write_text(
        "MACRO block_a\n  SIZE 40.0 BY 40.0 ;\nEND block_a\n")
    rc, rec, err = _refusal("macro_obs_load_parity_check", tmp_path)
    assert rc == 2 and "nothing was compared" in err, err
    assert rec["reason_class"] == T.DESIGN_DECLARED_NA, rec
    assert rec["masters_with_obs"] == [], "the audit's own census is kept"
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "routed.def").write_text(
        "VERSION 5.8 ;\nDESIGN top ;\nUNITS DISTANCE MICRONS 1000 ;\n"
        "COMPONENTS 1 ;\n- u0 block_a + FIXED ( 0 0 ) N ;\nEND COMPONENTS\n"
        "END DESIGN\n")
    rc, rec, err = _refusal("macro_obs_geometry_intersect_check", tmp_path)
    assert rc == 2 and "declares an OBS" in err, err
    assert rec["reason_class"] == T.DESIGN_DECLARED_NA, rec


def test_an_abstract_the_tech_lef_cannot_resolve_is_a_zero_denominator(
        tmp_path):
    """836f57214's refusal — a LEF set declaring zero layers — keeps its rc
    and gains the class that says the follow-up is real: vendor the tech LEF."""
    import _flow_reason_taxonomy as T
    (tmp_path / "macro.lef").write_text(
        "MACRO block_a\n  SIZE 40.0 BY 40.0 ;\n  OBS\n    LAYER metalA ;\n"
        "      RECT 0 0 1 1 ;\n  END\nEND block_a\n")
    rc, rec, err = _refusal("macro_obs_load_parity_check", tmp_path)
    assert rc == 2 and "ZERO layers" in err, err
    assert rec["reason_class"] == T.ZERO_DENOMINATOR, rec


if __name__ == "__main__":
    sys.exit(pytest.main([os.path.abspath(__file__), "-v"]))
