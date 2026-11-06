"""Neutral instrument writes; real Default producer, adoption and consumers."""

import pytest

import em_current_density_check as emc





































@pytest.mark.parametrize("changed", ["em_current_density_check.py",
                                    "em_peak_current_authority_check.py"])
def test_step25_keeps_its_complete_native_source_binding(tmp_path, monkeypatch, changed):
    from test_default_power_density import build
    project, _, _ = build(tmp_path, monkeypatch, direct=True)
    assert emc.validate_native_density(project)["valid"] is True
    current = emc.native_source_identity()
    current[changed] = "0" * 64
    monkeypatch.setattr(emc, "native_source_identity", lambda: dict(current))
    result = emc.validate_native_density(project)
    assert result["valid"] is False, result
    assert result["verdict"] == "NOT_MEASURED", result
    assert result["reason"] == "native producer/consumer source changed"
