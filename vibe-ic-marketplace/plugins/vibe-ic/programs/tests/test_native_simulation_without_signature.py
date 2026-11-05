"""Native result aggregation at real bounded coordinator; tools are SOFTWARE stubs."""
import json
import sys

import pytest
import design_one_shot_runner as runner


@pytest.mark.parametrize('status', ['PASS', 'FAIL'])
def test_bounded_simulation_keeps_native_result_without_approval_signature(tmp_path, monkeypatch, status):
    docs = tmp_path / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    for n in range(1, 14):
        (docs / f'L{n}.json').write_text('{}')
    for name in ('L10_TEST_CASES.json', 'L12_BEHAVIORAL_SEQUENCES.json'):
        (docs / name).write_text('{}')
    rtl = tmp_path / 'phase2/stage1/rtl/neutral.v'
    rtl.parent.mkdir(parents=True)
    rtl.write_text('module neutral(input clk, input d, output q); assign q=d; endmodule\n')
    gate = tmp_path / 'reports/phase2/gates/professional_tb.json'
    gate.parent.mkdir(parents=True)
    gate.write_text(json.dumps({'dut_kind': 'expert_reference'}))
    bundle = tmp_path / 'phase2/stage1/sim_professional/neutral'
    bundle.mkdir(parents=True)
    (bundle / 'expert_reference_tb.py').write_text('expected = 1\n')
    for name in list(vars(runner)):
        if not name.startswith('step_'):
            continue
        def stub(*a, _name=name, **kw):
            active = _name in ('step_professional_tb_gen', 'step_reference_tb',
                'step_step4_functional_evidence', 'step_verilator_coverage')
            row = runner.StepResult(_name.removeprefix('step_'),
                status if _name == 'step_professional_tb_gen' else 'PASS' if active else 'NOT_APPLICABLE',
                0.0, 'SOFTWARE tool boundary; no hardware proof', declared_by='unrelated tool stub')
            return [row] if _name == 'step_dft_lec_chain' else row
        monkeypatch.setattr(runner, name, stub)
    monkeypatch.setattr(runner._spf, 'gate', lambda project, owner, site, refuse, fn, *a, **kw:
        fn(*a, **{k:v for k,v in kw.items() if not k.startswith('_preflight')}))
    monkeypatch.setattr(runner._pl, 'emit_final_summary', lambda *a, **kw: False)
    def publish(project, programs, owner, summary, name, only_steps=None):
        output = tmp_path / name
        output.write_text(json.dumps(summary))
        return {}, output
    monkeypatch.setattr(runner._pl, 'publish_report_then_steps_view', publish)
    monkeypatch.setattr(sys, 'argv', ['runner', str(tmp_path), '--skip-hardware',
        '--skip-phase3', '--skip-analog', '--max-rtl-repair-retries', '0',
        '--entry-step', '4', '--exit-step', '4'])
    rc = runner.main()
    report = json.loads((tmp_path / 'phase2_one_shot.json').read_text())
    professional = next(r for r in report['steps'] if r['name'] == 'professional_tb_gen')
    assert professional['status'] == status, professional
    assert report['verdict'] == status, report
    assert rc == (0 if status == 'PASS' else 1)
    assert '4' not in report['ai_judgements']
    assert not (tmp_path / 'reports/audit/ai_judgements/4.json').exists()
