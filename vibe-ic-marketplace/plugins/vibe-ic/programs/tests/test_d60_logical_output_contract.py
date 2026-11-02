"""D60 owns the invocation's file top, independently of physical cell names."""
from pathlib import Path

import pytest

import execution_backend_gates as gates
import execution_backend_producers as producers
import execution_backend_worker as worker
import execution_policy
import flow_compliance_check as fcc
import step_required_inputs_check as required
import step_write_ledger as ledger
from test_native_backend_current_receipts import _retained_default_stream

SPEC = 'phase3/stage4/gds/*.gds'
OWNED = 'phase3/stage4/gds/logical.gds'
FOREIGN = 'phase3/stage4/gds/physical_cell.gds'


def _runtime(monkeypatch, project, top='logical'):
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', {
        'project': project, 'policy': {'mode': 'default'},
        'parameters': {'top': top}})


@pytest.fixture
def layout(tmp_path, monkeypatch):
    import klayout.db as db
    for relative, width in ((OWNED, 10), (FOREIGN, 20)):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        geometry = db.Layout()
        cell = geometry.create_cell('physical_cell')
        cell.shapes(geometry.layer(1, 0)).insert(db.Box(0, 0, width, 10))
        geometry.write(str(path))
    _runtime(monkeypatch, tmp_path)
    return tmp_path


@pytest.mark.parametrize('consumer', ['snapshot', 'receipt_contract', 'worker',
                                    'fcc', 'ledger', 'input_files', 'input_check'])
def test_every_consumer_selects_only_logical_file_top(layout, consumer):
    before = producers._native_output_identity(layout / FOREIGN)
    if consumer == 'snapshot':
        paths = producers._native_current_step_output_snapshot(layout, '37')
    elif consumer == 'receipt_contract':
        paths = gates.contracts(layout, {'id': 37, 'required_outputs': [SPEC]})[SPEC]
    elif consumer == 'worker':
        paths, missing = worker.resolve_contract(layout, [SPEC])
        assert missing == []
    elif consumer == 'fcc':
        binding = {'available': True, 'rows': {'37': {
            SPEC: {'produced': [FOREIGN, OWNED], 'rejected': []}}}}
        satisfied, paths, *_ = fcc._resolve_required_output(layout, 37, SPEC, binding)
        assert satisfied
    elif consumer == 'ledger':
        paths = ledger._spec_candidates(layout, SPEC)
    elif consumer == 'input_files':
        paths = worker._declared_input_files(layout, [{'from': 37, 'path': SPEC}])
    else:
        row = {'id': 'consumer', 'required_inputs': [{'from': 37, 'path': SPEC}]}
        result = required.check_one(layout, row, {'37': {'required_outputs': [SPEC]}}, {}, None)
        assert result['verdict'] == 'READY'
        paths = [result['inputs'][0]['evidence']]
    assert set(paths) == {OWNED}
    assert producers._native_output_identity(layout / FOREIGN) == before


@pytest.mark.parametrize('token', [SPEC, '--output=' + SPEC])
def test_gate_argv_selects_one_owned_path_including_leaf_glob(layout, token):
    assert fcc._expand_globs([token], layout) == [token.replace(SPEC, OWNED)]


def test_foreign_sibling_cannot_satisfy_missing_logical_output(layout):
    (layout / OWNED).unlink()
    paths, missing = worker.resolve_contract(layout, [SPEC])
    assert paths == {}
    assert missing == [SPEC]
    assert worker.resolve_input_contract(layout, [{'from': 37, 'path': SPEC}]) == [SPEC]
    assert not fcc._resolve_required_output(layout, 37, SPEC, {
        'available': True, 'rows': {'37': {SPEC: {'produced': [FOREIGN]}}}})[0]


@pytest.mark.parametrize('top', [None, '', '../physical_cell', 'a/b', '*', 'wrong'])
def test_unbound_unsafe_or_wrong_top_cannot_credit_sibling(layout, monkeypatch, top):
    _runtime(monkeypatch, layout, top)
    try:
        paths, missing = worker.resolve_contract(layout, [SPEC])
    except (ValueError, worker.em.Refusal) as exc:
        assert 'OUTPUT_TOP' in str(exc)
    else:
        assert paths == {}
        assert missing == [SPEC]


def test_retained_owner_does_not_adopt_foreign_physical_cell(tmp_path, monkeypatch):
    import klayout.db as db
    project, params, first, calls = _retained_default_stream(tmp_path, monkeypatch)
    _runtime(monkeypatch, project, params['top'])
    canonical = Path(first['canonical'])
    sibling = canonical.with_name('physical_cell.gds')
    geometry = db.Layout()
    geometry.read(str(canonical))
    geometry.top_cell().shapes(geometry.layer(99, 0)).insert(db.Box(1, 2, 30, 40))
    geometry.write(str(sibling))
    before = producers._native_output_identity(sibling)
    result = producers.produce(project, params)
    current = result['current_step_declared_producers']
    assert result['verdict'] == 'PASS', current
    assert str(sibling.relative_to(project)) not in current['outputs']
    assert str(canonical.relative_to(project)) in current['retained_outputs']['outputs']
    assert calls == ['primary', 'seal', 'filler-density']
    assert producers._native_output_identity(sibling) == before
