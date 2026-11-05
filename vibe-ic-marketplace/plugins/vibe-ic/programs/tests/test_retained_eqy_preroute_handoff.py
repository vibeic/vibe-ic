"""SOFTWARE native-reader handoff controls. No EDA qualification is claimed."""
import json

import pytest

import flow109
import lec_gate_netlist_select as netlists
from test_flow109_retained_frontend import case
from test_flow109_selection import profile


@pytest.fixture
def subject(tmp_path, monkeypatch):
    case(tmp_path, 'D25')
    mapped = tmp_path / 'phase2/stage2/synth/neutral.v'
    context = flow109.execution_context(flow109.resolve_plan(profile()), 'D30', 'D30')
    monkeypatch.setattr(flow109, 'dft_source_intent', lambda *_: {'requires_scan': False})
    monkeypatch.setattr(flow109, 'dft_plan_reference', lambda *_: {})
    monkeypatch.setattr(flow109, '_accepted_row', lambda *args: ({}, {}))
    monkeypatch.setattr(flow109, '_bound_project_json', lambda *args: ({'top': 'neutral'}, {}))
    monkeypatch.setattr(netlists, 'pnr_consumed_netlist', lambda *_: (mapped, 'SOFTWARE', False))
    monkeypatch.setattr(flow109, '_d26_timing_modes_binding', lambda *args, **kwargs: {})
    monkeypatch.setattr(flow109, '_preroute_chain_observation', lambda *args, **kwargs: {
        'status': 'NOT_MEASURED', 'reason': 'D30_DELIVERY_ARTIFACT_UNBOUND'})
    return tmp_path, context


def test_retained_native_eqy_reaches_handoff_without_legacy_receipts(subject):
    project, context = subject
    before = {p: p.read_bytes() for p in project.rglob('*') if p.is_file()}
    result = flow109.dft_preroute_admission(project, context)
    assert result['functional_equivalence']['path'] == 'reports/lec_eqy_execution.json'
    assert result['adopted_netlist']['sha256'] == flow109._file_digest(
        project / 'phase2/stage2/synth/neutral.v')
    assert {p: p.read_bytes() for p in project.rglob('*') if p.is_file()} == before


def test_retained_native_eqy_includes_current_headers(subject):
    project, context = subject
    header = project / 'phase2/stage1/rtl/definitions.vh'
    header.write_text('`define NEUTRAL_WIDTH 1\n')
    report = project / 'reports/lec_eqy_execution.json'
    execution = json.loads(report.read_text())
    execution['subject']['rtl'].append({'path': header.relative_to(project).as_posix(),
                                       'sha256': flow109._file_digest(header)})
    report.write_text(json.dumps(execution))
    assert flow109.dft_preroute_admission(project, context)['functional_equivalence']['path'] == (
        'reports/lec_eqy_execution.json')


@pytest.mark.parametrize('damage', ['rtl', 'gate', 'library', 'model', 'failed', 'unknown',
                                    'missing_status', 'missing_library', 'unproved_header'])
def test_retained_native_damage_keeps_handoff_closed(subject, damage):
    project, context = subject
    files = {
        'rtl': 'phase2/stage1/rtl/neutral.v',
        'gate': 'phase2/stage2/synth/neutral.v',
        'library': 'models/cells.lib',
        'model': 'models/cells.v',
        'failed': 'native/eqy/scratch/strategies/neutral.q/pdr/status',
        'unknown': 'native/eqy/scratch/strategies/neutral.q/pdr/status',
        'missing_status': 'native/eqy/scratch/strategies/neutral.q/pdr/status',
        'missing_library': 'models/cells.lib',
    }
    if damage == 'unproved_header':
        (project / 'phase2/stage1/rtl/definitions.vh').write_text('`define NEUTRAL_WIDTH 1\n')
        with pytest.raises(flow109.Flow109Error, match='FLOW109_D25_PROOF_NOT_ACCEPTED'):
            flow109.dft_preroute_admission(project, context)
        return
    path = project / files[damage]
    if damage.startswith('missing'):
        path.unlink()
    elif damage in ('failed', 'unknown'):
        path.write_text('FAIL\n' if damage == 'failed' else 'UNKNOWN\n')
    else:
        path.write_text(path.read_text() + '\nchanged software input\n')
    with pytest.raises(flow109.Flow109Error, match='FLOW109_D25_PROOF_NOT_ACCEPTED'):
        flow109.dft_preroute_admission(project, context)
