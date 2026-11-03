"""Native finishing XOR owns D64 for both IC and hard-IP streams."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import librelane_contract as contract
import librelane_fill_dfm as fill
import flow109_final_geometry as geometry
import librelane_pv_signoff as pv
import phase3_one_shot_runner as runner


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, dict) else value)
    return path


@pytest.mark.parametrize('status', ['PASS', 'FAIL'])
def test_d64_runs_native_finishing_on_ic_streams(tmp_path, monkeypatch, status):
    streams = {key: put(tmp_path / 'phase3' / (key + '.gds'), key)
               for key in ('stream', 'sealed', 'canonical')}
    monkeypatch.setattr(fill, 'validate_default_stream', lambda project: {
        **{key: str(value) for key, value in streams.items()}, 'finishing_status': 'PASS', 'pdk': 'stream_kit'})
    core = [2, 2, 18, 18]
    monkeypatch.setattr(contract, '_runner_floorplan', lambda project:
                        ([0, 0, 20, 20], core, {'CORE_AREA': 'native floorplan'}, '', {}))
    monkeypatch.setattr(runner, '_detect_pdk', lambda project: SimpleNamespace(name='host_available_kit'))
    monkeypatch.setattr(runner, '_librelane_step_ctx', lambda *args: ('wrong_image', tmp_path))
    monkeypatch.setattr(contract, 'resolve_image', lambda project, **kwargs: 'stream_image')
    resolved = []
    def root(project, pdk, *, image):
        resolved.append((pdk, image))
        return str(tmp_path)
    monkeypatch.setattr(contract, 'resolve_pdk_root', root)
    observed = []
    def native(project, image, root, pdk, **kwargs):
        observed.append((image, root, pdk, kwargs))
        return {'verdict': status, 'metrics': {'native-defects': 0 if status == 'PASS' else 1}}
    monkeypatch.setattr(pv, 'run_finishing_xor', native)
    result = geometry.execute(tmp_path, {'requested_step': 'D64'})
    assert resolved == [('stream_kit', 'stream_image')]
    assert observed == [('stream_image', tmp_path, 'stream_kit',
                         {'pre': streams['stream'], 'sealed': streams['sealed'],
                          'final': streams['canonical'], 'core': core,
                          'core_source': 'native floorplan'})]
    assert result['default_row_status'] == status
    assert geometry.consume_default_row_completion(tmp_path, {}, result)['completed'] == (status == 'PASS')


@pytest.mark.parametrize('count,status', [(0, 'PASS'), (1, 'FAIL')])
def test_retained_native_finishing_preserves_its_verdict(tmp_path, monkeypatch, count, status):
    streams = {key: put(tmp_path / 'phase3' / (key + '.gds'), key)
               for key in ('stream', 'sealed', 'canonical')}
    monkeypatch.setattr(fill, 'validate_default_stream', lambda project: {
        **{key: str(value) for key, value in streams.items()}, 'finishing_status': 'PASS', 'pdk': 'stream_kit'})
    core = [2, 2, 18, 18]
    monkeypatch.setattr(contract, '_runner_floorplan', lambda project:
                        ([0, 0, 20, 20], core, {'CORE_AREA': 'native floorplan'}, '', {}))
    folder = tmp_path / 'phase3/librelane/37.3-finishing/01-vibeic-finishingxor'
    put(folder / 'state_in.json', {'gds': str(streams['canonical'])})
    metrics = {key: count if key.endswith('__defect__count') else 0
               for key in pv.PRODUCED['Vibeic.FinishingXOR']}
    put(folder / 'state_out.json', {'gds': str(streams['canonical']), 'metrics': metrics})
    put(folder / 'input_fingerprint.json', {'state_files': {
        str(streams['canonical']): contract.digest(streams['canonical'])}})
    put(folder / 'config.json', {'meta': {'step': 'Vibeic.FinishingXOR'},
                                'VIBEIC_FINISHING_CORE_AREA': core})
    report = tmp_path / 'reports/phase3/librelane_finishing_xor.json'
    put(report, {'scope': {'pre_sha256': contract.digest(streams['stream']),
                          'sealed_sha256': contract.digest(streams['sealed']),
                          'final_sha256': contract.digest(streams['canonical'])},
                 'metrics': {key: {'folder': str(folder)} for key in metrics}})
    result = geometry.execute(tmp_path, {'requested_step': 'D64'})
    assert result['default_row_status'] == status
    assert result['native_started'] is False
    assert result['metrics']['vibeic__finishing_xor__defect__count']['value'] == count
