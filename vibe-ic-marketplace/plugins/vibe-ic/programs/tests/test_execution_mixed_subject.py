"""Canonical subject identity through actual M1/M3 consumers, without an issued controller."""
import json


import mixed_signal_top_lvs_run as m1








def test_m1_blocking_consumer_reports_row_identity_mismatch_before_other_material(tmp_path, monkeypatch):
    canonical = tmp_path / "canonical"
    staged = tmp_path / "staged"
    canonical.mkdir(); staged.mkdir()
    receipt = staged / "phase3/mixed_signal/m1_merge_receipt.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({"schema": "vibeic.mixed_signal.m1.v1", "subject": str(canonical.resolve())}))
    monkeypatch.setenv("VIBEIC_EXECUTION_BINDING", json.dumps({
        "step_id": "M3", "objective": {"project_subject": str(canonical.resolve())}}))
    got = m1.validate_current_receipt(staged, {})
    assert got == "M1 current receipt unavailable: MIXED_ISSUED_SUBJECT_MISMATCH"
    assert not (staged / "reports").exists()
