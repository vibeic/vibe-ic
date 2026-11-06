"""A design-owned hardening declaration selects macro work before views exist."""
import json

import pytest

import flow_engine as engine
import l9_l19_contract_carrythrough as carry


def case(project, *, harden=True, config_top='neutral_wrapper', wrapped=False):
    docs = project / 'input/docs'
    docs.mkdir(parents=True)
    (docs / 'L9_constraints.md').write_text(
        '# L9 — Constraints\n## compute_tile block\n'
        + ('- Hardened as a macro inside the wrapper, then the wrapper is hardened with the macro placed.\n'
           if harden else '- Ordinary RTL submodule instantiated inside the wrapper.\n'))
    generated = project / 'phase1/generated_docs'
    generated.mkdir(parents=True)
    l9 = {'top_module': 'neutral_wrapper', 'submodules': [{'name': 'compute_tile'}]}
    (generated / 'L9_INTEGRATION_SPEC.json').write_text(json.dumps({'fields': l9} if wrapped else l9))
    (generated / 'L19_CONSTRAINTS_PDK.json').write_text(json.dumps({'fields': {}}))
    if config_top:
        config = project / 'input/design_src/native' / config_top / 'config.json'
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({'DESIGN_NAME': config_top, 'MACROS': {
            'compute_tile': {'instances': {'u_compute': {'location': [48, 24], 'orientation': 'N'}},
                             'gds': ['dir::../../gds/compute_tile.gds'],
                             'lef': ['dir::../../lef/compute_tile.lef']}}}))
    return generated / 'L9_INTEGRATION_SPEC.json'


@pytest.mark.parametrize('wrapped', [False, True])
def test_hardened_child_selects_macro_row_without_fetched_or_placeholder_views(tmp_path, wrapped):
    path = case(tmp_path, wrapped=wrapped)
    carry.run(tmp_path)
    table = engine.read_json(engine.TABLE)
    route = {'delivery_target': 'ip_hardmacro', 'entry_step': 'D1', 'verify_through': '37.5ip'}
    actual = engine.design_features(tmp_path, route, table)
    assert actual['uses_macros'] is True
    assert 'macro_logical_and_timing_views' in {
        row['name'] for row in engine.select_steps(table, route, actual, None, None)}
    document = json.loads(path.read_text())
    macro = document.get('fields', document)['hard_macros'][0]
    assert macro['name'] == 'compute_tile'
    assert macro['instances']['u_compute'] == {'location': [48, 24], 'orientation': 'N'}
    assert not {'gds', 'lef', 'lib', 'nl'} & macro.keys()
    assert not list(tmp_path.rglob('*.gds')) and not list(tmp_path.rglob('*.lef'))
    before = path.read_bytes()
    carry.run(tmp_path)
    assert path.read_bytes() == before


def test_prose_hardening_obligation_does_not_need_an_operator_config(tmp_path):
    case(tmp_path, config_top=None)
    carry.run(tmp_path)
    table = engine.read_json(engine.TABLE)
    assert engine.design_features(tmp_path, {'delivery_target': 'ip_hardmacro'}, table)['uses_macros'] is True


@pytest.mark.parametrize('config_top', [None, 'other_wrapper'])
def test_regular_rtl_and_an_unrelated_wrapper_config_do_not_select_macros(tmp_path, config_top):
    case(tmp_path, harden=False, config_top=config_top)
    carry.run(tmp_path)
    table = engine.read_json(engine.TABLE)
    assert engine.design_features(tmp_path, {'delivery_target': 'ip_hardmacro'}, table)['uses_macros'] is False


def test_active_native_macro_declaration_does_not_require_duplicate_prose(tmp_path):
    case(tmp_path, harden=False)
    carry.run(tmp_path)
    table = engine.read_json(engine.TABLE)
    assert engine.design_features(tmp_path, {'delivery_target': 'ip_hardmacro'}, table)['uses_macros'] is True


def test_negated_hardening_does_not_select_macro_work(tmp_path):
    case(tmp_path, config_top=None)
    path = tmp_path / 'input/docs/L9_constraints.md'
    path.write_text('# L9\n## compute_tile block\nNot hardened as a macro; retain the RTL implementation.\n')
    carry.run(tmp_path)
    table = engine.read_json(engine.TABLE)
    assert engine.design_features(tmp_path, {'delivery_target': 'ip_hardmacro'}, table)['uses_macros'] is False
