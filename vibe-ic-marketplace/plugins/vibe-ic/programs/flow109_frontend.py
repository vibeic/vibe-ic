"""D22 uses the existing Default synthesis owner and its complete consumer.

The Default native owner validates mapped synthesis; optional explicit tool
qualification claims keep their strict registry path. PPA and whole-flow
acceptance are independent of completing the selected synthesis operation.
"""
from __future__ import annotations
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid
from contextvars import ContextVar

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from _atomic_artefact import write_json
from flow109_admission import AdmissionRefusal, require_launch_admission

INPUT = 'input/flow109/D22.json'
SCHEMA = 'vibeic.flow109.frontend-synthesis.v1'
D05_INPUT = 'input/flow109/D05.json'
D05_SCHEMA = 'vibeic.flow109.power-intent.v1'
_ACTIVE = ContextVar('flow109_synthesis_launch', default=None)
STEPS = {'Yosys.JsonHeader', 'Yosys.Synthesis', 'Checker.YosysUnmappedCells',
         'Checker.YosysSynthChecks', 'Checker.NetlistAssignStatements'}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def operation_sources():
    from execution_provider_catalog import source_closure
    from librelane.steps import pyosys
    from librelane.common import get_script_dir
    import pyosys.libyosys as native_yosys
    seeds = {HERE / 'design_one_shot_runner.py', HERE / 'step_preflight.py',
             HERE / 'execution_backend_gates.py', HERE / 'librelane_contract.py'}
    paths = source_closure(seeds)
    paths.update((Path(__file__), HERE / 'flow109.py', HERE / 'flow109_admission.py'))
    result = {str(p.relative_to(HERE.parent)): _sha(p) for p in sorted(paths)}
    native = Path(inspect.getsourcefile(pyosys))
    result['native/librelane/steps/pyosys.py'] = _sha(native)
    result['native/pyosys/libyosys.so'] = _sha(native_yosys.__file__)
    scripts = Path(get_script_dir())
    for path in sorted((scripts / 'pyosys').rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts:
            result['native/librelane/scripts/' + str(path.relative_to(scripts))] = _sha(path)
    return result


def _read(path):
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise AdmissionRefusal('D22_INPUT_INVALID', str(path))
    return value


def _d05_bound(project, value, label):
    """Reopen one declared D05 input and bind its current project bytes."""
    if (not isinstance(value, dict) or set(value) != {'path', 'sha256'}
            or not isinstance(value.get('path'), str)
            or not re.fullmatch(r'[0-9a-f]{64}', str(value.get('sha256')))):
        raise AdmissionRefusal('D05_INPUT_UNBOUND', label)
    relative = Path(value['path'])
    if relative.is_absolute():
        raise AdmissionRefusal('D05_INPUT_OUTSIDE_PROJECT', label)
    project = Path(project).resolve()
    path = project / relative
    try:
        resolved = path.resolve(strict=True)
        current = resolved.relative_to(project).as_posix()
    except (OSError, ValueError) as exc:
        raise AdmissionRefusal('D05_INPUT_OUTSIDE_PROJECT', label) from exc
    if (path.is_symlink() or not resolved.is_file() or current != relative.as_posix()
            or _sha(resolved) != value['sha256']):
        raise AdmissionRefusal('D05_INPUT_STALE', label)
    return resolved


def _d05_area(value):
    return (isinstance(value, list) and len(value) == 4
            and all(isinstance(item, (int, float)) and not isinstance(item, bool)
                    for item in value)
            and value[0] < value[2] and value[1] < value[3])


def _d05_prepare(project, context):
    """Bind the existing D05 manifest without treating declarations as metrics."""
    project = Path(project).resolve()
    if context.get('requested_step') != 'D05':
        raise AdmissionRefusal('D05_CONTEXT_MISMATCH', 'power-intent component only')
    try:
        manifest = json.loads((project / D05_INPUT).read_text())
    except (OSError, ValueError) as exc:
        raise AdmissionRefusal('D05_INPUT_INVALID', D05_INPUT) from exc
    expected = {'schema', 'top', 'upf', 'rtl', 'liberty', 'lefs', 'evaluation'}
    evaluation = manifest.get('evaluation') if isinstance(manifest, dict) else None
    if (not isinstance(manifest, dict) or set(manifest) != expected
            or manifest.get('schema') != D05_SCHEMA
            or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*', str(manifest.get('top', '')))
            or not isinstance(manifest.get('rtl'), list) or not manifest['rtl']
            or not isinstance(manifest.get('lefs'), list) or not manifest['lefs']
            or not isinstance(evaluation, dict)
            or set(evaluation) != {'site', 'die_area', 'core_area', 'domain_areas'}
            or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*', str(evaluation.get('site', '')))
            or not _d05_area(evaluation.get('die_area'))
            or not _d05_area(evaluation.get('core_area'))
            or not isinstance(evaluation.get('domain_areas'), dict)
            or any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*', str(name))
                   or not _d05_area(area)
                   for name, area in evaluation['domain_areas'].items())):
        raise AdmissionRefusal('D05_INPUT_INVALID', 'complete native inputs required')
    upf = _d05_bound(project, manifest['upf'], 'upf')
    rtl = [_d05_bound(project, item, f'rtl[{index}]')
           for index, item in enumerate(manifest['rtl'])]
    liberty = _d05_bound(project, manifest['liberty'], 'liberty')
    lefs = [_d05_bound(project, item, f'lefs[{index}]')
            for index, item in enumerate(manifest['lefs'])]
    sources = {
        'programs/flow109_frontend.py': _sha(Path(__file__)),
        'programs/flow109.py': _sha(HERE / 'flow109.py'),
        'programs/l21_to_upf_emit.py': _sha(HERE / 'l21_to_upf_emit.py'),
        'programs/power_domain_crossing_check.py':
            _sha(HERE / 'power_domain_crossing_check.py'),
    }
    paths = [project / D05_INPUT, upf, liberty, *rtl, *lefs]
    return {'manifest': manifest, 'evaluation': evaluation, 'upf': upf,
            'rtl': rtl, 'liberty': liberty, 'lefs': lefs, 'sources': sources,
            'inputs': {str(path.relative_to(project)): _sha(path) for path in paths}}


def _d05_tcl_path(path):
    value = str(path)
    if any(char in value for char in '{}\n\r'):
        raise AdmissionRefusal('D05_INPUT_INVALID', 'Tcl-unsafe path')
    return '{' + value + '}'


def _execute_d05(project, context):
    """Run OpenROAD's existing UPF evaluator; keep unsupported row metrics NM."""
    project = Path(project).resolve()
    attempt = project / 'reports/flow109/D05' / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    record = {
        'schema': D05_SCHEMA, 'step_id': 'D05',
        'component_status': 'NOT_MEASURED', 'default_row_status': 'NOT_MEASURED',
        'metric_acceptance_status': 'NOT_MEASURED_NATIVE_METHOD_UNAVAILABLE',
        'flow109_acceptance': 'NOT_MEASURED', 'whole_flow_acceptance': 'NOT_MEASURED',
        'delivery_accepted': False, 'completed': False, 'native_started': False,
        'context_sha256': context.get('context_sha256'),
    }
    try:
        prepared = _d05_prepare(project, context)
        record['source_sha256'] = prepared['sources']
        record['input_sha256'] = prepared['inputs']
        binary = shutil.which('openroad')
        if not binary:
            raise AdmissionRefusal('D05_NATIVE_TOOL_ABSENT', 'openroad')
        script = [f'read_liberty {_d05_tcl_path(prepared["liberty"])}']
        script += [f'read_lef {_d05_tcl_path(path)}' for path in prepared['lefs']]
        script += [f'read_verilog {_d05_tcl_path(path)}' for path in prepared['rtl']]
        script += [f'link_design {prepared["manifest"]["top"]}',
                   f'read_upf -file {_d05_tcl_path(prepared["upf"])}',
                   'set block [[[ord::get_db] getChip] getBlock]']
        for domain, bounds in sorted(prepared['evaluation']['domain_areas'].items()):
            script.append(f'set_domain_area {domain} -area {{{" ".join(map(str, bounds))}}}')
        script += [
            'initialize_floorplan '
            f'-die_area {{{" ".join(map(str, prepared["evaluation"]["die_area"]))}}} '
            f'-core_area {{{" ".join(map(str, prepared["evaluation"]["core_area"]))}}} '
            f'-site {prepared["evaluation"]["site"]}',
            'puts "FLOW109_D05_EVALUATE_UPF=PASS"',
        ]
        getters = {'domains': 'getPowerDomains', 'power_switches': 'getPowerSwitches',
                   'isolations': 'getIsolations', 'level_shifters': 'getLevelShifters'}
        for key, getter in getters.items():
            script += [f'set names_{key} {{}}',
                       f'foreach obj [$block {getter}] {{ lappend names_{key} [$obj getName] }}',
                       f'puts "FLOW109_D05_{key.upper()}=[join [lsort $names_{key}] ,]"']
        roundtrip = attempt / 'roundtrip.upf'
        script.append(f'write_upf {_d05_tcl_path(roundtrip)}')
        tcl = attempt / 'read_upf.tcl'
        tcl.write_text('\n'.join(script) + '\n', encoding='utf-8')
        record['native_started'] = True
        launched = subprocess.run([binary, '-no_init', '-exit', str(tcl)],
                                  text=True, capture_output=True, timeout=300)
        log = attempt / 'openroad.log'
        log.write_text(launched.stdout + launched.stderr, encoding='utf-8')
        record['native_receipt'] = {
            'path': str(log.relative_to(project)), 'sha256': _sha(log),
            'returncode': launched.returncode,
        }
        current = _d05_prepare(project, context)
        if current['sources'] != prepared['sources'] or current['inputs'] != prepared['inputs']:
            raise AdmissionRefusal('D05_INPUT_CHANGED', 'source or input changed during native run')
        if launched.returncode:
            record.update(component_status='FAIL', default_row_status='FAIL',
                          metric_acceptance_status='FAIL',
                          reason='D05_OPENROAD_READ_OR_EVALUATE_UPF_FAILED')
        elif not re.search(r'(?m)^FLOW109_D05_EVALUATE_UPF=PASS$', launched.stdout):
            raise AdmissionRefusal('D05_NATIVE_RESULT_ABSENT', 'evaluate_upf')
        else:
            measured = {}
            for key in getters:
                match = re.search(rf'(?m)^FLOW109_D05_{key.upper()}=(.*)$', launched.stdout)
                if match is None:
                    raise AdmissionRefusal('D05_NATIVE_RESULT_ABSENT', key)
                measured[key] = sorted(filter(None, match.group(1).strip().split(',')))
            semantic_objects = sum(len(measured[key]) for key in
                                   ('power_switches', 'isolations', 'level_shifters'))
            if not measured['domains'] or semantic_objects == 0:
                record.update(component_status='FAIL', default_row_status='FAIL',
                              metric_acceptance_status='FAIL',
                              reason='D05_NATIVE_SEMANTIC_POPULATION_MISSING')
            else:
                reason = 'D05_NATIVE_STATE_AND_SUPPLY_ANALYSIS_UNAVAILABLE'
                record['metrics'] = {
                    'native_structure': {
                        'status': 'PASS',
                        'mechanism': 'read_upf -> initialize_floorplan -> upf::eval_upf',
                        'population': measured,
                        'roundtrip_upf': {
                            'path': str(roundtrip.relative_to(project)),
                            'sha256': _sha(roundtrip),
                        },
                    },
                    'semantic_demand_coverage': {'status': 'NOT_MEASURED', 'reason': reason},
                    'illegal_power_states': {'status': 'NOT_MEASURED', 'reason': reason},
                    'supply_cell_assignments': {'status': 'NOT_MEASURED', 'reason': reason},
                }
                record.update(component_status='PASS', reason=reason)
    except AdmissionRefusal as exc:
        record.update(component_status=exc.status, default_row_status=exc.status,
                      reason=exc.code, detail=str(exc))
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        record.update(reason='D05_NATIVE_UNAVAILABLE_OR_UNSUPPORTED', detail=str(exc))
    write_json(attempt / 'component.json', record)
    record['receipt'] = {
        'path': str((attempt / 'component.json').relative_to(project)),
        'sha256': _sha(attempt / 'component.json'),
    }
    return record


def input_census(project):
    """Bind existing design input roots, not newly produced synthesis outputs."""
    project = Path(project)
    roots = ('input', 'input_doc', 'phase1/generated_docs', 'phase2/stage1/rtl',
             'phase2/stage2/constraints')
    paths = {p for root in roots for p in (project / root).rglob('*') if p.is_file()}
    from sdc_constraints import collect_sdc_files
    paths.update(collect_sdc_files(project))
    native_sdc = project / 'phase3/stage3/pnr/constraint.sdc'
    if native_sdc.is_file():
        paths.add(native_sdc)
    switch = project / 'phase3/librelane_switch.json'
    if switch.is_file():
        paths.add(switch)
    return {str(p.relative_to(project)): _sha(p) for p in sorted(paths)}


def _before(project, context, prepared):
    require_launch_admission(project, '9', {'flow109_context': context})
    import flow109
    try:
        current_dft_intent = flow109.dft_source_intent(project, context)
    except flow109.Flow109Error as exc:
        raise AdmissionRefusal(exc.code, exc.detail) from exc
    if current_dft_intent != prepared['dft_intent']:
        raise AdmissionRefusal('D22_DFT_INTENT_CHANGED', 'D09 DFT intent changed before synthesis launch')
    if operation_sources() != prepared['sources']:
        raise AdmissionRefusal('D22_OPERATION_SOURCE_CHANGED', 'source changed before synthesis launch')
    if input_census(project) != prepared['inputs']:
        raise AdmissionRefusal('D22_INPUT_CHANGED', 'consumed source population changed')


# The current request is visible at the contract's real config/native launch
# boundaries too. No request means ordinary old-flow behavior is unchanged.
def require_librelane_launch(project, operation, *, configuration=False):
    context_path = os.environ.get('VIBEIC_FLOW109_CONTEXT')
    if not context_path:
        return
    context = _read(context_path)
    if context.get('requested_step') != 'D22':
        return
    if operation not in STEPS:
        raise AdmissionRefusal('D22_NATIVE_OPERATION_UNQUALIFIED', str(operation))
    active = _ACTIVE.get()
    if active is None or active['project'] != Path(project).resolve() or active['context'] != context:
        raise AdmissionRefusal('D22_LAUNCH_CONTEXT_UNBOUND', str(operation))
    _before(Path(project), context, active['prepared'])
    if not configuration:
        active['operations'].append(operation)


def synthesis_fingerprint(project):
    """Existing native reuse must name the exact admitted producer identity."""
    path = os.environ.get('VIBEIC_FLOW109_CONTEXT')
    if not path or _read(path).get('requested_step') != 'D22':
        return None
    active = _ACTIVE.get()
    if active is None or active['project'] != Path(project).resolve():
        raise AdmissionRefusal('D22_LAUNCH_CONTEXT_UNBOUND', 'native fingerprint')
    _before(Path(project), active['context'], active['prepared'])
    return {'context_sha256': active['context']['context_sha256'],
            'qualification_uses': {use['use_id']: use['qualification_sha256']
                                   for use in (active['context']['runtime_tool_uses'] or [])}}


def d10_native_failure(result):
    """Recognize the existing reader's concrete missing-module error witness.

    This is an observed native defect, not tool-purpose qualification. Other
    execution failures remain unmeasured rather than inferred from wrapper rc.
    """
    import p0_tool_frontend_check as frontend
    tools = result.get('tools') or {}
    yosys = tools.get('Yosys.JsonHeader') or {}
    lint = tools.get('Verilator.Lint') or {}
    if (result.get('not_measured') or result.get('passed') is not False
            or any(type(tool.get('exit_code')) is not int
                   or not 0 < tool['exit_code'] < 128 for tool in (yosys, lint))
            or 'Yosys elaboration failed' not in result.get('findings', [])):
        return None
    diagnostics = frontend._diagnostic_codes(lint.get('output', ''))
    if diagnostics != lint.get('diagnostics'):
        raise ValueError('P0 native diagnostic reader differs')
    errors = [row for row in diagnostics if row.get('severity') == 'Error']
    if not errors or any(row.get('code') != 'MODMISSING' for row in errors):
        return None
    return {'status': 'FAIL', 'reason': 'D10_NATIVE_UNDEFINED_MODULE',
            'scope': 'coded native MODMISSING diagnostics',
            'elaboration_errors': len(errors), 'diagnostics': errors}


def prepare(project, context):
    require_launch_admission(project, '9', {'flow109_context': context})
    if context.get('requested_step') != 'D22':
        raise AdmissionRefusal('D22_CONTEXT_MISMATCH', 'synthesis component only')
    import flow109
    try:
        dft_intent = flow109.dft_source_intent(project, context)
    except flow109.Flow109Error as exc:
        raise AdmissionRefusal(exc.code, exc.detail) from exc
    sources = operation_sources()
    for use in (context['runtime_tool_uses'] or []):
        if use.get('semantics', {}).get('operation_sources') != sources:
            raise AdmissionRefusal('D22_OPERATION_SOURCE_CHANGED', use['use_id'])
    manifest = _read(project / INPUT)
    import re
    if (manifest.get('schema') != SCHEMA
            or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*', str(manifest.get('top', '')))
            or not isinstance(manifest.get('pdk'), str) or not manifest['pdk']):
        raise AdmissionRefusal('D22_INPUT_INVALID', 'explicit top and PDK required')
    if context['runtime_tool_uses'] is not None and not (project / 'input/submission_template/tapeout_declaration.json').is_file():
        raise AdmissionRefusal('D22_REQUIRED_INPUT_ABSENT', 'canonical submission declaration required')
    from _hdl_code_text import strip_hdl_comments_and_strings
    for rtl in (project / 'phase2/stage1/rtl').rglob('*'):
        if rtl.is_file() and rtl.suffix in ('.v', '.sv', '.vh', '.svh'):
            text = strip_hdl_comments_and_strings(rtl.read_text())
            if re.search(r'`include\b|\$(?:readmem[hb]|fopen|system)\b', text):
                raise AdmissionRefusal('D22_TRANSITIVE_INPUT_UNIMPLEMENTED', str(rtl))
    import librelane_contract as contract
    if contract.selected_mode(project, '9') != 'librelane':
        raise AdmissionRefusal('D22_ROUTE_UNSUPPORTED', 'only the existing native LibreLane Default owner is selected')
    import design_one_shot_runner as runner
    pdk = runner._phase2_pdk_config(project, manifest['pdk'])
    liberty = Path(pdk.liberty).resolve()
    for use in (context['runtime_tool_uses'] or []):
        deck = use.get('deck') or {}
        if (not deck.get('path') or (project / deck['path']).resolve() != liberty
                or deck.get('sha256') != _sha(liberty)):
            raise AdmissionRefusal('D22_LIBRARY_NOT_QUALIFIED', use['use_id'])
        config = _read(project / use['config']['path'])
        if config != {'schema': SCHEMA, 'operation': 'Default.NativeMappedSynthesis',
                      'pdk': manifest['pdk'], 'top': manifest['top']}:
            raise AdmissionRefusal('D22_CONFIGURATION_UNSUPPORTED', use['use_id'])
    inputs = input_census(project)
    if not any(p.startswith('phase2/stage1/rtl/') for p in inputs):
        raise AdmissionRefusal('D22_RTL_ABSENT', 'no bound RTL population')
    return {'manifest': manifest, 'pdk': pdk, 'sources': sources, 'inputs': inputs,
            'dft_intent': dft_intent}


def _canonical_publication(project, started_at):
    """Read this D22 invocation's existing complete-consumer publication."""
    import step_output_collector as versions
    try:
        rows = [row for row in versions.current_acceptance(project, started_at)
                if str(row.get('id')) == '9']
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise AdmissionRefusal('D22_CANONICAL_PUBLICATION_INVALID', str(exc)) from exc
    if len(rows) != 1:
        raise AdmissionRefusal('D22_CANONICAL_PUBLICATION_MISSING_OR_FOREIGN',
                               f'current step 9 publication count={len(rows)}')
    row = rows[0]
    result = row.get('result')
    consumer = result.get('canonical_consumer') if isinstance(result, dict) else None
    status = consumer.get('status') if isinstance(consumer, dict) else None
    step = consumer.get('step') if isinstance(consumer, dict) else None
    if (status not in {'PASS', 'NOT_MEASURED', 'FAIL'}
            or row.get('status') != status
            or not isinstance(step, dict) or str(step.get('id')) != '9'
            or step.get('status') != status
            or row.get('capture_errors') != []
            or result.get('runner') != 'design_one_shot_runner'
            or result.get('site') != 'step_yosys_synth'):
        raise AdmissionRefusal('D22_CANONICAL_PUBLICATION_INVALID',
                               'current step 9 consumer identity or verdict differs')
    if status == 'PASS':
        latest = versions.latest_pass(project, '9')
        if (row.get('canonical_pass') is not True or not isinstance(latest, dict)
                or latest.get('folder') != row.get('folder')
                or latest.get('current_inputs') is not True):
            raise AdmissionRefusal('D22_CANONICAL_PUBLICATION_STALE',
                                   'PASS publication is not the current input-bound latest pass')
    elif row.get('canonical_pass') is not False:
        raise AdmissionRefusal('D22_CANONICAL_PUBLICATION_INVALID',
                               'non-PASS consumer cannot publish canonical_pass')
    return row


def _execute_d22(project, context):
    project = Path(project).resolve()
    attempt = project / 'reports/flow109/D22' / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    record = {'schema': SCHEMA, 'step_id': 'D22', 'component_status': 'NOT_MEASURED',
              'flow109_acceptance': 'NOT_MEASURED', 'native_started': False,
              'context_sha256': context.get('context_sha256')}
    try:
        prepared = prepare(project, context)
        _before(project, context, prepared)
        import design_one_shot_runner as runner
        import step_preflight
        from dataclasses import asdict
        import step_output_collector as versions
        # Exactly the existing owner and the same retained complete consumer.
        # No frontend Controller/Ultra arm, copied Yosys recipe, or new checker.
        active = {'project': project, 'context': context, 'prepared': prepared, 'operations': []}
        token = _ACTIVE.set(active)
        publication_started_at = time.time()
        try:
            result = step_preflight.retained_call(project, '9', runner.step_yosys_synth,
                project, prepared['manifest']['top'], '', None,
                pdk_name=prepared['manifest']['pdk'],
                canonical_acceptance=True)
        finally:
            _ACTIVE.reset(token)
            record['native_operations'] = active['operations']
            record['native_started'] = bool(active['operations'])
        record['producer'] = asdict(result)
        publication = (_canonical_publication(project, publication_started_at)
                       if result.status == 'PASS' else None)
        if publication is not None:
            record['canonical_publication'] = {
                'folder': publication['folder'], 'status': publication['status'],
                'canonical_consumer': publication['result']['canonical_consumer']}
        record['canonical_current_pass'] = versions.latest_pass(project, '9')
        record['source_sha256'] = prepared['sources']
        record['inputs'] = prepared['inputs']
        record['dft_intent'] = prepared['dft_intent']
        _before(project, context, prepared)
        # Native execution is established by the existing receipt, not by
        # merely entering a function which can refuse before tool launch.
        folder = project / 'phase3/librelane/02-yosys-synthesis'
        receipt = folder / 'vibeic_receipt.json'
        if 'Yosys.Synthesis' in active['operations'] and receipt.is_file():
            record['native_receipt'] = {'path': str(receipt.relative_to(project)), 'sha256': _sha(receipt)}
        if result.status == 'FAIL':
            record.update(component_status='FAIL', reason='D22_EXISTING_PRODUCER_FAILED')
        elif result.status == 'PASS':
            status = publication['status']
            record.update(component_status=status, default_row_status=status,
                          completed=status == 'PASS',
                          reason=('D22_EXISTING_CANONICAL_CONSUMER_' + status))
        else:
            record['reason'] = 'D22_CANONICAL_ACCEPTANCE_NOT_MEASURED'
    except AdmissionRefusal as exc:
        record.update(component_status=exc.status, reason=exc.code, detail=str(exc))
    except (OSError, ValueError, ImportError) as exc:
        record.update(reason='D22_NATIVE_UNAVAILABLE_OR_UNSUPPORTED', detail=str(exc))
    write_json(attempt / 'component.json', record)
    return record


def _dft_tail_sources(step):
    from execution_provider_catalog import source_closure
    names = ({'D50': ('path_delay_fault_atpg_run.py', 'path_delay_coverage_check.py'),
              'D51': ('sdd_atpg_run.py', 'sdd_coverage_check.py')})[step]
    paths = source_closure({HERE / name for name in names})
    paths.update((Path(__file__), HERE / 'flow109.py'))
    return {str(path.relative_to(HERE.parent)): _sha(path) for path in sorted(paths)}


def _execute_dft_tail(project, context):
    project = Path(project).resolve()
    step = context.get('requested_step')
    attempt = project / 'reports/flow109' / step / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    record = {'schema': 'vibeic.flow109.dft-tail-component.v1',
              'step_id': step, 'component_status': 'NOT_MEASURED',
              'default_row_status': 'NOT_MEASURED', 'completed': False,
              'flow109_acceptance': 'NOT_MEASURED',
              'whole_flow_acceptance': 'NOT_MEASURED', 'delivery_accepted': False,
              'native_started': False, 'context_sha256': context.get('context_sha256')}
    try:
        import flow109
        admission = flow109.dft_final_timing_admission(project, context)
        intent = flow109.dft_source_intent(project, context)
        test_mode = intent['source_binding']['intent'].get('test_mode')
        clock = test_mode.get('clock') if isinstance(test_mode, dict) else None
        if not intent['requires_scan'] or not isinstance(clock, str) or not clock:
            raise flow109.Flow109Error('FLOW109_DFT_AT_SPEED_CLOCK_UNRESOLVED', str(clock))
        sources = _dft_tail_sources(step)
        timing = admission['timing']
        argv = [str(project), '--clock', clock,
                '--librelane-state', timing['state'],
                '--librelane-corner', timing['corner']]
        if step == 'D50':
            import path_delay_fault_atpg_run as producer
            import path_delay_coverage_check as consumer
            output = project / 'reports/phase2/dft/path_delay_coverage.json'
        else:
            import sdd_atpg_run as producer
            import sdd_coverage_check as consumer
            output = project / 'reports/phase2/dft/sdd_coverage.json'
        argv += ['--json', str(output)]
        record['native_started'] = True
        rc = producer.main(argv)
        judged = consumer.audit(project, str(output))
        record.update(native_rc=rc, consumer=judged, source_sha256=sources,
                      dft_final_timing_admission=admission)
        if rc == 0 and judged.get('verdict') == 'PASS':
            record.update(component_status='PASS', default_row_status='PASS',
                          completed=True, reason=step + '_EXISTING_CONSUMER_PASSED')
        elif judged.get('verdict') == 'FAIL':
            record.update(component_status='FAIL', default_row_status='FAIL',
                          reason=step + '_EXISTING_CONSUMER_FAILED')
        else:
            record['reason'] = step + '_EXISTING_CONSUMER_NOT_MEASURED'
        if _dft_tail_sources(step) != sources:
            raise flow109.Flow109Error('FLOW109_DFT_TAIL_SOURCE_CHANGED', step)
        if flow109.dft_final_timing_admission(project, context) != admission:
            raise flow109.Flow109Error('FLOW109_DFT_FINAL_INPUT_CHANGED', step)
    except flow109.Flow109Error as exc:
        record.update(component_status='NOT_MEASURED', default_row_status='NOT_MEASURED',
                      completed=False, reason=exc.code, detail=exc.detail,
                      native_started=record.get('native_started', False))
    except (OSError, ValueError, ImportError) as exc:
        record.update(reason=step + '_NATIVE_UNAVAILABLE_OR_UNSUPPORTED', detail=str(exc))
    write_json(attempt / 'component.json', record)
    return record


def execute(project, context):
    step = context.get('requested_step')
    if step == 'D05':
        return _execute_d05(project, context)
    if step == 'D22':
        return _execute_d22(project, context)
    if step in {'D50', 'D51'}:
        return _execute_dft_tail(project, context)
    return {'schema': 'vibeic.flow109.window-component.v1',
            'step_id': step, 'component_status': 'NOT_MEASURED',
            'reason': 'FLOW109_FRONTEND_CONTEXT_MISMATCH', 'native_started': False,
            'context_sha256': context.get('context_sha256'),
            'flow109_acceptance': 'NOT_MEASURED',
            'whole_flow_acceptance': 'NOT_MEASURED', 'delivery_accepted': False}
