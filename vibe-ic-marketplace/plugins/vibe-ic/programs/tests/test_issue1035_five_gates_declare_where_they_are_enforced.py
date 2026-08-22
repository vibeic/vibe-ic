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

import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
_FLOW = _PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
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


def _audit_mod():
    """A private copy, so a sibling test's `sys.modules` entry cannot decide
    which version of the program this file measures."""
    spec = importlib.util.spec_from_file_location(
        "_fgea_1035", _PROGRAMS / "flow_gate_enforcement_audit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ───────────────────────────────────────────── axis 1: the declaration exists

@pytest.mark.parametrize("gate,_step,_slot", _GATES)
def test_the_gate_declares_an_intent_the_audit_can_read(gate, _step, _slot):
    """RETURNED VALUE, not a grep. `declared_intent` is the exact function the
    audit calls to decide DECLARED vs UNDECLARED, so this cannot pass on a
    declaration the audit would not see — one indented past a comment marker it
    does not accept, one below the 4000-character window, or one that is prose
    about the token rather than the token opening a line."""
    mod = _audit_mod()
    assert mod.declared_intent(_PROGRAMS, gate) == "advisory", (
        f"{gate} does not state where its verdict is consumed in a form the "
        f"audit reads: `ENFORCEMENT: advisory|blocking` opening a line in the "
        f"first 4000 characters, or a lone `\"verdict_mode\"` literal")


# ────────────────────────────────── axis 2: the declaration bought no demotion

@pytest.mark.parametrize("gate,step,slot", _GATES)
def test_the_declaration_did_not_move_the_gate_between_flow_slots(
        gate, step, slot):
    """THE PAIRED HALF OF THE DECLARATION, and the one worth the most.

    `advisory` answers "no runner spawns this inline". It is NOT a statement
    that the finding may be ignored, and it must never be cited to move a
    clause from `program_exit_zero` to `advisory_program_exit_zero`, where
    `_evaluate_gate` records the finding and passes the step anyway. Three of
    these five are in the blocking slot on a measured argument recorded at
    their flow rows; if this declaration ever becomes the reason one of them
    moves, this assertion is what fails.

    It pins the advisory two just as hard, in the other direction: they are
    advisory by MEASUREMENT (41 of 107 published roots red for one broken L6
    extractor; 1 demonstrable wrong ruler in L9's 8 reds) with a promotion
    condition stated in each program, and a silent promotion would be as
    unreviewed as a silent demotion.

    Read from `clauses_in_flow` — the audit's own structural walk — so this is
    an assertion about what the flow ENGINE would dispatch, not about the text
    of a YAML line.
    """
    mod = _audit_mod()
    slots = sorted({c["slot"] for c in mod.clauses_in_flow(_FLOW)
                    if c["gate"] == gate})
    assert slots == [slot], (
        f"{gate} (step {step}) is wired in {slots}, not [{slot!r}]; the "
        f"`ENFORCEMENT: advisory` declaration answers a different axis and is "
        f"not permission to move this clause")


# ─────────────────────────────────────────────────── axis 3: end to end, rc 0

def test_the_audit_exits_zero_and_names_none_of_the_five(tmp_path):
    """END TO END, on EXIT CODE and EMITTED JSON.

    The failing runner is `tools/ci/repo_hygiene_gates.sh`, which invokes this
    program and reads its exit status, so the exit status is what this asserts.
    The JSON half is there because rc 0 alone is also satisfied by an audit
    that has stopped looking at these gates — which is the failure mode the
    controls at the bottom of this file exist to rule out.
    """
    out = tmp_path / "audit.json"
    # 60s is the per-call ceiling `ci_harness_timeout_ceiling_check` enforces
    # (the 180s harness session bound // 3): a bound above it can outlive the
    # session and take the rest of the subset down with it.
    cp = subprocess.run(
        [sys.executable, str(_PROGRAMS / "flow_gate_enforcement_audit.py"),
         "--json", str(out)],
        capture_output=True, text=True, timeout=60)
    assert cp.returncode == 0, (
        f"rc={cp.returncode}\n{cp.stdout[-4000:]}\n{cp.stderr[-2000:]}")
    rep = json.loads(out.read_text())
    undeclared = {u["gate"] for u in rep["undeclared_audit_only"]}
    contradicting = {c["gate"] for c in rep["contradictions"]}
    orphaned = {o["gate"] for o in rep["orphaned"]}
    rows = {r["gate"]: r for r in rep["gates"]}
    for gate, step, slot in _GATES:
        assert gate in rows, f"{gate} is not in the flow definition at all"
        assert rows[gate]["declared"] == "advisory", rows[gate]
        assert rows[gate]["slots"] == [slot], (step, rows[gate])
        assert gate not in undeclared
        assert gate not in contradicting
        assert gate not in orphaned


def test_the_recorded_register_did_not_grow_to_absorb_the_five():
    """The OTHER way to make the audit green, and the one this change refuses.

    `--write-baseline --scope-expanded '<why>'` would have recorded the five as
    permanent debt and exited 0 without any gate saying anything about itself.
    The register is shrink-only and the five must be paid down OUT of it, not
    INTO it, so this pins both halves: the file still records 116 entries, and
    none of them is one of the five.
    """
    doc = json.loads(_BASELINE.read_text())
    recorded = set(doc["undeclared_known"])
    for gate, _step, _slot in _GATES:
        assert f"undeclared::{gate}" not in recorded, (
            f"{gate} was recorded as debt instead of declaring an intent")
        assert f"undeclared::{gate}.py" not in recorded, gate
    prev = doc["undeclared_previous_size"]
    assert prev is None or len(recorded) <= prev, (
        f"the shrink-only register grew: {prev} -> {len(recorded)}")
    # `--write-baseline` will only GROW the register when a `--scope-expanded`
    # reason NAMES an entry it excuses (vibe-ic#900). The register does carry
    # one such reason already, recorded when #886 created it; what must stay
    # true is that no reason names one of the five, because that is exactly the
    # escape route this change refused to take.
    for key in ("scope_expanded", "undeclared_scope_expanded"):
        reason = doc.get(key) or ""
        for gate, _step, _slot in _GATES:
            assert gate not in reason, (
                f"the {key} reason names {gate}, so the register was widened "
                f"to absorb it instead of the gate declaring an intent")
    # And the register must still be EXACT: every recorded entry still holds,
    # and nothing the audit finds is missing from it. A register that merely
    # "does not contain the five" is also satisfied by one that has drifted out
    # of step with the tree in some other direction.
    mod = _audit_mod()
    computed = {f"undeclared::{u['gate']}"
                for u in mod.audit(_FLOW, _PROGRAMS)["undeclared_audit_only"]}
    assert computed == recorded, {
        "new_and_unrecorded": sorted(computed - recorded),
        "recorded_but_paid": sorted(recorded - computed)}


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
_FLOW_DOC = textwrap.dedent("""\
    steps:
      - id: 1
        name: "synthetic"
        gate:
          all_of:
    {rows}
    """)


def _synthetic(root: Path, gates: dict):
    """A synthetic plugin tree: every gate is wired into the flow's BLOCKING
    slot and NOTHING invokes any of them, which is the shape all five real
    gates are in."""
    progs = root / "programs"
    progs.mkdir(parents=True, exist_ok=True)
    for name, body in gates.items():
        (progs / f"{name}.py").write_text(body)
    flow = root / "flow.yaml"
    flow.write_text(_FLOW_DOC.format(rows="\n".join(
        f'        - program_exit_zero: "{n} . --json out.json"'
        for n in gates)))
    return flow, progs


def test_the_control_a_genuinely_undeclared_new_gate_is_still_reported(
        tmp_path):
    """THE GUARD. A sixth gate, added later, wired where it cannot block and
    saying nothing about that — the exact shape of the five — must still be
    named and must still exit 1.

    Both halves are asserted. `audit()` naming it proves the finding survives;
    `main()` returning 1 proves the finding still REACHES the exit status that
    `repo_hygiene_gates.sh` reads, which is the only channel that can stop a
    landing. A finding reported into a report nobody's exit code depends on is
    the #306 defect this whole program is about.
    """
    mod = _audit_mod()
    flow, progs = _synthetic(tmp_path / "t", {
        "declared_sibling_check": _DECLARING,     # like the five: green
        "brand_new_quiet_check": _SILENT,         # the regression: must fail
    })
    rep = mod.audit(flow, progs)
    assert [u["gate"] for u in rep["undeclared_audit_only"]] == [
        "brand_new_quiet_check"], rep
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"known": [], "undeclared_known": []}))
    assert mod.main(["--flow", str(flow), "--programs", str(progs),
                     "--baseline", str(baseline)]) == 1


def test_the_control_a_declared_gate_beside_it_stays_green(tmp_path):
    """The other half of the same tree, so "reports the new one" cannot be
    satisfied by reporting everything. A gate that declares `advisory` and is
    wired audit-only has made a decision that matches its wiring, and punishing
    it would make the register penalise exactly the gates that complied."""
    mod = _audit_mod()
    flow, progs = _synthetic(tmp_path / "t", {
        "declared_sibling_check": _DECLARING})
    rep = mod.audit(flow, progs)
    assert rep["undeclared_audit_only"] == [], rep
    assert rep["contradictions"] == [], rep
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"known": [], "undeclared_known": []}))
    assert mod.main(["--flow", str(flow), "--programs", str(progs),
                     "--baseline", str(baseline)]) == 0


def test_the_control_declaring_blocking_without_the_wiring_still_fails(
        tmp_path):
    """The third shape, and the reason `advisory` is the honest token for all
    five rather than `blocking`.

    Three of the five sit in the flow's BLOCKING slot, so `ENFORCEMENT:
    blocking` is a tempting thing to write in them. It would be a different
    claim — that a runner can stop the step — and the audit files it as a
    `contradiction::`, which fails just as hard and in a register whose debt is
    paid down differently. This control proves that branch is live, so the
    choice of `advisory` is a measured one and not a way around a check.
    """
    mod = _audit_mod()
    flow, progs = _synthetic(tmp_path / "t", {
        "overclaiming_check": _DECLARING_BLOCKING})
    rep = mod.audit(flow, progs)
    assert [c["gate"] for c in rep["contradictions"]] == [
        "overclaiming_check"], rep
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"known": [], "undeclared_known": []}))
    assert mod.main(["--flow", str(flow), "--programs", str(progs),
                     "--baseline", str(baseline)]) == 1


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve()), "-v"]))
