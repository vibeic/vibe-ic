"""Read real retained STA; extra-library mutations use explicit neutral doubles."""
import json
import os
from pathlib import Path
import sys

import pytest
import flow109
import flow109_metric_acceptance as metrics
import librelane_contract as native
from test_flow109_d26_metric_acceptance import _case, _put, _seal


_ACTIVE = False


def _no_tools(event, args):
    if _ACTIVE and event == 'subprocess.Popen':
        raise AssertionError('read-only consumer attempted native dispatch: ' + str(args[1]))


sys.addaudithook(_no_tools)


def read(project, context, component):
    global _ACTIVE
    _ACTIVE = True
    try:
        return metrics.accept_d26(project, context, component)
    finally:
        _ACTIVE = False


def test_actual_native_pad_libraries_bind_complete_per_corner_reads():
    raw = os.environ.get('FLOW109_D26_NATIVE_LIBRARY_PROJECT')
    if not raw:
        pytest.skip('actual retained native STA and root bounds required')
    project = Path(raw)
    manifest = json.loads(Path(os.environ['FLOW109_D26_NATIVE_LIBRARY_MANIFEST']).read_text())
    context = flow109.execution_context(flow109.resolve_plan(manifest['features']), 'D26', 'D26')
    timing = project / 'reports/flow109/d26_scan_mode.json'
    component = {'timing_modes_receipt': {'path': str(timing.relative_to(project)),
                                        'sha256': native.digest(timing)}}
    observed = read(project, context, component)
    assert observed['status'] == 'PASS', observed
    assert [o['status'] for o in observed['obligations']] == ['PASS'] * 3
    consumed = observed['native_observation']['consumed_inputs']
    folder = project / 'phase3/librelane/prelayout/design_sdc/02-openroad-staprepnr'
    cfg = json.loads((folder / 'config.json').read_text())
    import fnmatch
    corners = observed['native_observation']['corners']
    for corner in corners:
        paths = [p for pattern, group in cfg['PAD_LIBS'].items()
                 if fnmatch.fnmatch(corner, pattern) for p in group]
        assert paths
        assert all(consumed[str(Path(p).resolve())] == native.digest(Path(p)) for p in paths)
        assert corners[corner]['unit'] == 'ns'
    output = os.environ.get('FLOW109_D26_NATIVE_LIBRARY_OBSERVATION')
    if output:
        Path(output).write_text(json.dumps(observed, indent=2) + '\n')


def extra_library_case(project):
    """Source-only fixture producer, never a reseal of actual STA evidence."""
    context, component, folder, _ = _case(project)
    cfg = json.loads((folder / 'config.json').read_text())
    pad, extra = project / 'input/pad.lib', project / 'input/extra.lib'
    for path in (pad, extra):
        path.write_text('/* explicit library read boundary double */\n')
    cfg.update(PAD_LIBS={'corner_*': [str(pad)]}, EXTRA_LIBS=[str(extra)])
    _put(folder / 'config.json', cfg)
    fp = json.loads((folder / 'input_fingerprint.json').read_text())
    fp['config'] = native.digest(folder / 'config.json')
    fp['config_files'].update({str(p): native.digest(p) for p in (pad, extra)})
    _put(folder / 'input_fingerprint.json', fp)
    for corner in cfg['STA_CORNERS']:
        path = folder / corner / 'sta.log'
        path.write_text(path.read_text() + ''.join(
            f"Reading cell library for the '{corner}' corner at '{p}'…\n" for p in (pad, extra)))
    _seal(folder)
    return context, component, folder, pad, extra


def test_declared_pad_and_extra_library_reads_are_all_required(tmp_path):
    context, component, _, pad, extra = extra_library_case(tmp_path)
    observed = read(tmp_path, context, component)
    assert observed['status'] == 'PASS', observed
    consumed = observed['native_observation']['consumed_inputs']
    assert all(consumed[str(p)] == native.digest(p) for p in (pad, extra))


@pytest.mark.parametrize('field', ['pad', 'extra'])
def test_changed_actual_library_bytes_refuse_original_fingerprint(tmp_path, field):
    context, component, _, pad, extra = extra_library_case(tmp_path)
    changed = pad if field == 'pad' else extra
    changed.write_text('/* actual changed file bytes; original fingerprint retained */\n')
    observed = read(tmp_path, context, component)
    assert observed['status'] == 'NOT_MEASURED', observed
    assert observed['reason'] == 'D26_NATIVE_READSET_STALE'
    assert str(changed) in observed['detail']


@pytest.mark.parametrize('field', ['pad', 'extra'])
def test_unread_declared_library_cannot_disappear_from_population(tmp_path, field):
    context, component, folder, pad, extra = extra_library_case(tmp_path)
    unread = pad if field == 'pad' else extra
    path = folder / 'corner_a/sta.log'
    path.write_text(''.join(line for line in path.read_text().splitlines(True)
                            if str(unread) not in line))
    _seal(folder)  # explicit fresh neutral fixture producer only
    observed = read(tmp_path, context, component)
    assert observed['status'] == 'NOT_MEASURED', observed
    assert observed['reason'] == 'D26_NATIVE_READSET_UNPROVEN'


def test_duplicate_configured_library_is_not_silently_dropped(tmp_path):
    context, component, folder, pad, _ = extra_library_case(tmp_path)
    cfg = json.loads((folder / 'config.json').read_text())
    cfg['EXTRA_LIBS'].append(str(pad))
    _put(folder / 'config.json', cfg)
    fp = json.loads((folder / 'input_fingerprint.json').read_text())
    fp['config'] = native.digest(folder / 'config.json')
    _put(folder / 'input_fingerprint.json', fp)
    _seal(folder)
    observed = read(tmp_path, context, component)
    assert observed['status'] == 'NOT_MEASURED', observed
    assert observed['reason'] == 'D26_NATIVE_POPULATION_UNMEASURED'
