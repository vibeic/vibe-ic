"""Focused source controls for the canonical mixed Registry seam."""
from __future__ import annotations

import json

import pytest























def test_issued_project_subject_survives_staging_and_current_m3_reread(tmp_path, monkeypatch):
    """The producer uses issued canonical identity; no receipt rewrite is needed."""
    import shutil
    import mixed_signal_m3_run as m3

    staged = tmp_path / "arm-inputs/project"
    canonical = tmp_path / "canonical-project"
    staged.mkdir(parents=True)
    canonical.mkdir()
    binding = {"step_id": "M3", "objective": {"project_subject": str(canonical.resolve())}}
    monkeypatch.setenv("VIBEIC_EXECUTION_BINDING", json.dumps(binding))
    m3.produce(staged, "chip_top")  # source-only fallback; no native execution
    for rel in (*m3.OUTPUTS.values(), m3.RECEIPT):
        target = canonical / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(staged / rel, target)
    with pytest.raises(m3.Refusal) as exc:
        m3.verify(canonical, "cosim")
    assert exc.value.rule == "EMPTY_SCENARIOS"
