#!/usr/bin/env python3
"""ORGANIC #885 — the enforcement audit could not see 31 of the flow's 150
gates, so those 31 were audited by nothing at all.

THE DEFECT. `flow_gate_enforcement_audit.gates_in_flow` matched

    (?:optional_|advisory_)?program_exit_zero:\\s*["']?([\\w./-]+)

over the RAW TEXT of the flow definition. `\\s*` matches newlines. Against the
NESTED clause form the flow uses for every conditional gate —

    - optional_program_exit_zero:
        command: "spare_cell_preservation_check . --json ..."
        condition_files_exist: [...]

— the match ran past the end of the line and captured the following YAML KEY.
All 31 nested clauses collapsed into a single literal gate named `command`.
Measured on the real flow definition: 120 gates reported, 150 actually wired.

WHY IT MATTERS TWICE. An audit that cannot SEE a gate cannot report that gate
is unenforced, so the enforcement gap was under-reported by 31 — and
`post_route_signoff_corner_check`, which IS invoked inline by
`phase3_one_shot_runner._DECLARED_SIGNOFF_GATES` and therefore CAN block, got
no credit for it. The tally lied in both directions at once.

THE FIX these tests pin: read the flow with PyYAML — the same loader
`flow_compliance_check` uses to EXECUTE these clauses — and walk the document
structurally, so the audit's grammar is the engine's grammar rather than an
approximation of it.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import flow_gate_enforcement_audit as A  # noqa: E402

_FLOW = _PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"

# The keys of the clause grammar itself. None of them is a gate; every one of
# them is what the old regex captured instead of a gate.
_GRAMMAR_KEYS = {"command", "condition_files_exist"}


def _write_flow(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "flow.yaml"
    p.write_text(text)
    return p


# --------------------------------------------------------------------------
# The defect, minimal and chip-agnostic.
# --------------------------------------------------------------------------

def test_885_nested_clause_yields_the_gate_not_the_next_yaml_key(tmp_path):
    """THE regression. The nested form must name the PROGRAM, never `command`.

    Before the fix this returned `['command', 'flat_beta_check']`: the two
    nested gates vanished and a key of the grammar took their place.
    """
    flow = _write_flow(tmp_path, (
        "steps:\n"
        "  - id: 1\n"
        "    gate:\n"
        "      all_of:\n"
        "        - optional_program_exit_zero:\n"
        '            command: "nested_alpha_check . --json a.json"\n'
        '            condition_files_exist: ["in/alpha.txt"]\n'
        "        - advisory_program_exit_zero:\n"
        '            command: "nested_gamma_check . --json g.json"\n'
        '            condition_files_exist: ["in/gamma.txt"]\n'
        '        - program_exit_zero: "flat_beta_check . --json b.json"\n'
    ))
    assert A.gates_in_flow(flow) == [
        "flat_beta_check", "nested_alpha_check", "nested_gamma_check"]


def test_885_mapping_form_of_the_required_slot_is_walked_too(tmp_path):
    """`program_exit_zero:` also takes the mapping form (the flow's clock-plan
    step authors it that way). It swallowed the newline identically."""
    flow = _write_flow(tmp_path, (
        "steps:\n"
        "  - id: 16\n"
        "    gate:\n"
        "      program_exit_zero:\n"
        '        command: "nested_required_check . --json r.json"\n'
    ))
    assert A.gates_in_flow(flow) == ["nested_required_check"]


def test_885_a_swallowed_gate_is_a_gate_audited_by_nothing(tmp_path):
    """The consequence, stated as the audit's own output: a nested gate must
    get a row. Before the fix it had none, so no verdict about it existed."""
    (tmp_path / "nested_alpha_check.py").write_text('"""x"""\n')
    flow = _write_flow(tmp_path, (
        "steps:\n"
        "  - id: 1\n"
        "    gate:\n"
        "      all_of:\n"
        "        - optional_program_exit_zero:\n"
        '            command: "nested_alpha_check . --json a.json"\n'
        '            condition_files_exist: ["in/alpha.txt"]\n'
    ))
    rep = A.audit(flow, tmp_path)
    names = [r["gate"] for r in rep["gates"]]
    assert names == ["nested_alpha_check"]
    assert "command" not in names
    assert rep["total_gates"] == 1


def test_885_declared_intent_of_a_nested_gate_is_read(tmp_path):
    """A nested gate that DECLARES blocking while wired audit-only is the
    contradiction this audit exists to raise. While it was invisible, its
    declaration could not be read at all — the debt register was blind to
    every nested gate."""
    (tmp_path / "nested_alpha_check.py").write_text(
        '"""x\n\nENFORCEMENT: blocking\n"""\n')
    flow = _write_flow(tmp_path, (
        "steps:\n"
        "  - id: 1\n"
        "    gate:\n"
        "      all_of:\n"
        "        - optional_program_exit_zero:\n"
        '            command: "nested_alpha_check . --json a.json"\n'
        '            condition_files_exist: ["in/alpha.txt"]\n'
    ))
    rep = A.audit(flow, tmp_path)
    assert [c["gate"] for c in rep["contradictions"]] == ["nested_alpha_check"]


def test_885_a_nested_gate_is_not_reported_orphaned(tmp_path):
    """The second-order lie. ORPHANED means `not in the flow definition at
    all`. A gate the parser could not see looks exactly like one that is not
    wired, so a wired gate could be reported as reachable by nothing."""
    (tmp_path / "nested_alpha_check.py").write_text(
        '"""x\n\nENFORCEMENT: advisory\n"""\n')
    flow = _write_flow(tmp_path, (
        "steps:\n"
        "  - id: 1\n"
        "    gate:\n"
        "      all_of:\n"
        "        - optional_program_exit_zero:\n"
        '            command: "nested_alpha_check . --json a.json"\n'
        '            condition_files_exist: ["in/alpha.txt"]\n'
    ))
    rep = A.audit(flow, tmp_path)
    assert [o["gate"] for o in rep["orphaned"]] == []


def test_885_deeply_nested_and_any_of_clauses_are_reached(tmp_path):
    """The walk is structural, not positional: gates live under `gate:`,
    `all_of:`, `any_of:` and per-step lists at varying depth."""
    flow = _write_flow(tmp_path, (
        "steps:\n"
        "  - id: 1\n"
        "    gate:\n"
        "      any_of:\n"
        "        - all_of:\n"
        '            - program_exit_zero: "deep_one_check . --json 1.json"\n'
        "            - optional_program_exit_zero:\n"
        '                command: "deep_two_check . --json 2.json"\n'
        '                condition_files_exist: ["x"]\n'
    ))
    assert A.gates_in_flow(flow) == ["deep_one_check", "deep_two_check"]


# --------------------------------------------------------------------------
# The same invariants, asserted against the REAL flow definition.
# --------------------------------------------------------------------------

def test_885_no_grammar_key_is_ever_reported_as_a_gate():
    """The cheapest statement of the bug that stays true as gates are added:
    `command` is a key of the clause grammar, never the name of a gate."""
    rep = A.audit(_FLOW, _PROGRAMS)
    leaked = sorted({r["gate"] for r in rep["gates"]} & _GRAMMAR_KEYS)
    assert leaked == [], (
        f"clause-grammar keys reported as gates: {leaked} — the flow parser "
        f"is matching text across a newline again")


def test_885_every_audited_gate_resolves_to_a_real_program():
    """Non-vacuous and stable: a gate name is the first token of a command the
    flow engine will actually run, so `programs/<name>.py` must exist. `command`
    has no `command.py`, which is how this test catches the original defect
    without pinning a headcount that legitimately grows."""
    rep = A.audit(_FLOW, _PROGRAMS)
    missing = sorted(r["gate"] for r in rep["gates"]
                     if not (_PROGRAMS / f"{r['gate']}.py").is_file())
    assert missing == [], f"gate names with no program file: {missing}"


def test_885_the_nested_gates_named_in_the_finding_are_audited():
    """The five gates the review confirmed hidden. Each is wired in the flow
    definition's nested form; each had no row at all."""
    rep = A.audit(_FLOW, _PROGRAMS)
    names = {r["gate"] for r in rep["gates"]}
    for gate in ("spare_cell_preservation_check", "si_crosstalk_check",
                 "si_mcf_sta_check", "gds_antenna_deck_check",
                 "post_route_signoff_corner_check"):
        assert gate in names, f"{gate} is wired in the flow but not audited"


def test_885_an_inline_wired_nested_gate_gets_credit_for_it():
    """`post_route_signoff_corner_check` is invoked inline by
    `phase3_one_shot_runner._DECLARED_SIGNOFF_GATES`, so it CAN block the step
    it guards. The swallowed clause denied it that credit — the tally
    understated enforcement, not only coverage."""
    rep = A.audit(_FLOW, _PROGRAMS)
    row = next((r for r in rep["gates"]
                if r["gate"] == "post_route_signoff_corner_check"), None)
    assert row is not None
    assert row["enforcement"] == "ENFORCED", row


def test_885_the_real_flow_has_more_gates_than_the_regex_could_see():
    """A floor, not a target. The broken parser reported 120; the structural
    walk reports 150. If this drops below 150 a gate was REMOVED from the flow
    — deliberate or not, that must be noticed."""
    rep = A.audit(_FLOW, _PROGRAMS)
    assert rep["total_gates"] >= 150, rep["total_gates"]
    assert rep["total_clauses"] >= rep["total_gates"]


# --------------------------------------------------------------------------
# The fix must not become a NEW silent under-report.
# --------------------------------------------------------------------------

def test_885_a_clause_with_no_command_is_surfaced_not_dropped(tmp_path):
    """An unrunnable clause runs nothing, so it certifies nothing. Dropping it
    from the tally would be #885 in a new shape."""
    flow = _write_flow(tmp_path, (
        "steps:\n"
        "  - id: 1\n"
        "    gate:\n"
        "      all_of:\n"
        "        - optional_program_exit_zero:\n"
        '            condition_files_exist: ["in/alpha.txt"]\n'
    ))
    rep = A.audit(flow, tmp_path)
    assert rep["total_gates"] == 0
    assert len(rep["malformed_clauses"]) == 1
    assert rep["malformed_clauses"][0]["slot"] == "optional_program_exit_zero"


def test_885_the_real_flow_has_no_malformed_clause():
    rep = A.audit(_FLOW, _PROGRAMS)
    assert rep["malformed_clauses"] == []


def test_885_an_unparseable_flow_fails_loudly_never_partially(tmp_path):
    """A short gate list because the parser choked is indistinguishable from a
    flow with fewer gates. The audit must refuse to produce one."""
    flow = _write_flow(tmp_path, "steps:\n  - id: 1\n   bad_indent: [\n")
    with pytest.raises(A.FlowGrammarError):
        A.gates_in_flow(flow)
    rc = subprocess.run(
        [sys.executable, str(_PROGRAMS / "flow_gate_enforcement_audit.py"),
         "--flow", str(flow), "--programs", str(tmp_path)],
        capture_output=True, text=True)
    assert rc.returncode == 2, rc.stdout + rc.stderr


def test_885_missing_pyyaml_is_an_error_not_a_shorter_list(tmp_path, monkeypatch):
    """Without the loader the audit has no grammar. Returning `[]` would read
    as `this flow declares no gates`, the most dangerous lie available here."""
    flow = _write_flow(
        tmp_path, '      - program_exit_zero: "flat_beta_check . --json b"\n')
    monkeypatch.setattr(A, "yaml", None)
    with pytest.raises(A.FlowGrammarError):
        A.gates_in_flow(flow)


# --------------------------------------------------------------------------
# The tally the CLI prints must be the tally the report holds.
# --------------------------------------------------------------------------

def test_885_cli_json_and_stdout_agree_on_the_real_flow(tmp_path):
    out = tmp_path / "rep.json"
    rc = subprocess.run(
        [sys.executable, str(_PROGRAMS / "flow_gate_enforcement_audit.py"),
         "--json", str(out)], capture_output=True, text=True)
    assert rc.returncode in (0, 1), rc.stdout + rc.stderr
    rep = json.loads(out.read_text())
    assert f"gates in flow definition : {rep['total_gates']}" in rc.stdout
    assert rep["enforced"] + rep["audit_only"] == rep["total_gates"]
    assert len(rep["gates"]) == rep["total_gates"]
