"""Ordinary publication preserves the source of an unchanged authored choice."""
import json
import pytest
import spec_declaration_emit as producer
import fault_scan_chain_insert as consumer


def prepared(project):
    docs = project / 'input/docs';docs.mkdir(parents=True)
    (docs / 'L7_verification_plan.md').write_text(
        'The Plugin MUST declare `plugin_output/declaration.json` before authoring:\n'
        '| Field | Required | Example |\n|---|---|---|\n'
        '| `operating_mode` | Yes | functional |\n')
    path = project / 'input/feature-decisions.json'
    path.write_text(json.dumps({'dft': {'requires_scan':False,
        'reason':'The functional core has no selected scan insertion architecture.'}}))
    assert producer.main([str(project),'--from-json',str(path),
                          '--set','operating_mode=functional']) == 0
    binding, problems = consumer.load_d09_dft_contract(project, _validate_owner=False)
    assert binding is not None and not problems, problems
    return path


def test_ordinary_republication_keeps_actual_non_scan_author_source(tmp_path):
    prepared(tmp_path)
    before = (tmp_path / 'plugin_output/declaration.json').read_bytes()
    assert producer.main([str(tmp_path)]) == 0
    assert (tmp_path / 'plugin_output/declaration.json').read_bytes() == before
    binding, problems = consumer.load_d09_dft_contract(tmp_path, _validate_owner=False)
    assert binding is not None and not problems, problems
    assert 'input/feature-decisions.json' in binding['sources']


@pytest.mark.parametrize('change', ['requires_scan','reason'])
def test_changed_source_decision_cannot_reuse_old_authored_intent(tmp_path, change):
    path = prepared(tmp_path)
    body = json.loads(path.read_text())
    body['dft'][change] = True if change == 'requires_scan' else 'A different current integration decision.'
    path.write_text(json.dumps(body))
    assert producer.main([str(tmp_path)]) == 0
    binding, problems = consumer.load_d09_dft_contract(tmp_path, _validate_owner=False)
    assert binding is None and problems
