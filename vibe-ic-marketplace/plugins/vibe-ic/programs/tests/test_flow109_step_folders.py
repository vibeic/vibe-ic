import hashlib
import json

import pytest



def put(project, relative, value):
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path




































@pytest.mark.parametrize('cited', [False, True])
def test_scan_census_does_not_capture_files_unless_actual_evidence_cites_them(tmp_path, cited):
    import step_output_collector as collector
    native = put(tmp_path, 'reports/native.json', {'measured': 0})
    inspected = put(tmp_path, 'input/inspected.json', {'provenance': 'transport fixture'})
    record = {'result_file': str(native), 'native': {
        'documents_scanned': [str(inspected), {'path': str(inspected),
            'sha256': hashlib.sha256(inspected.read_bytes()).hexdigest()}]}}
    if cited:
        record['native']['derived_answers'] = {'evidence': str(inspected)}
    known = dict(collector._known_files(tmp_path, record))
    assert known['reports/native.json'] == hashlib.sha256(native.read_bytes()).hexdigest()
    assert ('input/inspected.json' in known) is cited
    assert json.loads(inspected.read_text()) == {'provenance': 'transport fixture'}
