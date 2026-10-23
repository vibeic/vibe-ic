"""Power-boundary projection must never discard a functional observation."""
import pytest
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
