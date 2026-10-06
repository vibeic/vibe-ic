"""A missing area comparison cannot mask the native handoff checks.

Only native synthesis/config resolution and final receipt publication are
fixtures. Area, netlist, PDK, provenance and constant-handoff programs execute
as real subprocesses against neutral fixture artifacts. This is not an EDA run.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as runner
import librelane_contract as lc
import synth_area_stats_emit as area_emit
import synth_handoff_netlist_check as handoff
import execution_production as production


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) + '\n')
    return path


def synth_case(tmp_path, monkeypatch, ceiling=None, damage=None):
    project = tmp_path / 'project'
    rtl = project / 'phase2/stage1/rtl/top.v'
    rtl.parent.mkdir(parents=True)
    rtl.write_text('module top(input a, output y);\nassign y = a;\nendmodule\n')
    root = tmp_path / 'pdk'
    root.mkdir()
    liberty = root / 'neutral_sc__tt.lib'
    liberty.write_text('library(neutral_sc) {\ncell(BUF_X1) { area : 1; }\n}\n')
    pdk = SimpleNamespace(name='neutral', liberty=str(liberty), macro_libs=[], macro_lefs=[], macro_v=[])
    if ceiling is not None:
        put(project / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json',
            {'fields': {'die_area_budget_um': ceiling}})
    monkeypatch.setattr(lc, 'resolve_image', lambda p: 'stated/tool@sha256:' + 'a' * 64)
    monkeypatch.setattr(lc, 'pdk_root_resolution', lambda *a, **k: {'path': str(root)})
    monkeypatch.setattr(runner, '_librelane_synth_fanout_updates', lambda *a: {})

    def config(project, pdk, output, *args, **kwargs):
        put(output.with_suffix('.provenance.json'), {})
        return {'SYNTH_FSM_ENCFILE': False, 'SYNTH_TIEHI_CELL': 'TIE_H/Y', 'SYNTH_TIELO_CELL': 'TIE_L/Y'}
    monkeypatch.setattr(lc, 'emit_synthesis_config', config)
    monkeypatch.setattr(lc, 'resolve_step_config',
                        lambda project, image, raw, output, **kw: put(output, json.loads(raw.read_text())))
    folder = project / 'phase3/librelane/02-yosys-synthesis'
    raw = folder / 'top.nl.v'

    def chain(project, image, steps, **kwargs):
        folder.mkdir(parents=True, exist_ok=True)
        raw.write_text('module top(input a, output y);\nBUF_X1 u_buf (.A(a), .Y(y));\nendmodule\n')
        put(folder / 'config.json', json.loads(steps[1][1].read_text()))
        put(folder / 'reports/stat.json', {'modules': {'\\top': {'num_cells': 1, 'area': 1.0}}})
        put(folder / 'state_out.json', {'nl': str(raw), 'metrics': {
            'design__instance__count': 1, 'design__instance__area': 1.0,
            'design__instance_unmapped__count': 0, 'synthesis__check_error__count': 0}})
        if damage == 'missing_tool_netlist':
            raw.unlink()
        if damage == 'area_cli_error':
            put(folder / 'area_budget_gate.json', {'verdict': 'INCOMPLETE'})
        return [folder, folder]
    monkeypatch.setattr(lc, 'run_chain', chain)

    def emit(project, log, netlist, **kwargs):
        return put(project / 'phase2/stage2/synth/stats.json', {
            'cell_count': 1, 'chip_area': 1.0, 'chip_area_unit': 'um^2',
            'top_module': 'top', 'selection': {'rule': 'SINGLE_MODULE_NO_HIERARCHY'},
            'netlist_sha256': 'sha256:' + hashlib.sha256(netlist.read_bytes()).hexdigest()})
    monkeypatch.setattr(area_emit, 'emit_for_run', emit)
    published = []
    monkeypatch.setattr(handoff, 'publish_handoff', lambda *a: published.append(a))
    real_run = subprocess.run
    calls = []

    def checked_run(argv, **kwargs):
        program = Path(argv[1]).stem if len(argv) > 1 else ''
        calls.append(program)
        if damage == program:
            if program == 'synth_netlist_check':
                Path(argv[argv.index('--netlist') + 1]).write_text('')
            elif program == 'pdk_consistency_check':
                liberty.write_text('library(neutral_sc) {\ncell(OTHER_X1) { area : 1; }\n}\n')
            elif program == 'provenance_check':
                (project / 'provenance.jsonl').write_text('')
            elif program == 'synth_handoff_netlist_check':
                put(folder / 'config.json', {})
        if program == 'area_total_vs_budget_check' and damage == 'area_cli_error':
            return subprocess.CompletedProcess(argv, 2, '', 'usage error')
        result = real_run(argv, **kwargs)
        if program == 'area_total_vs_budget_check' and damage in {'area_report_missing', 'area_report_malformed', 'area_report_conflicting'}:
            report = folder / 'area_budget_gate.json'
            if damage == 'area_report_missing':
                report.unlink(missing_ok=True)
            elif damage == 'area_report_malformed':
                report.write_text('{invalid json')
            else:
                put(report, {'verdict': 'PASS'})
        return result
    monkeypatch.setattr(runner.subprocess, 'run', checked_run)
    try:
        result = runner._step_synth_librelane(project, 'top', pdk, 'stated-container')
    finally:
        runner.set_invocation_provenance_sink(None)
    return result, calls, published, folder


CHECKS = ['synth_netlist_check', 'pdk_consistency_check', 'provenance_check', 'synth_handoff_netlist_check']


def test_uncompared_area_runs_checks_and_remains_unmeasured(tmp_path, monkeypatch):
    result, calls, published, folder = synth_case(tmp_path, monkeypatch)
    assert result.status == 'NOT_MEASURED', result.detail
    assert result.reason_class == 'inconclusive'
    assert [c for c in calls if c in CHECKS] == CHECKS
    assert len(published) == 1
    report = json.loads((folder / 'area_budget_gate.json').read_text())
    assert report['verdict'] == 'INCOMPLETE'
    assert production._gate_verdict(2, report) == 'NOT_MEASURED'
    # The actual Step9 consumer must retain this producer disposition.
    outputs = tmp_path / 'outputs'
    binding = {'required_gates': list(production.REQUIRED_GATES)}
    put(outputs / 'producer.json', {'binding': binding, 'status': result.status, 'detail': result.detail})
    (outputs / 'native_commands.jsonl').write_text('{}\n')
    evidence = production.validate_synthesis(outputs, binding)
    assert evidence.verdict == 'NOT_MEASURED'
    assert evidence.gates['area_total_vs_budget_check'] == 'NOT_MEASURED'


@pytest.mark.parametrize('damage,code', [
    ('synth_netlist_check', 'LL_SYNTH_NETLIST_GATE_FAILED'),
    ('pdk_consistency_check', 'LL_PDK_CONSISTENCY_FAILED'),
    ('provenance_check', 'LL_PROVENANCE_FAILED'),
    ('synth_handoff_netlist_check', 'LL_HANDOFF_NETLIST_FAILED'),
])
def test_actual_handoff_failure_wins_over_uncompared_area(tmp_path, monkeypatch, damage, code):
    result, calls, published, _ = synth_case(tmp_path, monkeypatch, damage=damage)
    assert result.status == 'FAIL', result.detail
    assert code in result.detail
    assert damage in calls
    assert not published


@pytest.mark.parametrize('ceiling,status', [('10x10', 'PASS'), ('0.5x0.5', 'FAIL')])
def test_measured_area_decisions_are_unchanged(tmp_path, monkeypatch, ceiling, status):
    result, calls, published, _ = synth_case(tmp_path, monkeypatch, ceiling=ceiling)
    assert result.status == status, result.detail
    if status == 'FAIL':
        assert 'area_total_vs_budget_check rc=1' in result.detail
        assert not published
    else:
        assert [c for c in calls if c in CHECKS] == CHECKS
        assert len(published) == 1


def test_missing_tool_netlist_remains_failure(tmp_path, monkeypatch):
    result, calls, published, _ = synth_case(tmp_path, monkeypatch, damage='missing_tool_netlist')
    assert result.status == 'FAIL'
    assert 'LL_SYNTH_OUTPUT_MISSING' in result.detail
    assert not published


@pytest.mark.parametrize('damage', ['area_report_missing', 'area_report_malformed', 'area_report_conflicting', 'area_cli_error'])
def test_unexplained_rc2_never_reuses_or_fabricates_area_evidence(tmp_path, monkeypatch, damage):
    result, calls, published, _ = synth_case(tmp_path, monkeypatch, damage=damage)
    assert result.status == 'FAIL', result.detail
    assert 'LL_SYNTH_AREA_REPORT_INVALID' in result.detail
    assert not published
