"""D62: the native PDK filler and its density-deck result."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from flow109_admission import AdmissionRefusal, require_launch_admission
from flow109_metric_acceptance import MetricRefusal, accept_d62, d62_authorities

INPUT = 'input/flow109/D62.json'
SCRIPT = HERE / 'flow109_density_fill.tcl'
CHECK_SCRIPT = HERE / 'flow109_density_checks.tcl'
SCHEMA = 'vibeic.flow109.density-fill.v1'


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def operation_sources():
    # These are the local executable sources this small adapter actually uses.
    # stdlib imports do not introduce unrelated legacy producer dependencies.
    paths = [Path(__file__), SCRIPT, CHECK_SCRIPT, HERE / 'flow109_admission.py', HERE / 'flow109.py',
             HERE / 'flow109_metric_acceptance.py']
    return {str(p.relative_to(HERE.parent)): _sha(p) for p in paths}


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


def _read(path):
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise AdmissionRefusal('D62_INPUT_ABSENT', str(path)) from exc
    if not isinstance(value, dict):
        raise AdmissionRefusal('D62_INPUT_INVALID', str(path))
    return value


def _bound(project, entry):
    if not isinstance(entry, dict) or not isinstance(entry.get('path'), str) or not entry.get('sha256'):
        raise AdmissionRefusal('D62_INPUT_UNBOUND', str(entry))
    path = (project / entry['path']).resolve()
    if not path.is_file():
        raise AdmissionRefusal('D62_INPUT_ABSENT', str(path))
    if _sha(path) != entry['sha256']:
        raise AdmissionRefusal('D62_INPUT_STALE', str(path))
    return path


def _record(project, path):
    path = Path(path).resolve()
    return {'path': str(path.relative_to(project)) if path.is_relative_to(project) else str(path),
            'sha256': _sha(path)}


def prepare(project, context):
    """Validate complete invocation inputs before any native launch."""
    project = Path(project).resolve()
    if context.get('requested_step') != 'D62' or context.get('native_step_id') != 'flow109.D62':
        raise AdmissionRefusal('D62_CONTEXT_MISMATCH', 'D62 ODB adapter only')
    runtime = context.get('runtime_tool_uses')
    if not isinstance(runtime, list) or len(runtime) != 1 or runtime[0].get('tool_id') != 'openroad':
        raise AdmissionRefusal('D62_TOOL_UNBOUND', 'one source-owned OpenROAD use required')
    use = runtime[0]
    if use.get('semantics', {}).get('operation_sources') != operation_sources():
        raise AdmissionRefusal('D62_OPERATION_SOURCE_CHANGED', 'qualification does not bind current operation')
    manifest = _read(project / INPUT)
    if manifest.get('schema') != SCHEMA:
        raise AdmissionRefusal('D62_INPUT_INVALID', 'unsupported invocation schema')
    paths = {key: _bound(project, manifest.get(key)) for key in ('input_odb', 'rules', 'pdk')}
    for role, key in [('rules', 'deck'), ('pdk', 'pdk')]:
        current = _bound(project, use.get(key))
        if current != paths[role] or use[key]['sha256'] != manifest[role]['sha256']:
            raise AdmissionRefusal('D62_RULES_NOT_QUALIFIED', role)
    config_path = _bound(project, use.get('config'))
    config = _read(config_path)
    if config != {'schema': SCHEMA, 'operation': 'density_fill', 'area': 'core'}:
        raise AdmissionRefusal('D62_CONFIGURATION_UNSUPPORTED', 'qualified native core-area operation required')
    rules = _read(paths['rules'])
    if not isinstance(rules.get('layers'), dict) or not rules['layers']:
        raise AdmissionRefusal('D62_RULES_ABSENT', 'native OpenROAD layers rules required')
    executable = _bound(project, use.get('executable'))
    inputs = {key: _record(project, path) for key, path in
              {**paths, 'config': config_path, 'executable': executable}.items()}
    try:
        authorities = d62_authorities(project, inputs)
    except MetricRefusal as exc:
        if exc.code != 'METRIC_AUTHORITY_ABSENT':
            raise AdmissionRefusal(exc.code, exc.detail) from exc
        # Additional audit documents are not native density_fill inputs.
        # Preserve the existing qualified fill/readback path; the metric
        # consumer still refuses density acceptance without those documents.
        authorities = {}
    authority_inputs = {}
    for name, authority in authorities.items():
        authority_inputs[name] = {'path': authority['path'], 'sha256': authority['sha256']}
        authority_inputs[name + '_source'] = authority['source']
    return {'paths': paths, 'executable': executable, 'config_path': config_path,
            'manifest': _record(project, project / INPUT),
            'inputs': inputs, 'authorities': authorities,
            'authority_inputs': authority_inputs,
            'tool': {key: use[key] for key in ('tool_id', 'version', 'build_sha256', 'executable')},
            'operation_sources': operation_sources()}


def _call(executable, env, log):
    argv = [str(executable), '-no_init', '-exit', str(SCRIPT)]
    with log.open('w') as stream:
        result = subprocess.run(argv,
                                env={**os.environ, **env}, stdout=stream,
                                stderr=subprocess.STDOUT)
    if result.returncode:
        raise AdmissionRefusal('D62_NATIVE_FAILED', f'rc={result.returncode}; {log}', status='FAIL')
    return {'argv': argv, 'returncode': result.returncode,
            'path_bindings': {key: env[key] for key in sorted(env)}}


def _native_checks(prepared, attempt, before_launch):
    """Run current-ODB density and native fill-obstruction checks."""
    authority = prepared['authorities']['density']
    limits = attempt / 'density-limits.txt'
    lines = ['# approved per-layer density bands; -1 means no stated bound']
    for layer, band in sorted(authority['limits'].items()):
        low = -1.0 if band['min'] is None else band['min']
        high = -1.0 if band['max'] is None else band['max']
        lines.append(f'{layer} {low} {high}')
    limits.write_text('\n'.join(lines) + '\n')
    scope = authority['scope']
    env = {
        'VIBEIC_D62_FILLED_ODB': str(attempt / 'filled.odb'),
        'VIBEIC_D62_DENSITY_LIMITS': str(limits),
        'VIBEIC_D62_DENSITY_WINDOW_UM': str(scope['window_um']),
        'VIBEIC_D62_DENSITY_STEP_UM': str(scope['step_um']),
        'VIBEIC_D62_DENSITY_REPORT': str(attempt / 'density.csv'),
        'VIBEIC_D62_CHECK_CENSUS': str(attempt / 'checker.census'),
    }
    before_launch()
    argv = [str(prepared['executable']), '-no_init', '-exit', str(CHECK_SCRIPT)]
    with (attempt / 'checker.log').open('w') as stream:
        result = subprocess.run(argv, env={**os.environ, **env},
                                stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        raise AdmissionRefusal('D62_CHECKER_FAILED',
            f'rc={result.returncode}; {attempt / "checker.log"}', status='FAIL')
    if not (attempt / 'density.csv').is_file() or not (attempt / 'checker.census').is_file():
        raise AdmissionRefusal('D62_CHECKER_OUTPUT_ABSENT', str(attempt), status='FAIL')
    prepared.setdefault('executions', []).append({
        'role': 'current_odb_metric_checker', 'argv': argv,
        'returncode': result.returncode,
        'read_set': {
            'filled_odb': env['VIBEIC_D62_FILLED_ODB'],
            'density_limits': env['VIBEIC_D62_DENSITY_LIMITS']},
        'path_bindings': {key: env[key] for key in sorted(env)}})


def _fill_records(text):
    matches = list(re.finditer(r'(?ms)^FILLS\s+(\d+)\s*;\s*\n(.*?)^END FILLS\s*\n', text))
    if len(matches) > 1:
        raise AdmissionRefusal('D62_DEF_INVALID', 'duplicate fill sections', status='FAIL')
    if not matches:
        return text, []
    match = matches[0]
    shapes = [' '.join(row.split()) for row in re.findall(r'(?ms)^\s*(-\s+(?:LAYER|VIA)\b.*?;)', match[2])]
    if len(shapes) != int(match[1]):
        raise AdmissionRefusal('D62_FILL_CENSUS_MISMATCH', 'DEF count differs from fill records', status='FAIL')
    return text[:match.start()] + text[match.end():], shapes


def _geometry_proof(before, filled, readback):
    original, old = _fill_records(before.read_text())
    result, new = _fill_records(filled.read_text())
    verified, reread = _fill_records(readback.read_text())
    if original != result or result != verified:
        raise AdmissionRefusal('D62_NONFILL_GEOMETRY_CHANGED', 'DEF geometry/connectivity changed', status='FAIL')
    if Counter(old) - Counter(new) or Counter(new) != Counter(reread):
        raise AdmissionRefusal('D62_FILL_GEOMETRY_CHANGED', 'retained or ODB-readback fill differs', status='FAIL')
    return {'fill_count_before': len(old), 'fill_count_after': len(new),
            'fill_count_added': len(new) - len(old), 'nonfill_geometry_preserved': True,
            'odb_readback_matches': True, 'density_signoff': 'NOT_MEASURED'}


def _native_fill(project, prepared, attempt, before_launch):
    """Actual native producer and independent ODB readback, also used by smoke tests."""
    attempt.mkdir(parents=True, exist_ok=False)
    env = {'VIBEIC_D62_MODE': 'produce',
           'VIBEIC_D62_INPUT_ODB': str(prepared['paths']['input_odb']),
           'VIBEIC_D62_RULES': str(prepared['paths']['rules']),
           'VIBEIC_D62_BEFORE_DEF': str(attempt / 'before.def'),
           'VIBEIC_D62_OUTPUT_ODB': str(attempt / 'filled.odb'),
           'VIBEIC_D62_OUTPUT_DEF': str(attempt / 'filled.def'),
           'VIBEIC_D62_CENSUS': str(attempt / 'producer.census')}
    before_launch()
    execution = _call(prepared['executable'], env, attempt / 'producer.log')
    if execution is not None:
        prepared.setdefault('executions', []).append(
            {'role': 'fill_producer',
             'read_set': {'input_odb': env['VIBEIC_D62_INPUT_ODB'],
                          'rules': env['VIBEIC_D62_RULES']}, **execution})
    if not (attempt / 'filled.odb').is_file():
        raise AdmissionRefusal('D62_OUTPUT_ABSENT', 'native tool did not write ODB')
    env.update(VIBEIC_D62_MODE='verify', VIBEIC_D62_INPUT_ODB=str(attempt / 'filled.odb'),
               VIBEIC_D62_OUTPUT_DEF=str(attempt / 'readback.def'),
               VIBEIC_D62_CENSUS=str(attempt / 'consumer.census'))
    before_launch()
    execution = _call(prepared['executable'], env, attempt / 'consumer.log')
    if execution is not None:
        prepared.setdefault('executions', []).append(
            {'role': 'independent_odb_readback',
             'read_set': {'filled_odb': env['VIBEIC_D62_INPUT_ODB']}, **execution})
    proof = _geometry_proof(attempt / 'before.def', attempt / 'filled.def', attempt / 'readback.def')
    producer = (attempt / 'producer.census').read_text().split()
    consumer = (attempt / 'consumer.census').read_text().split()
    expected = ['BEFORE', str(proof['fill_count_before']), 'AFTER', str(proof['fill_count_after'])]
    if producer != expected or consumer != ['BEFORE', expected[-1], 'AFTER', expected[-1]]:
        raise AdmissionRefusal('D62_ODB_CENSUS_MISMATCH', 'native ODB and DEF fill counts differ', status='FAIL')
    return proof


def validate_filled_odb(project, receipt_ref):
    """D69 consumes this explicit D62 receipt, never a legacy GDS fill PASS."""
    project = Path(project).resolve()
    receipt = _read(_bound(project, receipt_ref))
    if receipt.get('schema') != SCHEMA or receipt.get('component_status') != 'PASS':
        raise AdmissionRefusal('D62_OUTPUT_NOT_ACCEPTED', 'current D62 component receipt required')
    qualification = receipt.get('qualification', {})
    if qualification.get('status') != 'PASS' or not qualification.get('uses'):
        raise AdmissionRefusal('D62_QUALIFICATION_NOT_VERIFIED', 'qualified producer binding required')
    if receipt.get('operation_sources') != operation_sources():
        raise AdmissionRefusal('D62_OPERATION_SOURCE_CHANGED', 'D62 implementation changed')
    _bound(project, receipt['manifest'])
    for entry in receipt['inputs'].values():
        _bound(project, entry)
    for entry in receipt.get('authority_inputs', {}).values():
        _bound(project, entry)
    paths = {name: _bound(project, entry) for name, entry in receipt['outputs'].items()}
    proof = _geometry_proof(paths['before.def'], paths['filled.def'], paths['readback.def'])
    if proof != receipt['measurements']:
        raise AdmissionRefusal('D62_OUTPUT_NOT_ACCEPTED', 'consumer measurement changed')
    return {'odb': receipt['outputs']['filled.odb'], 'receipt': receipt_ref,
            'measurements': proof, 'qualification': receipt['qualification'],
            'flow109_acceptance': 'NOT_MEASURED',
            'extraction_fill_sensitivity': 'NOT_VERIFIED'}


def _gds_sources():
    paths = [Path(__file__), HERE / 'metal_fill_emit.py',
             HERE / '_klayout_launch.py', HERE / '_metal_fill_capacity.py',
             HERE / '_inplace_chain.py', HERE / 'flow109_admission.py',
             HERE / '_pdk_fill_readback.py']
    return {str(p.relative_to(HERE.parent)): _sha(p) for p in paths}


def _gds_input(project, entry):
    """Explicit project input, never a pick-first stream or another carrier."""
    if (not isinstance(entry, dict) or not isinstance(entry.get('path'), str)
            or Path(entry['path']).is_absolute() or '..' in Path(entry['path']).parts):
        raise AdmissionRefusal('D62_GDS_INPUT_UNBOUND', 'project-relative path/SHA required')
    path = _bound(project, entry)
    if not path.is_relative_to(project) or (project / entry['path']).is_symlink():
        raise AdmissionRefusal('D62_GDS_INPUT_FOREIGN', entry['path'])
    return path


def _discover_pdk_filler(project, manifest):
    """Discover native all-layer entry points by PDK files, never kit names.

    A bound PDK metadata document supplies name/root; otherwise use the
    explicitly selected PDK and PDK_ROOT in this launched runtime. No PDK is
    guessed from layout contents or a default kit.
    """
    metadata = _read(_bound(project, manifest['pdk'])) if manifest.get('pdk') else {}
    switch = project / 'phase3/librelane_switch.json'
    settings = _read(switch) if switch.is_file() else {}
    name = metadata.get('name') or settings.get('pdk') or os.environ.get('PDK')
    root = metadata.get('root')
    if not root:
        parent = settings.get('pdk_root_host') or os.environ.get('VIBEIC_LIBRELANE_PDK_ROOT') or os.environ.get('PDK_ROOT')
        root = str(Path(parent) / name) if parent and name else None
    if not root:
        return None
    kit = Path(root)
    if not kit.is_dir():
        raise AdmissionRefusal('D62_PDK_ROOT_ABSENT', str(kit))
    base = kit / 'libs.tech/klayout'
    scripts = [p for p in base.rglob('*') if p.is_file() and p.name in ('filler.py', 'fill_all.rb')]
    if len(scripts) > 1:
        raise AdmissionRefusal('D62_PDK_FILLER_AMBIGUOUS', str(scripts))
    if not scripts:
        return None
    import xml.etree.ElementTree as ET
    technologies = sorted(base.rglob('*.lyt'))
    if len(technologies) > 1:
        raise AdmissionRefusal('D62_PDK_TECHNOLOGY_AMBIGUOUS', str(technologies))
    technology = ET.parse(technologies[0]).findtext('name') if technologies else None
    # Native macros load dependencies relative to this tree. Bind the whole
    # tree instead of claiming that hashing the entry point binds its decks.
    sources = {str(p): _sha(p) for p in sorted(base.rglob('*')) if p.is_file()}
    return {'path': str(scripts[0].resolve()), 'sha256': _sha(scripts[0]),
            'kit': str(kit), 'technology': technology, 'sources': sources,
            'contract': 'active_layout_output_file' if scripts[0].name == 'filler.py' else 'input_output'}


def _execute_pdk_gds(project, context, manifest_path, manifest, paths, attempt, result, native):
    """Blocking native transform; density acceptance remains native DRC's job.

    A native failure never retries the generic fill engine. A successful
    transformation never issues a density/whole-row PASS or ODB handoff.
    """
    import librelane_contract as launch
    result.update(inputs={k: _record(project, p) for k, p in paths.items()},
                  manifest=_record(project, manifest_path), engine=native,
                  operation_sources=_gds_sources())
    try:
        if manifest.get('pdk'):
            result['inputs']['pdk'] = _record(project, _bound(project, manifest['pdk']))
        cell = manifest.get('cell')
        if not isinstance(cell, str) or not cell.strip():
            raise AdmissionRefusal('D62_GDS_CELL_UNBOUND', 'explicit input top cell required')
        binary = shutil.which('klayout')
        if not binary:
            raise AdmissionRefusal('D62_KLAYOUT_UNAVAILABLE', 'local KLayout required')
        executable = Path(binary).resolve()
        result['tool'] = {'path': str(executable), 'sha256': _sha(executable)}
        result['launch_admission'] = require_launch_admission(project, 'flow109.D62', {'flow109_context': context})
        result['native_launch'] = launch.local_image_attestation()
        output = attempt / 'filled.gds'
        kit = Path(native['kit'])
        env = {**os.environ, 'PDK_ROOT': str(kit.parent), 'PDK': kit.name,
               'KLAYOUT_PATH': str(kit / 'libs.tech/klayout') + os.pathsep + os.environ.get('KLAYOUT_PATH', ''),
               'QT_QPA_PLATFORM': 'offscreen'}
        argv = [str(executable)]
        if native['contract'] == 'active_layout_output_file':
            argv += ['-zz']
            if native['technology']:
                argv += ['-n', native['technology']]
            argv += ['-r', native['path'], '-rd', 'output_file=' + str(output), str(paths['input_gds'])]
        else:
            argv += ['-b', '-r', native['path'], '-rd', 'input=' + str(paths['input_gds']),
                     '-rd', 'output=' + str(output), '-rd', 'threads=2']
        result['native_started'] = True
        proc = subprocess.run(argv, capture_output=True, text=True, env=env)
        (attempt / 'producer.stdout').write_text(proc.stdout)
        (attempt / 'producer.stderr').write_text(proc.stderr)
        result['execution'] = {'argv': argv, 'returncode': proc.returncode,
                               'environment': {k: env[k] for k in ('PDK_ROOT', 'PDK', 'KLAYOUT_PATH', 'QT_QPA_PLATFORM')}}
        if proc.returncode:
            raise AdmissionRefusal('D62_PDK_FILL_FAILED', f'rc={proc.returncode}', status='FAIL')
        if not output.is_file() or not output.stat().st_size:
            raise AdmissionRefusal('D62_PDK_FILL_OUTPUT_ABSENT', str(output), status='FAIL')
        report = attempt / 'readback.json'
        read_env = {**env, 'D62_BEFORE': str(paths['input_gds']), 'D62_AFTER': str(output),
                    'D62_CELL': cell, 'D62_READBACK': str(report)}
        require_launch_admission(project, 'flow109.D62', {'flow109_context': context})
        argv = [str(executable), '-b', '-r', str(HERE / '_pdk_fill_readback.py')]
        check = subprocess.run(argv, capture_output=True, text=True, env=read_env)
        (attempt / 'readback.log').write_text(check.stdout + check.stderr)
        result['readback_execution'] = {'argv': argv, 'returncode': check.returncode}
        if check.returncode or not report.is_file():
            raise AdmissionRefusal('D62_PDK_FILL_READBACK_FAILED', str(report), status='FAIL')
        result['measurements'] = _read(report)
        if not result['measurements'].get('original_polygon_geometry_preserved'):
            raise AdmissionRefusal('D62_PDK_FILL_GEOMETRY_LOST', str(report), status='FAIL')
        result['component_status'] = 'PASS'
    except AdmissionRefusal as exc:
        result.update(component_status='FAIL' if exc.status == 'FAIL' else 'NOT_MEASURED', reason=exc.code, detail=str(exc))
    except (OSError, ValueError, KeyError, TypeError, launch.Refusal) as exc:
        result.update(reason='D62_PDK_FILL_INCOMPLETE', detail=str(exc))
    try:
        _bound(project, result['manifest'])
        for entry in result['inputs'].values():
            _bound(project, entry)
        current = _discover_pdk_filler(project, manifest)
        if current != native or result['operation_sources'] != _gds_sources():
            raise AdmissionRefusal('D62_PDK_FILL_STALE', 'native PDK/source changed')
        if result.get('native_started') and (_sha(result['tool']['path']) != result['tool']['sha256'] or launch.local_image_attestation() != result['native_launch']):
            raise AdmissionRefusal('D62_PDK_FILL_STALE', 'tool/image changed')
    except (AdmissionRefusal, OSError, ValueError, KeyError, TypeError, launch.Refusal) as exc:
        result.update(component_status='NOT_MEASURED', reason='D62_PDK_FILL_STALE', detail=str(exc))
    result['outputs'] = {p.name: _record(project, p) for p in attempt.iterdir() if p.is_file()}
    receipt = attempt / 'receipt.json'
    _write(receipt, result)
    result['receipt'] = _record(project, receipt)
    result['metric_acceptance'] = accept_d62(project, context, result)
    result['metric_acceptance_status'] = result['metric_acceptance']['status']
    result['default_row_status'] = result['metric_acceptance_status']
    result['completed'] = False
    return result


def _execute_gds(project, context):
    """Existing KLayout fill component; no ODB or final-geometry credit.

    The actual emitter owns density/floor/keepout semantics. This caller binds
    its explicit stream and rule config and preserves its negative verdict.
    Full D62 metrics still use their existing qualified consumer and refuse
    unsupported GDS qualification; a component PASS is never row signoff.
    """
    import metal_fill_emit as emitter
    import librelane_contract as launch
    import _klayout_launch as klayout
    project = Path(project).resolve()
    attempt = project / 'phase3/flow109/D62' / (
        datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex[:8])
    attempt.mkdir(parents=True, exist_ok=False)
    result = {'schema': SCHEMA, 'step_id': 'D62', 'geometry_format': 'GDS',
              'component_status': 'NOT_MEASURED', 'native_started': False,
              'context_sha256': context['context_sha256'],
              'flow109_acceptance': 'NOT_MEASURED', 'whole_flow_acceptance': 'NOT_MEASURED',
              'qualification_status': 'NOT_MEASURED', 'completed': False}
    try:
        if context.get('requested_step') != 'D62' or context.get('native_step_id') != 'flow109.D62':
            raise AdmissionRefusal('D62_CONTEXT_MISMATCH', 'registered D62 GDS component required')
        manifest_path = project / INPUT
        manifest = _read(manifest_path)
        if manifest.get('schema') != SCHEMA:
            raise AdmissionRefusal('D62_INPUT_INVALID', 'existing D62 invocation schema required')
        paths = {'input_gds': _gds_input(project, manifest.get('input_gds'))}
        native = _discover_pdk_filler(project, manifest)
        if native is not None:
            return _execute_pdk_gds(project, context, manifest_path, manifest, paths, attempt, result, native)
        paths['rules'] = _gds_input(project, manifest.get('rules'))
        cfg = _read(paths['rules'])
        if not isinstance(cfg.get('layers'), list) or not cfg['layers']:
            raise AdmissionRefusal('D62_RULES_ABSENT', 'declared per-layer GDS fill configuration required')
        cell = manifest.get('cell')
        if not isinstance(cell, str) or not cell.strip():
            raise AdmissionRefusal('D62_GDS_CELL_UNBOUND', 'explicit input top cell required')
        # Remain in this launched runtime. Never attach a shared container via
        # the legacy launcher's docker-exec fallback when KLayout is absent.
        binary = shutil.which('strmrun') or shutil.which('klayout')
        if not binary:
            raise AdmissionRefusal('D62_KLAYOUT_UNAVAILABLE', 'local KLayout required')
        runner = klayout.find_runner()
        if not isinstance(runner, klayout.HostRunner):
            raise AdmissionRefusal('D62_KLAYOUT_UNAVAILABLE', 'current runtime host runner required')
        executable = Path(binary).resolve()
        # This source-owned method uses the existing vendored engine. A stale
        # image override must not silently ignore the source's declared
        # protected-instance configuration. The normal locator consumes this
        # explicit root in the child; no global/runtime install is changed.
        engine = HERE / 'metal_fill/metal_fill.py'
        if not engine.is_file():
            raise AdmissionRefusal('D62_GDS_ENGINE_UNAVAILABLE', 'existing density-fill engine absent')
        sources = _gds_sources()
        result.update(inputs={k: _record(project, p) for k, p in paths.items()},
                      manifest=_record(project, manifest_path), operation_sources=sources,
                      engine={'path': str(engine.resolve()), 'sha256': _sha(engine)},
                      tool={'path': str(executable), 'sha256': _sha(executable),
                            'runner': runner.detail})
        result['launch_admission'] = require_launch_admission(
            project, 'flow109.D62', {'flow109_context': context})
        result['native_launch'] = launch.local_image_attestation()
        output, report, observed = (attempt / n for n in ('filled.gds', 'fill-report.json', 'emitter-result.json'))
        argv = [sys.executable, '-B', str(HERE / 'metal_fill_emit.py'), str(project),
                '--gds', str(paths['input_gds']), '--config', str(paths['rules']),
                '--out', str(output), '--cell', cell, '--report', str(report), '--json', str(observed)]
        result['native_started'] = True
        proc = subprocess.run(argv, capture_output=True, text=True,
                              env={**os.environ, 'VIBEIC_KLAYOUT_TOOLS': str(HERE)})
        (attempt / 'producer.stdout').write_text(proc.stdout)
        (attempt / 'producer.stderr').write_text(proc.stderr)
        result['execution'] = {'argv': argv, 'returncode': proc.returncode,
                               'environment': {'VIBEIC_KLAYOUT_TOOLS': str(HERE)}}
        emitted = _read(observed)
        result['emitter_result'] = emitted
        if proc.returncode == emitter.SKIP or emitted.get('verdict') == 'DISCLOSED_SKIP':
            raise AdmissionRefusal('D62_GDS_FILL_NOT_MEASURED', emitted.get('reason', 'emitter did not run'))
        if proc.returncode != emitter.PASS:
            raise AdmissionRefusal('D62_GDS_FILL_FAILED', emitted.get('reason', 'native density target not reached'), status='FAIL')
        above_floor = (emitter._clears_foundry_floor(emitted, cfg)
                       if emitted.get('verdict') == 'PARTIAL' else None)
        success = (emitted.get('verdict') == 'PASS' or (above_floor is not None
                   and emitted.get('promoted_on_foundry_floor') == above_floor))
        if not success:
            raise AdmissionRefusal('D62_GDS_FILL_FAILED',
                'emitter verdict does not satisfy its existing success semantics',
                status='FAIL' if emitted.get('verdict') in ('FAIL', 'PARTIAL') else 'NOT_MEASURED')
        reread = emitter.verify_only(project, str(report))
        raw = _read(report)
        if (reread.get('verdict') != emitted.get('verdict')
                or raw.get('layers') != emitted.get('layers')
                or emitted.get('runner') != 'host:' + runner.detail
                or Path(raw.get('gds_in', '')).resolve() != paths['input_gds']
                or Path(raw.get('gds_out', '')).resolve() != output.resolve()
                or not isinstance(raw.get('layers'), list) or not raw['layers']
                or not output.is_file() or output.stat().st_size == 0):
            raise AdmissionRefusal('D62_GDS_REPORT_UNBOUND', 'fresh native report/output/runner mismatch', status='FAIL')
        result['verify_only'] = reread
        result['component_status'] = 'PASS'
    except AdmissionRefusal as exc:
        result.update(component_status='FAIL' if exc.status == 'FAIL' else 'NOT_MEASURED',
                      reason=exc.code, detail=str(exc))
    except (OSError, ValueError, KeyError, TypeError, launch.Refusal) as exc:
        result.update(reason='D62_GDS_EXECUTION_INCOMPLETE', detail=str(exc))
    # Reopen bindings even on a native negative, retaining all raw failed data.
    try:
        for entry in result.get('inputs', {}).values():
            _gds_input(project, entry)
        if result.get('manifest'):
            _bound(project, result['manifest'])
        if result.get('native_started') and (
                _gds_sources() != result['operation_sources']
                or (HERE / 'metal_fill/metal_fill.py').resolve() != Path(result['engine']['path'])
                or _sha(Path(result['engine']['path'])) != result['engine']['sha256']
                or _sha(Path(result['tool']['path'])) != result['tool']['sha256']
                or launch.local_image_attestation() != result['native_launch']):
            raise AdmissionRefusal('D62_GDS_EXECUTION_STALE', 'source/tool/launch changed during native execution')
    except (AdmissionRefusal, OSError, ValueError, KeyError, TypeError, launch.Refusal) as exc:
        result.update(component_status='NOT_MEASURED', reason='D62_GDS_BINDING_STALE', detail=str(exc))
    result['outputs'] = {p.name: _record(project, p) for p in attempt.iterdir() if p.is_file()}
    receipt = attempt / 'receipt.json'
    _write(receipt, result)
    result['receipt'] = _record(project, receipt)
    result['metric_acceptance'] = accept_d62(project, context, result)
    result['metric_acceptance_status'] = result['metric_acceptance']['status']
    result['default_row_status'] = result['metric_acceptance_status']
    # The existing metric consumer cannot qualify this new GDS method merely
    # from its native component verdict; no accepted ODB/GDS handoff is issued.
    result['completed'] = False
    return result


def execute(project, context):
    """Run the native PDK filler, or reuse its unchanged native density result."""
    if context.get('resolved_row', {}).get('profile', {}).get('id') == 'gds_only_analog':
        return _execute_gds(project, context)
    import librelane_contract as contract
    import librelane_fill_dfm as native
    import phase3_one_shot_runner as runner
    project = Path(project).resolve()
    result = {'schema': SCHEMA, 'step_id': 'D62', 'component_status': 'NOT_MEASURED',
              'default_row_status': 'NOT_MEASURED', 'completed': False,
              'native_started': False, 'context_sha256': context.get('context_sha256')}
    try:
        doc = (native._load(project / native.RECORD_REL)
               if (project / native.RECORD_REL).is_file() else {})
        arm = (doc.get('gds') or {}).get('librelane')
        row = native.validate_density_result(project, arm) if arm else {}
        if arm:
            try:
                native._current_stage(project, contract.project_path(project, arm['filler']['state']),
                                      'KLayout.Filler')
            except (OSError, ValueError, KeyError, TypeError, contract.Refusal):
                row = {}
        if native._count(row.get('value')) is None:
            promotion = native._load(project / native.DEFAULT_STREAM_REL)
            gds = contract.project_path(project, promotion['sealed'])
            pdk = runner._detect_pdk(project)
            if pdk is None:
                raise ValueError('project PDK not available')
            image, root = runner._librelane_step_ctx(project, '34', pdk.name)
            result['native_started'] = True
            arm = native.run_density(project, image, root, pdk.name, gds=gds,
                                      lane='34-fill', steps=native.GDS_FILL_STEPS)
            if arm[native.DENSITY_METRIC] == 0:
                subject = contract.project_path(project, arm['subject'])
                promotion['source'] = str(subject)
                promotion['source_sha256'] = contract.digest(subject)
                for key in ('canonical', 'pnr_gds'):
                    target = contract.project_path(project, promotion[key])
                    shutil.copyfile(subject, target)
                    promotion[key + '_sha256'] = contract.digest(target)
                native.write_json(project / native.DEFAULT_STREAM_REL, promotion)
                native.update_record(project, 'default_stream', promotion)
            native.update_record(project, 'gds', {'mode': 'librelane',
                'librelane': arm, 'shipped': 'librelane' if arm[native.DENSITY_METRIC] == 0 else None})
            row = native.validate_density_result(project, arm)
        count = native._count(row.get('value'))
        status = 'NOT_MEASURED' if count is None else 'PASS' if count == 0 else 'FAIL'
        result.update(component_status=status, default_row_status=status,
            flow109_acceptance=status, completed=status == 'PASS',
            native_step='KLayout.Filler / KLayout.Density / Checker.KLayoutDensity',
            native_report=str(contract.project_path(project, arm['state'])),
            metrics={native.DENSITY_METRIC: count}, reason=row.get('reason'))
    except (OSError, ValueError, KeyError, TypeError, contract.Refusal) as exc:
        result.update(reason='D62_NATIVE_FILL_UNAVAILABLE', detail=str(exc))
    _write(project / 'reports/flow109/D62/result.json', result)
    return result
