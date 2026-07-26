"""test_p0_failed_gate_names_preserved.py — the audit JSON must keep the
NAMES of every failing P0 sub-gate, no matter how many failed.

THE DEFECT THIS PINS DOWN
-------------------------
The P0 umbrella emits its failing sub-gates in one of two shapes, chosen
purely by HOW MANY gates failed:

    exactly 1 failure   ->  "FAIL: <gate> — <msg>"                  (Form 1)
    2 or more failures  ->  "Failed gates (N):"
                            "  - <gate> — <msg>"                    (Form 2)

`flow_compliance_check.main()` built the machine-readable audit artifact
`reports/audit/phase23_completion_audit.json` with matchers that recognised
Form 1 ONLY. So `failed_gates` / `failed_gate_count` / `gates` came out
EMPTY exactly when two or more gates failed — the list went blank precisely
when it had the most to report, while a single-failure run reported fine.

Measured end-to-end on a real run dir, plugin 1.5.85 and plugin 1.6.4 (the
two files are byte-identical in this region, so this is NOT a version
regression — the variable is the failure COUNT):

    2 failing gates -> "failed_gates": []
    1 failing gate  -> "failed_gates": ["provenance_output_hash_completeness_check"]

This matters because that artifact is, by its own comment at the write site,
"the contract the mcp-eda pre-burn guard now consumes (replacing the brittle
stdout regex parser that produced 0 failed_gates from 14 real FAILs)". The
replacement reintroduced the very failure mode it was written to eliminate.

A correct Form-2-aware parser — `_parse_p0_failing_subgates` — already
existed in the same file and is already trusted by the promotion logic. The
JSON writer simply never called it.

BIDIRECTIONAL
-------------
Every test below is written so that it FAILS if the normalisation is removed
and PASSES with it in place. The Form-1 tests are the no-regression half:
they must keep passing, which is what stops the fix from being "rewrite the
parser and hope".
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]


def _load():
    """Import flow_compliance_check by path (programs/ is not a package)."""
    mod_name = "_fcc_under_test"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(
        mod_name, _PROGRAMS / "flow_compliance_check.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


fcc = _load()


# --------------------------------------------------------------------------
# The two real shapes, transcribed from the composition site.
# --------------------------------------------------------------------------

FORM1_ONE_FAILURE = [
    "FAIL: provenance_output_hash_completeness_check — FAIL: 1 provenance "
    "fault(s):",
]

FORM2_TWO_FAILURES = [
    "Failed gates (2):",
    "  - project_outputs_in_tree_check — [FAIL] project_outputs_in_tree_check: "
    "1 live external-storage artifact(s)",
    "  - provenance_output_hash_completeness_check — FAIL: 1 provenance "
    "fault(s):",
]

FORM2_FOUR_FAILURES = [
    "Failed gates (4):",
    "  - l1_pin_bus_width_actionable_check — FAIL: 1/1 bus-confirmed pin(s) "
    "carry no width phase2 can emit a port declaration from.",
    "  - l22_verification_plan_measurable_check — [FAIL] "
    "TARGET_OUTSIDE_CONSUMING_LAYER",
    "  - project_outputs_in_tree_check — [FAIL] 7 live external-storage "
    "artifact(s)",
    "  - provenance_output_hash_completeness_check — FAIL: 1 provenance "
    "fault(s):",
]


def _fail_names(reasons):
    return [g["name"] for g in fcc._per_gate_from_p0_reasons(reasons)
            if g["verdict"] == "FAIL"]


# --------------------------------------------------------------------------
# DEFECT DIRECTION — these are the assertions that go red without the fix.
# --------------------------------------------------------------------------

def test_form2_two_failures_keeps_both_names():
    """The measured defect: 2 failures -> the list was empty."""
    assert _fail_names(FORM2_TWO_FAILURES) == [
        "project_outputs_in_tree_check",
        "provenance_output_hash_completeness_check",
    ]


def test_form2_four_failures_keeps_all_four_names():
    assert _fail_names(FORM2_FOUR_FAILURES) == [
        "l1_pin_bus_width_actionable_check",
        "l22_verification_plan_measurable_check",
        "project_outputs_in_tree_check",
        "provenance_output_hash_completeness_check",
    ]


def test_form2_never_yields_an_empty_list_when_gates_failed():
    """The invariant that the whole verification discipline rests on:
    a FAILing P0 must never hand downstream an empty NAME SET."""
    for reasons in (FORM2_TWO_FAILURES, FORM2_FOUR_FAILURES):
        assert _fail_names(reasons), (
            "empty failed-gate name set for a P0 that reported failures")


def test_form2_header_is_not_mistaken_for_a_gate():
    """`Failed gates (4):` is a header, not a gate. It must not appear as
    a name, and must not be silently counted as a passing gate either."""
    names = [g["name"] for g in fcc._per_gate_from_p0_reasons(
        FORM2_FOUR_FAILURES)]
    assert not any("Failed" in n for n in names), names
    assert len(names) == 4, names


def test_form2_messages_survive_not_just_names():
    per = fcc._per_gate_from_p0_reasons(FORM2_TWO_FAILURES)
    by_name = {g["name"]: g["message"] for g in per}
    assert "provenance fault" in \
        by_name["provenance_output_hash_completeness_check"]


# --------------------------------------------------------------------------
# NO-REGRESSION DIRECTION — Form 1 already worked and must keep working.
# --------------------------------------------------------------------------

def test_form1_single_failure_still_parsed():
    assert _fail_names(FORM1_ONE_FAILURE) == [
        "provenance_output_hash_completeness_check"]


def test_form1_pass_lines_still_parsed_as_pass():
    per = fcc._per_gate_from_p0_reasons(
        ["PASS: testbench_exists_check — ok"])
    assert per == [{"name": "testbench_exists_check",
                    "verdict": "PASS",
                    "message": "ok"}]


def test_bare_inline_check_line_still_parsed():
    """The third historical shape: a bare `<name>_check — msg` line."""
    per = fcc._per_gate_from_p0_reasons(
        ["lint_clean_check — [FAIL] 3 lint errors"])
    assert per[0]["name"] == "lint_clean_check"
    assert per[0]["verdict"] == "FAIL"


def test_empty_and_blank_reasons_are_safe():
    assert fcc._per_gate_from_p0_reasons([]) == []
    assert fcc._per_gate_from_p0_reasons(None) == []
    assert fcc._per_gate_from_p0_reasons(["", "   "]) == []


# --------------------------------------------------------------------------
# The COUNT is the only variable — this is the factorial, as a test.
# --------------------------------------------------------------------------

def test_same_gate_reported_identically_in_both_shapes():
    """One gate, two shapes, one answer. If the name set depends on which
    shape the umbrella happened to choose, the bug is back."""
    one = _fail_names(
        ["FAIL: provenance_output_hash_completeness_check — 1 fault"])
    two = _fail_names(
        ["Failed gates (2):",
         "  - provenance_output_hash_completeness_check — 1 fault",
         "  - project_outputs_in_tree_check — 1 live artifact"])
    assert one[0] in two
    assert set(one).issubset(set(two))


@pytest.mark.parametrize("n", [2, 3, 5, 12])
def test_name_set_size_tracks_failure_count(n):
    """14 real FAILs producing 0 names is the historical incident this
    artifact was created to end. Scale it."""
    reasons = [f"Failed gates ({n}):"] + [
        f"  - gate_{i}_check — [FAIL] synthetic" for i in range(n)]
    got = _fail_names(reasons)
    assert len(got) == n, f"expected {n} names, got {len(got)}: {got}"


# --------------------------------------------------------------------------
# The normaliser itself.
# --------------------------------------------------------------------------

def test_normalise_maps_form2_onto_form1():
    assert fcc._normalise_p0_reason_line("  - foo_check — bar") == \
        "FAIL: foo_check — bar"


def test_normalise_drops_the_header_only():
    assert fcc._normalise_p0_reason_line("Failed gates (3):") == ""
    assert fcc._normalise_p0_reason_line(
        "FAIL: foo_check — bar") == "FAIL: foo_check — bar"


# --------------------------------------------------------------------------
# The backstop: the canonical parser and the JSON writer must agree.
# --------------------------------------------------------------------------

def test_canonical_parser_and_json_writer_agree_on_form2():
    """`_parse_p0_failing_subgates` handled Form 2 all along and the JSON
    writer did not. They must not be able to disagree again."""
    p0 = SimpleNamespace(id="P0", status="FAIL",
                         reasons=FORM2_FOUR_FAILURES)
    canonical = fcc._parse_p0_failing_subgates(p0)
    json_side = _fail_names(FORM2_FOUR_FAILURES)
    assert set(canonical) == set(json_side), (
        f"canonical={canonical} json={json_side}")
