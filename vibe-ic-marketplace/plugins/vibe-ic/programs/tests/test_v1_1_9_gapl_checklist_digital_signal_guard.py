"""Step-2.7 §4.05 guard for the gapL verification_checklist exemption (PR #2).

PR #2 scopes `kind=verification_checklist` (DV-milestone) rows OUT of the
TB-evidence demand — a DV process milestone is not TB-traceable. But the original
exemption fired for ANY case whose kind matched a checklist token, so a genuine
DIGITAL case carrying a real opcode/cmd field (i.e. `_has_digital_signal` True)
mislabeled `kind=verification_checklist` with status=done and NO testbench
evidence was credited as a PASS — masking a missing digital TB (Step-2.7 HIGH
leak; the file's own #773 r2 doctrine forbids exactly this).

FIX: the checklist exemption fires ONLY for a row that carries NO digital signal
(mirrors the established `_has_digital_signal` guard the file already uses for the
#773 verification_intent case). A digital case falls through to the unchanged
TB-evidence logic and still FAILs without evidence. This file PINS both halves.

chip-AGNOSTIC: a kind/status/digital-class vocabulary, no chip/vendor/SKU literal.
"""
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import l10_tb_conformance_check as L  # noqa: E402


@pytest.mark.parametrize("digital_field", ["opcode", "cmd", "cmd_hex", "cmd_byte"])
def test_digital_case_mislabeled_checklist_still_fails_without_tb(digital_field):
    # §4.05 NO-LEAK: a real digital case carrying an opcode/cmd field, even when
    # mislabeled kind=verification_checklist with status=done, must STILL FAIL
    # without TB evidence (it is NOT a process milestone).
    case = [{"id": "cmd_write_reg", "kind": "verification_checklist",
             "category": "cmd_response", digital_field: "0x3A", "status": "done"}]
    res, ok, fail = L.evaluate(case, tb_blob="", summary="")
    assert res[0]["status"] == "fail"
    assert (ok, fail) == (0, 1)


def test_digital_category_token_mislabeled_checklist_still_fails():
    # a digital CATEGORY token (register_access) under a checklist kind must
    # still demand TB evidence.
    case = [{"id": "reg_rw", "kind": "verification_checklist",
             "category": "register_access", "status": "done"}]
    res, ok, fail = L.evaluate(case, tb_blob="", summary="")
    assert res[0]["status"] == "fail"
    assert (ok, fail) == (0, 1)


def test_pure_dv_milestone_satisfied_still_credited():
    # FP-fix PRESERVED: a genuine process milestone (no digital signal),
    # status=done, is credited (not counted as a TB-evidence miss).
    case = [{"id": "code_review", "kind": "verification_checklist",
             "category": "verification_checklist", "status": "done"}]
    res, ok, fail = L.evaluate(case, tb_blob="", summary="")
    assert res[0]["status"] == "pass"
    assert (ok, fail) == (1, 0)


def test_pure_dv_milestone_blank_is_checklist_gap_not_fail():
    # FP-fix PRESERVED: a blank-status milestone surfaces as a checklist gap,
    # NOT folded into fail_count (cannot mask a missing digital TB, but also not
    # a hard TB-evidence failure).
    case = [{"id": "smoke", "kind": "verification_checklist",
             "category": "verification_checklist"}]
    res, ok, fail = L.evaluate(case, tb_blob="", summary="")
    assert res[0]["status"] == "checklist_gap"
    assert (ok, fail) == (0, 0)


def test_digital_checklist_with_tb_evidence_still_passes():
    # no over-correction: a digital case that DOES have TB evidence passes.
    case = [{"id": "cmd_write_reg", "kind": "verification_checklist",
             "category": "cmd_response", "opcode": "0x3A", "status": "done"}]
    res, ok, fail = L.evaluate(case, tb_blob="opcode 0x3A driven; cmd_write_reg",
                               summary="")
    assert res[0]["status"] == "pass"
    assert (ok, fail) == (1, 0)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
