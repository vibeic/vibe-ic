"""Execute the actual coordinator; unrelated tools are bounded recording stubs."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import design_one_shot_runner as runner


@pytest.mark.parametrize('exit_step', ['2', '4', None])
def test_main_scopes_step4_producers_and_real_consumer(tmp_path, monkeypatch, exit_step):
    docs = tmp_path / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    for n in range(1, 14):
        (docs / f'L{n}.json').write_text('{}')
    calls = []
    for name in list(vars(runner)):
        if not name.startswith('step_') or name == 'step_step4_functional_evidence':
            continue
        def stub(*args, _name=name, **kwargs):
            calls.append(_name)
            # R-0915-85 — the stub stands for "some other step ran and is not
            # this test's subject", which was `SKIP`. That is `NOT_APPLICABLE`
            # -- declared out of this case's scope -- and NOT `NOT_MEASURED`,
            # which would make every stubbed row a hole and put the whole run
            # off PASS for a reason the fixture invented.
            result = runner.StepResult(
                _name.removeprefix('step_'), "NOT_APPLICABLE", 0.0,
                'unrelated tool stub',
                declared_by='this test stubs every step but its subject')
            return [result] if _name == 'step_dft_lec_chain' else result
        monkeypatch.setattr(runner, name, stub)
    monkeypatch.setattr(runner._spf, 'gate', lambda project, owner, site, refuse, fn, *a, **kw:
                        fn(*a, **{k: v for k, v in kw.items() if not k.startswith('_preflight')}))
    monkeypatch.setattr(runner._pl, 'emit_final_summary', lambda *a, **kw: False)
    published = {}

    def publish(project, programs, owner, summary, name, only_steps=None):
        # `only_steps` is R-0924-1's bounded steps view: a run that declared a
        # window refreshes its own step rows and carries the rest. Recorded
        # here so this test -- which already drives main() with and without a
        # window -- also witnesses that the window reaches the view.
        out = tmp_path / name
        out.write_text(json.dumps(summary))
        published['only_steps'] = only_steps
        return {}, out
    monkeypatch.setattr(runner._pl, 'publish_report_then_steps_view', publish)
    argv = ['runner', str(tmp_path), '--skip-hardware', '--skip-phase3', '--skip-analog',
            '--max-rtl-repair-retries', '0']
    if exit_step:
        argv += ['--exit-step', exit_step]
    monkeypatch.setattr(sys, 'argv', argv)
    rc = runner.main()
    report = json.loads((tmp_path / 'phase2_one_shot.json').read_text())
    rows = {row['name']: row for row in report['steps']}
    # R-0924-1: the declared window bounds the finalize tail, and says so.
    if exit_step:
        assert published['only_steps'], (
            'a run declaring --exit-step must bound the steps view to its own '
            'rows; the view was rebuilt for the whole flow')
        assert isinstance(published['only_steps'], set)
        assert report['declared_window']['exit_step'] == exit_step
        assert report['declared_window']['flags'] == [f'--exit-step {exit_step}']
        disclosed = {d['refresh']: d['kind']
                     for d in report['bounded_disclosures']}
        assert disclosed.get('final_audit') == 'skipped', disclosed
        assert disclosed.get('emit_final_summary') == 'skipped', disclosed
        assert disclosed.get('steps_view') == 'narrowed', disclosed
        assert rows['final_audit']['status'] == 'NOT_APPLICABLE', rows['final_audit']
    else:
        assert published['only_steps'] is None, (
            'an unbounded run must rebuild the whole steps view')
        assert 'declared_window' not in report
        assert 'bounded_disclosures' not in report
    if exit_step == '2':
        for name in ['sim', 'reference_tb', 'step4_functional_evidence', 'verilator_coverage']:
            assert rows[name]['status'] == 'NOT_APPLICABLE', rows[name]
        assert not any(name in calls for name in ['step_full_stack_tb_gen', 'step_reference_tb',
                                                  'step_professional_tb_gen', 'step_verilator_coverage'])
        assert rc == 0, report
    else:
        assert 'step_reference_tb' in calls
        assert 'step_full_stack_tb_gen' in calls
        assert rows['step4_functional_evidence']['status'] == 'FAIL', rows
        assert rc == 1


_NEUTRAL_STEP4_OUTPUTS = (
    'phase2/stage1/sim/results.xml',
    'phase2/stage1/sim_professional/neutral_logic/results.xml',
    'phase2/stage1/sim_professional/l10_unit_tb/results.xml',
    'reports/phase2/coverage/coverage_actual.json',
    'reports/phase2/coverage/coverage_verilator.json',
    'phase2/stage1/sim_professional/neutral_logic/cocotb_run.log',
    'step4_execution.json',
)








if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] != '--neutral-step4':
        raise SystemExit(2)
    _neutral_selected_step4(sys.argv[2], sys.argv[3])
