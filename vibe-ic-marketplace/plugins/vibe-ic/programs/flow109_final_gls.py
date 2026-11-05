"""Replay the declared L10 scenarios against every final native STA SDF.

The existing arithmetic emitter schedules observations at STA's required
output time. LibreLane's GateLevelSim executes Icarus/vvp, and its existing
transcript reader measures annotation and functional errors.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import time
import json
from pathlib import Path
import re
import shutil
import sys
from types import SimpleNamespace
import uuid

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _atomic_artefact import write_json, write_text
import sdf_gate_sim as sgs


class NativeResultError(ValueError):
    def __init__(self, code, detail, *, status='NOT_MEASURED'):
        self.code, self.status = code, status
        super().__init__(f'{code}: {detail}')


SCHEMA = 'vibeic.flow109.final-gls.v1'
SUPPORTED_REQUIRED_BEHAVIORS = frozenset({'sdf_delay_annotation', 'functional_self_check'})
LIMITATIONS = [
    'Icarus/vvp only; no alternate or commercial simulator result is implied.',
    'Only observed SDF delay application and declared self-checking functional scenarios are accepted.',
    'Setup/hold, recovery/removal, width/period, pulse rejection, min/typ/max sweep semantics and other timing checks are not qualified by this component.',
    'The native result covers the declared corner/scenario functional replay; device timing-check semantics remain outside Icarus scope.',
]
IDENT = re.compile(r'[A-Za-z_][A-Za-z0-9_$]*\Z')


def _read(path, code='D71_INPUT_INVALID'):
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise NativeResultError(code, str(path)) from exc
    if not isinstance(value, dict):
        raise NativeResultError(code, str(path))
    return value


def _bound(project, value, code='D71_INPUT_UNAVAILABLE'):
    from librelane_contract import project_path
    value = value.get('path') if isinstance(value, dict) else value
    if not isinstance(value, str) or not value:
        raise NativeResultError(code, str(value))
    path = project_path(Path(project), value)
    if not path.is_file():
        raise NativeResultError(code, str(path))
    return path


def _record(project, path):
    path = Path(path).resolve()
    return {'path': str(path.relative_to(project)) if path.is_relative_to(project) else str(path)}


def _sdf_census(path, top):
    text = Path(path).read_text(errors='replace')
    if text.count('(') != text.count(')') or not re.search(r'\(SDFVERSION\s+"3\.0"\)', text):
        raise NativeResultError('D71_FINAL_SDF_CORRUPT', str(path))
    design = re.search(r'\(DESIGN\s+"([^"]+)"\)', text)
    if not design or design.group(1) != top:
        raise NativeResultError('D71_FINAL_SDF_WRONG_NETLIST', str(path))
    cells = len(re.findall(r'\(CELL\s*(?=\()', text))
    delays = len(re.findall(r'\((?:IOPATH|INTERCONNECT)\b', text))
    if not re.search(r'\(TIMESCALE\s+[^)]+\)', text) or not cells or not delays:
        raise NativeResultError('D71_FINAL_SDF_INCOMPLETE', str(path))
    return {'sdfversion': '3.0', 'design': top, 'cells': cells, 'delay_records': delays}


ENGINEERING_SCOPE = 'engineering_native_component'


def engineering_bench_text(project, source, module, top, *, observation_schedule=None,
                           netlist=None, sdc=None, sdfs=None, sta_step_dir=None):
    """Existing arithmetic emitter owns any final-SDF observation rescheduling."""
    text = Path(source).read_text()
    instance = sgs._tb_dut_instance(text, top)
    if not instance:
        raise NativeResultError('D71_SCENARIO_INVALID', 'actual native top instance absent')
    observation = None
    if observation_schedule is not None:
        if observation_schedule != 'native_sta_output_deadline':
            raise NativeResultError('D71_OBSERVATION_UNSUPPORTED', str(observation_schedule))
        import arith_oracle_tb_gen as arith
        plan = arith._scenario_header(Path(source))
        if plan is None:
            raise NativeResultError('D71_EXISTING_ARITHMETIC_PRODUCER_REQUIRED', str(source))
        declared = sgs.declared_dut_binding(Path(project), plan['spec']['top'], Path(netlist).read_text())
        deadline = sgs._postlayout_output_deadline(Path(project), plan, declared,
                                                  Path(netlist), Path(sdc), list(sdfs or []),
                                                  sta_step_dir=sta_step_dir)
        updated = json.loads(json.dumps(plan))
        updated['observation'].update(sample_offset_ns=deadline['sample_offset_ns'],
                                      postlayout_deadline=deadline)
        text = arith.emit_arithmetic_scenario_module(module, updated, dut_module=top)
        observation = {'original': plan['observation'], 'final': updated['observation'],
                       'framing': plan['framing'], 'transactions': plan['transactions'],
                       'comparisons': plan['comparisons'],
                       'producer': 'arith_oracle_tb_gen.emit_arithmetic_scenario_module'}
    return sgs.inject_sdf_annotation(text, module, instance, sgs.SDF_PLACEHOLDER), observation


def prepare(project, context):
    """Prepare the executed L10 population against the native final STA State."""
    import librelane_contract as contract
    import librelane_postroute as postroute
    import arith_oracle_tb_gen as arith
    project = Path(project).resolve()
    folder, state = postroute.stapostpnr_state(project)
    config = _read(folder / 'config.json')
    top = config['DESIGN_NAME']
    chip = project / sgs.CHIP_TOP_RECORD_REL
    logical_top = _read(chip).get('core_module', top) if chip.is_file() else top
    netlist, sdc = Path(state['nl']), Path(state['sdc'])
    sdfs = postroute.corner_sdfs(state)
    corners = config.get('STA_CORNERS') or list(sdfs)
    if set(corners) != set(sdfs):
        raise ValueError('Native STA configuration and SDF corner population differ')
    suite = sgs.find_l10_executed_cases(project, logical_top)
    if not suite or not suite.get('cases') or suite.get('skipped'):
        raise ValueError('The declared L10 population is not fully executable: ' + str(suite))
    image = contract.resolve_image(project)
    root = contract.resolve_pdk_root(project, config['PDK'], image=image)
    mounts = [(Path(root) / config['PDK'], '/pdk/' + config['PDK']),
              (Path(root) / config['PDK'], str(Path(config['PDK_ROOT']) / config['PDK']))] if root else []
    models = []
    for key in ('CELL_VERILOG_MODELS', 'PAD_VERILOG_MODELS', 'EXTRA_VERILOG_MODELS'):
        for value in config.get(key) or []:
            asset = contract.resolve_state_pdk_asset(value, pdk=config['PDK'], mounts=mounts)
            if asset is None:
                raise ValueError('Native model is unavailable: ' + str(value))
            models.append(asset)
    used = sgs.netlist_used_cells(netlist.read_text())
    closure = sgs.verilog_model_closure(models, used)
    models = list(map(Path, closure['files']))
    declared = sgs.declared_dut_binding(project, logical_top, netlist.read_text())
    clocks = sgs.declared_sdc_clocks(sdc, [p.read_text() for p in sdfs.values()])
    out = project / 'reports/flow109/D71' / ('benches-' + uuid.uuid4().hex)
    out.mkdir(parents=True)
    cases = []
    for case in suite['cases']:
        text, observation = sgs._bound_arithmetic_case(project, case, logical_top, declared,
            list(map(str, models)), netlist=netlist, sdc=sdc, sdfs=list(sdfs.values()),
            sta_step_dir=folder, pdk_mounts=mounts,
            existing_plan=arith._scenario_header(Path(case['path'])))
        source = out / (case['id'] + '.source.v')
        write_text(source, text)
        text, final_observation = engineering_bench_text(project, source, case['module'], logical_top,
            observation_schedule='native_sta_output_deadline' if arith._scenario_header(source) else None,
            netlist=netlist, sdc=sdc, sdfs=list(sdfs.values()), sta_step_dir=folder)
        text, binding = sgs.bind_dut_module(text, logical_top, case['dut_instance'], netlist.read_text(), declared)
        text, clock = sgs.bind_bench_clock(text, case['dut_instance'], clocks)
        bench = out / (case['id'] + '.v')
        write_text(bench, text)
        cases.append({'id': case['id'], 'module': case['module'], 'testbench': str(bench),
                      'observation': final_observation or observation, 'binding': binding, 'clock': clock})
    return {'engineering': False, 'manifest': {'case_workers': 4}, 'top': top,
        'netlist': netlist, 'sdc': sdc, 'sdfs': sdfs,
        'sdf_census': {c: _sdf_census(p, top) for c, p in sdfs.items()},
        'requirements': {'required_corners': list(corners), 'required_scenarios': [c['id'] for c in cases]},
        'cases': cases, 'models': models, 'model_closure': closure,
        'inputs': {}}


def engineering_transcript_readback(step_dir, judged):
    """Reuse the original case scorer; measured arithmetic FAIL outranks no marker."""
    from full_stack_functional_tb import score_transcript, FAILED
    runs = _read(Path(step_dir) / 'gls_runs.json')
    evidence = []
    for run in runs.get('runs') or []:
        path = Path(run['stdout'])
        text = path.read_text(errors='replace') if path.is_file() else ''
        scored = score_transcript(run['case'], run.get('sim_rc'), text)
        row = {'corner': run['corner'], 'scenario': run['case'],
               'source_self_check': scored, 'stdout': str(path),
               'timingcheck_unsupported': len(re.findall(r'^SDF WARNING:.*TIMINGCHECK not supported', text, re.M))}
        evidence.append(row)
        if scored.get('state') == FAILED:
            corner = judged['corners'][run['corner']]
            for case in corner['cases']:
                if case['id'] == run['case']:
                    case.update(verdict='FAIL', source_self_check=scored)
            corner['verdict'] = 'FAIL'
            reasons = set(corner.get('reasons', [])) | {'CASE_FAIL'}
            if all(case.get('verdict') is not None for case in corner['cases']):
                reasons.discard('NOT_EXECUTED')
            corner['reasons'] = sorted(reasons)
            judged['verdict'] = 'FAIL'
    judged['existing_case_readback'] = evidence
    return judged


def _publish(project, prepared, judged, attempt):
    publication_root = attempt / 'engineering' if prepared.get('engineering') else project
    sim_dir = publication_root / 'phase3/stage3/sim_postlayout'
    sim_dir.mkdir(parents=True, exist_ok=True)
    copied = {}
    for corner, source in prepared['sdfs'].items():
        target = sim_dir / f"{prepared['top']}__final__{corner}.sdf"
        shutil.copyfile(source, target)
        copied[corner] = _record(project, target)
    lines = ['Final SDF-annotated gate-level replay (Flow109 D71)',
             f"design           : {prepared['top']}",
             'sdf source       : final OpenROAD.STAPostPNR State',
             f"compile flags    : {judged.get('compile_flags')}",
             f"required corners : {', '.join(prepared['requirements']['required_corners'])}",
             f"required cases   : {', '.join(prepared['requirements']['required_scenarios'])}", '']
    rows = []
    for corner, result in sorted((judged.get('corners') or {}).items()):
        lines.append(f"-- final corner {corner}: $sdf_annotate(\"{copied[corner]['path']}\") --")
        lines.append(f"sdf annotation: {result.get('delays_applied')} delay(s) applied, "
                     f"{result.get('sdf_errors')} SDF error record(s)")
        for case in result.get('cases') or []:
            rows.append({'corner': corner, **case})
            lines.append(f"  {case['id']:<40} {case.get('verdict') or 'NOT_EXECUTED'}")
        if result.get('verdict') != 'PASS':
            lines.append(f"ERROR: final corner {corner} {result.get('verdict')}: "
                         + ', '.join(result.get('reasons') or []))
        lines.append('')
    lines.append(f"VERDICT: {judged.get('verdict')}")
    write_text(sim_dir / 'results.log', '\n'.join(lines) + '\n')
    expected = {(corner, case) for corner in prepared['requirements']['required_corners']
                for case in prepared['requirements']['required_scenarios']}
    observed = {(row['corner'], row['id']) for row in rows}
    population = {'required': [{'corner': c, 'scenario': s} for c, s in sorted(expected)],
                  'observed': [{'corner': c, 'scenario': s} for c, s in sorted(observed)],
                  'missing': [{'corner': c, 'scenario': s} for c, s in sorted(expected - observed)],
                  'all_functional_pass': bool(rows) and all(row.get('verdict') == 'PASS' for row in rows),
                  'all_corners_annotated': bool(judged.get('corners')) and all(
                      value.get('delays_applied', 0) > 0 for value in judged['corners'].values())}
    doc = {'schema': SCHEMA, 'program': 'flow109_final_gls', 'step_id': 'D71',
           'verdict': judged.get('verdict'), 'annotation_population': population,
           'final_sdfs': copied,
           'native_step': _record(project, attempt / 'native/gls_runs.json'),
           'limitations': LIMITATIONS, 'judge': judged,
           'execution_scope': ENGINEERING_SCOPE if prepared.get('engineering') else 'final_gls_component',
           'full_row_acceptance': judged.get('verdict')}
    write_json(sim_dir / 'results.json', doc)
    flag = sim_dir / 'pass.flag'
    if (not prepared.get('engineering') and judged.get('verdict') == 'PASS' and not population['missing']
            and population['all_functional_pass'] and population['all_corners_annotated']):
        write_text(flag, f"PASS {len(expected)} final corner/scenario observation(s)\n")
    elif flag.exists():
        flag.unlink()
    checker = {'verdict': judged.get('verdict')}
    doc['results_log'] = _record(project, sim_dir / 'results.log')
    doc['results_json'] = _record(project, sim_dir / 'results.json')
    return doc, checker


def run_native_cases(step, state, manifest, *, workers=1, native_run=None):
    """Bound independent existing GateLevelSim calls; only this thread publishes the index."""
    if type(workers) is not int or not 1 <= workers <= 4:
        raise NativeResultError('D71_CASE_WORKERS_INVALID', str(workers))
    from librelane.state import DesignFormat
    from librelane.steps import StepError
    from librelane_plugin_vibeic import GateLevelSim
    native_run = native_run or GateLevelSim.run
    root = Path(step.step_dir)
    cases = sorted(manifest['cases'], key=lambda case: case['id'])
    if len({case['id'] for case in cases}) != len(cases):
        raise NativeResultError('D71_DUPLICATE_CASE', 'native output ownership must be unique')
    sdfs = state[DesignFormat.SDF]
    jobs = [(corner, case) for corner in sorted(sdfs) for case in cases]

    def one(job):
        corner, case = job
        folder = root / 'case_runs' / corner / case['id']
        folder.mkdir(parents=True, exist_ok=False)
        manifest_path = folder / 'manifest.json'
        write_json(manifest_path, {**manifest, 'cases': [case]})
        child = SimpleNamespace(config={**step.config, 'VIBEIC_GLS_MANIFEST': str(manifest_path)},
                                step_dir=str(folder), _run=step._run)
        child_state = {**state, DesignFormat.SDF: {corner: sdfs[corner]}}
        started = time.time_ns(); argv_calls = []
        def logged_run(argv, log, limit, cwd=None):
            resources = str(log) + '.resources.txt'
            # The native runner owns child accounting, cwd, timeout, logs and rc.
            call = {'argv': list(argv), 'executed_argv': list(argv), 'log': str(log),
                    'cwd': str(cwd) if cwd else None, 'resources': resources}
            argv_calls.append(call)
            rc = step._run(argv, log, limit, cwd=cwd)
            call['returncode'] = rc
            return rc
        child._run = logged_run
        try:
            try: native_run(child, child_state)
            except StepError:
                if _read(folder / 'gls_results.json').get('verdict') != 'FAIL': raise
            result = _read(folder / 'gls_runs.json')['runs']
            if len(result) != 1 or (result[0]['corner'], result[0]['case']) != (corner, case['id']):
                raise RuntimeError('native case output population differs')
            row = result[0]
        except Exception as exc:
            # Preserve an infrastructure failure without discarding other independent cases.
            error = folder / 'runner-error.log'
            write_text(error, f'{type(exc).__name__}: {exc}\n')
            row = {'corner': corner, 'case': case['id'], 'sdf': str(sdfs[corner]),
                   'compile_rc': 125, 'sim_rc': None, 'compile_log': str(error),
                   'stdout': str(folder / 'absent.stdout.log'), 'runner_error': str(exc)}
        row['execution'] = {'started_ns': started, 'finished_ns': time.time_ns(),
                            'argv': argv_calls, 'worker_output': str(folder)}
        write_json(folder / 'case_execution.json', row)
        return row

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='native-gls') as pool:
        rows = sorted(pool.map(one, jobs), key=lambda row: (row['corner'], row['case']))
    write_json(root / 'gls_runs.json', {'manifest': step.config['VIBEIC_GLS_MANIFEST'],
        'netlist': str(state[DesignFormat.NETLIST]), 'runs': rows, 'case_workers': workers})
    return rows


def execute(project, context):
    if context.get('requested_step') == 'D72':
        return execute_patterns(project, context)
    project = Path(project).resolve()
    attempt = project / 'reports/flow109/D71' / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    record = {'schema': SCHEMA, 'step_id': 'D71', 'component_status': 'NOT_MEASURED',
              'default_row_status': 'NOT_MEASURED', 'completed': False,
              'flow109_acceptance': 'NOT_MEASURED', 'native_started': False,
              'limitations': LIMITATIONS}
    try:
        prepared = prepare(project, context)
        record.update(inputs=prepared['inputs'],
                      sdf_readback=prepared['sdf_census'],
                      execution_scope=ENGINEERING_SCOPE if prepared.get('engineering') else 'final_gls_component',
                      full_row_acceptance='NOT_MEASURED')
        manifest_dir = attempt / 'manifest'
        manifest_dir.mkdir()
        stubs = manifest_dir / 'phys_cell_stubs.v'
        netlist_text = prepared['netlist'].read_text()
        physical = sgs.missing_empty_cell_stubs(netlist_text, sgs.netlist_used_cells(netlist_text),
            '\n'.join(path.read_text() for path in prepared['models']))
        write_text(stubs, ''.join(f'module {cell} (); endmodule\n' for cell in physical))
        manifest = {'compile_flags': sgs._IVERILOG_FLAGS, 'top': prepared['top'],
                    'netlist': str(prepared['netlist']), 'cases': prepared['cases'],
                    'not_a_subject': [], 'models': list(map(str, prepared['models'])),
                    'stubs': str(stubs), 'sdf_placeholder': sgs.SDF_PLACEHOLDER,
                    'model_closure': prepared['model_closure']}
        manifest_path = manifest_dir / 'gls_manifest.json'
        write_json(manifest_path, manifest)
        record['native_started'] = True
        sys.path.insert(0, str(HERE / 'librelane_plugins'))
        from librelane.state import DesignFormat
        from librelane.common import Path as LLPath
        from librelane_plugin_vibeic import GateLevelSim
        state = {DesignFormat.NETLIST: LLPath(str(prepared['netlist'])),
                 DesignFormat.SDF: {corner: LLPath(str(path))
                                    for corner, path in prepared['sdfs'].items()}}
        # GateLevelSim.run is the existing native implementation.  Its two
        # declared config values are all this PDK-independent simulation step
        # consumes; constructing a full LibreLane Config would incorrectly
        # demand a PDK merely to spawn Icarus/vvp (the canonical T106 consumer
        # invokes this same method boundary).
        step = SimpleNamespace(config={'VIBEIC_GLS_MANIFEST': str(manifest_path),
                                       'VIBEIC_GLS_TIMEOUT_S': 900},
                               step_dir=str(attempt / 'native'), _run=GateLevelSim._run)
        (attempt / 'native').mkdir()
        workers = prepared['manifest'].get('case_workers', 1)
        run_native_cases(step, state, manifest, workers=workers)
        judged = sgs.judge_tool_arm(attempt / 'native', manifest)
        judged = engineering_transcript_readback(attempt / 'native', judged)
        if any(row.get('sdf_errors', 0) for row in judged.get('corners', {}).values()):
            judged['verdict'] = 'FAIL'
        published, checker = _publish(project, prepared, judged, attempt)
        record.update(native={'manifest': _record(project, manifest_path),
                              'runs': _record(project, attempt / 'native/gls_runs.json')},
                      result=published, checker=checker)
        population = published['annotation_population']
        if (judged.get('verdict') == 'PASS'
                and not population['missing'] and population['all_functional_pass']
                and population['all_corners_annotated']):
            record.update(component_status='PASS', default_row_status='PASS', completed=True,
                          flow109_acceptance='PASS', full_row_acceptance='PASS',
                          reason='D71_FINAL_GLS_COMPONENT_MEASURED')
        else:
            record.update(component_status='FAIL', default_row_status='FAIL',
                          reason='D71_NATIVE_GLS_FAILED')
    except NativeResultError as exc:
        record.update(component_status=exc.status, reason=exc.code, detail=str(exc))
    except Exception as exc:
        record.update(component_status='NOT_MEASURED', reason='D71_NATIVE_UNAVAILABLE_OR_UNSUPPORTED',
                      detail=f'{type(exc).__name__}: {exc}')
    path = attempt / 'component.json'
    write_json(path, record)
    write_json(project / 'reports/flow109/components/D71.json', record)
    record['report'] = _record(project, path)
    return record


def execute_patterns(project, context):
    """D72 uses the existing pattern replayer on its own routed scan subject.

    This is a bounded owner entry, not an ATPG implementation. The caller
    supplies source-bound patterns and a self-checking bench; native STA
    views must name the same netlist/SDF before the existing replayer runs.
    """
    from librelane.state import DesignFormat
    from librelane_plugin_vibeic import TestPatternReplay
    project = Path(project).resolve()
    attempt = project / 'reports/flow109/D72' / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    record = {'schema': 'vibeic.flow109.pattern-replay.v1', 'step_id': 'D72',
              'component_status': 'NOT_MEASURED', 'default_row_status': 'NOT_MEASURED',
              'native_started': False,
              'flow109_acceptance': 'NOT_MEASURED', 'whole_flow_acceptance': 'NOT_MEASURED',
              'delivery_accepted': False, 'completed': False}
    try:
        spec = context['patterns']
        names = ('requirements', 'scan_netlist', 'scan_map',
                 'netlist', 'sdf', 'sdc', 'sta_state',
                 'patterns', 'testbench', 'pattern_requirements')
        paths = {name: _bound(project, spec.get(name)) for name in names}
        models = [_bound(project, ref) for ref in spec.get('models', [])]
        if not models:
            raise NativeResultError('D72_MODELS_ABSENT', 'native simulation model closure required')
        from fault_scan_chain_insert import parse_chain_metadata, chain_order_counts
        requirements = _read(paths['requirements'])
        chain = parse_chain_metadata(paths['scan_netlist'].read_text())
        contract = requirements.get('dft_contract') or {}
        if (not chain or type(contract.get('internal_cells')) is not int
                or contract['internal_cells'] <= 0
                or chain.get('internalCount') != contract['internal_cells']
                or chain.get('boundaryCount') != 0 or contract.get('boundary_scan') is not False
                or chain_order_counts(chain).get('dff') != contract['internal_cells']):
            raise NativeResultError('D72_SCAN_CARRIER_MISMATCH', 'declared real scan state required')
        physical = paths['netlist'].read_text()
        for item in chain.get('order', []):
            if item.get('kind') == 'dff' and not re.search(re.escape(item['name']) + r'\s*\(', physical):
                raise NativeResultError('D72_SCAN_CELL_CORRESPONDENCE_MISSING', item['name'])
        record['scan_metadata'] = chain
        state = _read(paths['sta_state'])
        for actual, expected in ((state.get('nl'), paths['netlist']),
                                 (state.get('sdc'), paths['sdc'])):
            if not actual or _bound(project, actual).resolve() != expected.resolve():
                raise NativeResultError('D72_PHYSICAL_INPUT_IDENTITY_MISMATCH', str(actual))
        corner = spec.get('corner')
        native_sdf = (state.get('sdf') or {}).get(corner)
        if not native_sdf or _bound(project, native_sdf).resolve() != paths['sdf'].resolve():
            raise NativeResultError('D72_SDF_NOT_FROM_NATIVE_STA', str(corner))
        top = requirements.get('configuration', {}).get('top')
        census = _sdf_census(paths['sdf'], top)
        metrics = state.get('metrics') or {}
        required_metrics = ('timing__setup_vio__count', 'timing__hold_vio__count')
        if any(type(metrics.get(k)) not in (int, float) for k in required_metrics):
            raise NativeResultError('D72_STA_SETUP_HOLD_UNMEASURED', 'native counts required')
        if any(metrics[k] != 0 for k in required_metrics):
            raise NativeResultError('D72_STA_SETUP_HOLD_FAILED', str({k: metrics[k] for k in required_metrics}), status='FAIL')
        count = spec.get('vector_count')
        pattern_requirements = _read(paths['pattern_requirements'])
        if pattern_requirements.get('required_vector_count') != count:
            raise NativeResultError('D72_REQUIRED_PATTERN_POPULATION_MISMATCH', 'source-derived plan differs')
        if type(count) is not int or count <= 0:
            raise NativeResultError('D72_PATTERN_POPULATION_INVALID', str(count))
        words = paths['patterns'].read_text().split()
        if len(words) != count or any(not re.fullmatch(r'[0-9a-fA-F]+', word) for word in words):
            raise NativeResultError('D72_PATTERN_ROUNDTRIP_FAILED', 'readmemh population differs')
        bench = paths['testbench'].read_text()
        reads = re.findall(r'\$readmemh\(\s*"([^"\n]+)"', bench)
        if reads != [str(paths['patterns'])] or re.search(r'\$(?:fopen|system|readmemb|sdf_annotate)\b|`include\b', bench):
            raise NativeResultError('D72_BENCH_INPUT_UNBOUND', 'only the bound pattern read is permitted')
        manifest = {'compile_flags': '-g2012 -ginterconnect -gspecify -Tmax',
                    'models': [str(path) for path in models],
                    'timing': {'sdf': str(paths['sdf'])},
                    'cases': [{'id': 'scan_capture', 'module': spec.get('bench_module'),
                               'dut_instance': spec.get('dut_instance'),
                               'testbench': str(paths['testbench']),
                               'pattern': str(paths['patterns']),
                               'vector_count': count}]}
        manifest_path = attempt / 'manifest.json'
        write_json(manifest_path, manifest)
        step = SimpleNamespace(id=TestPatternReplay.id, config={
            'VIBEIC_PATTERN_MANIFEST': str(manifest_path), 'VIBEIC_PATTERN_TIMEOUT_S': 300},
            step_dir=str(attempt / 'native'), _run=TestPatternReplay._run)
        record['native_started'] = True
        native_error = None
        try:
            TestPatternReplay.run(step, {DesignFormat.NETLIST: str(paths['netlist'])})
        except Exception as exc:
            native_error = str(exc)
        result_path = Path(step.step_dir) / 'pattern_replay_results.json'
        result = _read(result_path)
        status = 'PASS' if native_error is None and result.get('verdict') == 'PASS' else 'FAIL'
        record.update(component_status=status, default_row_status=status, completed=status == 'PASS',
                      flow109_acceptance=status, reason='D72_NATIVE_TIMED_PATTERN_' + status,
                      result=_record(project, result_path), sdf_census=census,
                      sta_setup_hold={k: metrics[k] for k in required_metrics},
                      scope=requirements.get('scope'), native_error=native_error,
                      metrics={'final_pattern_good_machine_errors': 0 if status == 'PASS' else None,
                               'timed_pattern_sdf_identity': {'netlist': spec['netlist'], 'sdf': spec['sdf']},
                               'export_roundtrip_errors': len(result.get('export_roundtrip_errors', []))},
                      unsupported_scope='ATPG coverage, other carriers, whole-IP and whole-IC qualification')
    except (NativeResultError, OSError, ValueError, KeyError) as exc:
        record.update(reason=getattr(exc, 'code', 'D72_INPUT_UNRESOLVED'), detail=str(exc),
                      component_status=getattr(exc, 'status', 'NOT_MEASURED'),
                      default_row_status=getattr(exc, 'status', 'NOT_MEASURED'))
    write_json(attempt / 'component.json', record)
    return record
