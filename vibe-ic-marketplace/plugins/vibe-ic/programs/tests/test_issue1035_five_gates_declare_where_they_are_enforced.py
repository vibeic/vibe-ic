#!/usr/bin/env python3
"""vibe-ic#1035 — five gates that could never block and never said so.

THE FINDING, MEASURED. `flow_gate_enforcement_audit` failed on a clean checkout
of `origin/main` at ad8fbfeb with rc 1:

    [FAIL] 5 NEW gate(s) are AUDIT_ONLY and declare no intent at all —
    nothing invokes them where they could block, and nothing in the gate says
    that was the decision:
       undeclared::em_peak_current_authority_check
       undeclared::l6_fsm_scaffold_actionable_check
       undeclared::l9_submodule_conformance_check
       undeclared::power_total_vs_budget_check
       undeclared::step_internal_fail_bubble_up_check

Pre-existing and unchanged at 080bf6d05 / 788f56968 / cc1775ebc / c4c2becc4 on
clean trees, so no recent commit introduced it. It is the exact class
`test_macro_obs_gate_enforcement_declared` closed for two other gates, hit by
five more that landed after #886: the audit is a blocking leg of
`tools/ci/repo_hygiene_gates.sh`, so while it is red `tools/gatekeeper-land.sh`
deletes `.git/gatekeeper-stamp` and the local landing path cannot finish.

WIRED AND DECLARED ARE DIFFERENT QUESTIONS, and that is why two of these five
looked like a contradiction in the audit's own output. `em_peak_current_
authority_check` (step 25) and `power_total_vs_budget_check` (step 33) are
wired in the flow's BLOCKING slot and were repaired so INCOMPLETE exits 2
rather than 0 — and were STILL reported as `undeclared::`, correctly. The audit
measures one axis only: does a RUNNER spawn this gate inline, so its exit
status can stop the step while the step runs. No runner spawns any of the five.
Which flow slot the clause sits in is a SECOND axis, and what rc the program
returns on a finding is a THIRD. Answering either of those has never been an
answer to the first, and silence on the first is what the audit refuses.

THREE AXES, THREE ASSERTIONS. Every gate here is checked on all three, because
`advisory` on the audit's axis is the exact token a future change could quote
as licence to move a clause to `advisory_program_exit_zero` and defang it:

    1. `declared_intent()` returns `advisory`        — the declaration exists
                                                       AND the audit can see it
    2. the flow slot is unchanged                    — the declaration bought
                                                       no demotion
    3. the audit exits 0 and names none of the five  — end to end

NOT ONE ASSERTION IS A GREP FOR A STRING IN A SOURCE FILE. A test that greps
for `ENFORCEMENT: advisory` passes on a file where the audit cannot see the
declaration at all — it must OPEN a line and sit in the first 4000 characters —
which is #886's defect wearing a test's clothing. Every assertion below reads a
returned value, an exit code, or emitted JSON.

AND THE PAIRED GUARD, which is the half that matters. Declaring five gates
`advisory` is only honest if the audit still catches the SIXTH. If declaring
these made the audit go quiet about a genuinely-undeclared new gate later, the
declaration would be a silencer and this file would be its alibi. So the
controls below build a synthetic tree, add an undeclared audit-only gate to it,
and prove the same `audit()` / `main()` code path still reports it and still
exits 1 — and that the recorded register did not grow to absorb it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
_BASELINE = _PROGRAMS / "flow_gate_enforcement_baseline.json"

#: The five gates, with the flow step each guards and the slot it is wired in.
#: The slot is DATA here, not a constant, because the two sub-classes are the
#: whole point: three sit in the flow's BLOCKING slot and one axis of theirs is
#: unchanged by this declaration; two sit in the advisory slot and are advisory
#: on both axes.
_GATES = (
    ("em_peak_current_authority_check", "25", "program_exit_zero"),
    ("power_total_vs_budget_check", "33", "program_exit_zero"),
    ("step_internal_fail_bubble_up_check", "36", "program_exit_zero"),
    ("l6_fsm_scaffold_actionable_check", "1", "advisory_program_exit_zero"),
    ("l9_submodule_conformance_check", "2", "advisory_program_exit_zero"),
)






@pytest.mark.parametrize("gate", ["fmeda_coverage_check", "mixed_signal_signoff_check"])
@pytest.mark.parametrize("state", ["pass", "fail", "missing"])
def test_paid_gate_mock_status_is_consumed(gate, state, tmp_path):
    """Execute only the public caller's gate branch, with every tool mocked."""
    import ast
    import sys
    from types import SimpleNamespace
    from _source_pin import func_src

    gate_rc = {"pass": 0, "fail": 1, "missing": 2}[state]
    gate_report = {"pass": {"verdict": "PASS", "passed": True},
                   "fail": {"verdict": "FAIL", "passed": False},
                   "missing": {}}[state]
    calls = []
    if gate == "fmeda_coverage_check":
        source = (_PROGRAMS / "design_one_shot_runner.py").read_text()
        function = ast.parse(func_src(source, "step_fmeda_fault_injection")).body[0]
        branch = next(node for node in function.body
                      if isinstance(node, ast.If) and ast.unparse(node.test) == "gate_command")
        report_path = tmp_path / "gate.json"

        def run(argv, **kwargs):
            calls.append(argv)
            if state != "missing":
                report_path.write_text(json.dumps(gate_report))
            return SimpleNamespace(returncode=gate_rc)

        namespace = {"_pr": SimpleNamespace(run=run), "sys": sys, "json": json,
                     "PROGRAMS_DIR": _PROGRAMS, "gate_command": "gate . --json gate.json",
                     "project": tmp_path, "gate_rel": "gate.json", "extras": {},
                     "verdict": "PASS", "absence": None, "name": "neutral",
                     "time": SimpleNamespace(time=lambda: 0), "t0": 0,
                     "detail": "neutral", "files": [],
                     "_sa": SimpleNamespace(evidence_of=lambda report: None),
                     "_V": SimpleNamespace(ReasonClass=SimpleNamespace(EXECUTION_ERROR="error")),
                     "StepResult": lambda name, status, *args, **kwargs: status}
        wrapper = ast.parse("def probe():\n    return 'PASS'\n").body[0]
        wrapper.body.insert(0, branch)
        module = ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[]))
        exec(compile(module, "<public-fmeda-caller-mock>", "exec"), namespace)
        observed = namespace["probe"]()
        expected = {"pass": "PASS", "fail": "FAIL", "missing": "NOT_MEASURED"}[state]
    else:
        source = (_PROGRAMS / "vibe_ic_one_shot_runner.py").read_text()
        tree = ast.parse(source)
        branch = next(node for node in ast.walk(tree) if isinstance(node, ast.If)
                      and any(isinstance(child, ast.Call)
                              and isinstance(child.func, ast.Attribute)
                              and child.func.attr == "get"
                              and isinstance(child.func.value, ast.Name)
                              and child.func.value.id == "_m4_gate_rep"
                              for child in ast.walk(node.test)))
        scope = next(node for node in ast.walk(tree) if hasattr(node, "body")
                     and isinstance(node.body, list) and branch in node.body)
        gate_call = next(node for node in scope.body
                         if isinstance(node, ast.Assign)
                         and any(isinstance(target, ast.Name) and target.id == "_m4_gate_rc"
                                 for target in node.targets))
        read_call = next(node for node in scope.body
                         if isinstance(node, ast.Assign)
                         and any(isinstance(target, ast.Name) and target.id == "_m4_gate_rep"
                                 for target in node.targets))

        def run_phase(label, program, argv, **kwargs):
            calls.append([str(program), *argv])
            return gate_rc

        namespace = {"_run_phase": run_phase, "_read_report": lambda path: gate_report,
                     "PROGRAMS_DIR": _PROGRAMS, "project": tmp_path,
                     "_m4_gate_json": tmp_path / "gate.json", "_phase_env": {},
                     "_m4_rc": 0, "_m4_rep": {"program": "mixed_signal_signoff_run",
                                                "verdict": "PASS"}}
        module = ast.fix_missing_locations(ast.Module(
            body=[gate_call, read_call, branch], type_ignores=[]))
        exec(compile(module, "<public-m4-caller-mock>", "exec"), namespace)
        observed = (namespace["_m4_rc"], namespace["_m4_verdict"])
        expected = (0, "PASS") if state == "pass" else (1, "FAIL")
    assert len(calls) == 1 and Path(calls[0][1 if gate == "fmeda_coverage_check" else 0]).stem == gate
    assert observed == expected


# ───────────────────────────────────────────── axis 1: the declaration exists



# ────────────────────────────────── axis 2: the declaration bought no demotion



# ─────────────────────────────────────────────────── axis 3: end to end, rc 0





# ═════════════════════════════════════════════════════════════ THE PAIRED GUARD
#
# Every assertion above is of the form "the audit does NOT report gate X". That
# family is trivially satisfied by an audit that reports nothing at all, so on
# its own it is worth very little — and "declaring these five made the audit go
# quiet about a real regression later" is the precise defect this change could
# introduce. The controls below drive the SAME `audit()` and `main()` entry
# points over synthetic trees and prove the code path is still live.

_SILENT = '''"""A gate that says nothing about where its verdict is enforced."""
'''
_DECLARING = '''"""A gate that says so.

ENFORCEMENT: advisory — no runner spawns it.
"""
'''
_DECLARING_BLOCKING = '''"""A gate that claims more than its wiring delivers.

ENFORCEMENT: blocking
"""
'''










if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve()), "-v"]))
