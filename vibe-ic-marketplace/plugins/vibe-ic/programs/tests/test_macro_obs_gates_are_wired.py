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


if __name__ == "__main__":
    sys.exit(pytest.main([os.path.abspath(__file__), "-v"]))
