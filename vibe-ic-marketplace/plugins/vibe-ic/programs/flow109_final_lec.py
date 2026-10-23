"""Blocking D44 component: native LibreLane EQY on the adopted final netlist.

No pre-layout proof is reused. Functional model/port census and complete EQY
partition results are required. Unproven/unsupported transformations remain
NOT_MEASURED. Produces a common netlist baseline, not downstream STA/LVS PASS.
"""
from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _atomic_artefact import write_json
from flow109_admission import AdmissionRefusal, require_launch_admission
from flow109_metric_acceptance import accept_d44
import librelane_eqy as eqy
import flow109_final_lec_physical as physical

SCHEMA = 'vibeic.flow109.final-lec.v1'
INPUT = 'input/flow109/D44.json'
BASELINE = 'adopted/final_lec/sta_lvs_release_netlist_mapping.json'
METRICS_SCHEMA = 'vibeic.flow109.D44.metric-bindings.v1'
RETAINED_SCHEMA = 'vibeic.flow109.final-lec-retained-native.v1'
EDA_IMAGE = ('ghcr.io/vibeic/vibeic-eda@sha256:'
             '0fc30ecd1307a11bd7757d1c5710127cd88e245059f29eab8b52e38ba4d60406')


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def operation_sources():
    from execution_provider_catalog import source_closure
    paths = source_closure({HERE / 'librelane_eqy.py', HERE / 'lec_post_layout_check.py',
                            HERE / 'flow109_final_lec_physical.py'})
    paths.update((Path(__file__), HERE / 'flow109.py', HERE / 'flow109_admission.py',
                  HERE / 'flow109_metric_acceptance.py'))
    result = {str(path.relative_to(HERE.parent)): _sha(path) for path in sorted(paths)}
    # Native EQY is Python too; its installed Step implementation is part of
    # the qualified operation, rather than merely the interpreter version.
    from librelane.steps.yosys import EQY
    native = Path(inspect.getsourcefile(EQY))
    result['native/librelane/steps/yosys.py'] = _sha(native)
    return result


def _read(path):
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise AdmissionRefusal('D44_INPUT_ABSENT', str(path)) from exc
    if not isinstance(value, dict):
        raise AdmissionRefusal('D44_INPUT_INVALID', str(path))
    return value


def _bound(project, value):
    if not isinstance(value, dict) or not value.get('path') or not value.get('sha256'):
        raise AdmissionRefusal('D44_INPUT_UNBOUND', str(value))
    path = (project / value['path']).resolve()
    if not path.is_file() or _sha(path) != value['sha256']:
        raise AdmissionRefusal('D44_INPUT_STALE_OR_MISSING', str(path))
    return path


def _record(project, path):
    path = Path(path).resolve()
    return {'path': str(path.relative_to(project)) if path.is_relative_to(project) else str(path),
            'sha256': _sha(path)}


def _project_bound(project, value):
    """Resolve immutable retained evidence, which must travel with the project."""
    path = _bound(project, value)
    try:
        path.relative_to(project)
    except ValueError as exc:
        raise AdmissionRefusal('D44_RETAINED_EVIDENCE_OUTSIDE_PROJECT', str(path)) from exc
    return path


def prepare(project, context):
    if context.get('requested_step') != 'D44' or context.get('native_step_id') != 'flow109.D44':
        raise AdmissionRefusal('D44_CONTEXT_MISMATCH', 'final netlist EQY component only')
    sources = operation_sources()
    uses = context.get('runtime_tool_uses') or []
    for use in uses:
        if use.get('semantics', {}).get('operation_sources') != sources:
            raise AdmissionRefusal('D44_OPERATION_SOURCE_CHANGED', use.get('use_id'))
    manifest = _read(project / INPUT)
    if manifest.get('schema') != SCHEMA or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*', str(manifest.get('top', ''))):
        raise AdmissionRefusal('D44_INPUT_INVALID', 'schema/top must identify the exact proof subject')
    transforms = manifest.get('transformations')
    physical_manifest = None
    if transforms != []:
        if (not isinstance(transforms, list) or len(transforms) != 1
                or not isinstance(transforms[0], dict)
                or set(transforms[0]) != {'kind', 'input'}
                or transforms[0]['kind'] != physical.KIND):
            raise AdmissionRefusal('D44_TRANSFORMATION_NOT_QUALIFIED',
                                   'only source-owned DEF-bound physical preparation is supported')
        physical_manifest = _read(_bound(project, transforms[0]['input']))
    retained_record = manifest.get('retained_native')
    retained = _project_bound(project, retained_record) if retained_record is not None else None
    rtl = manifest.get('rtl')
    if not isinstance(rtl, list) or not rtl:
        raise AdmissionRefusal('D44_RTL_ABSENT', 'nonempty reference RTL population required')
    paths = {'rtl': [_bound(project, item) for item in rtl],
             'adopted_netlist': _bound(project, manifest.get('adopted_netlist')),
             'liberty': _bound(project, manifest.get('liberty'))}
    physical_inputs = {}
    if physical_manifest is not None:
        if (physical_manifest.get('schema') != physical.SCHEMA
                or physical_manifest.get('top') != manifest['top']
                or len(paths['rtl']) != 1):
            raise AdmissionRefusal('D44_PHYSICAL_INPUT_MISMATCH', 'physical schema/top/reference')
        for name, expected in [('rtl', paths['rtl'][0]),
                               ('adopted_netlist', paths['adopted_netlist']),
                               ('liberty', paths['liberty'])]:
            if _bound(project, physical_manifest.get(name)) != expected:
                raise AdmissionRefusal('D44_PHYSICAL_INPUT_MISMATCH', name)
        for name in ('rtl', 'adopted_netlist', 'adopted_state', 'adopted_receipt',
                     'final_def', 'wrapper', 'wrapper_record', 'liberty', 'io_liberty'):
            path = _bound(project, physical_manifest.get(name))
            physical_inputs[str(path)] = _sha(path)
        path = _bound(project, transforms[0]['input'])
        physical_inputs[str(path)] = _sha(path)
        physical_inputs.update(physical.native_fill_inputs({
            name: _bound(project, physical_manifest[name])
            for name in ('adopted_netlist', 'adopted_state', 'adopted_receipt', 'final_def')}))
    roles = manifest.get('consumer_netlists')
    if not isinstance(roles, dict) or set(roles) != {'sta', 'lvs_reference', 'release'}:
        raise AdmissionRefusal('D44_CONSUMER_BASELINE_ABSENT', 'STA/LVS-reference/release must all have a source')
    for role, item in roles.items():
        value = _bound(project, item)
        if _sha(value) != _sha(paths['adopted_netlist']):
            raise AdmissionRefusal('D44_CONSUMER_BASELINE_DIFFERS', role)
        paths[role] = value
    native = manifest.get('librelane')
    if (not isinstance(native, dict) or set(native) != {'PDK', 'STD_CELL_LIBRARY', 'pdk_root'}
            or not Path(native['pdk_root']).is_dir()):
        raise AdmissionRefusal('D44_PDK_CONFIGURATION_ABSENT', 'explicit existing LibreLane PDK root/library required')
    for use in uses:
        if physical_manifest is None:
            if _bound(project, use['deck']) != paths['liberty']:
                raise AdmissionRefusal('D44_LIBRARY_NOT_QUALIFIED', use['use_id'])
        elif _read(_bound(project, use['deck'])) != {
                'liberties': [manifest['liberty'], physical_manifest['io_liberty']]}:
            raise AdmissionRefusal('D44_LIBRARY_NOT_QUALIFIED', use['use_id'])
        pdk = _read(_bound(project, use['pdk']))
        expected_pdk = {'librelane': native, 'liberty': manifest['liberty']}
        if physical_manifest is not None:
            expected_pdk.update(io_liberty=physical_manifest['io_liberty'],
                                physical_input=transforms[0]['input'])
        if pdk != expected_pdk:
            raise AdmissionRefusal('D44_PDK_SCOPE_NOT_QUALIFIED', use['use_id'])
        config = _read(_bound(project, use['config']))
        if config != {'schema': SCHEMA, 'operation': 'Yosys.EQY', 'transformations': transforms}:
            raise AdmissionRefusal('D44_CONFIGURATION_UNSUPPORTED', use['use_id'])
    inputs = {INPUT: _sha(project / INPUT), **physical_inputs}
    if retained is not None:
        inputs[str(retained)] = _sha(retained)
    for group in paths.values():
        for path in group if isinstance(group, list) else [group]:
            inputs[str(path)] = _sha(path)
    if uses:
        tools = {use['tool_id']: use['executable']['path'] for use in uses}
    else:
        dispatch = context.get('resolved_row', {}).get('profile', {}).get('dispatch', {})
        declared = dispatch.get('engine_executables')
        if not isinstance(declared, dict) or set(declared) != set(dispatch.get('engine_families', ())):
            raise AdmissionRefusal('D44_NATIVE_TOOL_INVENTORY_ABSENT', 'source-owned engine inventory')
        tools = {name: shutil.which(executable) for name, executable in declared.items()}
        if not all(tools.values()):
            missing = sorted(name for name, path in tools.items() if not path)
            raise AdmissionRefusal('D44_NATIVE_UNAVAILABLE', ','.join(missing))
    return {'manifest': manifest, 'paths': paths, 'sources': sources, 'inputs': inputs,
            'physical_input': transforms[0]['input'] if physical_manifest is not None else None,
            'retained_native': retained,
            'tools': tools}


def _before(project, context, prepared):
    require_launch_admission(project, 'flow109.D44', {'flow109_context': context})
    if operation_sources() != prepared['sources']:
        raise AdmissionRefusal('D44_OPERATION_SOURCE_CHANGED', 'source changed before native launch')
    for name, sha in prepared['inputs'].items():
        if not (project / name).is_file() or _sha(project / name) != sha:
            raise AdmissionRefusal('D44_INPUT_STALE_OR_MISSING', name)


def _yosys_word(path):
    return '"' + str(path).replace('\\', '\\\\').replace('"', '\\"') + '"'


def _model_census(project, prepared, attempt, before):
    """Model/port elaboration only: no second equivalence engine or proof."""
    result = {}
    proof_paths = prepared.get('proof_paths', prepared['paths'])
    for side, files in [('gold', proof_paths['rtl']),
                        ('gate', [proof_paths['adopted_netlist']])]:
        output = attempt / (side + '.model.json')
        text = ''
        if side == 'gate':
            text += 'read_liberty -ignore_miss_func ' + _yosys_word(prepared['paths']['liberty']) + '\n'
        text += 'read_verilog -formal -sv -icells ' + ' '.join(_yosys_word(p) for p in files) + '\n'
        text += f"hierarchy -check -top {prepared['manifest']['top']}\nproc\n"
        text += 'write_json ' + _yosys_word(output) + '\n'
        script = attempt / (side + '.model.ys')
        script.write_text(text)
        before()
        process = subprocess.run([prepared['tools']['yosys'], '-Q', '-T', '-s', str(script)],
                                 capture_output=True, text=True)
        (attempt / (side + '.model.log')).write_text(process.stdout + process.stderr)
        if process.returncode or not output.is_file():
            raise AdmissionRefusal('D44_MODEL_ELABORATION_UNSUPPORTED', side)
        modules = _read(output).get('modules', {})
        top = prepared['manifest']['top']
        pending, visited = [top], set()
        while pending:
            name = pending.pop()
            if name in visited or name.startswith('$'):
                continue
            visited.add(name)
            module = modules.get(name)
            attrs = module.get('attributes', {}) if isinstance(module, dict) else {}
            if module is None or any(str(attrs.get(a, '0')).strip('0') for a in ('blackbox', 'whitebox')):
                raise AdmissionRefusal('D44_FUNCTIONAL_MODEL_UNSUPPORTED', f'{side}:{name}')
            pending.extend(cell['type'] for cell in module.get('cells', {}).values())
        result[side] = {'modules': sorted(visited), 'ports': modules[top].get('ports', {})}
    # Never drop/rename a port merely to make the proof line up.
    interface = lambda side: {name: (p['direction'], len(p['bits']))
                              for name, p in result[side]['ports'].items()}
    if interface('gold') != interface('gate'):
        raise AdmissionRefusal('D44_PORT_MAPPING_UNSUPPORTED', 'reference and adopted interfaces differ')
    return result


def _native_eqy(project, prepared, attempt, before):
    from librelane.config import Config
    from librelane.state import State, DesignFormat
    from librelane.common import Path as LLPath
    from librelane.steps.yosys import EQY
    from librelane.steps import StepError

    manifest, paths = prepared['manifest'], prepared.get('proof_paths', prepared['paths'])
    script = attempt / 'final.eqy'
    script.write_text(eqy.eqy_script(manifest['top'], paths['rtl'], paths['adopted_netlist'], str(paths['liberty'])))
    config, _ = Config.load({'DESIGN_NAME': manifest['top'],
        'PDK': manifest['librelane']['PDK'], 'STD_CELL_LIBRARY': manifest['librelane']['STD_CELL_LIBRARY'],
        'VERILOG_FILES': [str(p) for p in paths['rtl']], 'EQY_SCRIPT': str(script),
        'EQY_FORCE_ACCEPT_PDK': True}, EQY.get_all_config_variables(), design_dir=str(project),
        pdk_root=manifest['librelane']['pdk_root'])
    (attempt / 'resolved-config.json').write_text(config.dumps())
    # Native LibreLane has two preprocessing branches. This tranche qualifies
    # its generic iverilog branch; it does not silently run the other helper
    # (which is absent from the current image and source-owned use inventory).
    if config['PDK'].startswith('sky130A'):
        raise AdmissionRefusal('D44_NATIVE_PREPROCESSOR_UNQUALIFIED',
                               'LibreLane formal_pdk_proc branch needs a separately qualified tool use')
    model_inputs = {str(p): _sha(p) for p in config['CELL_VERILOG_MODELS']}
    step = EQY(config=config, state_in=State({DesignFormat.NETLIST: LLPath(str(paths['adopted_netlist']))}))
    before()
    try:
        step.start(step_dir=str(attempt / 'native'))
        native_error = None
    except StepError as exc:
        # A native counterexample is an answer. Consume retained partitions;
        # do not relabel all EQY nonzero exits as proof of inequivalence.
        native_error = str(exc)
    if any(_sha(path) != sha for path, sha in model_inputs.items()):
        raise AdmissionRefusal('D44_MODEL_INPUT_CHANGED', 'LibreLane preprocessing model changed', status='FAIL')
    return native_error, model_inputs


def consume_eqy(folder, output):
    """Extend the existing consumer with a complete declared partition census."""
    result = eqy.judge_eqy(folder, output)
    listing = folder / 'scratch/partition.list'
    def incomplete(reason, **extra):
        value = {**result, 'verdict': 'FAIL' if result['verdict'] == 'FAIL' else 'NOT_MEASURED',
                 'explanation': reason, **extra}
        write_json(output, value)
        return value
    if not listing.is_file():
        return incomplete('D44_PARTITION_LIST_ABSENT')
    names = []
    for line in listing.read_text().splitlines():
        if not line.strip():
            continue
        words = line.partition(':')[0].split()
        if len(words) < 2:
            return incomplete('D44_PARTITION_LIST_INVALID')
        names.append(words[1])
    parts = result.get('partitions') or {}
    if not names or len(names) != len(set(names)) or set(names) != set(parts):
        return incomplete('D44_PARTITION_COVERAGE_INCOMPLETE', declared_partitions=names)
    evidence = [listing, *sorted((folder / 'scratch/strategies').glob('*/*/status'))]
    value = {**result, 'declared_partitions': names,
             'evidence_sha256': {str(p.relative_to(folder)): _sha(p) for p in evidence}}
    write_json(output, value)
    return value


def _metric_contract(context):
    """Return the two source-owned D44 obligations or refuse substitution."""
    row = context.get('resolved_row')
    obligations = row.get('obligations') if isinstance(row, dict) else None
    if not isinstance(row, dict) or row.get('id') != 'D44' or not isinstance(obligations, list):
        raise AdmissionRefusal('D44_METRIC_CONTRACT_UNBOUND', 'resolved D44 obligations required')
    by_name = {item.get('metric'): item for item in obligations if isinstance(item, dict)}
    if set(by_name) != {'final_lec_unproved', 'sta_lvs_release_netlist_mapping'}:
        raise AdmissionRefusal('D44_METRIC_CONTRACT_UNBOUND', 'exact D44 metric set required')
    unproved = by_name['final_lec_unproved'].get('expectation')
    mapping = by_name['sta_lvs_release_netlist_mapping'].get('expectation')
    if unproved != {'operator': 'eq', 'value': 0, 'unit': 'count',
                    'source': 'contract invariant: no unresolved required violations'}:
        raise AdmissionRefusal('D44_METRIC_REQUIREMENT_CHANGED', 'final_lec_unproved')
    if mapping != {'operator': 'matches_adopted_reference', 'reference_ref': BASELINE}:
        raise AdmissionRefusal('D44_METRIC_REQUIREMENT_CHANGED',
                               'sta_lvs_release_netlist_mapping')
    return by_name


def _proof_binding(proof):
    """Measure unresolved declared partitions; never infer coverage from PASS."""
    if not isinstance(proof, dict):
        return {'status': 'NOT_MEASURED', 'reason': 'D44_PROOF_ABSENT'}
    declared, parts = proof.get('declared_partitions'), proof.get('partitions')
    if (not isinstance(declared, list) or not declared
            or len(declared) != len(set(declared)) or not isinstance(parts, dict)
            or set(declared) != set(parts)):
        return {'status': 'NOT_MEASURED', 'reason': 'D44_PARTITION_COVERAGE_INCOMPLETE'}
    statuses = {name: set(strategies.values()) if isinstance(strategies, dict) else set()
                for name, strategies in parts.items()}
    native_proven = {name for name, words in statuses.items() if 'PASS' in words}
    failed = {name for name, words in statuses.items() if 'PASS' not in words and 'FAIL' in words}
    unknown = set(declared) - native_proven - failed
    # A gold-X comparison is not a proof even when the native strategy says PASS.
    xbits = proof.get('xbits_partitions')
    if not isinstance(xbits, list) or not set(xbits) <= set(declared):
        return {'status': 'NOT_MEASURED', 'reason': 'D44_PARTITION_CENSUS_INVALID'}
    unresolved = sorted(failed | unknown | set(xbits))
    if (proof.get('compared_points') != len(parts)
            or proof.get('proven_points') != len(native_proven)
            or set(proof.get('non_equivalent_points') or []) != failed
            or set(proof.get('unproven_points') or []) != unknown):
        return {'status': 'NOT_MEASURED', 'reason': 'D44_PARTITION_CENSUS_INVALID'}
    value = len(unresolved)
    status = 'PASS' if value == 0 and proof.get('verdict') == 'PASS' else 'FAIL'
    return {'status': status, 'value': value, 'unit': 'count',
            'declared_partition_count': len(declared), 'unproved_partitions': unresolved}


def _mapping_binding(project, context, component, proof_metric):
    """Rebind the published common baseline to this exact D44 attempt."""
    if component.get('component_status') != 'PASS' or proof_metric.get('status') != 'PASS':
        return {'status': 'NOT_MEASURED', 'reason': 'D44_EQUIVALENCE_PREREQUISITE_UNMET'}
    path = project / BASELINE
    try:
        baseline = _read(path)
        prepared = prepare(project, context)
        proof_record = baseline.get('proof')
        if proof_record != component.get('proof_receipt'):
            raise AdmissionRefusal('D44_PROOF_RECEIPT_DIFFERS', str(proof_record), status='FAIL')
        proof_path = _bound(project, proof_record)
    except AdmissionRefusal as exc:
        return {'status': 'NOT_MEASURED' if not path.is_file() else 'FAIL',
                'reason': exc.code, 'detail': str(exc)}
    expected = {
        'schema': SCHEMA,
        'producer': 'flow109_final_lec',
        'context_sha256': context.get('context_sha256'),
        'source_sha256': prepared['sources'],
        'rtl': [_record(project, item) for item in prepared['paths']['rtl']],
        'adopted_netlist': _record(project, prepared['paths']['adopted_netlist']),
        'consumer_netlists': {role: _record(project, prepared['paths'][role])
                              for role in ('sta', 'lvs_reference', 'release')},
        'transformations': prepared['manifest']['transformations'],
        'mapping': 'same_logical_bytes',
        'consumer_adoption': 'NOT_MEASURED',
        'proof': proof_record,
    }
    if prepared.get('physical_input'):
        transform_record = component.get('transformation_receipt')
        try:
            transform = _read(_bound(project, transform_record))
            if (transform.get('kind') != physical.KIND
                    or transform.get('status') != 'PREPARED_NOT_EQUIVALENCE_PROVEN'
                    or transform.get('raw_adopted_netlist', {}).get('sha256')
                    != _sha(prepared['paths']['adopted_netlist'])):
                raise AdmissionRefusal('D44_PHYSICAL_RECEIPT_DIFFERS', str(transform_record))
            for input_path, digest in transform['inputs'].items():
                if (prepared['inputs'].get(input_path) != digest
                        or _sha(input_path) != digest):
                    raise AdmissionRefusal('D44_PHYSICAL_INPUT_MISMATCH', input_path)
            for value in transform['outputs'].values():
                _bound(project, value)
        except (AdmissionRefusal, KeyError, OSError) as exc:
            return {'status': 'FAIL', 'reason': 'D44_PHYSICAL_RECEIPT_DIFFERS', 'detail': str(exc)}
        expected['transformation_receipt'] = transform_record
    if baseline != expected:
        return {'status': 'FAIL', 'reason': 'D44_BASELINE_SUBJECT_MISMATCH'}
    if component.get('source_sha256') != prepared['sources']:
        return {'status': 'FAIL', 'reason': 'D44_OPERATION_SOURCE_CHANGED'}
    roles = baseline.get('consumer_netlists')
    records = [baseline.get('adopted_netlist')]
    if not isinstance(roles, dict) or set(roles) != {'sta', 'lvs_reference', 'release'}:
        return {'status': 'FAIL', 'reason': 'D44_CONSUMER_BASELINE_ABSENT'}
    records.extend(roles.values())
    try:
        paths = [_bound(project, item) for item in records]
    except AdmissionRefusal as exc:
        return {'status': 'FAIL', 'reason': exc.code, 'detail': str(exc)}
    if len({_sha(item) for item in paths}) != 1:
        return {'status': 'FAIL', 'reason': 'D44_CONSUMER_BASELINE_DIFFERS'}
    try:
        retained = _read(proof_path)
    except AdmissionRefusal as exc:
        return {'status': 'FAIL', 'reason': exc.code, 'detail': str(exc)}
    if retained != component.get('proof'):
        return {'status': 'FAIL', 'reason': 'D44_PROOF_RECEIPT_DIFFERS'}
    common = component.get('common_baseline')
    current_common = _record(project, path)
    if not isinstance(common, dict) or common != current_common:
        return {'status': 'FAIL', 'reason': 'D44_BASELINE_RECEIPT_DIFFERS',
                'detail': {'component': common, 'current': current_common}}
    return {'status': 'PASS', 'value': 'matches_adopted_reference',
            'reference': _record(project, path),
            'consumer_roles': ['lvs_reference', 'release', 'sta'],
            'consumer_adoption': 'NOT_MEASURED'}


def bind_metrics(project, context, component):
    """Bind D44's two metrics without promoting them to whole-flow acceptance."""
    project = Path(project).resolve()
    try:
        contract = _metric_contract(context)
    except AdmissionRefusal as exc:
        return {'schema': METRICS_SCHEMA, 'step_id': 'D44', 'status': exc.status,
                'reason': exc.code, 'detail': str(exc), 'metrics': {}}
    proof = _proof_binding(component.get('proof'))
    mapping = _mapping_binding(project, context, component, proof)
    metrics = {'final_lec_unproved': {**proof, 'obligation': contract['final_lec_unproved']},
               'sta_lvs_release_netlist_mapping': {
                   **mapping, 'obligation': contract['sta_lvs_release_netlist_mapping']}}
    statuses = {item['status'] for item in metrics.values()}
    status = 'FAIL' if 'FAIL' in statuses else ('PASS' if statuses == {'PASS'} else 'NOT_MEASURED')
    return {'schema': METRICS_SCHEMA, 'step_id': 'D44', 'status': status,
            'context_sha256': context.get('context_sha256'), 'metrics': metrics,
            'scope': 'D44 metric bindings only; not STA/LVS execution or whole-flow acceptance'}


def validate_common_baseline(project, receipt_ref):
    """Re-open D44's current producer, proof and common consumer baseline.

    This is the owning downstream boundary for D44 output.  A project-authored
    PASS document is not authority: the recorded D44 execution context, current
    operation sources, native proof and mapping metric must all revalidate.
    """
    project = Path(project).resolve()
    component = _read(_bound(project, receipt_ref))
    context = component.get('execution_context')
    if (component.get('schema') != SCHEMA or component.get('step_id') != 'D44'
            or component.get('component_status') != 'PASS'
            or not isinstance(context, dict)):
        raise AdmissionRefusal('D44_CURRENT_COMPONENT_REQUIRED',
                               'current D44 PASS receipt and execution context required')
    require_launch_admission(project, 'flow109.D44', {'flow109_context': context})
    if component.get('source_sha256') != operation_sources():
        raise AdmissionRefusal('D44_OPERATION_SOURCE_CHANGED', 'D44 producer or consumer changed')
    rebound = bind_metrics(project, context, component)
    proof = rebound.get('metrics', {}).get('final_lec_unproved', {})
    mapping = rebound.get('metrics', {}).get('sta_lvs_release_netlist_mapping', {})
    if rebound.get('status') != 'PASS' or proof.get('status') != 'PASS' or mapping.get('status') != 'PASS':
        reason = mapping.get('reason') or proof.get('reason') or rebound.get('reason')
        raise AdmissionRefusal('D44_CURRENT_BASELINE_NOT_ACCEPTED', str(reason))
    baseline_ref = mapping.get('reference')
    if baseline_ref != component.get('common_baseline'):
        raise AdmissionRefusal('D44_BASELINE_RECEIPT_DIFFERS', str(baseline_ref))
    baseline = _read(_bound(project, baseline_ref))
    return {'baseline': baseline_ref, 'adopted_netlist': baseline['adopted_netlist'],
            'consumer_netlists': baseline['consumer_netlists'], 'proof': baseline['proof'],
            'component': receipt_ref, 'component_current': True,
            'flow109_acceptance': 'NOT_MEASURED'}


def _consume_retained_native(project, prepared):
    """Re-open an actual EQY run without rerunning its already-complete proof.

    Changed orchestration or physical-view code is not declared compatible by
    name.  The caller must first reproduce byte-identical functional views with
    the current producer.  The proof kernel, image, native inputs, partition
    census and every retained status are then checked independently here.
    """
    path = prepared.get('retained_native')
    if path is None:
        raise AdmissionRefusal('D44_RETAINED_EVIDENCE_ABSENT', 'retained receipt required')
    retained = _read(path)
    required = {'native_receipt', 'operation_sources', 'preparation', 'proof',
                'reference_view', 'gate_view', 'config', 'state_in',
                'input_fingerprint', 'native_step_receipt', 'partition_list',
                'method_source', 'run_script'}
    base_keys = required | {'strategy_statuses', 'schema', 'status', 'image', 'scope'}
    optional_keys = {'current_preparation', 'argv'}
    if (retained.get('schema') != RETAINED_SCHEMA or retained.get('status') != 'PASS'
            or retained.get('image') != EDA_IMAGE or not base_keys <= set(retained)
            or set(retained) - base_keys > optional_keys):
        raise AdmissionRefusal('D44_RETAINED_RECEIPT_INVALID', str(path))
    files = {name: _project_bound(project, retained[name]) for name in required}
    native, proof = _read(files['native_receipt']), _read(files['proof'])
    original_sources = _read(files['operation_sources'])
    old_preparation = _read(files['preparation'])
    current_preparation = _read(_bound(project, prepared['transformation_receipt']))
    proof_paths = prepared.get('proof_paths') or {}
    if (native.get('component_status') != 'PASS' or native.get('native_status') != 'PASS'
            or native.get('image') != EDA_IMAGE or native.get('exit_code') != 0):
        raise AdmissionRefusal('D44_RETAINED_NATIVE_NOT_PASS', str(files['native_receipt']))
    if (native.get('source_closure', {}).get('sha256') != _sha(files['operation_sources'])
            or native.get('positive', {}).get('proof', {}).get('sha256') != _sha(files['proof'])
            or native.get('physical_preparation', {}).get('sha256') != _sha(files['preparation'])
            or native.get('raw_adopted_netlist', {}).get('sha256') !=
               _sha(prepared['paths']['adopted_netlist'])
            or native.get('reference_rtl', {}).get('sha256') != _sha(prepared['paths']['rtl'][0])):
        raise AdmissionRefusal('D44_RETAINED_SUBJECT_MISMATCH', str(files['native_receipt']))
    # Only the unchanged proof-producing kernel is inherited.  Adapter and
    # view-preparation changes are covered by current-source consumption and
    # exact regenerated view identity below, not by a blanket source waiver.
    current_sources = operation_sources()
    for source in ('programs/librelane_eqy.py', 'programs/lec_post_layout_check.py',
                   'native/librelane/steps/yosys.py'):
        if original_sources.get(source) != current_sources.get(source):
            raise AdmissionRefusal('D44_RETAINED_PROOF_SOURCE_CHANGED', source)
    for side, field in (('gold', 'reference_view'), ('gate', 'gate_view')):
        current = proof_paths['rtl'][0] if side == 'gold' else proof_paths['adopted_netlist']
        if (_sha(files[field]) != _sha(current)
                or old_preparation.get('outputs', {}).get(side, {}).get('sha256') != _sha(current)
                or current_preparation.get('outputs', {}).get(side, {}).get('sha256') != _sha(current)):
            raise AdmissionRefusal('D44_RETAINED_VIEW_CHANGED', side)
    if (old_preparation.get('kind') != physical.KIND
            or old_preparation.get('powered_mode') != current_preparation.get('powered_mode')
            or old_preparation.get('projected_supply_ports') !=
               current_preparation.get('projected_supply_ports')
            or old_preparation.get('functional_interfaces') !=
               current_preparation.get('functional_interfaces')):
        raise AdmissionRefusal('D44_RETAINED_TRANSFORMATION_CHANGED', str(files['preparation']))
    fingerprint, config = _read(files['input_fingerprint']), _read(files['config'])
    state, step_receipt = _read(files['state_in']), _read(files['native_step_receipt'])
    if (fingerprint.get('image') != EDA_IMAGE
            or proof.get('config_sha256') != _sha(files['config'])
            or fingerprint.get('state_files', {}).get(state.get('nl')) != _sha(files['gate_view'])
            or fingerprint.get('config_files', {}).get(config.get('VERILOG_FILES', [None])[0])
               != _sha(files['reference_view'])
            or step_receipt.get('input') != fingerprint):
        raise AdmissionRefusal('D44_RETAINED_NATIVE_INPUT_CHANGED', str(files['input_fingerprint']))
    if (config.get('DESIGN_NAME') != prepared['manifest']['top']
            or config.get('PDK') != prepared['manifest']['librelane']['PDK']
            or config.get('STD_CELL_LIBRARY') !=
               prepared['manifest']['librelane']['STD_CELL_LIBRARY']):
        raise AdmissionRefusal('D44_RETAINED_CONFIGURATION_CHANGED', str(files['config']))
    config_files = fingerprint.get('config_files') or {}
    models = config.get('CELL_VERILOG_MODELS')
    if (not isinstance(models, list) or not models
            or any(config_files.get(name) != _sha(name) for name in models)):
        raise AdmissionRefusal('D44_RETAINED_MODEL_INPUT_CHANGED', str(models))
    script_path = config.get('EQY_SCRIPT')
    original_script = eqy.eqy_script(
        prepared['manifest']['top'], [Path(name) for name in config['VERILOG_FILES']],
        Path(state['nl']), prepared['manifest']['liberty']['path'])
    if (not script_path or config_files.get(script_path) !=
            hashlib.sha256(original_script.encode()).hexdigest()):
        raise AdmissionRefusal('D44_RETAINED_CONFIGURATION_CHANGED', str(script_path))
    listing = files['partition_list']
    statuses = retained['strategy_statuses']
    if not isinstance(statuses, list) or not statuses:
        raise AdmissionRefusal('D44_RETAINED_PARTITIONS_ABSENT', 'strategy status population')
    evidence = proof.get('evidence_sha256') or {}
    expected = {'scratch/partition.list': _sha(listing)}
    for item in statuses:
        status_path = _project_bound(project, item)
        suffix = str(status_path).split('/scratch/', 1)
        if len(suffix) != 2:
            raise AdmissionRefusal('D44_RETAINED_PARTITIONS_INVALID', str(status_path))
        expected['scratch/' + suffix[1]] = _sha(status_path)
    if evidence != expected:
        raise AdmissionRefusal('D44_RETAINED_PARTITIONS_STALE', str(files['proof']))
    metric = _proof_binding(proof)
    if metric.get('status') != 'PASS':
        raise AdmissionRefusal(metric.get('reason', 'D44_RETAINED_PROOF_NOT_PASS'),
                               str(files['proof']), status=metric.get('status', 'NOT_MEASURED'))
    return proof, {'receipt': _record(project, path),
                   'original_source_closure': _record(project, files['operation_sources']),
                   'image': EDA_IMAGE, 'scope': retained['scope'],
                   'mode': 'current_views_exactly_match_retained_native_EQY_subject'}


def _retained_physical_views(project, prepared):
    """Re-open a current-source preparation receipt without rerunning its producer."""
    retained_path = prepared.get('retained_native')
    if retained_path is None:
        return None
    retained = _read(retained_path)
    current = retained.get('current_preparation')
    if current is None:
        return None
    receipt_path = _project_bound(project, current)
    views = _read(receipt_path)
    if (views.get('schema') != physical.SCHEMA or views.get('producer') !=
            'flow109_final_lec_physical' or views.get('status') !=
            'PREPARED_NOT_EQUIVALENCE_PROVEN' or views.get('kind') != physical.KIND):
        raise AdmissionRefusal('D44_RETAINED_TRANSFORMATION_INVALID', str(receipt_path))
    if (views.get('top') != prepared['manifest']['top']
            or views.get('raw_adopted_netlist', {}).get('sha256') !=
               _sha(prepared['paths']['adopted_netlist'])):
        raise AdmissionRefusal('D44_RETAINED_TRANSFORMATION_CHANGED', str(receipt_path))
    for input_path, digest in (views.get('inputs') or {}).items():
        if prepared['inputs'].get(input_path) != digest or _sha(input_path) != digest:
            raise AdmissionRefusal('D44_PHYSICAL_INPUT_MISMATCH', input_path)
    outputs = views.get('outputs')
    if not isinstance(outputs, dict) or set(outputs) != {'gold', 'gate'}:
        raise AdmissionRefusal('D44_RETAINED_VIEW_CHANGED', 'output population')
    for side, value in outputs.items():
        _bound(project, value)
    return views, _record(project, receipt_path)


def execute(project, context):
    project = Path(project).resolve()
    attempt = project / 'reports/flow109/D44' / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    record = {'schema': SCHEMA, 'step_id': 'D44', 'component_status': 'NOT_MEASURED',
              'flow109_acceptance': 'NOT_MEASURED', 'native_started': False,
              'context_sha256': context.get('context_sha256'), 'execution_context': context,
              'baseline_adoption': 'NOT_MEASURED'}
    try:
        require_launch_admission(project, 'flow109.D44', {'flow109_context': context})
        prepared = prepare(project, context)
        record.update(source_sha256=prepared['sources'], inputs=prepared['inputs'])
        def before():
            _before(project, context, prepared)
            record['native_started'] = True
        if prepared.get('physical_input'):
            retained_views = _retained_physical_views(project, prepared)
            if retained_views is not None:
                views, record['transformation_receipt'] = retained_views
                record['physical_preparation_reused'] = True
            else:
                view_dir = attempt / 'physical-views'
                try:
                    views = physical.produce(project, _bound(project, prepared['physical_input']),
                                             view_dir, before=before)
                except (ValueError, RuntimeError, KeyError) as exc:
                    raise AdmissionRefusal('D44_PHYSICAL_PROOF_INPUT_REFUSED', str(exc)) from exc
                record['transformation_receipt'] = _record(project, view_dir / 'preparation.json')
            prepared['proof_paths'] = {'rtl': [_bound(project, views['outputs']['gold'])],
                                      'adopted_netlist': _bound(project, views['outputs']['gate']),
                                      'liberty': prepared['paths']['liberty']}
            for name in ('gold', 'gate'):
                item = views['outputs'][name]
                prepared['inputs'][item['path']] = item['sha256']
            transformation_path = _bound(project, record['transformation_receipt'])
            prepared['inputs'][str(transformation_path)] = _sha(transformation_path)
            prepared['transformation_receipt'] = record['transformation_receipt']
        record['model_census'] = _model_census(project, prepared, attempt, before)
        if prepared.get('retained_native'):
            proof, adoption = _consume_retained_native(project, prepared)
            native_error, models = None, {}
            record.update(retained_native=adoption, native_proof_reused=True)
            write_json(attempt / 'eqy-result.json', proof)
        else:
            native_error, models = _native_eqy(project, prepared, attempt, before)
            proof = consume_eqy(attempt / 'native', attempt / 'eqy-result.json')
        record.update(native_error=native_error, preprocessing_models=models)
        record['proof'] = proof
        record['proof_receipt'] = _record(project, attempt / 'eqy-result.json')
        _before(project, context, prepared)
        record['component_status'] = {'PASS': 'PASS', 'FAIL': 'FAIL'}.get(proof['verdict'], 'NOT_MEASURED')
        record['reason'] = proof.get('explanation')
        if native_error and record['component_status'] == 'PASS':
            record.update(component_status='NOT_MEASURED', reason='D44_NATIVE_STEP_INCOMPLETE')
        if record['component_status'] == 'PASS':
            paths = prepared['paths']
            baseline = {'schema': SCHEMA, 'producer': 'flow109_final_lec',
                'context_sha256': context['context_sha256'],
                'source_sha256': prepared['sources'],
                'rtl': [_record(project, p) for p in paths['rtl']],
                'adopted_netlist': _record(project, paths['adopted_netlist']),
                'consumer_netlists': {r: _record(project, paths[r]) for r in ('sta', 'lvs_reference', 'release')},
                'transformations': prepared['manifest']['transformations'], 'mapping': 'same_logical_bytes',
                'consumer_adoption': 'NOT_MEASURED', 'proof': record['proof_receipt']}
            if record.get('transformation_receipt'):
                baseline['transformation_receipt'] = record['transformation_receipt']
            write_json(project / BASELINE, baseline)
            record['common_baseline'] = _record(project, project / BASELINE)
    except AdmissionRefusal as exc:
        record.update(component_status=exc.status, reason=exc.code, detail=str(exc))
    except (ImportError, OSError, ValueError) as exc:
        record.update(component_status='NOT_MEASURED', reason='D44_NATIVE_UNAVAILABLE_OR_UNSUPPORTED', detail=str(exc))
    record['metric_bindings'] = bind_metrics(project, context, record)
    record['metric_acceptance'] = accept_d44(project, context, record)
    record['metric_acceptance_status'] = record['metric_acceptance']['status']
    record['unimplemented_obligations'] = [
        item['id'] for item in record['metric_acceptance']['obligations']
        if item['status'] == 'UNIMPLEMENTED_METRIC_BINDING']
    record['receipt'] = {'path': str((attempt / 'component.json').relative_to(project))}
    write_json(attempt / 'component.json', record)
    return record
