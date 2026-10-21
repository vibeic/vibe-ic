"""Step 5 must not count DV process milestones as executable functions."""
from __future__ import annotations

import full_stack_functional_tb as F


def checklist(name="spec_complete", **changes):
    row = {
        "name": name,
        "kind": "verification_checklist",
        "status": "Done",
        "stimulus": "DV checklist item SPEC_COMPLETE — Done",
        "expected": "DV checklist item satisfied (Done)",
    }
    row.update(changes)
    return row


def test_process_milestone_is_reported_outside_functional_denominator():
    disposition = F.process_milestone_disposition(checklist())
    assert disposition == {
        "case": "spec_complete",
        "disposition": F.DISP_PROCESS_MILESTONE,
        "blocking": False,
        "ruling": "ORGANIC #808 / v1.15.80",
        "source_status": "done",
        "note": ("declared verification-checklist process milestone; excluded "
                 "from the executable functional denominator, not claimed "
                 "executed or functionally verified; status remains owned by "
                 "l10_tb_conformance_check"),
    }


def test_real_functional_row_among_103_milestones_remains_executable():
    rows = [checklist(f"item_{i}") for i in range(103)]
    rows.insert(50, {"name": "real_vector", "kind": "functional_vector",
                     "stimulus": "drive x=1", "expected": "observe y=1"})
    dispositions = [F.process_milestone_disposition(row) for row in rows]
    assert sum(d is not None for d in dispositions) == 103
    assert dispositions[50] is None


def test_missing_or_unknown_kind_stays_fail_closed():
    assert F.process_milestone_disposition(
        {"name": "unknown", "stimulus": "x", "expected": "y"}) is None
    assert F.process_milestone_disposition(
        {"name": "unknown", "kind": "new_kind",
         "stimulus": "x", "expected": "y"}) is None


def test_digital_signal_mislabel_cannot_gain_process_exemption():
    assert F.process_milestone_disposition(
        checklist("opcode_case", opcode="0x42")) is None
    assert F.process_milestone_disposition(
        checklist("command_case", category="command")) is None


def test_blank_or_failed_status_is_visible_but_not_claimed_verified_here():
    for status in (None, "Fail"):
        disposition = F.process_milestone_disposition(
            checklist("milestone_gap", status=status))
        assert disposition["source_status"] == (status.lower() if status else None)
        assert disposition["blocking"] is False
        assert "not claimed" in disposition["note"]
