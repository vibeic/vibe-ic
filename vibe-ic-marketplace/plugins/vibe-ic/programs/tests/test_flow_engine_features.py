"""Selection reads Phase 1's structured outputs, without extra operator input."""
import json

import pytest

import flow_engine as engine


@pytest.fixture
def table():
    return engine.read_json(engine.TABLE)


def layer(project, code, fields, wrapped=True):
    path = project / 'phase1/generated_docs' / (code + '_STRUCTURED.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'fields': fields} if wrapped else fields))
    return path


def profile(project, **fields):
    path = project / 'reports/ic_class.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fields))


def features(project, table, target='ip_hardmacro'):
    return engine.design_features(project, {'delivery_target': target}, table)


def test_converter_class_and_power_domains_select_actual_analog_and_mixed_rows(tmp_path, table):
    profile(tmp_path, has_analog=True, is_data_converter=True, is_mixed_signal=False, is_pure_analog=False)
    layer(tmp_path, 'L21', {'power_domains': [{'name': 'core'}, {'name': 'io'}]}, wrapped=False)
    actual = features(tmp_path, table)
    assert actual['has_analog'] and actual['has_digital'] and actual['mixed']
    assert actual['has_power_intent']
    route = {'delivery_target': 'ip_hardmacro', 'entry_step': 'D1', 'verify_through': '37.5ip'}
    selected = {r['name'] for r in engine.select_steps(table, route, actual, None, None)}
    assert {'analog_specifications', 'mixed_signal_signoff', 'power_intent_and_domain_rules'} <= selected


@pytest.mark.parametrize('wrapped', [False, True])
def test_layer_aliases_and_exact_source_path(tmp_path, table, wrapped):
    path = layer(tmp_path, 'L23', {'security_requirements_present': True}, wrapped=wrapped)
    sources = {}
    actual = engine.design_features(tmp_path, {'delivery_target': 'ip_hardmacro'}, table, sources=sources)
    assert actual['requires_security'] is True
    assert sources['requires_security'] == str(path.relative_to(tmp_path)) + '#/' + ('fields/' if wrapped else '') + 'security_requirements_present'


@pytest.mark.parametrize('fields,dft,scan', [
    ({'dft_present': True}, True, False),
    ({'dft_present': False, 'scan_chains': [{'name': 'chain'}]}, True, True),
    ({'bist_mbist': [{'name': 'memory_test'}]}, True, False),
    ({'dft_present': None, 'dft_intent_status': 'PLANNED_UNMEASURED'}, True, False),
    ({'dft_present': False, 'scan_chains': [], 'jtag_tap': None}, False, False),
])
def test_dft_and_scan_follow_distinct_structured_obligations(tmp_path, table, fields, dft, scan):
    layer(tmp_path, 'L20', fields)
    actual = features(tmp_path, table)
    assert actual['requires_dft'] is dft
    assert actual['requires_scan'] is scan


def test_digital_class_and_electrical_specs_never_enable_analog(tmp_path, table):
    profile(tmp_path, has_analog=False, is_pure_digital=False, is_data_converter=False)
    layer(tmp_path, 'L5', {'analog_blocks_detected': False, 'analog_blocks': [],
        'electrical_specs': [{'supply_v': 1.2}], 'notes': 'Analog and mixed-signal reference information.'}, wrapped=False)
    actual = features(tmp_path, table)
    assert not actual['has_analog'] and not actual['mixed']
    assert actual['has_digital']


def test_l5_without_class_report_is_still_a_structured_analog_source(tmp_path, table):
    layer(tmp_path, 'L5', {'analog_blocks_detected': True}, wrapped=False)
    assert features(tmp_path, table)['has_analog'] is True


def test_pure_analog_class_disables_the_digital_entry_default(tmp_path, table):
    profile(tmp_path, has_analog=True, is_pure_analog=True, is_mixed_signal=False, is_data_converter=False)
    actual = features(tmp_path, table)
    assert actual['has_analog'] and not actual['has_digital'] and not actual['mixed']


@pytest.mark.parametrize('macro_fields,expected', [
    ({'submodules': [{'name': 'logic_unit'}], 'memories': [{'kind': 'ram'}]}, False),
    ({'hard_macros': [{'name': 'storage'}]}, True),
    ({'macros': {'storage': {'lef': 'storage.lef'}}}, True),
])
def test_module_or_memory_presence_does_not_claim_hard_macros(tmp_path, table, macro_fields, expected):
    layer(tmp_path, 'L9', macro_fields, wrapped=False)
    assert features(tmp_path, table)['uses_macros'] is expected


@pytest.mark.parametrize('package,expected', [(None, False), ({'pdk': 'process'}, False),
                                            ({'package_type': 'NOT_DETERMINED'}, False),
                                            ({'package_type': 'QFN'}, True)])
def test_package_requires_an_actual_package_type(tmp_path, table, package, expected):
    layer(tmp_path, 'L1', {'package_info': package}, wrapped=False)
    actual = features(tmp_path, table)
    assert actual['package_declared'] is expected
    assert actual['package_interface'] is expected
    assert not actual['package_model_required']


def test_empty_and_unstated_fields_are_not_obligations(tmp_path, table):
    layer(tmp_path, 'L20', {'dft_present': False, 'scan_chains': [], 'bist_mbist': []})
    layer(tmp_path, 'L21', {'power_domains': [], 'upf_path': None})
    layer(tmp_path, 'L23', {'security_requirements_present': None, 'key_handling': {}, 'secure_boot': None})
    layer(tmp_path, 'L24', {'signoff_requirements': [
        {'check': name, 'stated': False} for name in ('IR_drop', 'EM', 'SI')]})
    layer(tmp_path, 'L25', {'aging_margin': None, 'em_budget': None, 'unmeasured_obligations': []})
    actual = features(tmp_path, table, target='rtl')
    for name in ('has_analog', 'mixed', 'has_power_intent', 'requires_dft', 'requires_scan',
                 'requires_security', 'uses_macros', 'package_declared', 'requires_aging',
                 'requires_ir', 'requires_em', 'requires_si'):
        assert actual[name] is False, name


def test_unmeasured_reliability_obligations_still_select_work(tmp_path, table):
    layer(tmp_path, 'L25', {'unmeasured_obligations': [{'subject': 'aging', 'status': 'NOT_MEASURED'}]})
    assert features(tmp_path, table)['requires_aging'] is True


def test_not_selected_reports_structured_values_and_their_sources(tmp_path, table):
    profile(tmp_path, has_analog=False)
    route = {'delivery_target': 'ip_hardmacro', 'entry_step': 'mixed_signal_signoff',
             'verify_through': 'mixed_signal_signoff'}
    report = engine.run(tmp_path, table=table, route=route)
    assert report['selected'] == 0
    assert report['features']['has_analog'] is False
    assert report['feature_sources']['has_analog'] == 'reports/ic_class.json#/has_analog'
    omitted = next(row for row in report['not_selected'] if row['name'] == 'mixed_signal_signoff')
    assert omitted['features'] == {'mixed': False}
    assert omitted['feature_sources']['mixed'] == 'Derived from has_digital and has_analog'
