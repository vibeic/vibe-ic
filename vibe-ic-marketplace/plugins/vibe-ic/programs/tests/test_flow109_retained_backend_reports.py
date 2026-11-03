"""C7 report reuse through the existing public front-door preparation seam."""
import hashlib
import json
from types import SimpleNamespace

import pytest
import flow109


def put(project, name, value):
    path = project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value))
    return path


def fixture(project, step, bad=False):
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'Small digital IC without DFT')
    features = {**features, 'requires_si': True}
    manifest = put(project, 'input/selection.json', {'features': features})
    put(project, 'input/step_0_5ic_answers.json', {'answers': {'deliverable': 'DIE'},
        'answer_provenance': {'deliverable': {'answered_by': 'owner', 'citation': 'neutral IC fixture'}}})
    design = put(project, 'phase3/stage3/pnr/design.v', 'native design input')
    sha = hashlib.sha256(design.read_bytes()).hexdigest()
    folder = project / 'phase3/librelane/current/tool'
    state = folder / 'state_out.json'
    inputs = {'state_files': {str(design): sha}}
    put(project, str(folder.relative_to(project) / 'input_fingerprint.json'), inputs)
    if step in ('D41', 'D49', 'D56'):
        values = dict(setup_ws=-1 if bad else 1, hold_ws=1, setup_tns=0, hold_tns=0,
                      setup_vio=0, hold_vio=0, max_slew_vio=0, max_cap_vio=0, max_fanout_vio=0)
        put(project, str(state.relative_to(project)), {'metrics': {
            'design__max_slew_violation__count': 0, 'design__max_cap_violation__count': 0,
            'design__max_fanout_violation__count': 0, 'power__total__corner:neutral_tt': 0.01}})
        put(project, 'reports/phase3/sta_postpnr_signoff.json',
            {'sta_state': str(state), 'corners': {'neutral_tt': values}})
    elif step == 'D43':
        put(project, 'reports/phase3/antenna.json',
            {'tool_state': str(state), 'net_violations': int(bad), 'pin_violations': 0})
    elif step == 'D47':
        spef = put(project, 'phase3/native.spef', '*SPEF "IEEE 1481-1998"\n')
        put(project, str(state.relative_to(project)), {'spef': {'nom_*': str(spef)}})
        put(project, 'reports/phase3/librelane_rcx_handoff.json', {'state': str(state)})
    elif step == 'D48':
        put(project, 'reports/phase3/si_mcf_sta.json', {'windows_rc': 0, 'scope': 'native MCF',
            'corners': {'setup': {'sta_rc': 0, 'worst_slack_after_ns': -1 if bad else 1}}})
        put(project, 'reports/phase3/si_crosstalk.current.json',
            {'inputs': [{'role': 'netlist', 'path': str(design), 'sha256': sha}]})
    elif step == 'D57':
        put(project, 'reports/phase3/ir_drop.json', {'tool_state': str(state),
            'worst_ir_pct_vdd': 11 if bad else 1, 'budget_pct_vdd': 10,
            'worst_ir_uv': 1000, 'per_net_worst_drop_v': {'supply': 0.001}})
    elif step == 'D58':
        put(project, 'reports/phase3/em_openroad_density.json', {'scope': 'native PG EM',
            'signal_em': 'NOT_MEASURED', 'inputs': {'netlist': {
                'project_path': str(design.relative_to(project)), 'sha256': sha}},
            'nets': {'supply': {'no_limit': 0, 'violated': int(bad)}}})
    elif step == 'D59':
        put(project, 'reports/phase3/perc_equivalent.json', {'CVC_total': int(bad)})
    return SimpleNamespace(flow='109', flow109_manifest=manifest,
        flow109_plan_only=False, execution_mode='default', entry_step=step, exit_step=step)


@pytest.mark.parametrize('step', ['D41', 'D43', 'D47', 'D48', 'D49', 'D56', 'D57', 'D58', 'D59'])
def test_native_report_reaches_default_rows_without_rerun(tmp_path, step):
    args = fixture(tmp_path, step)
    assert flow109.prepare_front_door(args, tmp_path) == 0
    result = json.loads((tmp_path / f'reports/flow109/default_rows/{step}.json').read_text())
    assert result['default_row_status'] == 'PASS'
    assert result['native_started'] is False
    assert result['whole_flow_acceptance'] == 'NOT_MEASURED'


@pytest.mark.parametrize('step', ['D41', 'D43', 'D48', 'D49', 'D57', 'D58', 'D59'])
def test_native_violation_keeps_its_original_limit_and_fails(tmp_path, step):
    args = fixture(tmp_path, step, bad=True)
    assert flow109.prepare_front_door(args, tmp_path) == 1
    result = json.loads((tmp_path / f'reports/flow109/default_rows/{step}.json').read_text())
    assert result['default_row_status'] == 'FAIL'
    assert result['completed'] is False


def test_changed_native_design_input_reaches_the_normal_execution_route(tmp_path):
    args = fixture(tmp_path, 'D43')
    (tmp_path / 'phase3/stage3/pnr/design.v').write_text('changed input')
    assert flow109.prepare_front_door(args, tmp_path) is None
    assert args.entry_step == args.exit_step == '26'
    assert not (tmp_path / 'reports/flow109/default_rows/D43.json').exists()


def test_existing_and_extended_backend_rows_resolve_in_the_same_project(tmp_path):
    from test_flow109_retained_padring import _case, _write
    args = _case(tmp_path)
    manifest = json.loads(args.flow109_manifest.read_text())
    manifest['features'].update(requires_spares=True, requires_si=True)
    _write(args.flow109_manifest, manifest)
    plan = flow109.resolve_plan(manifest['features'])
    cohort = [row for row in plan['rows'] if 51 <= row['position'] <= 61
              and row['profile'].get('dispatch', {}).get('kind') == 'canonical_backend_window']
    steps = sorted({step for row in cohort for step in row['profile']['native_steps']}
                   | {'OpenROAD.PadRing', 'OpenROAD.GeneratePDN'})
    states = []
    for step in steps:
        path = tmp_path / 'native' / step / 'state_out.json'
        _write(path, {'metrics': {'flow__errors__count': 0, 'design__power_grid_violation__count': 0,
            'design__violations': 0, 'vibeic__spare__planned': 8, 'vibeic__spare__inserted': 8,
            'vibeic__spare__tieoff__candidates': 16, 'vibeic__spare__tieoff__connected': 16,
            'vibeic__spare__pg__unconnected': 0, 'vibeic__spare__check_placement__violations': 0,
            'route__drc_errors_final': 0, 'design__critical_disconnected_pin__count': 0,
            'timing__setup__ws': 1, 'timing__hold__ws': 1}})
        if step == 'OpenROAD.CTS':
            (path.parent / 'cts.rpt').write_text('Total number of Sinks: 3\nTotal number of Buffers Inserted: 2\n')
        states.append({'step': step, 'state': str(path)})
    _write(tmp_path / 'reports/phase3/execution-backend-15.json', {'states': states})
    observed = []
    for row in cohort:
        context = flow109.execution_context(plan, row['id'], row['id'])
        result = flow109._retained_backend_result(tmp_path, context)
        assert result is not None and result['default_row_status'] == 'PASS', (row['id'], result)
        observed.append(row['position'])
    assert set(observed) == {51, 52, 56, 58, 59, 60, 61}
    for step in ('D41', 'D43', 'D47', 'D48', 'D49', 'D56', 'D57', 'D58', 'D59'):
        current_args = fixture(tmp_path, step)
        assert flow109.prepare_front_door(current_args, tmp_path) == 0, step


def test_report_cannot_supply_its_own_relaxed_ir_limit(tmp_path):
    args = fixture(tmp_path, 'D57')
    path = tmp_path / 'reports/phase3/ir_drop.json'
    report = json.loads(path.read_text())
    report.update(worst_ir_pct_vdd=7, budget_pct_vdd=10)
    path.write_text(json.dumps(report))
    assert flow109.prepare_front_door(args, tmp_path) == 1
    result = json.loads((tmp_path / 'reports/flow109/default_rows/D57.json').read_text())
    assert result['default_row_status'] == 'FAIL'


@pytest.mark.parametrize(('errors', 'rc'), [(0, 0), (1, 1)])
def test_route_checks_read_completed_native_checkers(tmp_path, errors, rc):
    from test_flow109_retained_padring import _case, _write
    args = _case(tmp_path)
    args.entry_step = args.exit_step = 'D42'
    for index, (step, metric) in enumerate((('Checker.TrDRC', 'route__drc_errors'),
        ('Checker.DisconnectedPins', 'design__critical_disconnected_pin__count'),
        ('Checker.WireLength', 'route__wirelength__max'))):
        folder = tmp_path / 'native' / f'{index:02d}-checker'
        _write(folder / 'config.json', {'meta': {'step': step}, 'WIRE_LENGTH_THRESHOLD': None})
        _write(folder / 'state_out.json', {'metrics': {'flow__errors__count': 0, metric: errors}})
    assert flow109.prepare_front_door(args, tmp_path) == rc
    row = json.loads((tmp_path / 'reports/flow109/default_rows/D42.json').read_text())
    assert row['default_row_status'] == ('FAIL' if errors else 'PASS')
    assert row['unmeasured_obligations'] == ['wire-length limit absent from PDK']
