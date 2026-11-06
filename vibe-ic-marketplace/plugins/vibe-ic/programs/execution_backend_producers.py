"""Native backend tools called through the general runner's current State."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import re
import shutil
import vibeic_temp as tempfile
import time

from _atomic_artefact import write_json
from librelane_contract import Refusal

PNR = 'phase3/stage3/pnr/'
RPT = 'reports/phase3/'

NATIVE_STEP_NAMES = {
    '18': 'spare_cells_and_eco_preparation',
    '27': 'candidate_signal_integrity',
    '30': 'post_layout_spice_correlation',
    '25': 'candidate_electromigration',
    '28': 'candidate_reliability_and_esd',
    'D66': 'final_perc_esd_and_latch_up',
}


def _step30_parallel_instruments(simulators, run_one):
    """Run distinct Step30 instruments and collect every sibling outcome.

    A single worker may refuse, time out, or raise after another worker has
    already measured a FAIL.  Collection therefore records that sibling as
    NOT_MEASURED and continues until every future has been reaped; callers can
    preserve the measured FAIL through the joint consumer.
    """
    names = tuple(simulators)
    if not names:
        return {}
    results = {}
    pool = ThreadPoolExecutor(max_workers=len(names),
                              thread_name_prefix='step30-instrument')
    try:
        futures = {pool.submit(run_one, name): name for name in names}
        for future in as_completed(futures):
            name = futures[future]
            started = time.monotonic_ns()
            try:
                value = future.result()
            except Exception as exc:  # preserve sibling evidence
                value = {'verdict': 'NOT_MEASURED',
                         'reason': type(exc).__name__ + ': ' + str(exc)}
            if isinstance(value, dict):
                value.setdefault('lifecycle', {})
                value['lifecycle'].setdefault('collector_pid', os.getpid())
                value['lifecycle'].setdefault('collected_ns', time.monotonic_ns())
                value['lifecycle'].setdefault('future_started_ns', started)
            results[name] = value
    finally:
        # Cancel work that has not entered a worker and wait for every running
        # sibling's supervised container to reach its terminal record.
        pool.shutdown(wait=True, cancel_futures=True)
    return {name: results[name] for name in names}


def _step30_rebind_private(value, private_project, project, simulator):
    """Translate private-project paths to retained canonical paths."""
    private_project, project = Path(private_project).resolve(), Path(project).resolve()
    arm = Path('phase3/tool_arms/30') / simulator
    if isinstance(value, Path):
        value = str(value)
    if isinstance(value, list):
        return [_step30_rebind_private(item, private_project, project, simulator) for item in value]
    if isinstance(value, tuple):
        return [_step30_rebind_private(item, private_project, project, simulator) for item in value]
    if isinstance(value, dict):
        return {key: _step30_rebind_private(item, private_project, project, simulator)
                for key, item in value.items()}
    if not isinstance(value, str) or not value.startswith('/'):
        return value
    candidate = Path(value)
    try:
        relative = candidate.resolve().relative_to(private_project)
    except (OSError, ValueError):
        return value
    destination = project / arm / relative.relative_to(arm) if relative.parts[:len(arm.parts)] == arm.parts else project / relative
    return str(destination)


def _step30_rebase_project_paths(private_project, original_project):
    """Rebase copied state manifests before any post-PNR consumer reads them."""
    private_project = Path(private_project).resolve()
    original_project = Path(original_project).resolve()

    def translate(value):
        if isinstance(value, list):
            return [translate(item) for item in value]
        if isinstance(value, dict):
            return {key: translate(item) for key, item in value.items()}
        if isinstance(value, str) and value.startswith('/'):
            try:
                relative = Path(value).resolve().relative_to(original_project)
            except (OSError, ValueError):
                return value
            return str(private_project / relative)
        return value

    for manifest in private_project.rglob('*.json'):
        try:
            before = json.loads(manifest.read_text())
            after = translate(before)
        except (OSError, ValueError):
            continue
        if after != before:
            write_json(manifest, after)


def _step30_retain_document(project, private_project, simulator, document):
    """Copy a private arm before TemporaryDirectory cleanup and validate paths."""
    source = Path(private_project) / 'phase3/tool_arms/30' / simulator
    target = Path(project) / 'phase3/tool_arms/30' / simulator
    if source.is_dir():
        shutil.copytree(source, target, symlinks=False, dirs_exist_ok=True)
    retained = _step30_rebind_private(document, private_project, project, simulator)
    missing = []

    def visit(value):
        if isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, str) and value.startswith('/'):
            path = Path(value)
            if not path.is_file() and ('/phase3/' in value or '/reports/' in value or value.endswith(('.sp', '.spef', '.rpt', '.v', '.sdc'))):
                missing.append(value)
    visit(retained)
    if missing:
        raise Refusal('STEP30_RETAINED_ARTIFACT_ABSENT',
                         'inspected retained artifact paths: ' + repr(sorted(set(missing))))
    return retained


def _step30_private_projects(project, simulators, run_one):
    """Give concurrent instrument runs private report/output populations."""
    with tempfile.TemporaryDirectory(prefix='step30-instruments-') as folder:
        root = Path(folder)
        private = {}
        for simulator in simulators:
            target = root / simulator
            shutil.copytree(project, target, symlinks=False)
            _step30_rebase_project_paths(target, project)
            private[simulator] = target
        return _step30_parallel_instruments(
            simulators, lambda simulator: run_one(simulator, private[simulator]))


def _step30_merge_parallel(project, results, simulators, spice):
    """Merge private native documents before the mandatory joint consumer."""
    judgments = {}
    paths = {}
    details = {}
    for simulator in simulators:
        document = results.get(simulator)
        if not isinstance(document, dict):
            document = {'verdict': 'NOT_MEASURED', 'reason': 'instrument document absent'}
        judgment = (document.get('arms') or {}).get(simulator)
        if document.get('verdict') == 'FAIL':
            judgment = {**(judgment or {}), 'verdict': 'FAIL'}
        judgments[simulator] = judgment or {'verdict': 'FAIL' if document.get('verdict') == 'FAIL' else 'NOT_MEASURED',
                                             'reason': document.get('reason', 'instrument document absent')}
        detail = dict((document.get('detail') or {}).get(simulator) or {})
        if document.get('lifecycle'):
            detail['lifecycle'] = document['lifecycle']
        details[simulator] = detail
        paths[simulator] = (detail.get('base') or {}).get('paths') or []
    seed = next((results[name] for name in simulators if 'arms' in results[name]),
                results[simulators[0]])
    merged = dict(seed)
    merged['arms'] = judgments
    merged['detail'] = details
    merged.update(spice.step_verdict(judgments, paths))
    merged['mode'] = 'ultra'
    merged['instruments_concurrent'] = list(simulators)
    write_json(project / RPT / 'spice_path_tool.json', merged)
    return merged


def _require(path):
    p = Path(path)
    if not p.is_file() or not p.stat().st_size:
        raise Refusal('BACKEND_PRODUCER_INPUT_ABSENT', str(p))
    return p


def _copy(source, target):
    source = _require(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def _handoff(project, ll, folder, names):
    target = {view: project / name for view, name in names.items()}
    return ll.handoff_to_direct(folder / 'state_out.json', target,
               project / RPT / ('execution-backend-' + folder.parent.name + '-handoff.json'))


def _logs(project, folders, name='openroad.log'):
    target = project / PNR / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(''.join('# ' + str(f.relative_to(project)) + '/' + p.name + '\n' +
                     p.read_text(errors='replace') + '\n' for f in folders for p in sorted(f.glob('*.log'))))
    return target


def _d39_parse_repair_history(text):
    """Read complete native setup/hold progress, never count STA corners.

    Setup uses reported committed move counters; hold uses the native
    inserted-buffer delta that determines its progress flag. Sparse/truncated
    traces remain unmeasured. No numeric acceptance limit is chosen here.
    """
    phases, table, pending = {}, None, None
    setup_rows, hold_rows = {}, []
    error = None
    try:
        for line in text.splitlines():
            if re.search(r'\bNo setup violations found\b', line):
                phases['setup'] = {'complete': True, 'rows': [], 'stagnation_iterations': 0,
                                   'basis': 'native explicit absence of setup violations'}
            if re.search(r'\bNo hold violations found\b', line):
                phases['hold'] = {'complete': True, 'rows': [], 'stagnation_iterations': 0,
                                  'basis': 'native explicit absence of hold violations'}
            columns = [part.strip() for part in line.split('|')]
            if len(columns) > 6 and columns[0] in ('Iter', 'Iteration'):
                table = 'setup' if 'Removed' in columns else 'hold'
                continue
            if 'repair_hold' in line:
                match = re.search(r'\bpass (\d+) hold slack \S+ setup slack \S+', line)
                if match:
                    if pending is not None:
                        raise ValueError('hold progress delta absent')
                    pending = int(match[1])
                match = re.search(r'\binserted (\d+)\s*$', line)
                if match:
                    if pending is None or (hold_rows and pending <= hold_rows[-1]['native_pass']):
                        raise ValueError('hold progress order is not current')
                    hold_rows.append({'native_pass': pending, 'inserted_buffers': int(match[1])})
                    pending = None
            setup_label = re.fullmatch(r'(\d+)[A-Za-z]?', columns[0])
            if table == 'setup' and len(columns) > 6 and setup_label:
                number = int(setup_label[1])
                moves = [int(value) for value in columns[1:6]]
                if any(value < 0 for value in moves) or number < max(setup_rows, default=0):
                    raise ValueError('setup progress order/counters invalid')
                setup_rows[number] = moves
            if table and columns[0] == 'final':
                if table == 'setup':
                    if (not setup_rows or sorted(setup_rows) != list(range(max(setup_rows) + 1))
                            or [int(v) for v in columns[1:6]] != setup_rows[max(setup_rows)]):
                        raise ValueError('setup iteration population is incomplete')
                    run = longest = 0
                    previous = None
                    for number, moves in sorted(setup_rows.items()):
                        if previous is not None:
                            if any(a < b for a, b in zip(moves, previous)):
                                raise ValueError('setup cumulative move counters decreased')
                            run = run + 1 if moves == previous else 0
                            longest = max(longest, run)
                        previous = moves
                    phases['setup'] = {'complete': True,
                        'rows': [{'native_iteration': n, 'committed_moves': m} for n, m in sorted(setup_rows.items())],
                        'stagnation_iterations': longest,
                        'basis': 'consecutive native iterations with unchanged committed move counters'}
                else:
                    if not hold_rows or pending is not None:
                        raise ValueError('hold iteration population is incomplete')
                    run = longest = 0
                    for index, row in enumerate(hold_rows):
                        if row['inserted_buffers'] == 0 and index + 1 < len(hold_rows):
                            raise ValueError('native hold loop continued after its no-progress stop')
                        run = run + 1 if row['inserted_buffers'] == 0 else 0
                        longest = max(longest, run)
                    phases['hold'] = {'complete': True, 'rows': hold_rows,
                        'stagnation_iterations': longest, 'basis': 'native hold inserted-buffer progress flag'}
                table = None
        if set(phases) != {'setup', 'hold'} or pending is not None:
            raise ValueError('both native repair phases must close')
    except (ValueError, TypeError) as exc:
        error = str(exc)
    result = {'status': 'NOT_MEASURED' if error else 'MEASURED', 'phases': phases}
    if error:
        result['reason'] = error
    else:
        result['value'] = max(p['stagnation_iterations'] for p in phases.values())
        result['unit'] = 'count'
    return result


def _d38_sink_report_tcl():
    """Read-only census in the existing STAMidPNR post-load report callback.

    Reuse D34's OpenSTA sink grammar and query; also enumerate ALL register
    clock pins so an unreached pin cannot vanish from the observation.
    """
    return '\n'.join([
        'puts "CLOCK_PLAN_ROSTER_BEGIN"',
        'set d38_all [all_registers -clock_pins]',
        'foreach p $d38_all {puts "CLOCK_PLAN_ALL_SINK [get_full_name $p]"}',
        'puts "CLOCK_PLAN_ALL_SINK_COUNT [llength $d38_all]"',
        'foreach c [all_clocks] {',
        '  set sources [get_full_name [get_property $c sources]]',
        '  puts "CLOCK_PLAN_NATIVE [get_full_name $c]|[get_property $c period]|$sources"',
        '  set pins [all_registers -clock $c -clock_pins]',
        '  foreach p $pins {puts "CLOCK_PLAN_SINK [get_full_name $c]|[get_full_name $p]"}',
        '  puts "CLOCK_PLAN_SINK_COUNT [get_full_name $c]|[llength $pins]"',
        '}',
        'puts "CLOCK_PLAN_DONE"', ''])


def _d38_sink_report_config(ll, config):
    """Use the native report callback only for this row's measurement config."""
    config = Path(config)
    body = json.loads(config.read_text())
    script = config.parent / 'cts_sink_roster.tcl'
    existing = body.get('STA_EXTRA_CORNER_TCL_FILE')
    # Preserve another owner's custom callback instead of replacing it or
    # silently claiming this measurement ran. No shared helper is changed.
    if existing and (Path(existing) != script or not script.is_file()
                     or script.read_text() != _d38_sink_report_tcl()):
        raise Refusal('D38_NATIVE_REPORT_CALLBACK_ALREADY_BOUND', str(existing))
    script.write_text(_d38_sink_report_tcl())
    return ll.derive_step_config(config, config, {
        'STA_EXTRA_CORNER_TCL_FILE': (str(script),
            'row59 complete clock-reached sink-pin roster in the actual post-load native session')})


def _d41_filler_roster(path, patterns):
    """Read the selected native ODB in-process; this does not run an engine."""
    import fnmatch
    import odb
    database = odb.dbDatabase.create()
    try:
        odb.read_db(database, str(path))
        block = database.getChip().getBlock()
        return [{'instance':inst.getName(), 'master':inst.getMaster().getName(),
                 'type':str(inst.getMaster().getType()), 'status':str(inst.getPlacementStatus()),
                 'location':list(inst.getLocation()), 'orient':str(inst.getOrient())}
            for inst in sorted(block.getInsts(), key=lambda i:i.getName())
            if str(inst.getMaster().getType()) == 'CORE_SPACER'
            or any(fnmatch.fnmatchcase(inst.getMaster().getName(), pattern) for pattern in patterns)]
    finally:
        odb.dbDatabase.destroy(database)


def _d39_capture_repair_history(project, folder, initial, config):
    folder, project = Path(folder), Path(project)
    log = folder / 'invocation.log'
    record = {'native_step': 'OpenROAD.ResizerTimingPostCTS',
              'state': str(folder / 'state_out.json'), 'log': str(log),
              'initial_state': str(initial), 'config': str(config),
              'observation': _d39_parse_repair_history(log.read_text())}
    output = project / RPT / 'pnr/post_cts_repair_history.json'
    write_json(output, record)
    return {'path': str(output.relative_to(project))}


def _native_tool(name):
    from flow_engine import TABLE, read_json
    row = next(row for row in read_json(TABLE)['steps'] if row['name'] == name)
    tool = row['tool']
    candidates = ([profile['tool'] for profile in tool['profiles']
                   if profile['tool']['kind'] == 'librelane']
                  if tool['kind'] == 'profiles' else [tool] if tool['kind'] == 'librelane' else [])
    if len(candidates) != 1:
        raise ValueError(f'{name}: expected one native tool in the canonical step table')
    return candidates[0]


def produce(project, params):
    """Execute the selected native backend tool in the general runner's chain."""
    from dataclasses import asdict
    from flow_engine import NativeChain, read_json, select_route
    from librelane.state import State

    project = Path(project).resolve()
    name = str(params.get('name') or params.get('step_id') or '')
    name = NATIVE_STEP_NAMES.get(name, name)
    tool = _native_tool(name)
    chain = params.get('native_chain')
    if chain is None:
        chain = NativeChain(project, params.get('route') or select_route(project), pdk=params.get('pdk_name'))
        error = chain.prepare()
        if error is not None:
            result = chain.preparation_result()
            return {**asdict(result), 'verdict': 'NOT_MEASURED'}
        state_path = params.get('state_path')
        if state_path:
            from librelane_contract import project_path
            chain.state = State.load(read_json(project_path(project, state_path)))
    directory = Path(params['directory'])
    directory.mkdir(parents=True, exist_ok=True)
    result = chain.execute(directory, tool)
    status = 'NOT_MEASURED' if not result.ran else 'FAIL' if result.exit_code else 'PASS'
    if any(row.get('status') == 'NOT_MEASURED' or not row.get('ran')
           for row in result.native_steps):
        status = 'FAIL' if result.exit_code else 'NOT_MEASURED'
    return {**asdict(result), 'verdict': status}
