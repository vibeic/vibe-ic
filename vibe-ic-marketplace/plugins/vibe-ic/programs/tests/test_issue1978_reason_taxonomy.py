#!/usr/bin/env python3
"""Issue #1978: non-verdict reasons are typed and affect the P0 tier."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _flow_reason_taxonomy as T  # noqa: E402
from _hostpaths import require_repo  # noqa: E402


def _load_flow():
    spec = importlib.util.spec_from_file_location(
        "issue1978_flow", PROGRAMS / "flow_compliance_check.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


F = _load_flow()


@pytest.fixture
def one_record_per_reason_class():
    cases = [
        (T.DESIGN_DECLARED_NA, "SKIP", "the design declares no command protocol"),
        (T.CAPABILITY_ABSENT, "SKIP", "the required simulator is absent"),
        (T.EXTERNAL, "SKIP", "board-level work is external to this run"),
        (T.BLOCKED_BY_UPSTREAM, "BLOCKED", "the producing step has not run"),
        (T.EXECUTION_ERROR, "INCOMPLETE", "the caller supplied the wrong path"),
        (T.ZERO_DENOMINATOR, "INCOMPLETE", "0 of 13 documents were examined"),
    ]
    return [
        F._p0_gate_record(f"reason_{i}_check", verdict, message,
                          reason_class=reason_class)
        for i, (reason_class, verdict, message) in enumerate(cases)
    ]


def test_every_reason_class_is_represented_and_machine_readable(
        one_record_per_reason_class):
    records = one_record_per_reason_class
    assert {r["reason_class"] for r in records} == set(T.REASON_CLASSES)
    assert all(r["reason_class"] in T.REASON_CLASS_SET for r in records)


def test_only_declared_na_capability_or_external_may_remain_skip(
        one_record_per_reason_class):
    for record in one_record_per_reason_class:
        if record["verdict"] == "SKIP":
            assert record["reason_class"] in T.SKIP_ELIGIBLE
        else:
            assert record["reason_class"] in T.INCOMPLETE


@pytest.mark.parametrize("reason_class, expected", [
    (T.BLOCKED_BY_UPSTREAM, "BLOCKED"),
    (T.EXECUTION_ERROR, "INCOMPLETE"),
    (T.ZERO_DENOMINATOR, "INCOMPLETE"),
])
def test_record_constructor_refuses_unsafe_skip_pairing(reason_class, expected):
    record = F._p0_gate_record(
        "unsafe_skip_check", "SKIP", "same legacy token",
        reason_class=reason_class)
    assert record["verdict"] == expected


@pytest.mark.parametrize("reason_class, expected", [
    (T.DESIGN_DECLARED_NA, "PASS"),
    (T.CAPABILITY_ABSENT, "PASS"),
    (T.EXTERNAL, "PASS"),
    (T.BLOCKED_BY_UPSTREAM, "INCOMPLETE"),
    (T.EXECUTION_ERROR, "INCOMPLETE"),
    (T.ZERO_DENOMINATOR, "INCOMPLETE"),
])
def test_each_reason_class_changes_the_top_level_p0_tier(
        reason_class, expected):
    # Keep the old ambiguous SKIP token fixed.  The reason class alone must
    # change the top-level answer, proving the class is consumed rather than
    # decorative metadata.
    # Deliberately build the already-published record shape directly.  The
    # control run keeps this guard while restoring the old roll-up code, so it
    # observes the wrong top-level VALUE instead of failing merely because the
    # new constructor parameter is absent.
    record = {"name": "same_gate", "verdict": "SKIP",
              "reason_class": reason_class, "message": "same message",
              "evidence": {"exit_code": 2}}
    assert F._p0_umbrella_status(True, [record]) == expected


def test_caller_error_zero_denominator_and_missing_upstream_are_not_skips():
    cases = [
        ("path not found", {}, T.EXECUTION_ERROR, "INCOMPLETE"),
        ("docs loaded NONE; 0/13 examined", {}, T.ZERO_DENOMINATOR,
         "INCOMPLETE"),
        ("no deliverable at RESULT.md — producer has not run", {},
         T.BLOCKED_BY_UPSTREAM, "BLOCKED"),
    ]
    for message, evidence, expected_class, expected_verdict in cases:
        reason_class = T.infer_nonverdict_reason(
            verdict="SKIP", message=message, evidence=evidence)
        assert reason_class == expected_class
        assert T.record_verdict(reason_class) == expected_verdict


def test_bare_not_applicable_is_not_a_design_declaration():
    assert T.infer_nonverdict_reason(
        verdict="SKIP", message="NOT_APPLICABLE") == T.EXECUTION_ERROR


def test_completed_clean_doc_consistency_is_pass(tmp_path, monkeypatch, capsys):
    import doc_consistency_no_unresolved_conflicts_check as gate
    monkeypatch.setattr(sys, "argv", [gate.__file__, str(tmp_path)])
    assert gate.main() == 0
    assert "[PASS]" in capsys.readouterr().out


def test_slot_missing_upstream_is_blocked_in_the_shared_gate_ledger(tmp_path):
    F._GATE_LEDGER.clear()
    ok, out = F._check_program_exit_zero(
        tmp_path,
        "slot_pad_budget_check . --json reports/slot_pad_budget.json")
    assert ok is True                 # no design FAIL was manufactured
    assert out.startswith("INCOMPLETE:")
    row = F._GATE_LEDGER[-1]
    assert row["verdict"] == "BLOCKED"
    assert row["reason_class"] == T.BLOCKED_BY_UPSTREAM


def test_safe_rc2_preserves_the_command_identity(monkeypatch, tmp_path):
    cmd = "declared_na_check ."
    monkeypatch.setattr(
        F, "__check_program_exit_zero",
        lambda _project, _cmd: (
            True, f"{F._VACUOUS_HINT_PREFIX}{_cmd}\nno analog blocks declared"))
    F._GATE_LEDGER.clear()
    ok, out = F._check_program_exit_zero(tmp_path, cmd)
    assert ok is True
    assert out == f"{F._VACUOUS_HINT_PREFIX}{cmd}"
    assert F._GATE_LEDGER[-1]["reason_class"] == T.DESIGN_DECLARED_NA


def test_untyped_json_not_applicable_is_incomplete(monkeypatch, tmp_path):
    report = tmp_path / "gate.json"
    report.write_text('{"status": "NOT_APPLICABLE"}')
    monkeypatch.setattr(
        F, "__check_program_exit_zero",
        lambda _project, _cmd: (True, "gate exited zero"))
    F._GATE_LEDGER.clear()
    ok, out = F._check_program_exit_zero(
        tmp_path, "some_check . --json gate.json")
    assert ok is True
    assert out.startswith("INCOMPLETE:")
    assert F._GATE_LEDGER[-1]["verdict"] == "INCOMPLETE"
    assert F._GATE_LEDGER[-1]["reason_class"] == T.EXECUTION_ERROR


def test_banner_is_not_mistaken_for_the_skip_reason():
    reason = F._p0_skip_reason_from_output(
        "waiver_staleness_check",
        "=== waiver_staleness_check (run) ===\n"
        "  [skipped] 3 of 3 open waiver entries carry no approved_at, so "
        "NONE could be aged",
        "")
    assert "NONE could be aged" in reason
    assert T.infer_nonverdict_reason(message=reason) == T.ZERO_DENOMINATOR


def test_real_flow_keeps_protocol_independent_questions_out_of_class_skips():
    # Real-artifact backing required by flow-change acceptance: prove the four
    # named gates are actual canonical-flow questions, then prove the runtime
    # class tables cannot suppress them wholesale.
    flow = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "flow",
        "phase1_phase2_phase3.yaml").read_text(encoding="utf-8")
    independent = {
        "spice_correlation_check",
        "bit_level_full_stack_tb_oracle_check",
        "l1_electrical_specs_typed_depth_check",
        "assertion_covers_l3_constraints_check",
    }
    assert "spice_correlation_check" in flow
    assert independent <= set(F._STRUCTURAL_RTL_GATES)
    suppressed = (set(F._CLASS_SKIPPABLE_PROTOCOL_GATES)
                  | set(F._CLASS_SKIPPABLE_ANALOG_GATES))
    assert independent.isdisjoint(suppressed)


# ── a counted zero is not an execution error (C1) ──────────────────────────
#
# THE MESSAGES BELOW ARE MEASURED, NOT WRITTEN. Each is the exact prose the
# named gate emits, captured on tree ca330272d through
# `flow_compliance_check._check_program_exit_zero`. A recogniser tuned against
# invented sentences is tuned against nothing.
_ZERO_DENOMINATOR_MESSAGES = {
    "em_peak_current_authority_check, no EM segments":
        "em_peak_current_authority_check: read 0 peak-current figure(s) and 0 "
        "declared supply authority(ies); 0 of 0 segment(s) screened against "
        "Jmax.\n  no comparison was possible: the report declares neither a "
        "peak segment current nor a supply authority.\nINCOMPLETE: "
        "electromigration was NOT screened",
    "si_mcf_sta_check, a SPEF it parsed to zero coupling pairs":
        "VACUOUS_PASS: the SPEF named by the report parses to 2 net record(s), "
        "0 two-node (coupling) *CAP entries and therefore 0 inter-net coupling "
        "pairs, so the MCF fold has nothing to re-derive. Read this as NOT "
        "CHECKED.",
}

_EXECUTION_ERROR_MESSAGES = {
    "sdc_validator_check, a positional that does not exist":
        "[SKIP] sdc_validator_check: NOT CHECKED — the positional "
        "does_not_exist does not exist, so 0 of 2 declared search root(s) "
        "(phase2/stage1/fpga, phase2/stage2/constraints) could be resolved and "
        "0 .sdc file(s) were read. The positional is the PROJECT ROOT",
    "provenance_check, argparse rejecting its own command line":
        "usage: provenance_check.py [-h] [--output OUTPUT] [--tool TOOL]\n"
        "provenance_check.py: error: argument --output: expected one argument",
    "a program that crashed":
        "Traceback (most recent call last):\n  File \"g.py\", line 3, in <m>\n"
        "ZeroDivisionError: division by zero",
}


@pytest.mark.parametrize("label", sorted(_ZERO_DENOMINATOR_MESSAGES))
def test_a_counted_zero_over_a_read_input_is_a_zero_denominator(label):
    """`EXECUTION_ERROR` says the program errored. These two did not: one read
    an EM report and found no segments, the other opened a SPEF, parsed two net
    records, and found no coupling. Booking them as errors sends a reviewer to
    debug a crash that did not happen."""
    assert T.infer_nonverdict_reason(
        message=_ZERO_DENOMINATOR_MESSAGES[label]) == T.ZERO_DENOMINATOR


@pytest.mark.parametrize("label", sorted(_EXECUTION_ERROR_MESSAGES))
def test_a_real_execution_fault_stays_an_execution_error(label):
    """THE OTHER DIRECTION, and the reason the patterns above are narrow.

    The sdc message truthfully reports `0 .sdc file(s) were read` and `0 of 2
    ... could be resolved`: zeroes that are the CONSEQUENCE of a bad argument,
    not a denominator anybody measured. A widening that swallows this sentence
    has widened too far, and this parametrisation is what says so."""
    assert T.infer_nonverdict_reason(
        message=_EXECUTION_ERROR_MESSAGES[label]) == T.EXECUTION_ERROR


def test_the_reclassification_greens_nothing():
    """THE ANTI-BACKDOOR PIN. Fixing the recogniser must not be a route back to
    the skip tier — the whole reason C1's five migrated assertions could not be
    'fixed' this way. Both classes are outside SKIP_ELIGIBLE, so both render
    INCOMPLETE; only the published row's wording changes."""
    for cls in (T.ZERO_DENOMINATOR, T.EXECUTION_ERROR):
        assert cls not in T.SKIP_ELIGIBLE
        assert T.record_verdict(cls) == "INCOMPLETE"
        assert T.p0_tier_for_reason_classes([cls]) == "INCOMPLETE"


def test_zero_of_zero_and_zero_of_n_are_not_the_same_question():
    """The discriminator, isolated. `0 of 0` is an empty population; `0 of N`
    is a population of N that failed to resolve, which is a fault."""
    assert T.infer_nonverdict_reason(
        message="0 of 0 segment(s) screened") == T.ZERO_DENOMINATOR
    assert T.infer_nonverdict_reason(
        message="the positional does not exist, so 0 of 2 declared search "
                "root(s) could be resolved") == T.EXECUTION_ERROR


# ── why a producer must declare, and prose cannot decide for it ────────────
#
# THE TWO SENTENCES BELOW ARE MEASURED, and they are the reason this file
# cannot grow a counted-zero recogniser for either of them. Both state a zero
# of the SAME noun. One is a zero denominator; the other is a design saying
# the question does not apply to it. No lexical rule separates them, because
# what separates them is what CAUSED the zero — and only the gate knows that.
_SI_ZERO = (
    "the SPEF named by the report parses to 2 net record(s), 0 two-node "
    "(coupling) *CAP entries and therefore 0 inter-net coupling pairs, so the "
    "MCF fold has nothing to re-derive")
_SI_ZERO_BARE = (
    "0 two-node (coupling) *CAP entries and therefore 0 inter-net coupling "
    "pairs")
_FSTC_NA = (
    "VACUOUS_PASS: no command protocol - the design's L3 declares no opcodes "
    "(L3.json); per-opcode state-transition coverage is N/A for this "
    "non-protocol IC (0 coverage entries, nothing to assert)")


def test_two_gates_state_the_same_shaped_zero_and_mean_opposite_classes():
    """MEASURED, and the measurement is the point.

    `si_mcf_sta_check` opened its input, parsed it, and found the population
    empty -> ZERO_DENOMINATOR, which is NOT skip-eligible and must not become a
    benign skip. `functional_state_transition_coverage_check` was told by the
    design that the question does not apply -> DESIGN_DECLARED_NA, which IS
    skip-eligible and must not be turned into an incomplete.

    Written out, both sentences contain `0 <words> entries`. A counted-zero
    pattern wide enough for the first is wide enough for the second, and it
    would fire FIRST -- `_ZERO_RE` is tried before `_DECLARED_NA_RE` -- turning
    every non-protocol IC's honest N/A into an unexamined question. This test
    exists so the next author who reaches for that pattern measures it against
    this pair before landing it."""
    import re
    counted_zero = re.compile(
        r"\b0\s+[^\n]{0,40}?\b(?:entr(?:y|ies)|pairs?|records?)\b", re.I)
    assert counted_zero.search(_SI_ZERO), _SI_ZERO
    assert counted_zero.search(_SI_ZERO_BARE), _SI_ZERO_BARE
    assert counted_zero.search(_FSTC_NA), (
        "if this stops matching, the two sentences have become lexically "
        "separable and a recogniser may be worth revisiting")


def test_the_declared_class_decides_both_and_the_prose_decides_neither():
    """THE REMEDY, and it is the one `_flow_reason_taxonomy`'s own docstring
    already asks for: "Producers should publish an explicit `reason_class`
    whenever possible."

    Given the declaration, both sentences classify correctly and the ambiguity
    above is irrelevant. Without it, the fail-closed default books BOTH as
    EXECUTION_ERROR -- "the gate blew up" -- which is wrong about both."""
    # The full si sentence is recognised today, but only because it ENDS with
    # "nothing to re-derive" (v1.16.64). State the same fact WITHOUT that
    # clause -- which `_vacuity`'s sibling branches do -- and the fail-closed
    # default books it "the gate blew up".
    assert T.infer_nonverdict_reason(message=_SI_ZERO) == T.ZERO_DENOMINATOR
    assert T.infer_nonverdict_reason(
        message=_SI_ZERO_BARE) == T.EXECUTION_ERROR
    assert T.infer_nonverdict_reason(
        message=_SI_ZERO_BARE,
        explicit=T.ZERO_DENOMINATOR) == T.ZERO_DENOMINATOR
    assert T.infer_nonverdict_reason(
        message=_FSTC_NA, explicit=T.DESIGN_DECLARED_NA) == T.DESIGN_DECLARED_NA
    # ...and the two land on OPPOSITE sides of the skip bar, which is why
    # getting it wrong is not a cosmetic error.
    assert T.ZERO_DENOMINATOR not in T.SKIP_ELIGIBLE
    assert T.DESIGN_DECLARED_NA in T.SKIP_ELIGIBLE
    assert T.p0_tier_for_reason_classes([T.ZERO_DENOMINATOR]) == "INCOMPLETE"
    assert T.p0_tier_for_reason_classes([T.DESIGN_DECLARED_NA]) == "PASS"


def test_both_gates_actually_declare_what_this_test_assumes():
    """The pair above is only an argument if both gates really do declare.
    Read it out of the shipped sources rather than trusting the prose."""
    si = (PROGRAMS / "si_mcf_sta_check.py").read_text(encoding="utf-8")
    fstc = (PROGRAMS
            / "functional_state_transition_coverage_check.py").read_text(
                encoding="utf-8")
    assert 'summary["reason_class"] = _reason_taxonomy.ZERO_DENOMINATOR' in si
    assert '"reason_class"' in fstc and "DESIGN_DECLARED_NA" in fstc
