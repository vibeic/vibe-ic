"""Default reruns the native STA call after its SDC/netlist input changes."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import librelane_contract as LC
import librelane_signoff as LS
import phase3_one_shot_runner as R


@pytest.mark.parametrize('changed', ['constraint.sdc', 'top_pnr.v'])
def test_default_record_runs_sta_again_with_current_native_inputs(tmp_path, monkeypatch, changed):
    pnr = tmp_path / 'phase3/stage3/pnr'
    pnr.mkdir(parents=True)
    for name in ('top.def', 'constraint.sdc', 'top_pnr.v'):
        (pnr / name).write_text('first input\n')
    spef = tmp_path / 'phase3/stage3/extracted/top.spef'
    spef.parent.mkdir(parents=True)
    spef.write_text('*SPEF "IEEE 1481-1998"\n')
    monkeypatch.setattr(R, '_LL_SIGNOFF_RUNS', {})
    monkeypatch.setattr(R, '_librelane_handed_spefs', lambda receipt: {'nom': spef})
    monkeypatch.setattr(LC, 'pdk_root_resolution', lambda *args: {'path': str(tmp_path)})
    monkeypatch.setattr(LC, 'resolve_image', lambda project: 'fixture-image')
    monkeypatch.setattr(LS, 'corner_timing', lambda folder: {'TT': {}})
    monkeypatch.setattr(LS, 'judge_timing', lambda corners: {'verdict': 'PASS'})
    calls = []
    def native(project, image, root, pdk, **kwargs):
        calls.append({name: (pnr / name).read_text() for name in ('constraint.sdc', 'top_pnr.v')})
        folder = tmp_path / 'native' / str(len(calls))
        folder.mkdir(parents=True)
        (folder / 'state_out.json').write_text(json.dumps(calls[-1]))
        return {'sta': folder}
    monkeypatch.setattr(LS, 'run', native)
    def produce():
        R._librelane_signoff_record(
            tmp_path, 'top', SimpleNamespace(name='test'), 'librelane', 'librelane',
            spef.parent / 'spef_corners', tmp_path / 'ocv.rpt', [], [], [], qualify=False)
    produce()
    assert len(calls) == 1
    (pnr / changed).write_text('current input\n')
    produce()
    assert len(calls) == 2, 'a current invocation must not borrow a cached STA run'
    assert calls[-1][changed] == 'current input\n'
    record = json.loads((tmp_path / 'reports/phase3/sta_postpnr_signoff.json').read_text())
    assert Path(record['sta_state']).parent.name == '2'
