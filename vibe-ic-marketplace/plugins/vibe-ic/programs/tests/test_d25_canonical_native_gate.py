"""Canonical gate binds the adopted native consumer, without legacy rewriting."""
import sys



_ACTIVE = False


















def test_native_gate_source_change_reopens_only_once(tmp_path, monkeypatch):
    # Existing actual admission control: changed consumed gate bytes reopen;
    # unchanged/restored duplicates and missing/foreign source still refuse.
    from test_canonical_run_admission import test_native_handoff_resolver_source_reopens_only_once
    test_native_handoff_resolver_source_reopens_only_once(
        tmp_path, monkeypatch, 'lec_equivalence_check.py',
        'res = AuditResult()', 'res = AuditResult(passed=True)')
