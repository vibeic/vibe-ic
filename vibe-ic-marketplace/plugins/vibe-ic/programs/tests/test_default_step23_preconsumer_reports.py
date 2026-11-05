"""Step23 writes current hold/clock verdicts before its independent audit."""
import json
import importlib
import shlex

import _flow_yaml

import pytest

import flow_declared_producer_run as declared
import test_f15_step23_gates_read_the_tool_arm as fixture

REPORTS = {
    'hold_corner_coverage_check': 'reports/phase3/sta/hold_corner_coverage.json',
    'sta_assumed_clock_disclosure_check': 'reports/phase3/sta/assumed_clock_disclosure.json',
    'clock_target_record_agreement_check': 'reports/phase3/clock_target_record_agreement.json',
}




@pytest.mark.parametrize('program', sorted(REPORTS))
def test_the_same_checker_called_by_audit_is_not_producer_evidence(tmp_path, monkeypatch, program):
    import importlib
    import _gate_authorship as authorship
    project = fixture.tool_project(tmp_path)
    fixture.gate_inputs(project)
    target = project/REPORTS[program]
    monkeypatch.setenv(authorship.ROLE_ENV, authorship.ROLE_AUDIT)
    assert importlib.import_module(program).main([str(project), '--json', str(target)]) == 0
    assert json.loads(target.read_text())['invoked_as'] == 'audit'
    assert declared._producer_target_has_content(target) is False


def test_drv_audit_uses_its_own_verdict_without_replacing_producer_evidence(tmp_path, monkeypatch):
    """Actual project judge; unavailable capture remains NM, never invented P."""
    import test_drv_signoff_judge as fixture_drv
    import drv_signoff_judge as drv
    fixture_drv._synthetic_scene_profile.__wrapped__(tmp_path, monkeypatch)
    bundle, *_ = fixture_drv._project_clean_opensta_census_bundle(tmp_path, monkeypatch)
    # The native capture data is an explicit neutral unit fixture. The real
    # project-aware scientific judge still has to accept its whole census.
    assert drv.judge(bundle, project=tmp_path)['verdict'] == 'PASS'
    source = tmp_path / 'reports/phase3/sta/drv_signoff_bundle.json'
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(json.dumps(bundle))
    raw = tmp_path / 'reports/phase3/sta/drv_signoff.json'
    producer_rc = drv.main([str(tmp_path), '--json', str(raw)])
    assert producer_rc == 1
    assert json.loads(raw.read_text())['verdict'] == 'NOT_MEASURED'
    original = raw.read_bytes()
    row = next(r for r in _flow_yaml.load()['steps'] if str(r['id']) == '31')
    command = next(c['program_exit_zero'] for c in row['gate']['all_of']
                   if str(c.get('program_exit_zero', '')).startswith('drv_signoff_judge '))
    args = shlex.split(command)[1:]
    args[0] = str(tmp_path)
    target = args.index('--json') + 1
    args[target] = str(tmp_path / args[target])
    assert args[target] != str(raw)
    with monkeypatch.context() as audit:
        audit.setenv('VIBEIC_FCC_ROLE', 'audit')
        assert drv.main(args) == 1
    assert raw.read_bytes() == original
    verdict = json.loads(open(args[target]).read())
    assert verdict['verdict'] == 'NOT_MEASURED'
    assert any('capture plan absent' in reason for reason in verdict['not_measured'])
    (tmp_path / 'STEP23_DRV_VERDICT_OBSERVATION.json').write_text(json.dumps({
        'neutral_project_scientific_judge': 'PASS',
        'actual_producer_main_rc': producer_rc, 'canonical_audit_result': verdict,
        'producer_report_unchanged': True,
        'scope': 'source-control census only; no native capture or whole IC PASS'}, indent=2))
