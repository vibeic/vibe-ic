"""Power-boundary projection must never discard a functional observation."""
import pytest
import flow109_final_lec_physical as physical
from flow109_final_lec_physical import unused_supply_projection


@pytest.mark.parametrize('bits,expected', [([9], 1), (['1'], 1), (['0'], 0)])
def test_inert_or_exact_powered_native_supply_projects(bits, expected):
    model = {'ports': {'rail': {'direction': 'inout', 'bits': bits}}, 'cells': {}}
    assert unused_supply_projection(model, ['rail'], {'rail': expected}) == ['rail']


@pytest.mark.parametrize('bits,expected', [(['0'], 1), (['1'], 0), (['x'], 1), (['z'], 0)])
def test_reversed_or_unresolved_native_power_model_refuses(bits, expected):
    model = {'ports': {'rail': {'direction': 'inout', 'bits': bits}}, 'cells': {}}
    with pytest.raises(ValueError, match='functionally connected'):
        unused_supply_projection(model, ['rail'], {'rail': expected})


def test_functional_connection_or_alias_refuses_even_for_declared_rail():
    model = {'ports': {'rail': {'direction': 'inout', 'bits': [8]}},
             'cells': {'logic': {'connections': {'A': [8], 'Y': [9]}}}}
    with pytest.raises(ValueError, match='functionally connected'):
        unused_supply_projection(model, ['rail'], {'rail': 1})
    model['cells'] = {}
    model['ports']['observed'] = {'direction': 'output', 'bits': [8]}
    with pytest.raises(ValueError, match='functionally connected'):
        unused_supply_projection(model, ['rail'], {'rail': 1})


def test_undeclared_or_functional_port_is_never_projected():
    model = {'ports': {'debug': {'direction': 'input', 'bits': [8]}}, 'cells': {}}
    with pytest.raises(ValueError, match='non-supply'):
        unused_supply_projection(model, ['debug'], {})
    with pytest.raises(ValueError, match='non-supply'):
        unused_supply_projection(model, ['debug'], {'debug': 1})


def _fill_case(tmp_path, monkeypatch):
    import json
    import librelane_fill_dfm as fill
    owner = tmp_path / 'native-owner'
    stage = owner / 'phase3/librelane/34/01-openroad-fillinsertion'
    stage.mkdir(parents=True)
    paths = {name: stage / value for name, value in {
        'adopted_netlist': 'chip.nl.v', 'final_def': 'chip.def',
        'adopted_state': 'state_out.json'}.items()}
    for name in ['adopted_netlist', 'final_def']: paths[name].write_text(name)
    paths['adopted_state'].write_text(json.dumps({'nl': str(paths['adopted_netlist']),
                                               'def': str(paths['final_def'])}))
    initial, config, receipt = [stage / name for name in ('state_in.json', 'config.json', 'vibeic_receipt.json')]
    for path in (initial, config, receipt): path.write_text('{}')
    tool = {'step': fill.ODB_FILL_STEP, 'state': str(paths['adopted_state']),
        'state_sha256': physical.sha(paths['adopted_state']),
        'filled_def_sha256': physical.sha(paths['final_def']), 'subject': str(stage / 'input.def'),
        'binding': {'input_state': str(initial), 'config': str(config),
                    'receipt_sha256': physical.sha(receipt)}}
    report = owner / fill.RECORD_REL; report.parent.mkdir(parents=True)
    report.write_text(json.dumps({'odb': {'tool': tool}})); paths['adopted_receipt'] = report
    calls = []
    def validate(project, record, *, routed_def):
        calls.append((project, record, routed_def))
        return {'input': {'state_files': {}, 'config_files': {},
                          'state': physical.sha(initial), 'config': physical.sha(config)}}
    monkeypatch.setattr(fill, 'validate_fill_handoff', validate)
    return paths, calls


def test_native_fill_selection_reopens_existing_owner_and_binds_dependencies(tmp_path, monkeypatch):
    paths, calls = _fill_case(tmp_path, monkeypatch)
    inputs = physical.native_fill_inputs(paths)
    assert len(calls) == 1
    assert inputs[str(paths['adopted_state'])] == physical.sha(paths['adopted_state'])
    assert str(paths['adopted_state'].parent / 'vibeic_receipt.json') in inputs


@pytest.mark.parametrize('role', ['adopted_netlist', 'final_def', 'adopted_state'])
def test_native_fill_selection_rejects_foreign_current_view(tmp_path, monkeypatch, role):
    paths, calls = _fill_case(tmp_path, monkeypatch)
    other = tmp_path / 'different'; other.write_text('different')
    paths[role] = other
    with pytest.raises(ValueError): physical.native_fill_inputs(paths)


def test_native_fill_selection_propagates_owning_consumer_refusal(tmp_path, monkeypatch):
    import librelane_fill_dfm as fill
    from librelane_contract import Refusal
    paths, calls = _fill_case(tmp_path, monkeypatch)
    def refuse(*args, **kwargs): raise Refusal('LL_STEP_OUTPUT_UNBOUND', 'changed receipt')
    monkeypatch.setattr(fill, 'validate_fill_handoff', refuse)
    with pytest.raises(Refusal, match='LL_STEP_OUTPUT_UNBOUND'): physical.native_fill_inputs(paths)
