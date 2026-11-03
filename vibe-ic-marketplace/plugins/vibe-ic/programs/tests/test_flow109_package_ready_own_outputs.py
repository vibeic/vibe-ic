"""D75's existing native consumers, without GDS or qualification wrappers."""
import json

import flow109_package_ready as package
import test_flow109_package_ready as fixture


def project(tmp_path, monkeypatch):
    monkeypatch.setattr(fixture, '_gds', lambda path: None)
    root = fixture._project(tmp_path)
    (root / package.PROVIDER_TARGET).unlink()
    declaration = json.loads((root / package.DECLARATION).read_text())
    declaration['operator_template'] = {'absent_reason': 'Input selects independent bare-die delivery.'}
    (root / package.DECLARATION).write_text(json.dumps(declaration))
    (root / 'reports/phase3/perc_equivalent.json').write_text(json.dumps({
        'native_cvc': {'native_result': 'PASS', 'counts': {'errors': 0},
                       'report': 'phase3/librelane/cvc/cvc.log'}}))
    return root


def test_own_pad_and_cvc_results_complete_the_package_row(tmp_path, monkeypatch):
    root = project(tmp_path, monkeypatch)
    result = package.execute(root, fixture._context(root))
    assert result['default_row_status'] == 'PASS', result
    assert result['completed'] is True
    assert {row['check']: row['status'] for row in result['checks']} == {
        'declared_delivery_form': 'PASS', 'pad_side_constraint_check': 'PASS',
        'pad_bterm_coincidence_check': 'PASS', 'provider_bond_pad_edge': 'NOT_APPLICABLE',
        'test_access_applicability': 'NOT_APPLICABLE', 'perc_signoff_check': 'PASS',
        'package_electrical_feedback': 'NOT_APPLICABLE'}


def test_native_cvc_failure_survives_package_aggregation(tmp_path, monkeypatch):
    root = project(tmp_path, monkeypatch)
    path = root / 'reports/phase3/perc_equivalent.json'
    record = json.loads(path.read_text())
    record['native_cvc']['native_result'] = 'FAIL'
    record['native_cvc']['counts']['errors'] = 2
    path.write_text(json.dumps(record))
    result = package.execute(root, fixture._context(root))
    assert result['default_row_status'] == 'FAIL'
    assert result['completed'] is False


def test_unmeasured_is_not_package_completion(tmp_path):
    result = package.execute(tmp_path, {'features': {}})
    assert result['default_row_status'] == 'NOT_MEASURED'
    assert result['completed'] is False
