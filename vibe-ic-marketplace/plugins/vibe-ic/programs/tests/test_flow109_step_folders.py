import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import _delivery_route
import benchmark_evidence_publish as publish
import flow109


def put(project, relative, value):
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


def case(project, step):
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'Small digital IC without DFT')
    manifest = put(project, 'selection.json', {'features': features})
    assert _delivery_route.admit(project, 'ic') is None
    return SimpleNamespace(flow='109', flow109_manifest=manifest,
        flow109_plan_only=False, execution_mode='default', entry_step=step, exit_step=step)


def run(project, args):
    execute = getattr(flow109, 'run_rows', None)
    if execute is None:
        return flow109.prepare_front_door(args, project)
    return execute(args, project, lambda selected: flow109.prepare_front_door(selected, project))


def versions(project, step):
    spec = next(row for row in flow109.load_registry()['rows'] if row['id'] == step)
    return sorted((project / 'steps').glob(f"{spec['position']:03d}_*/*/result.json"))


def tree_bytes(folder):
    return {str(path.relative_to(folder)): path.read_bytes()
            for path in folder.rglob('*') if path.is_file()}


def native_case(project):
    states = []
    for name in ('Yosys.JsonHeader', 'OpenROAD.Floorplan', 'Odb.ManualMacroPlacement', 'OpenROAD.PadRing',
                 'OpenROAD.GeneratePDN', 'OpenROAD.GlobalPlacement',
                 'OpenROAD.RepairDesignPostGPL', 'OpenROAD.DetailedPlacement'):
        relative = f'native/{name}/state_out.json'
        put(project, relative, {'metrics': {'flow__errors__count': 0,
            'design__power_grid_violation__count': 0, 'design__violations': 0}})
        states.append({'step': name, 'state': relative})
    put(project, 'reports/phase3/execution-backend-15.json', {'states': states})


def test_native_row_and_rerun_preserve_earlier_bytes(tmp_path):
    native_case(tmp_path)
    args = case(tmp_path, 'D31')
    assert run(tmp_path, args) == 0
    first = versions(tmp_path, 'D31')
    assert len(first) == 1, 'the native row left no retained folder'
    folder = first[0].parent
    saved = tree_bytes(folder)
    report = folder / 'outputs/native/OpenROAD.Floorplan/state_out.json'
    assert json.loads(report.read_text())['metrics']['flow__errors__count'] == 0
    assert json.loads(first[0].read_text()) == json.loads(
        (tmp_path / 'reports/flow109/default_rows/D31.json').read_text())
    assert json.loads((folder / 'inputs.json').read_text())
    assert run(tmp_path, case(tmp_path, 'D35')) == 0
    put(tmp_path, 'native/OpenROAD.Floorplan/state_out.json', {
        'metrics': {'flow__errors__count': 2}})
    assert run(tmp_path, args) == 1
    assert len(versions(tmp_path, 'D31')) == 2
    assert tree_bytes(folder) == saved
    assert json.loads(versions(tmp_path, 'D31')[-1].read_text())['default_row_status'] == 'FAIL'


@pytest.mark.parametrize('failure', ['exception', 'missing'])
def test_unavailable_tool_leaves_its_reason(tmp_path, monkeypatch, failure):
    args = case(tmp_path, 'D31')
    def failed(project, context):
        if failure == 'exception':
            raise OSError('native executable absent')
        return {'step_id': 'D31', 'component_status': 'NOT_MEASURED',
                'default_row_status': 'NOT_MEASURED', 'completed': False,
                'reason': 'native report absent'}
    monkeypatch.setattr(flow109, '_retained_native_result', failed)
    if failure == 'exception':
        with pytest.raises(OSError, match='native executable absent'):
            run(tmp_path, args)
    else:
        assert run(tmp_path, args) == 2
    result = versions(tmp_path, 'D31')
    assert len(result) == 1
    answer = json.loads(result[0].read_text())
    assert answer['default_row_status'] == 'NOT_MEASURED'
    assert answer['reason'] == ('native executable absent' if failure == 'exception'
                                else 'native report absent')


def test_row_folders_are_published_verbatim_with_private_and_size_handling(tmp_path):
    project, dest = tmp_path / 'run', tmp_path / 'cell'
    native_case(project)
    assert run(project, case(project, 'D31')) == 0
    result = versions(project, 'D31')[0]
    folder = result.parent
    put(folder, 'outputs/public/report.json', {'errors': 0})
    put(folder, 'outputs/private/design.json', {'private': True})
    small = folder / 'outputs/public/design.def'
    small.write_text('VERSION 5.8 ;\n')
    large = folder / 'outputs/public/design.gds'
    with large.open('wb') as stream:
        stream.truncate(publish._SIZE_CEILING + 1)
    linked = folder / 'outputs/public/linked.def'
    linked.symlink_to(small)
    plan_path = project / 'reports/flow109/plan.json'
    plan = json.loads(plan_path.read_text())
    plan['rows'] = [row for row in plan['rows'] if row['id'] == 'D31']
    plan_path.write_text(json.dumps(plan))
    layouts = []
    summary = publish.publish_steps(project, dest, False, layout_out=layouts)
    relative = folder.relative_to(project)
    assert summary['n_steps'] == 1
    assert (dest / relative / 'result.json').read_bytes() == result.read_bytes()
    assert (dest / relative / 'outputs/public/report.json').is_file()
    assert (dest / relative / 'outputs/public/design.def').read_bytes() == small.read_bytes()
    assert not (dest / relative / 'outputs/private').exists()
    assert not (dest / relative / 'outputs/public/linked.def').exists()
    assert not (dest / relative / 'outputs/public/design.gds').exists()
    routed = next(record for record in layouts if record['decision'] == 'ROUTED_AWAY')
    assert routed['bytes'] == publish._SIZE_CEILING + 1
    assert routed['sha256'] == hashlib.sha256(large.read_bytes()).hexdigest()


def test_tool_writes_survive_a_later_tool_replacing_and_deleting_them(tmp_path, monkeypatch):
    args = case(tmp_path, 'D31')
    source = put(tmp_path, 'input/neutral.json', {'limit': 0})
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    calls = []
    def tool(project, context):
        script = '''import pathlib,sys
p=pathlib.Path(sys.argv[1]); p.mkdir(exist_ok=True)
(p/'native.rpt').write_text('errors='+sys.argv[2]+'\\n')
if sys.argv[2]=='0': (p/'extra.log').write_text('original log\\n')
elif (p/'extra.log').exists(): (p/'extra.log').unlink()
'''
        subprocess.run([sys.executable, '-c', script, str(project / 'shared'),
                        str(len(calls))], check=True)
        calls.append(context['resolved_row']['id'])
        return {'step_id': calls[-1], 'context_sha256': context['context_sha256'], 'component_status': 'PASS',
                'default_row_status': 'PASS', 'completed': True,
                'native_report': str(project / 'shared/native.rpt'),
                'inputs': [{'path': 'input/neutral.json', 'sha256': source_sha}]}
    monkeypatch.setattr(flow109, '_retained_native_result', tool)
    assert run(tmp_path, args) == 0
    results = versions(tmp_path, 'D31')
    assert len(results) == 1
    folder = results[0].parent
    original = tree_bytes(folder)
    assert (folder / 'outputs/shared/extra.log').read_text() == 'original log\n'
    assert run(tmp_path, case(tmp_path, 'D35')) == 0
    assert not (tmp_path / 'shared/extra.log').exists()
    assert run(tmp_path, args) == 0
    assert (tmp_path / 'shared/native.rpt').read_text() == 'errors=2\n'
    assert tree_bytes(folder) == original
    assert {'path': 'input/neutral.json', 'sha256': source_sha} in json.loads(
        (folder / 'inputs.json').read_text())
    assert all(row['path'] != 'shared/extra.log' for row in json.loads(
        (folder / 'inputs.json').read_text()))


def test_oversize_layout_is_listed_without_a_copy(tmp_path, monkeypatch):
    args = case(tmp_path, 'D31')
    def tool(project, context):
        path = project / 'native.odb'
        with path.open('wb') as stream:
            stream.truncate(publish._SIZE_CEILING + 1)
        return {'step_id': 'D31', 'context_sha256': context['context_sha256'], 'component_status': 'PASS',
                'default_row_status': 'PASS', 'completed': True}
    monkeypatch.setattr(flow109, '_retained_native_result', tool)
    assert run(tmp_path, args) == 0
    results = versions(tmp_path, 'D31')
    assert len(results) == 1
    folder = results[0].parent
    assert not (folder / 'outputs/native.odb').exists()
    listed = next(row for row in json.loads((folder / 'outputs.json').read_text())['outputs']
                  if row.get('path') == 'native.odb')
    assert listed['bytes'] == publish._SIZE_CEILING + 1
    assert listed['sha256'] == hashlib.sha256((tmp_path / 'native.odb').read_bytes()).hexdigest()


@pytest.mark.parametrize('entry,exit_', [('D31', 'D32'), ('A04', 'A05')])
def test_native_windows_capture_before_the_next_row_overwrites_a_report(tmp_path, entry, exit_):
    args = case(tmp_path, entry)
    if entry.startswith('A'):
        features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                        if p['name'] == 'Analog IC external trim')
        put(tmp_path, 'selection.json', {'features': features})
    args.exit_step = exit_
    def native(selected):
        assert selected.entry_step == selected.exit_step
        report = tmp_path / 'native.rpt'
        report.write_text(selected.entry_step)
        put(tmp_path, f'reports/flow109/default_rows/{selected.entry_step}.json', {
            'step_id': selected.entry_step, 'component_status': 'PASS',
            'default_row_status': 'PASS', 'completed': True})
        return 0
    assert flow109.run_rows(args, tmp_path, native) == 0
    first = versions(tmp_path, entry)
    assert len(first) == 1
    assert (first[0].parent / 'outputs/native.rpt').read_text() == entry
    assert (tmp_path / 'native.rpt').read_text() == exit_


def test_inputs_are_only_paths_already_exposed_in_row_result(tmp_path, monkeypatch):
    args = case(tmp_path, 'D31')
    source = put(tmp_path, 'input/neutral.json', {'limit': 0})
    unreported = put(tmp_path, 'input/unreported.json', {'read': True})
    report = tmp_path / 'answer.rpt'
    report.write_text('errors=0\n')
    original_source = hashlib.sha256(source.read_bytes()).hexdigest()
    original_report = hashlib.sha256(report.read_bytes()).hexdigest()
    def native(project, context):
        assert json.loads(source.read_text())['limit'] == 0
        assert json.loads(unreported.read_text())['read'] is True
        assert report.read_text() == 'errors=0\n'
        return {'step_id': 'D31', 'context_sha256': context['context_sha256'],
                'component_status': 'PASS', 'default_row_status': 'PASS', 'completed': True,
                'native_report': str(report),
                'inputs': [{'path': 'input/neutral.json', 'sha256': original_source}]}
    monkeypatch.setattr(flow109, '_retained_native_result', native)
    assert run(tmp_path, args) == 0
    result = versions(tmp_path, 'D31')[0]
    folder = result.parent
    assert (folder / 'outputs/answer.rpt').read_text() == 'errors=0\n'
    assert json.loads((folder / 'inputs.json').read_text()) == [
        {'path': 'answer.rpt', 'sha256': original_report},
        {'path': 'input/neutral.json', 'sha256': original_source}]
    assert not (folder / 'outputs/input/unreported.json').exists()


@pytest.mark.parametrize('step,answer', [
    ('D22', 'phase3/librelane/02-yosys-synthesis/state_out.json'),
    ('D25', None),
    ('D26', 'phase3/librelane/prelayout/design_sdc/02-openroad-staprepnr/state_out.json')])
def test_native_frontend_inputs_and_answer_files_are_retained(tmp_path, step, answer):
    from test_flow109_retained_frontend import case as frontend_case
    args, _ = frontend_case(tmp_path, step)
    assert run(tmp_path, args) == 0
    results = versions(tmp_path, step)
    assert len(results) == 1
    folder = results[0].parent
    inputs = {r['path'] for r in json.loads((folder / 'inputs.json').read_text())}
    assert inputs == ({answer} if answer else set())
    if answer:
        assert (folder / 'outputs' / answer).read_bytes() == (tmp_path / answer).read_bytes()
    else:
        native_report = 'reports/flow109/components/D25-native.json'
        assert (folder / 'outputs' / native_report).read_bytes() == (tmp_path / native_report).read_bytes()


@pytest.mark.parametrize('value', [None, '{', '[]'])
def test_row_wrapper_preserves_manifest_refusal(tmp_path, value):
    args = case(tmp_path, 'D31')
    if value is None:
        args.flow109_manifest = None
    else:
        args.flow109_manifest.write_text(value)
    with pytest.raises(flow109.Flow109Error, match='FLOW109_MANIFEST_(REQUIRED|INVALID)'):
        flow109.run_rows(args, tmp_path, lambda _: pytest.fail('invalid selection ran'))


def test_lingering_child_cannot_append_to_a_finished_row(tmp_path, monkeypatch):
    import step_output_collector as collector
    args = case(tmp_path, 'D31')
    source = put(tmp_path, 'input/later.json', {'later': True})
    trigger = tmp_path / 'read-after-row'
    children = []
    def native(project, context):
        script = '''import sys,time
sys.path.insert(0,sys.argv[1])
import step_output_collector
from pathlib import Path
while not Path(sys.argv[2]).exists(): time.sleep(0.01)
Path(sys.argv[3]).read_text()
'''
        children.append(subprocess.Popen([sys.executable, '-c', script,
            str(Path(collector.__file__).parent), str(trigger), str(source)]))
        return {'step_id': 'D31', 'context_sha256': context['context_sha256'],
                'component_status': 'PASS', 'default_row_status': 'PASS', 'completed': True}
    monkeypatch.setattr(flow109, '_retained_native_result', native)
    try:
        assert run(tmp_path, args) == 0
        results = versions(tmp_path, 'D31')
        assert len(results) == 1
        folder = results[0].parent
        before = tree_bytes(folder)
        trigger.touch()
        assert children[0].wait(timeout=5) == 0
        assert tree_bytes(folder) == before
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)


@pytest.mark.parametrize('cited', [False, True])
def test_scan_census_does_not_capture_files_unless_actual_evidence_cites_them(tmp_path, cited):
    import step_output_collector as collector
    native = put(tmp_path, 'reports/native.json', {'measured': 0})
    inspected = put(tmp_path, 'input/inspected.json', {'provenance': 'transport fixture'})
    record = {'result_file': str(native), 'native': {
        'documents_scanned': [str(inspected), {'path': str(inspected),
            'sha256': hashlib.sha256(inspected.read_bytes()).hexdigest()}]}}
    if cited:
        record['native']['derived_answers'] = {'evidence': str(inspected)}
    known = dict(collector._known_files(tmp_path, record))
    assert known['reports/native.json'] == hashlib.sha256(native.read_bytes()).hexdigest()
    assert ('input/inspected.json' in known) is cited
    assert json.loads(inspected.read_text()) == {'provenance': 'transport fixture'}
