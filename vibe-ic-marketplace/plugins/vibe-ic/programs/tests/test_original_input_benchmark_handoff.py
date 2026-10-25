"""Existing coordinator handoff for a selected original-input RTL request."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import benchmark_dispatch as dispatch


@pytest.mark.parametrize('terminal, resumed_entry', [('1', '1'), ('2', '2')])
def test_original_reentry_preserves_family_and_bounded_verification(tmp_path, terminal, resumed_entry):
    runner = Path('/programs/vibe_ic_one_shot_runner.py')
    first = dispatch._solver_argv(runner, tmp_path, '1', terminal, 'ic', 'original')
    resumed = dispatch._resume_solver_argv(runner, tmp_path, True, '1', terminal, 'ic', 'original')
    for argv in (first, resumed):
        assert argv[argv.index('--route') + 1] == 'ic'
        assert argv[argv.index('--exit-step') + 1] == terminal
        assert argv[argv.index('--rtl-input') + 1] == 'original'
        assert '--skip-phase3' in argv
    assert first[first.index('--entry-step') + 1] == '1'
    assert resumed[resumed.index('--entry-step') + 1] == resumed_entry
    structured = dispatch._solver_argv(runner, tmp_path, 'D1', '4', 'ip')
    assert '--rtl-input' not in structured


@pytest.mark.parametrize('status,program_status,reason,expected', [
    ('WAIVED', None, '', True),
    ('NOT_MEASURED', 'PASS_WITH_WAIVERS', 'awaiting_signed_judgement', True),
    ('NOT_MEASURED', 'FAIL', 'awaiting_signed_judgement', False),
    ('NOT_MEASURED', 'PASS_WITH_WAIVERS', 'tool_unavailable', False),
])
def test_pending_author_handoff_uses_declared_program_result(tmp_path, status, program_status, reason, expected):
    # This is a protocol fixture, not an AI/D1 judgement or RTL qualification.
    report = tmp_path / 'reports/orchestrator/phase2_one_shot.json'
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({'steps': [{
        'name': 'rtl_gen', 'status': status, 'program_status': program_status,
        'reason_class': reason, 'extras': {'fallback_skill': 'spec-to-rtl'},
        'detail': 'The ordinary producer declares its missing author output.'}]}))
    result = dispatch._rtl_gen_waive(tmp_path)
    assert bool(result) is expected
    if expected:
        assert result['fallback_skill'] == 'spec-to-rtl'


def test_task_input_authority_comes_from_the_measured_invocation():
    task = {'input_contract': 'original', 'program_verification': {
        'runner_invocation': {'argv': ['python3', 'vibe_ic_one_shot_runner.py', '/project']}}}
    assert dispatch._task_rtl_input(task) == 'structured'
    task['program_verification']['runner_invocation']['argv'] += ['--rtl-input', 'original']
    assert dispatch._task_rtl_input(task) == 'original'
    task['program_verification']['runner_invocation']['argv'] += ['--rtl-input', 'structured']
    with pytest.raises(ValueError, match='RUNNER_RTL_INPUT_INVALID'):
        dispatch._task_rtl_input(task)
