"""D69 keeps engineering RCX distinct from unmeasured fill response."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from flow109_admission import AdmissionRefusal
import flow109_final_extract as d69


def _d62(fill_count=None, **untrusted):
    measurements = {} if fill_count is None else {'fill_count_after': fill_count}
    return {'measurements': measurements, **untrusted}


@pytest.mark.parametrize('count,reason', [
    (None, 'D69_NATIVE_FILL_CENSUS_ABSENT'),
    (0, 'D69_FINAL_ODB_HAS_NO_NATIVE_DENSITY_FILL'),
    (147, 'D69_SELECTED_RCX_DBFILL_RESPONSE_NOT_PROVEN'),
])
def test_fill_scope_is_derived_from_native_census(count, reason):
    assert d69._fill_extraction_scope(_d62(count)) == {
        'status': 'NOT_MEASURED',
        'reason': reason,
        'native_fill_count': count,
        'basis': 'source-owned D62 census and selected OpenRCX data model',
    }


def test_forged_verified_string_cannot_upgrade_fill_scope():
    baseline = d69._fill_extraction_scope(_d62(147))
    forged = d69._fill_extraction_scope(_d62(147, extraction_fill_sensitivity='VERIFIED'))
    assert forged == baseline
    assert forged['status'] == 'NOT_MEASURED'


def test_consumer_refuses_forged_fill_sensitive_pass():
    scope = d69._fill_extraction_scope(_d62(147))
    record = {
        'reason': 'D69_ROUTED_ODB_RCX_MEASURED',
        'component_scope': 'engineering_routed_odb_parasitics',
        'fill_sensitive_parasitics': {**scope, 'status': 'PASS'},
    }
    with pytest.raises(AdmissionRefusal, match='D69_COMPONENT_SCOPE_CHANGED'):
        d69._component_scope(record, _d62(147))


def test_engineering_rcx_reaches_native_seam_with_fill_scope_unmeasured(tmp_path, monkeypatch):
    files = {}
    for name, text in {
        'd62.json': json.dumps({'outputs': {'filled.def': {'path': 'filled.def', 'sha256': 'x'}}}),
        'filled.odb': 'odb', 'filled.def': 'def', 'netlist.v': 'module neutral; endmodule',
        'constraint.sdc': '',
    }.items():
        path = tmp_path / name
        path.write_text(text)
        files[name] = path
    manifest = {
        'schema': d69.SCHEMA,
        'd62_receipt': {'path': str(files['d62.json']), 'sha256': 'd62'},
        'stream_bridge': {'path': 'bridge.json', 'sha256': 'bridge'},
        'librelane': {'image': 'selected', 'pdk_root': str(tmp_path), 'pdk': 'neutral'},
        'adopted_views': {
            'netlist': {'path': str(files['netlist.v']), 'sha256': 'netlist'},
            'sdc': {'path': str(files['constraint.sdc']), 'sha256': 'sdc'},
        },
    }
    target = tmp_path / d69.INPUT
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(manifest))
    odb_ref = {'path': str(files['filled.odb']), 'sha256': 'odb'}
    monkeypatch.setattr(d69, 'require_launch_admission', lambda *args, **kwargs: None)
    monkeypatch.setattr(d69.density, 'validate_filled_odb', lambda *args, **kwargs:
                        {'odb': odb_ref, 'measurements': {'fill_count_after': 147},
                         'extraction_fill_sensitivity': 'VERIFIED'})
    monkeypatch.setattr(d69.files, 'validate_bridge', lambda *args, **kwargs:
                        {'d62_receipt': manifest['d62_receipt'], 'odb': odb_ref})
    monkeypatch.setattr(d69, '_bound', lambda project, ref: Path(ref['path']))
    monkeypatch.setattr(d69, '_sha', lambda path: 'bound')
    launches = []

    def native(*args, **kwargs):
        launches.append((args, kwargs))
        raise RuntimeError('bounded native seam reached')

    monkeypatch.setattr(d69.signoff, 'run', native)

    result = d69.execute(tmp_path, {'context_sha256': 'developer-control'})

    assert len(launches) == 1
    assert result['native_started'] is True
    assert result['fill_sensitive_parasitics']['status'] == 'NOT_MEASURED'
    assert result['fill_sensitive_parasitics']['reason'] == \
        'D69_SELECTED_RCX_DBFILL_RESPONSE_NOT_PROVEN'
