"""Registered distribution spelling at the existing Phase-2 consumer boundary."""
import json
import os
from pathlib import Path

import pytest
import librelane_contract as contract
import pdk_family_identity as identity
import phase3_one_shot_runner as phase3
import synth_handoff_netlist_check as handoff


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


@pytest.mark.parametrize('declared,record,selected,expected', [
    ('gf180mcud', 'gf180mcuD', None, 'gf180mcuD'),
    ('GF180MCUD', 'gf180mcuD', 'gf180mcud', 'gf180mcuD'),
    ('sky130a', 'sky130A', None, 'sky130A'),
    ('ihpsg13g2', 'ihp-sg13g2', None, 'ihp-sg13g2'),
], ids=['measured-gf180-case', 'selected-registered-alias', 'registered-sky-case',
        'existing-normalised-spelling'])
def test_registered_spelling_reaches_exact_distribution(tmp_path, declared, record,
                                                       selected, expected):
    put(tmp_path / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json',
        {'fields': {'pdk_target': declared}})
    put(tmp_path / 'input/project.json', {'pdk': record})
    resolved, source = contract.phase2_pdk(tmp_path, selected=selected)
    assert resolved == expected
    assert 'L19_CONSTRAINTS_PDK.json:fields.pdk_target' in source
    phase3._assert_pdk_name_resolvable(resolved)


@pytest.mark.parametrize('other', ['gf180mcuC', 'sky130A'])
def test_distinct_revision_or_family_remains_conflicting(tmp_path, other):
    put(tmp_path / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json',
        {'fields': {'pdk_target': 'gf180mcuD'}})
    put(tmp_path / 'input/project.json', {'pdk': other})
    with pytest.raises(contract.Refusal, match='LL_PHASE2_PDK_CONFLICT'):
        contract.phase2_pdk(tmp_path, selected='gf180mcuD')


def test_conflicting_switch_stays_refused(tmp_path):
    put(tmp_path / 'input/project.json', {'pdk': 'gf180mcuD'})
    put(tmp_path / 'phase3/librelane_switch.json', {'pdk': 'sky130A'})
    with pytest.raises(contract.Refusal, match='switch.pdk disagrees'):
        contract.phase2_pdk(tmp_path)


def test_registered_switch_alias_keeps_same_distribution(tmp_path):
    put(tmp_path / 'input/project.json', {'pdk': 'gf180mcuD'})
    put(tmp_path / 'phase3/librelane_switch.json', {'pdk': 'GF180MCUD'})
    assert contract.phase2_pdk(tmp_path)[0] == 'gf180mcuD'


@pytest.mark.parametrize('names,alias', [(['kit-a', 'kit_a'], 'KIT_A'),
                                          (['KitA', 'kita'], 'KITA')])
def test_ambiguous_registered_alias_is_refused(tmp_path, monkeypatch, names, alias):
    registry = tmp_path / 'registry.json'
    put(registry, {'pdks': [{'name': name} for name in names]})
    monkeypatch.setattr(identity, '_REGISTRY_PATH', registry)
    put(tmp_path / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json',
        {'fields': {'pdk_target': alias}})
    put(tmp_path / 'input/project.json', {'pdk': names[0]})
    with pytest.raises(contract.Refusal, match='LL_PHASE2_PDK_INVALID'):
        contract.phase2_pdk(tmp_path)


@pytest.mark.parametrize('names', [['kit-a', 'kit_a'], ['KitA', 'kita']])
def test_exact_distinct_registered_distributions_are_not_collapsed(tmp_path,
                                                                 monkeypatch, names):
    registry = tmp_path / 'registry.json'
    put(registry, {'pdks': [{'name': name} for name in names]})
    monkeypatch.setattr(identity, '_REGISTRY_PATH', registry)
    put(tmp_path / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json',
        {'fields': {'pdk_target': names[1]}})
    put(tmp_path / 'input/project.json', {'pdk': names[0]})
    with pytest.raises(contract.Refusal, match='LL_PHASE2_PDK_CONFLICT'):
        contract.phase2_pdk(tmp_path)


def test_unregistered_tokens_gain_no_case_aliases(tmp_path):
    put(tmp_path / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json',
        {'fields': {'pdk_target': 'privateKit'}})
    put(tmp_path / 'input/project.json', {'pdk': 'privatekit'})
    with pytest.raises(contract.Refusal, match='LL_PHASE2_PDK_CONFLICT'):
        contract.phase2_pdk(tmp_path)


@pytest.mark.parametrize('target', ['unregisteredKit', 'gf180mcuC'])
def test_unsupported_distribution_still_refuses_native_resolution(tmp_path, target):
    put(tmp_path / 'input/project.json', {'pdk': target})
    # Reading a literal declaration is not permission to substitute a model.
    resolved, _ = contract.phase2_pdk(tmp_path)
    with pytest.raises(ValueError, match='unknown PDK'):
        phase3._assert_pdk_name_resolvable(resolved)


@pytest.mark.skipif(not os.environ.get('FLOW109_NEUTRAL_CANONICAL'),
                    reason='exact retained native neutral subject required')
def test_actual_native_synthesis_handoff_reopens_without_proof_replay():
    project = Path(os.environ['FLOW109_NEUTRAL_CANONICAL'])
    result = handoff.bound_handoff(project)
    assert result and result['verdict'] == 'PASS', result
