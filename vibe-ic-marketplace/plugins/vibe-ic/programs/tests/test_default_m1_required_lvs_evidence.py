"""M1 independently requires the LVS evidence consumed by its blocking gate."""
import json
import fnmatch
from pathlib import Path

import _flow_yaml
import flow_compliance_check as compliance

LVS_REPORT = 'reports/analog/mixed_signal/top_lvs.json'


def m1():
    return next(row for row in _flow_yaml.load()['steps'] if str(row['id']) == 'M1')


def test_m1_declares_the_blocking_consumers_lvs_report():
    assert LVS_REPORT in m1()['required_outputs']
    assert 'reports/analog/mixed_signal/top_lvs_run.json' not in m1()['required_outputs']


def test_missing_lvs_report_cannot_be_created_by_the_auditor(tmp_path, monkeypatch):
    step = m1()
    analog = tmp_path/'phase1/analog/analog_block_list.json'
    analog.parent.mkdir(parents=True)
    analog.write_text(json.dumps({'blocks': [{'name': 'analog_unit'}]}))
    for relative in ('phase3/mixed_signal/top_merged.gds',
                     'reports/analog/mixed_signal/merge.json'):
        path = tmp_path/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'controlled existing merge evidence\n')
    called = []
    def gate(*args, **kwargs):
        called.append(True)
        (tmp_path/LVS_REPORT).write_text(json.dumps({'verdict': 'PASS'}))
        return True, []
    monkeypatch.setattr(compliance, '_evaluate_gate', gate)
    result = compliance.check_step(tmp_path, step, {})
    assert result.status == compliance._T.Verdict.FAIL.value, result
    assert result.reason_class == compliance._T.ReasonClass.MISSING_ARTEFACT.value, result
    assert any(LVS_REPORT in reason for reason in result.reasons), result.reasons
    # Diagnostic gates may run, but their newly written document cannot
    # become evidence that the producer completed this step.
    assert (tmp_path/LVS_REPORT).is_file()


def test_all_native_receipt_inputs_are_declared_by_m1():
    proof = json.loads((Path(__file__).parent/'fixtures/m1_native_report_proof.json').read_text())
    consumed = set(proof['merge_artifacts']) | set(proof['output']['lvs_artifacts'])
    consumed |= {proof['merge_receipt_path'], proof['output']['path'],
                 'reports/analog/mixed_signal/merge.json'}
    declared = m1()['required_outputs']
    assert not [path for path in consumed if not any(fnmatch.fnmatch(path, pattern) for pattern in declared)]
