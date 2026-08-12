"""D1 must not declare a deliverable no clause of its own gate reads.

WHY THIS FILE EXISTS, AND WHY IT IS NOT PART OF `test_matrix_d4_criteria_match`
==============================================================================
D4 caught the same defect on step 1 and went green when it was fixed. It cannot
catch it on D1, and finding that out is the reason this file exists.

D4 routes on gate SHAPE:

    if _exec_clauses(sid):
        _assert_cli_contract(sid); _assert_artefacts_grounded(sid); return
    _assert_files_only_gate_matches_claim(sid)

The ALL-of-N entry-coverage question — "is every declared `required_outputs`
entry read by some clause of this step's own gate" — lives only in the
files-only branch. Step 1's gate is `files_exist` alone, so D4 asked it there.
D1's gate has 24 program clauses, so D4 takes the other branch and never asks.

MEASURED, and it is why the fix that moved the declaration from step 1 to D1
needed this file: with D1 declaring
`reports/phase1/extraction_coverage_report.{md,json}` and the clause that reads
them DELETED, `test_matrix_d4_criteria_match` still reports **69 passed**. A
green D4 is therefore not evidence that the property holds for D1, and moving a
declaration into a branch that does not ask the question is relocation, not
repair.

WHY THE GLOBAL FIX IS NOT HERE
------------------------------
Asking the entry-coverage question of every exec-clause gate is the right end
state, and it is a separate change with a number attached: **43 of the 61
gated steps with exec clauses** have at least one declared entry that no clause
NAMES. That count is an upper bound of the naive predicate rather than 43 real
defects — a clause spelled `foo_check .` takes the project root and names no
path at all, so "names no path" and "reads nothing" are not the same claim, and
separating them is the design work that change needs. Reddening 43 steps on a
predicate that cannot yet tell those apart would be a ban, not a check.

So this file pins the ONE step whose declaration moved, at the strength D4
applies to a files-only gate, and says plainly what it does not cover.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

_PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent
sys.path.insert(0, str(_PROGRAMS))

from flow_compliance_check import (  # noqa: E402
    _flow_command_input_atoms, _flow_glob_re, _flow_path_atoms,
)

FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"

#: The artefacts this test exists for. Named because the assertion below is
#: about a SPECIFIC declaration that moved, not about the flow in general.
MOVED = ("reports/phase1/extraction_coverage_report.md",
         "reports/phase1/extraction_coverage_report.json")


def _steps():
    doc = yaml.safe_load(FLOW.read_text(errors="replace"))
    out = []

    def walk(node):
        if isinstance(node, dict):
            if "id" in node and "gate" in node:
                out.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(doc)
    return {str(s["id"]): s for s in out}


def _clause_commands(gate) -> list:
    found = []

    def walk(node):
        if isinstance(node, dict):
            for key, val in node.items():
                if key in ("program_exit_zero", "advisory_program_exit_zero",
                           "optional_program_exit_zero", "command") and isinstance(val, str):
                    found.append(val)
                else:
                    walk(val)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(gate)
    return found


def _gate_named_paths(step) -> list:
    """Every path a clause of this step's gate NAMES.

    `files_exist` patterns plus the POSITIONAL path arguments of each program
    clause — the same reading `flow_compliance_check._flow_command_input_atoms`
    gives, imported rather than restated so this cannot drift from the thing
    that resolves them.
    """
    named = []

    def walk(node):
        if isinstance(node, dict):
            for key, val in node.items():
                if key in ("files_exist", "condition_files_exist"):
                    named.extend(_flow_path_atoms(val))
                elif key in ("program_exit_zero", "advisory_program_exit_zero",
                             "optional_program_exit_zero", "command") and isinstance(val, str):
                    named.extend(_flow_command_input_atoms(val))
                else:
                    walk(val)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(step.get("gate"))
    return named


def test_the_moved_declaration_is_on_D1_and_not_on_step_1():
    """The ownership half. `phase1_coverage_report_gen` writes these and the
    path is `reports/phase1/`; step 1 is Spec-to-RTL in phase 2."""
    steps = _steps()
    step1 = [str(e) for e in (steps["1"].get("required_outputs") or [])]
    d1 = [str(e) for e in (steps["D1"].get("required_outputs") or [])]
    for path in MOVED:
        assert not any(path in e for e in step1), (
            f"{path} is declared by step 1 (Spec-to-RTL, phase 2) again. Its "
            f"producer is phase 1 and its own gate does not read it, which is "
            f"the D4 mismatch this moved to fix.")
        assert any(path in e for e in d1), (
            f"{path} is declared by neither step 1 nor D1 — moving it must not "
            f"mean dropping it; an undeclared deliverable is checked by nothing "
            f"at all, which is strictly worse than the mismatch.")


@pytest.mark.parametrize("path", MOVED)
def test_D1_gate_actually_READS_what_D1_now_declares(path):
    """The half D4 cannot ask of D1.

    This is the paired guard for the move: delete the clause that reads these
    and D4 still reports 69 passed, so without this test the fix would be green
    by relocation. With it, removing
    `phase1_coverage_report_present_check` from D1's gate fails here.
    """
    steps = _steps()
    named = _gate_named_paths(steps["D1"])
    commands = " ".join(_clause_commands(steps["D1"].get("gate")))

    # A clause NAMES the path, or a clause is the checker written for it. The
    # second arm is needed because the checker takes the project root (`.`) and
    # resolves the path internally — "names no path" is not "reads nothing",
    # and conflating them is exactly the ambiguity that keeps the global form
    # of this question from being landable yet.
    by_name = any(_flow_glob_re(p).match(path) or p == path for p in named)
    by_checker = "phase1_coverage_report_present_check" in commands
    assert by_name or by_checker, (
        f"D1 declares {path} as a required_output but no clause of D1's own "
        f"gate reads it. `test_matrix_d4_criteria_match` CANNOT catch this — "
        f"D1 has exec clauses, so D4 takes the `_assert_artefacts_grounded` "
        f"branch and the ALL-of-N entry-coverage question is only asked of "
        f"files-only gates. Measured: with this clause deleted D4 still reports "
        f"69 passed.")


def test_the_checker_D1_now_calls_actually_exists_and_is_a_gate_program():
    """A clause naming a program that is not there is a gate that cannot run,
    which reads as a pass in every channel that only checks the exit code."""
    steps = _steps()
    commands = _clause_commands(steps["D1"].get("gate"))
    named = [c.split()[0] for c in commands if c.split()]
    assert "phase1_coverage_report_present_check" in named, named
    assert (_PROGRAMS / "phase1_coverage_report_present_check.py").is_file()
