"""A DV process checklist is not a test-case population.

MEASURED, opentitan_aes at v1.15.80: `cpu_functional_oracle_waiver_check`
reported "103 declared L10 row(s), 0 functional tests ran" and blocked Step 4.
Every one of the 103 carried `kind: "verification_checklist"`, harvested by
Phase 1 from the vendor's DV checklist — `spec_complete`, `csr_defined`,
`clkrst_connected` — with stimulus "DV checklist item SPEC_COMPLETE — Done"
and expected "DV checklist item satisfied (Done)".

Nothing can drive those. The unit-TB producer was RIGHT to put 0 of 103 in its
scaffold scope (`0 in scope, 103 out of scope`): the defect was never that the
tests do not run, it is that project milestones were counted as tests, so the
gate demanded execution of 103 things that cannot be executed.

This NARROWS a blocking denominator, so the controls below hide a genuine
functional row inside a checklist-dominated L10 and prove it is still counted
and still demanded — the new blind spot must not swallow a real test.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import cpu_functional_oracle_waiver_check as C  # noqa: E402

_KEYS = ("test_cases", "cases", "vectors")

CHECKLIST_ROW = {
    "name": "spec_complete", "kind": "verification_checklist",
    "stimulus": "DV checklist item SPEC_COMPLETE — Done",
    "expected": "DV checklist item satisfied (Done)",
}
REAL_ROW = {
    "name": "ecb_encrypt_128", "kind": "functional_vector",
    "stimulus": "key=..., pt=...", "expected": "ct=...",
}


def _l10(tmp_path: Path, rows) -> Path:
    p = tmp_path / "L10_TEST_CASES.json"
    p.write_text(json.dumps({"test_cases": rows}))
    return p


def test_a_checklist_of_milestones_is_not_an_executable_denominator(tmp_path):
    """THE FALSIFIER. Red while a process checklist counts as 103 tests."""
    p = _l10(tmp_path, [dict(CHECKLIST_ROW, name=f"item_{i}")
                        for i in range(103)])
    assert C._list_denominator(p, _KEYS) == 0, (
        "103 DV-checklist milestones were counted as executable tests")


def test_the_excluded_rows_are_reported_not_discarded(tmp_path):
    """Narrowing must be visible: a reader sees what was not demanded."""
    p = _l10(tmp_path, [dict(CHECKLIST_ROW, name=f"item_{i}")
                        for i in range(103)])
    assert C._process_only_count(p, _KEYS) == 103


def test_a_real_functional_row_hidden_among_milestones_is_still_demanded(tmp_path):
    """THE BLIND-SPOT CONTROL — the one that makes the narrowing safe.

    A design that declares one genuine vector alongside a hundred checklist
    items must still owe that vector. If this passes vacuously the narrowing
    has become a silencer.
    """
    rows = [dict(CHECKLIST_ROW, name=f"item_{i}") for i in range(103)]
    rows.insert(50, REAL_ROW)
    p = _l10(tmp_path, rows)
    assert C._list_denominator(p, _KEYS) == 1, (
        "the real functional vector was swallowed by the exclusion")
    assert C._process_only_count(p, _KEYS) == 103


def test_an_all_functional_l10_is_untouched(tmp_path):
    """DIRECTIONAL CONTROL — passes in BOTH arms, and must."""
    p = _l10(tmp_path, [dict(REAL_ROW, name=f"v{i}") for i in range(7)])
    assert C._list_denominator(p, _KEYS) == 7
    assert C._process_only_count(p, _KEYS) == 0


def test_a_row_with_no_declared_kind_stays_executable(tmp_path):
    """Fail-closed on silence: an undeclared kind is DEMANDED, not excused.

    Only an explicit process-milestone kind leaves the denominator, so a
    design cannot escape the gate by omitting `kind`.
    """
    p = _l10(tmp_path, [{"name": "mystery", "stimulus": "x", "expected": "y"}])
    assert C._list_denominator(p, _KEYS) == 1


def test_bad_input_still_invents_no_denominator(tmp_path):
    """Control: unreadable or absent L10 yields 0, not a guess. Both arms."""
    missing = tmp_path / "nope.json"
    assert C._list_denominator(missing, _KEYS) == 0
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert C._list_denominator(bad, _KEYS) == 0
