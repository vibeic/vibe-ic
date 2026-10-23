"""D69 must not relabel an ODB path match as fill-sensitive extraction."""
from __future__ import annotations

import json
import pytest

from flow109_admission import AdmissionRefusal
import flow109_final_extract as d69


def _d62(fill_count, sensitivity='NOT_VERIFIED'):
    return {
        'measurements': {'fill_count_after': fill_count},
        'extraction_fill_sensitivity': sensitivity,
    }


def test_zero_native_fill_census_refuses_before_rcx():
    with pytest.raises(AdmissionRefusal, match='D69_FINAL_ODB_HAS_NO_NATIVE_DENSITY_FILL'):
        d69._require_fill_sensitive_extraction(_d62(0))


def test_native_dbfill_without_supported_rcx_view_refuses_before_rcx():
    with pytest.raises(AdmissionRefusal, match='D69_FILL_SENSITIVE_RCX_NOT_VERIFIED'):
        d69._require_fill_sensitive_extraction(_d62(147))


def test_only_explicit_fill_sensitive_extraction_view_can_continue():
    assert d69._require_fill_sensitive_extraction(_d62(147, 'VERIFIED')) is None


def test_missing_native_fill_census_is_not_assumed_zero_or_present():
    with pytest.raises(AdmissionRefusal, match='D69_NATIVE_FILL_CENSUS_ABSENT'):
        d69._require_fill_sensitive_extraction({'extraction_fill_sensitivity': 'VERIFIED'})


@pytest.mark.parametrize('fill_count,reason', [
    (0, 'D69_FINAL_ODB_HAS_NO_NATIVE_DENSITY_FILL'),
    (147, 'D69_FILL_SENSITIVE_RCX_NOT_VERIFIED'),
])
def test_execute_refuses_before_native_rcx(tmp_path, monkeypatch, fill_count, reason):
    manifest = {
        'schema': d69.SCHEMA,
        'd62_receipt': {'path': 'd62.json', 'sha256': 'd62'},
        'stream_bridge': {'path': 'bridge.json', 'sha256': 'bridge'},
    }
    target = tmp_path / d69.INPUT
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(manifest))
    monkeypatch.setattr(d69, 'require_launch_admission', lambda *args, **kwargs: None)
    monkeypatch.setattr(d69.density, 'validate_filled_odb', lambda *args, **kwargs: {
        'odb': {'path': 'filled.odb', 'sha256': 'odb'},
        'measurements': {'fill_count_after': fill_count},
        'extraction_fill_sensitivity': 'NOT_VERIFIED',
    })
    monkeypatch.setattr(d69.files, 'validate_bridge', lambda *args, **kwargs: {
        'd62_receipt': manifest['d62_receipt'],
        'odb': {'path': 'filled.odb', 'sha256': 'odb'},
    })
    launches = []
    monkeypatch.setattr(d69.signoff, 'run', lambda *args, **kwargs: launches.append(True))

    result = d69.execute(tmp_path, {'context_sha256': 'developer-control'})

    assert result['component_status'] == 'NOT_MEASURED'
    assert result['reason'] == reason
    assert result['native_started'] is False
    assert launches == []


def test_source_only_reverse_removing_guard_loses_the_fill_refusal(tmp_path, monkeypatch):
    manifest = {
        'schema': d69.SCHEMA,
        'd62_receipt': {'path': 'd62.json', 'sha256': 'd62'},
        'stream_bridge': {'path': 'bridge.json', 'sha256': 'bridge'},
    }
    target = tmp_path / d69.INPUT
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(manifest))
    monkeypatch.setattr(d69, 'require_launch_admission', lambda *args, **kwargs: None)
    monkeypatch.setattr(d69.density, 'validate_filled_odb', lambda *args, **kwargs: {
        'odb': {'path': 'filled.odb', 'sha256': 'odb'},
        'measurements': {'fill_count_after': 0},
        'extraction_fill_sensitivity': 'NOT_VERIFIED',
    })
    monkeypatch.setattr(d69.files, 'validate_bridge', lambda *args, **kwargs: {
        'd62_receipt': manifest['d62_receipt'],
        'odb': {'path': 'filled.odb', 'sha256': 'odb'},
    })
    monkeypatch.setattr(d69, '_require_fill_sensitive_extraction', lambda value: None)

    result = d69.execute(tmp_path, {'context_sha256': 'source-only-reverse'})

    assert result['reason'] == 'D69_NATIVE_CONFIGURATION_ABSENT'
    assert result['reason'] != 'D69_FINAL_ODB_HAS_NO_NATIVE_DENSITY_FILL'
