"""Neutral Default dispatch/consumer controls; no native IC measurement."""
import hashlib
import json
from pathlib import Path

import pytest

import execution_policy as policy


def put(project, rel, data):
    path = project / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode())
    return path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def default_mode(monkeypatch):
    monkeypatch.setattr(policy, 'request', lambda: {'mode': 'default'})
    monkeypatch.setattr(policy, '_ordinary_runtime', None)










def test_actual_librelane_stream_selects_and_emits_the_same_seal_stage(tmp_path, monkeypatch):
    import librelane_step37 as stream
    import librelane_fill_dfm as fill
    import librelane_pv_signoff as pv

    route = put(tmp_path, 'route.def', b'current route')
    initial = put(tmp_path, 'initial.json', {'metrics': {}})
    configs = {sid: put(tmp_path, 'configs/' + sid + '.json', {}) for sid in stream.STEPS}
    monkeypatch.setattr(stream, 'resolve_step_configs', lambda *a, **k: configs)
    monkeypatch.setattr(stream, 'declaration_config', lambda *a:
                        ({'CORE_AREA': [1, 1, 9, 9]}, {'CORE_AREA': 'neutral owner declaration'}))
    monkeypatch.setattr(stream, '_routed_state', lambda *a: initial)
    monkeypatch.setattr(pv, 'tech_lef_overlay', lambda *a: {})

    def native(project, image, root, pdk, steps, state, lane, resolved):
        folders = []
        incoming = json.loads(Path(state).read_text())
        for i, sid in enumerate(steps):
            folder = project / 'phase3/librelane' / lane / str(i)
            payload = dict(incoming)
            payload['metrics'] = dict(payload.get('metrics', {}))
            if sid in ('Magic.StreamOut', 'KLayout.StreamOut'):
                gds = put(project, str(folder.relative_to(project) / 'stream.gds'), sid.encode())
                payload['gds'] = str(gds)
                if sid == 'Magic.StreamOut':
                    payload['mag_gds'] = str(gds)
                else:
                    payload['klayout_gds'] = str(gds)
            elif sid in ('KLayout.SealRing', 'KLayout.Filler'):
                body = Path(payload['gds']).read_bytes() + (' ' + sid).encode()
                gds = put(project, str(folder.relative_to(project) / 'finished.gds'), body)
                payload['gds'] = str(gds)
            put(project, str(folder.relative_to(project) / 'state_out.json'), payload)
            incoming = payload
            folders.append(folder)
        return folders

    monkeypatch.setattr(stream, '_run', native)
    monkeypatch.setattr(stream, 'judge_step', lambda folder, keys, *a, **k:
                        {'verdict': 'PASS', 'metrics': {key: {'value': 0} for key in keys}})
    monkeypatch.setattr(fill, 'measure_density_ratios', lambda *a: {})
    monkeypatch.setattr(pv, 'run_finishing_xor', lambda *a, **k: {'verdict': 'PASS'})
    monkeypatch.setattr(stream, '_vibeic_gds_gates', lambda *a:
                        {'substance': {'rc': 0, 'sha256': 'neutral'},
                         'port_labels': {'rc': 0, 'sha256': 'neutral'}})
    monkeypatch.setattr(stream, '_measured_drc', lambda *a, **k:
                        {'magic': 0, 'klayout': 0, 'total': 0})
    target = tmp_path / 'final.gds'
    result = stream.run(tmp_path, 'neutral image', tmp_path, 'neutral',
                        route, route, route, target)
    promotion = json.loads(result['promotion'].read_text())
    handoff = result['sealring']
    assert promotion['sealring'] == handoff
    assert promotion['streams'][result['engine']] == handoff['gds_in']
    assert json.loads(Path(handoff['state']).read_text())['gds'] == handoff['sealed_gds']
    assert digest(Path(handoff['state'])) == handoff['state_sha256']
    assert digest(Path(handoff['sealed_gds'])) == handoff['sealed_sha256']
    assert b'KLayout.SealRing' in Path(handoff['sealed_gds']).read_bytes()
    assert b'KLayout.Filler' not in Path(handoff['sealed_gds']).read_bytes()
    assert b'KLayout.Filler' in target.read_bytes()
