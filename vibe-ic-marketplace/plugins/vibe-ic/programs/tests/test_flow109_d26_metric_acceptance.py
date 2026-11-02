"""Real D26 readers/finalizer over neutral sealed STA doubles, not native proof."""
import json
from pathlib import Path

import pytest

import flow109
import flow109_metric_acceptance as metrics
import librelane_contract as native
import vibe_ic_one_shot_runner as front
from test_flow109_selection import profile
from programs.tests._hostpaths import require_repo


def _put(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2) + '\n')
    return path


def _ref(project, path):
    return {'path': str(path.relative_to(project)), 'sha256': native.digest(path)}


def _seal(folder):
    """Fixture producer only; never used to qualify or reseal a real carrier."""
    fp = json.loads((folder / 'input_fingerprint.json').read_text())
    _put(folder / 'vibeic_receipt.json', {'input': fp, 'sha256': {
        str(p.relative_to(folder)): native.digest(p) for p in folder.rglob('*')
        if p.is_file() and p.name != 'vibeic_receipt.json'}})


def _case(project):
    # Use the actual checked-in registry contract, not a parallel test schema.
    registry = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'flow', 'flow109.json')
    row = flow109.resolve_step(flow109.resolve_plan(profile()), 'D26')
    assert row['position'] == 38 and json.loads(registry.read_text())['schema']
    context = {'resolved_row': row}
    netlist = project / 'synth/neutral.v'
    netlist.parent.mkdir(parents=True)
    netlist.write_text('module neutral(input clk, d, output q); assign q=d; endmodule\n')
    sdc = project / 'input/neutral.sdc'
    sdc.parent.mkdir()
    sdc.write_text('create_clock -period 12 [get_ports clk]\n')
    library = project / 'input/neutral.lib'
    library.write_text('/* SOURCE CONTROL DOUBLE: no electrical qualification */\n')
    folder = project / 'native/sta'
    config = {'meta': {'step': 'OpenROAD.STAPrePNR'}, 'PNR_SDC_FILE': str(sdc),
              'STA_CORNERS': ['corner_a', 'corner_b'], 'LIB': {'*': [str(library)]}}
    _put(folder / 'config.json', config)
    _put(folder / 'state_in.json', {'nl': str(netlist)})
    values = {f'timing__{sense}__ws__corner:{corner}': 0.5
              for sense in ['setup', 'hold'] for corner in config['STA_CORNERS']}
    _put(folder / 'state_out.json', {'nl': str(netlist), 'metrics': values})
    _put(folder / 'pdk_root.json', {'mounts_under_it': [], 'test_double': True})
    fp = {'step': 'OpenROAD.STAPrePNR', 'image': 'SOURCE_CONTROL_NOT_NATIVE',
          'state': native.digest(folder / 'state_in.json'),
          'config': native.digest(folder / 'config.json'),
          'state_files': {str(netlist): native.digest(netlist)},
          'config_files': {str(p): native.digest(p) for p in [sdc, library]}}
    _put(folder / 'input_fingerprint.json', fp)
    (folder / 'invocation.log').write_text('SOURCE CONTROL DOUBLE; no native dispatch\n')
    for corner in config['STA_CORNERS']:
        d = folder / corner
        d.mkdir()
        (d / 'checks.rpt').write_text('check_setup\n')
        (d / 'vibeic_time_unit.rpt').write_text('STA_TIME_UNIT: ns\n')
        (d / 'sta.log').write_text(
            f"Reading cell library for the '{corner}' corner at '{library}'…\n"
            f"Reading top-level netlist at '{netlist}'…\n"
            f"Reading design constraints file at '{sdc}'…\n")
    _seal(folder)
    _put(project / 'phase3/librelane/prelayout/gates/step10_slack.json', {
        'source': str(folder / 'state_out.json'),
        'state_out_sha256': native.digest(folder / 'state_out.json')})
    timing = _put(project / 'reports/modes.json', {
        'schema': 'vibeic.flow109.d26-timing-modes.v1', 'step_id': 'D26', 'position': 38,
        'aggregate_status': 'PASS', 'scan': {'applicability': 'NOT_APPLICABLE'},
        'post_scan_arms': {}})
    payload = {'limits': {'setup_ws': {'min': 0}}, 'units': {'setup_ws': 'ns'}}
    source = _put(project / 'input/independent-bounds.json', {'prelayout_timing_targets': payload})
    authority = _put(project / 'requirements/base_13/prelayout_timing_targets.json', {
        'schema': metrics.AUTHORITY_SCHEMA, **payload,
        'approval': {'status': 'APPROVED', 'authority': 'requirements_owner', 'approver': 'neutral-requirements-reviewer',
                     'source_reference': _ref(project, source)}})
    return context, {'timing_modes_receipt': _ref(project, timing)}, folder, authority


def _read(project, context, component):
    return metrics.accept_d26(project, context, component)


def test_d26_actual_registry_metrics_all_bind_to_sealed_native_state(tmp_path):
    context, component, _, _ = _case(tmp_path)
    observed = _read(tmp_path, context, component)
    assert observed['status'] == 'PASS', observed
    assert [o['status'] for o in observed['obligations']] == ['PASS'] * 3
    assert len(observed['obligations'][1]['checks']) == 2
    assert all(c['metric'] == 'setup_ws' for c in observed['obligations'][1]['checks'])


@pytest.mark.parametrize('damage', ['missing_bounds', 'unapproved', 'source_semantics',
    'stale_sdc', 'stale_library', 'unsealed_checks', 'missing_unit', 'missing_corner', 'missing_hold'])
def test_d26_missing_or_unbound_inputs_never_become_zero(tmp_path, damage):
    context, component, folder, authority = _case(tmp_path)
    if damage == 'missing_bounds':
        authority.unlink()
    elif damage in ['unapproved', 'source_semantics']:
        body = json.loads(authority.read_text())
        if damage == 'unapproved':
            body['approval']['status'] = 'DRAFT'
        else:
            body['limits']['setup_ws']['min'] = -99
        _put(authority, body)
    elif damage in ['stale_sdc', 'stale_library']:
        (tmp_path / ('input/neutral.sdc' if damage == 'stale_sdc' else 'input/neutral.lib')).write_text('changed\n')
    elif damage == 'unsealed_checks':
        body = json.loads((folder / 'vibeic_receipt.json').read_text())
        del body['sha256']['corner_a/checks.rpt']
        _put(folder / 'vibeic_receipt.json', body)
    elif damage == 'missing_unit':
        (folder / 'corner_a/vibeic_time_unit.rpt').unlink()
        _seal(folder)
    elif damage == 'missing_corner':
        (folder / 'corner_a/sta.log').unlink()
        _seal(folder)
    else:
        p = folder / 'state_out.json'
        body = json.loads(p.read_text())
        del body['metrics']['timing__hold__ws__corner:corner_a']
        _put(p, body)
        gate = tmp_path / 'phase3/librelane/prelayout/gates/step10_slack.json'
        body = json.loads(gate.read_text()); body['state_out_sha256'] = native.digest(p); _put(gate, body)
        _seal(folder)
    observed = _read(tmp_path, context, component)
    assert observed['status'] == 'NOT_MEASURED', observed
    assert observed['delivery_blocked'] is True


@pytest.mark.parametrize('failure', ['unconstrained', 'setup', 'hold'])
def test_d26_real_report_values_fail_without_weaker_bounds(tmp_path, failure):
    context, component, folder, authority = _case(tmp_path)
    if failure == 'unconstrained':
        (folder / 'corner_a/checks.rpt').write_text('check_setup\nWarning: There is 1 unconstrained endpoint.\n')
        authority.unlink()  # A different unmeasured metric cannot erase a failure.
    else:
        if failure == 'hold':
            # An independently declared NEUTRAL fixture hold limit exercises
            # the generic consumer; the SPM source proposal declares setup only.
            body = json.loads(authority.read_text())
            body['limits']['hold_ws'] = {'min': 0};body['units']['hold_ws'] = 'ns'
            source = tmp_path / body['approval']['source_reference']['path']
            _put(source, {'prelayout_timing_targets': {k: v for k, v in body.items()
                                                     if k not in ('schema', 'approval')}})
            body['approval']['source_reference'] = _ref(tmp_path, source)
            _put(authority, body)
        p = folder / 'state_out.json';body = json.loads(p.read_text())
        body['metrics'][f'timing__{failure}__ws__corner:corner_a'] = -0.5
        _put(p, body)
        gate = tmp_path / 'phase3/librelane/prelayout/gates/step10_slack.json'
        body = json.loads(gate.read_text());body['state_out_sha256'] = native.digest(p);_put(gate, body)
    _seal(folder)
    observed = _read(tmp_path, context, component)
    assert observed['status'] == 'FAIL', observed
    assert any(o['status'] == 'FAIL' for o in observed['obligations'])


def test_d26_reports_hold_without_inventing_an_undeclared_metric_bound(tmp_path):
    context, component, folder, _ = _case(tmp_path)
    p = folder / 'state_out.json';body = json.loads(p.read_text())
    body['metrics']['timing__hold__ws__corner:corner_a'] = -0.5
    _put(p, body)
    gate = tmp_path / 'phase3/librelane/prelayout/gates/step10_slack.json'
    body = json.loads(gate.read_text());body['state_out_sha256'] = native.digest(p);_put(gate, body)
    _seal(folder)
    observed = _read(tmp_path, context, component)
    assert observed['status'] == 'PASS', observed  # Registry metrics only.
    assert observed['native_observation']['corners']['corner_a']['slack']['hold_ws'] == -0.5
    assert all(c['metric'] == 'setup_ws' for c in observed['obligations'][1]['checks'])
    # The existing native/semantic finalizer remains a separate conjunction;
    # this does not override a native hold FAIL or post-CTS criteria.


def test_d26_normal_finalizer_refuses_native_only_pass_without_metrics(tmp_path, monkeypatch):
    from test_d26_semantic_terminal_binding import _prepared
    acceptance, _, _ = _prepared(tmp_path, monkeypatch, 'PASS')
    observed = front._finish_d26_selected_owner(tmp_path, acceptance)
    assert observed['verdict'] == 'NOT_MEASURED', observed
    canonical = json.loads((tmp_path / 'reports/flow109/default_rows/D26.json').read_text())
    assert canonical['default_row_status'] == 'NOT_MEASURED'
    assert canonical['completed'] is False
