"""D69 native owner: final State -> OpenROAD.RCX min/nom/max SPEFs for STA.

The final-fill tool's net totals sit beside the result as a comparison only.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import uuid
import shutil
import subprocess

import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _atomic_artefact import write_json
from flow109_admission import AdmissionRefusal, require_launch_admission
import flow109_density_fill as density
import librelane_fill_stream as files
import librelane_signoff as signoff
from librelane_contract import Refusal
from spef_extraction_check import scan_spef

SCHEMA = 'vibeic.flow109.final-extract.v1'
INPUT = 'input/flow109/D69.json'


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path):
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise AdmissionRefusal('D69_REQUIRED_INPUT_ABSENT', str(path)) from exc
    if not isinstance(value, dict):
        raise AdmissionRefusal('D69_REQUIRED_INPUT_INVALID', str(path))
    return value


def _bound(project, ref):
    return files._bound(Path(project), ref)


def _retained_geometry(project, manifest):
    """Reopen the existing Default native owner; never translate its verdict."""
    import librelane_fill_dfm as retained
    from _prestream_native import signoff_inputs
    ref = manifest.get('retained_default_fill')
    report = _bound(project, ref)
    if report.parts[-3:] != ('reports', 'phase3', 'fill_librelane.json'):
        raise AdmissionRefusal('D69_RETAINED_OWNER_INVALID', str(report))
    owner = report.parents[2]
    document = _read(report)
    tool = document['odb']['tool']
    state_path = Path(tool['state'])
    from librelane_contract import digest, validate_step_receipt
    validate_step_receipt(state_path.parent, retained.ODB_FILL_STEP)
    if digest(state_path) != tool['state_sha256']:
        raise AdmissionRefusal('D69_RETAINED_STATE_CHANGED', str(state_path))
    state = _read(state_path)
    if not Path(state['odb']).resolve().is_relative_to(state_path.parent.resolve()):
        raise AdmissionRefusal('D69_RETAINED_ODB_UNBOUND', str(state['odb']))
    if digest(Path(state['def'])) != tool['filled_def_sha256']:
        raise AdmissionRefusal('D69_RETAINED_DEF_CHANGED', str(state['def']))
    actual = signoff_inputs(owner, 'gds', 'odb', 'def', 'netlist', 'sdc')
    views = manifest.get('adopted_views') or {}
    if set(views) != {'netlist', 'sdc'}:
        raise AdmissionRefusal('D69_ADOPTED_VIEWS_ABSENT', 'current netlist and SDC required')
    for key, expected in [('netlist', actual['netlist']), ('sdc', actual['sdc'])]:
        if _bound(project, views[key]).resolve() != expected.resolve():
            raise AdmissionRefusal('D69_RETAINED_ADOPTED_VIEW_MISMATCH', key)
    from librelane_contract import resolve_image
    image = resolve_image(owner, record=False)
    if manifest.get('librelane', {}).get('image', image) != image:
        raise AdmissionRefusal('D69_RETAINED_IMAGE_MISMATCH', 'native image differs from stream owner')
    # Native cell-fill/stream evidence is not a dbFill census or fill-sensitive RC proof.
    geometry = {'odb': files._record(project, actual['odb']),
                'filled_def': files._record(project, actual['def']),
                'retained_default_fill': ref,
                'native_fill_state': files._record(project, state_path),
                'native_fill_receipt': files._record(project, state_path.parent / 'vibeic_receipt.json'),
                'final_gds': files._record(project, Path(actual['gds']))}
    return geometry


def _native_refusal_status(code):
    return 'FAIL' if code == 'LL_STEP_FAILED' else 'NOT_MEASURED'


# The shipped reducer refuses an elimination whose clique fill-in exceeds
# --max-degree (vibeic-eda tools/pdk/final_fill/final_fill_spef.py:477, default
# 64 at :1838 in image 0.4.67). That limit is our own computational guard, not a
# signoff threshold: the Schur elimination is exact at any degree (ruling #88
# D2). A node's degree when it is eliminated includes fill-in from earlier
# eliminations, so the layout and the raw SPEF's static degree do not bound it,
# and the raw SPEF only exists inside the native run. The guard's own refusal is
# therefore the measurement.
_DEGREE_REFUSAL = re.compile(
    r'REFUSED: floating node (\S+) degree ([1-9][0-9]*) exceeds fail-closed limit ([1-9][0-9]*)')
# Twice the measured degree admits at most four times that node's d*(d-1)/2
# clique edges. A denser graph is refused again by the tool, never retried here.
DEGREE_HEADROOM = 2


def _measured_degree(completed):
    """Return the tool's degree-guard measurement, or None for any other outcome."""
    refusals = [line for line in completed.stderr.splitlines() if line.startswith('REFUSED:')]
    match = (completed.returncode == 2 and len(refusals) == 1
             and _DEGREE_REFUSAL.fullmatch(refusals[0]))
    if not match or int(match[2]) <= int(match[3]):
        return None
    return {'floating_node': match[1], 'measured_degree': int(match[2]), 'tool_limit': int(match[3]),
            'headroom_factor': DEGREE_HEADROOM, 'max_degree': DEGREE_HEADROOM * int(match[2])}


def _fill_extraction_scope(d62):
    """Current-geometry correlation is separate from tool availability."""
    measurements = d62.get('measurements') or {}
    count = measurements.get('fill_count_after')
    return {'status': 'NOT_MEASURED', 'reason': 'D69_CURRENT_FINAL_FILL_CORRELATION_NOT_MEASURED',
            'native_fill_count': count if type(count) is int else None,
            'basis': 'source-owned D62 census; current final-GDS correlation remains separate'}


def _component_scope(record, d62):
    fill_scope = _fill_extraction_scope(d62)
    if (record.get('reason') != 'D69_FINAL_STATE_RCX_MEASURED'
            or record.get('component_scope') != 'final_filled_odb_rcx_component_only'
            or record.get('fill_sensitive_parasitics') != fill_scope):
        raise AdmissionRefusal('D69_COMPONENT_SCOPE_CHANGED',
                               'native component cannot invent current-geometry correlation')
    return fill_scope


def operation_sources():
    paths = (Path(__file__), Path(signoff.__file__), Path(files.__file__),
             Path(density.__file__), Path(__file__).with_name('spef_extraction_check.py'),
             Path(__file__).with_name('librelane_fill_dfm.py'),
             Path(__file__).with_name('_physical_current.py'))
    return {str(path.resolve()): _sha(path) for path in paths}


def _fill_net_comparison(project, attempt, final_gds, routed_def, spefs):
    """Compare net capacitance with the final-fill tool's totals; never a verdict.

    Those files hold net totals with no pins or resistance, so STA cannot read
    them and they never enter `spefs`. No outcome here changes D69's status.
    """
    binary = shutil.which('vibeic-final-fill-spef')
    if binary is None:
        return {'status': 'NOT_MEASURED', 'reason': 'FILL_TOOL_ABSENT'}
    top = files.fill_records(routed_def)['top']

    def launch(name, *bound):
        argv = [binary, 'extract', '--gds', str(final_gds), '--def', str(routed_def),
                '--top', top, '--output-dir', str(attempt / name), *bound]
        completed = subprocess.run(argv, cwd=project, capture_output=True, text=True)
        log = attempt / f'{name}.log'; log.write_text(completed.stdout + completed.stderr)
        return completed, {'argv': argv, 'returncode': completed.returncode,
                           'log': files._record(project, log)}
    native = 'fill-totals'
    completed, execution = launch(native)
    comparison = {'status': 'NOT_MEASURED', 'scope': 'net capacitance only; not read by STA'}
    measured = _measured_degree(completed)
    if measured is not None:
        comparison['degree_bound'] = {**measured, 'measuring_execution': execution}
        native = 'fill-totals-measured-bound'
        completed, execution = launch(native, '--max-degree', str(measured['max_degree']))
    comparison['execution'] = execution
    if completed.returncode != 0:
        return {**comparison, 'reason': 'FILL_TOOL_REFUSED'}
    receipt = _read(attempt / native / 'FINAL_FILL_EXTRACTION.json')
    corners = {}
    for corner, ref in spefs.items():
        fill_path = Path(receipt['corners'][corner]['output_spef'])
        openrcx = signoff.spef_census(_bound(project, ref))['nets']
        fill = signoff.spef_census(fill_path)['nets']
        openrcx = {name.replace('\\', ''): value for name, value in openrcx.items()}
        fill = {name.replace('\\', ''): value for name, value in fill.items()}
        common = sorted(set(openrcx) & set(fill))
        ratios = sorted(fill[n] / openrcx[n] for n in common if openrcx[n] > 0)
        if not ratios:
            return {**comparison, 'reason': 'NO_COMMON_NETS'}
        corners[corner] = {'fill_totals': files._record(project, fill_path),
            'common_nets': len(common), 'only_openrcx': len(set(openrcx) - set(fill)),
            'only_fill': len(set(fill) - set(openrcx)),
            'openrcx_total_pf': sum(openrcx[n] for n in common),
            'fill_total_pf': sum(fill[n] for n in common),
            'fill_over_openrcx': {'min': ratios[0], 'median': ratios[len(ratios) // 2],
                                  'max': ratios[-1]}}
    return {**comparison, 'status': 'MEASURED', 'tool_status': receipt.get('status'), 'corners': corners}


def execute(project, context):
    if context.get('resolved_row', {}).get('profile', {}).get('id') == 'analog_die':
        return _execute_analog(project, context)
    project = Path(project).resolve()
    attempt = project / 'reports/flow109/D69' / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    result = {'schema': SCHEMA, 'step_id': 'D69', 'component_status': 'NOT_MEASURED',
              'flow109_acceptance': 'NOT_MEASURED', 'native_started': False,
              'unmeasured_obligations': ['final_extractor_qualification',
                  'fill_sensitive_reference_correlation', 'final_parasitic_corner_coverage'],
              'context_sha256': context.get('context_sha256')}
    try:
        require_launch_admission(project, 'flow109.D69', {'flow109_context': context})
        manifest = _read(project / INPUT)
        if manifest.get('schema') != SCHEMA:
            raise AdmissionRefusal('D69_REQUIRED_INPUT_INVALID', 'schema')
        retained_geometry = None
        if manifest.get('retained_default_fill') is not None:
            if manifest.get('d62_receipt') is not None or manifest.get('stream_bridge') is not None:
                raise AdmissionRefusal('D69_GEOMETRY_AUTHORITY_AMBIGUOUS', 'one native owner required')
            retained_geometry = _retained_geometry(project, manifest)
            d62 = {}
            bridge = {'odb': retained_geometry['odb']}
            odb = _bound(project, bridge['odb'])
            d62_path = _bound(project, manifest['retained_default_fill'])
            routed_def = _bound(project, retained_geometry['filled_def'])
            final_gds = _bound(project, retained_geometry['final_gds'])
        else:
            d62 = density.validate_filled_odb(project, manifest.get('d62_receipt'))
            bridge = files.validate_bridge(project, manifest.get('stream_bridge'))
            if bridge['d62_receipt'] != manifest['d62_receipt'] or bridge['odb'] != d62['odb']:
                raise AdmissionRefusal('D69_FINAL_GEOMETRY_MISMATCH', 'stream-out and D62 ODB differ')
            odb, d62_path = _bound(project, bridge['odb']), _bound(project, manifest['d62_receipt'])
            d62doc = _read(d62_path)
            routed_def = _bound(project, d62doc['outputs']['filled.def'])
            final_gds = _bound(project, bridge.get('gds'))
        fill_scope = _fill_extraction_scope(d62)
        result['fill_sensitive_parasitics'] = fill_scope
        views = manifest.get('adopted_views') or {}
        if set(views) != {'netlist', 'sdc'}:
            raise AdmissionRefusal('D69_ADOPTED_VIEWS_ABSENT', 'netlist and SDC required')
        netlist = _bound(project, views['netlist']); sdc = _bound(project, views['sdc'])
        basis = {str(p): _sha(p) for p in (project / INPUT, odb, routed_def, final_gds, netlist, sdc, d62_path)}
        native = manifest.get('librelane') or {}
        if set(native) != {'image', 'pdk_root', 'pdk'}:
            raise AdmissionRefusal('D69_NATIVE_CONFIGURATION_ABSENT', 'image/pdk_root/pdk required')
        sources = operation_sources()
        result['native_started'] = True
        run = signoff.run(project, native['image'], Path(native['pdk_root']), native['pdk'],
                          routed_def=routed_def, routed_odb=odb, netlist=netlist, sdc=sdc,
                          extract=True, time=False, lane='flow109-d69')
        binding = signoff.bind_rcx_spefs(Path(run['rcx']), Path(run['rcx']) / 'state_in.json')
        scans = {signoff.rc_corner(pattern): scan_spef(Path(path)) for pattern, path in run['spef'].items()}
        bad = {c: f for c, f in scans.items() if not f['has_header'] or not f['has_design']
               or not (f['d_nets'] or f['r_nets']) or f['negative_caps'] or f['negative_net_totals']}
        if bad:
            raise AdmissionRefusal('D69_SPEF_CONSUMER_FAILED', str(bad), status='FAIL')
        if sources != operation_sources() or any(_sha(Path(p)) != digest for p, digest in basis.items()):
            raise AdmissionRefusal('D69_INPUT_CHANGED', 'source or geometry changed during extraction')
        final_spefs = {signoff.rc_corner(pattern): files._record(project, Path(path))
                       for pattern, path in run['spef'].items()}
        gds_ref, def_ref = files._record(project, final_gds), files._record(project, routed_def)
        # C7: Magic plus the reducer take hours and change no verdict, so opt-in.
        comparison = {'status': 'NOT_RUN', 'reason': 'FILL_COMPARISON_OFF'}
        if manifest.get('fill_net_comparison') is True:
            try:
                comparison = _fill_net_comparison(project, attempt, final_gds, routed_def, final_spefs)
            except (OSError, ValueError, KeyError, TypeError, Refusal) as exc:
                comparison = {'status': 'NOT_MEASURED', 'reason': 'FILL_COMPARISON_UNAVAILABLE', 'detail': str(exc)}
        result.update(component_status='PASS', reason='D69_FINAL_STATE_RCX_MEASURED',
                      producer='flow109_final_extract',
                      component_scope='final_filled_odb_rcx_component_only',
                      d62_receipt=manifest.get('d62_receipt'), stream_bridge=manifest.get('stream_bridge'),
                      retained_geometry=retained_geometry,
                      adopted_views=views, inputs=basis,
                      operation_sources=sources,
                      final_geometry=bridge['odb'],
                      final_gds=gds_ref, final_def=def_ref,
                      rcx_state=files._record(project, Path(run['rcx']) / 'state_out.json'),
                      rcx_receipt=files._record(project, Path(run['rcx']) / 'vibeic_receipt.json'),
                      spefs=final_spefs, final_spefs=final_spefs,
                      spef_consumer=scans, rcx_binding=binding,
                      fill_net_comparison=comparison, execution_context=context)
    except AdmissionRefusal as exc:
        result.update(component_status=exc.status, reason=exc.code, detail=str(exc))
    except Refusal as exc:
        result.update(component_status=_native_refusal_status(exc.code),
                      reason=exc.code, detail=str(exc))
    except Exception as exc:
        result.update(component_status='NOT_MEASURED', reason='D69_NATIVE_UNAVAILABLE_OR_UNSUPPORTED', detail=str(exc))
    path = attempt / 'component.json'; write_json(path, result)
    result['receipt'] = files._record(project, path)
    return result


def validate_final_parasitics(project, receipt_ref):
    project = Path(project).resolve(); record = _read(_bound(project, receipt_ref))
    if record.get('component_scope') == 'native_analog_final_gds_capacitance_component':
        return _validate_analog(project, _analog_read(_bound(project, receipt_ref)), receipt_ref)
    if record.get('schema') != SCHEMA or record.get('component_status') != 'PASS':
        raise AdmissionRefusal('D69_COMPONENT_NOT_ACCEPTED', 'current native RCX receipt required')
    require_launch_admission(project, 'flow109.D69', {'flow109_context': record.get('execution_context')})
    if record.get('operation_sources') != operation_sources():
        raise AdmissionRefusal('D69_OPERATION_SOURCE_CHANGED', 'adapter or retained consumer changed')
    if record.get('retained_geometry') is not None:
        geometry = _retained_geometry(project, {**record['retained_geometry'],
                                               'adopted_views': record['adopted_views']})
        if geometry != record['retained_geometry']:
            raise AdmissionRefusal('D69_RETAINED_GEOMETRY_CHANGED', 'native owner changed')
        d62 = {}
        bridge = {'odb': geometry['odb']}
        filled_def = geometry['filled_def']
        final_gds = geometry['final_gds']
    else:
        d62 = density.validate_filled_odb(project, record['d62_receipt'])
        bridge = files.validate_bridge(project, record['stream_bridge'])
        if bridge['d62_receipt'] != record['d62_receipt'] or bridge['odb'] != d62['odb']:
            raise AdmissionRefusal('D69_FINAL_GEOMETRY_MISMATCH', 'stream-out and D62 ODB differ')
        filled_def = _read(_bound(project, record['d62_receipt']))['outputs']['filled.def']
        final_gds = bridge['gds']
    if (record.get('producer') != 'flow109_final_extract'
            or record.get('final_geometry') != bridge['odb']
            or record.get('final_gds') != final_gds or record.get('final_def') != filled_def
            or record.get('final_spefs') != record.get('spefs')):
        raise AdmissionRefusal('D69_FINAL_OUTPUT_BINDING_MISMATCH', 'final ODB/SPEF aliases drifted')
    fill_scope = _component_scope(record, d62)
    for path, sha in record['inputs'].items():
        if not Path(path).is_file() or _sha(path) != sha:
            raise AdmissionRefusal('D69_INPUT_CHANGED', path)
    rcx_state = _bound(project, record['rcx_state'])
    state = {signoff.rc_corner(k): v for k, v in (_read(rcx_state).get('spef') or {}).items()}
    if set(state) != set(record['spefs']):
        raise AdmissionRefusal('D69_SPEF_CHANGED', 'RCX scene population changed')
    for corner, ref in record['spefs'].items():
        path = _bound(project, ref)
        if scan_spef(path) != record['spef_consumer'][corner] or Path(state[corner]).resolve() != path.resolve():
            raise AdmissionRefusal('D69_SPEF_CHANGED', corner)
    if signoff.bind_rcx_spefs(rcx_state.parent, rcx_state.parent / 'state_in.json') != record['rcx_binding']:
        raise AdmissionRefusal('D69_SPEF_CHANGED', 'RCX binding changed')
    return {'odb': bridge['odb'], 'filled_def': filled_def, 'd62_receipt': record['d62_receipt'],
            'adopted_views': record['adopted_views'],
            'spefs': record['spefs'], 'final_geometry': record['final_geometry'],
            'final_spefs': record['final_spefs'], 'parasitic_receipt': receipt_ref,
            'final_gds': final_gds, 'fill_net_comparison': record.get('fill_net_comparison'),
            'fill_sensitive_parasitics': fill_scope,
            'component_parasitics_current': True, 'flow109_acceptance': 'NOT_MEASURED'}


def _analog_sources():
    paths = (Path(__file__), HERE / 'magic_extract_spice_emit.py',
             HERE / 'analog_a7_post_layout_emit.py', HERE / 'analog_pdk_availability.py',
             HERE / 'declared_pdk_is_the_pdk_used_check.py', HERE / 'spef_extraction_check.py')
    return {str(p): _sha(p) for p in paths} | density._gds_sources()


def _analog_read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise AdmissionRefusal('D69_REQUIRED_INPUT_INVALID', 'duplicate key ' + key)
            result[key] = value
        return result
    value = json.loads(Path(path).read_text(), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise AdmissionRefusal('D69_REQUIRED_INPUT_INVALID', str(path))
    return value


def _original_launch(project, ref, expected):
    path = density._gds_input(project, ref)
    launch = _analog_read(path)
    inspected = launch['container_inspect']
    image = next(p for p in launch['image_inspect'] if p['Id'] == inspected['Image'])
    if (_sha(path) != expected.get('attestation_sha256')
            or launch['cid'] != expected.get('cid') or inspected['Id'] != launch['cid']
            or inspected['Image'] != expected.get('image_id')
            or launch['image'] != expected.get('image')
            or image.get('RepoDigests') != expected.get('repo_digests')):
        raise AdmissionRefusal('D69_ORIGINAL_LAUNCH_CHANGED', str(path))
    return launch


def _analog_inputs(project):
    """Reopen the GDS fill owner and its original inputs, not a PASS alias."""
    import metal_fill_emit as fill
    import analog_a7_post_layout_emit as a7
    import analog_pdk_availability as resolver
    from declared_pdk_is_the_pdk_used_check import declared_target
    if not (project / INPUT).is_file():
        raise AdmissionRefusal('D69_REQUIRED_INPUT_ABSENT', INPUT)
    manifest = _analog_read(project / INPUT)
    if manifest.get('schema') != SCHEMA:
        raise AdmissionRefusal('D69_REQUIRED_INPUT_INVALID', 'schema')
    paths = {key: density._gds_input(project, manifest.get(key)) for key in
             ('final_gds', 'fill_receipt', 'fill_launch', 'logical_netlist')}
    owner = _analog_read(paths['fill_receipt'])
    if (owner.get('schema') != density.SCHEMA or owner.get('step_id') != 'D62'
            or owner.get('geometry_format') != 'GDS' or owner.get('component_status') != 'PASS'
            or owner.get('native_started') is not True
            or owner.get('operation_sources') != density._gds_sources()):
        raise AdmissionRefusal('D69_FINAL_FILL_NOT_CURRENT', 'native GDS fill producer required')
    outputs = owner['outputs']
    for ref in [owner['manifest'], *owner['inputs'].values(), *outputs.values()]:
        density._gds_input(project, ref)
    if outputs['filled.gds'] != manifest['final_gds']:
        raise AdmissionRefusal('D69_FINAL_GEOMETRY_MISMATCH', 'final GDS differs from fill output')
    producer = _analog_read(density._gds_input(project, owner['manifest']))
    if any(producer.get(k) != owner['inputs'][k] for k in ('input_gds', 'rules')):
        raise AdmissionRefusal('D69_FILL_INPUT_BINDING_CHANGED', 'original fill invocation differs')
    report = density._gds_input(project, outputs['fill-report.json'])
    raw = _analog_read(report)
    observed = fill.verify_only(project, str(report))
    argv = owner['execution']['argv']
    expected = {'--gds': density._gds_input(project, owner['inputs']['input_gds']),
                '--config': density._gds_input(project, owner['inputs']['rules']),
                '--out': paths['final_gds'], '--report': report}
    if (owner['execution']['returncode'] != 0 or observed != owner.get('verify_only')
            or any(argv.count(flag) != 1 or argv[argv.index(flag) + 1] != str(p)
                   for flag, p in expected.items())
            or raw.get('gds_in') != str(expected['--gds'])
            or raw.get('gds_out') != str(paths['final_gds'])
            or producer.get('cell') != manifest.get('top')
            or not raw.get('layers')):
        raise AdmissionRefusal('D69_FILL_VERIFICATION_CHANGED', 'fill report/invocation mismatch')
    _bound(project, owner['tool']); _bound(project, owner['engine'])
    _original_launch(project, manifest['fill_launch'], owner['native_launch'])
    top = manifest.get('top')
    if not isinstance(top, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]*', top):
        raise AdmissionRefusal('D69_TOP_INVALID', 'explicit top required')
    text = paths['logical_netlist'].read_text()
    definitions = re.findall(r'(?im)^\s*\.subckt\s+(\S+)', text)
    if definitions != [top] or re.search(r'(?im)^\s*\.(?:inc|include|lib)\b', text):
        raise AdmissionRefusal('D69_NET_CENSUS_UNSUPPORTED', 'one flat adopted logical subcircuit required')
    ports, internal = a7.rcx_nets(text, top)
    nets = sorted(ports | internal)
    if not nets or any(not re.fullmatch(r'[A-Za-z0-9_!./:$-]+', n) for n in nets):
        raise AdmissionRefusal('D69_NET_CENSUS_UNSUPPORTED', 'complete logical net census required')
    target, target_source = declared_target(project)
    facts = resolver.resolve_pdk(target)
    if not facts.get('available') or facts.get('source') != 'container_installed':
        raise AdmissionRefusal('D69_INSTALLED_MODEL_ABSENT', 'declared PDK must resolve in this runtime')
    directory = (Path(facts['pdk_root']) / 'libs.tech/magic').resolve(strict=True)
    model = _bound(project, manifest.get('rc_model'))
    if model.parent != directory or model.suffix != '.tech':
        raise AdmissionRefusal('D69_MODEL_PDK_MISMATCH', 'installed declared-PDK extraction model required')
    closure, pending = set(), [model]
    while pending:
        path = pending.pop()
        if path in closure:
            continue
        if path.parent != directory or path.is_symlink() or not path.is_file():
            raise AdmissionRefusal('D69_MODEL_CLOSURE_UNSUPPORTED', str(path))
        closure.add(path)
        for line in path.read_text().splitlines():
            match = a7._INCLUDE_RE.match(line.strip())
            if match:
                child = path.parent / match[1]
                if not child.is_file():
                    child = Path(str(child) + '.tech')
                pending.append(child)
    corners = manifest.get('corners')
    styles = {style for path in closure for style in a7.extraction_styles(path)}
    if (not isinstance(corners, dict) or not corners or len(corners) > 16
            or any(not re.fullmatch(r'[A-Za-z0-9_]+', c) or s not in styles
                   for c, s in corners.items()) or type(manifest.get('require_resistance')) is not bool):
        raise AdmissionRefusal('D69_CORNERS_INVALID', 'explicit native extraction styles and RC requirement required')
    technology = [p for p in directory.rglob('*') if p.is_file()]
    if len(technology) > 512 or sum(p.stat().st_size for p in technology) > 67108864:
        raise AdmissionRefusal('D69_MODEL_CLOSURE_UNSUPPORTED', str(directory))
    label = target_source.rsplit(':', 1)[0]
    target_paths = [p for p in (project / label, project / 'run' / label) if p.is_file()]
    readset = [project / INPUT, *target_paths, *paths.values(), *technology,
               density._gds_input(project, owner['manifest']),
               *(density._gds_input(project, r) for r in owner['inputs'].values()),
               *(density._gds_input(project, r) for r in outputs.values())]
    if any(p.is_symlink() for p in readset):
        raise AdmissionRefusal('D69_MODEL_CLOSURE_UNSUPPORTED', 'regular native model files required')
    return {'manifest': manifest, 'nets': nets, 'model': str(model),
            'declared_target': target, 'declared_target_source': target_source,
            'inputs': {str(p): _sha(p) for p in readset}, 'fill_verification': observed}


def _analog_outputs(project, record):
    """Consume the shipped reducer and the complete adopted net census."""
    required = set(record['required_nets'])
    scans = {}
    for corner, ref in record['final_spefs'].items():
        reduction = _analog_read(density._gds_input(project, record['reductions'][corner]))
        path = density._gds_input(project, ref)
        for key in ('raw_spef', 'keep_nets', 'output_spef'):
            _bound(project, {'path': reduction[key], 'sha256': reduction[key + '_sha256']})
        names = [line.strip().lower() for line in Path(reduction['keep_nets']).read_text().splitlines()]
        facts = scan_spef(path)
        text = path.read_text()
        actual = re.findall(r'(?m)^\*D_NET\s+(\S+)', text)
        design = re.findall(r'(?m)^\*DESIGN\s+"([^"]+)"\s*$', text)
        if (reduction.get('status') != 'PASS'
                or reduction.get('method') != 'exact-capacitance-matrix-schur-complement'
                or reduction.get('floating_boundary_condition') != 'zero-net-charge'
                or reduction.get('grounded_fill_approximation') is not False
                or reduction.get('retained_net_count') != len(required)
                or len(names) != len(required) or set(names) != required
                or set(n.lower() for n in actual) != required or len(actual) != len(required)
                or design != [record['input_binding']['manifest']['top']]
                or Path(reduction['output_spef']) != path
                or not facts['has_header'] or not facts['has_design']
                or facts['negative_caps'] or facts['negative_net_totals']
                or not (facts['grounded_caps'] + facts['coupling_caps'])):
            raise AdmissionRefusal('D69_ANALOG_PARASITIC_CENSUS_FAILED', corner, status='FAIL')
        scans[corner] = facts
    return scans


def _analog_recipe(top, style):
    import magic_extract_spice_emit as recipe
    text = recipe.build_extraction_tcl(top, 'raw.spef',
        recipe.MagicResimExtractOptions(extract_style=style, extresist=False))
    text = text.replace('ext2spice -o raw.spef', 'ext2spice format spef\next2spice -o raw.spef')
    if not recipe.validate_extraction_tcl(text).passed:
        raise AdmissionRefusal('D69_NATIVE_RECIPE_INVALID', style)
    return ('drc off\ntech load $env(D69_MODEL)\ngds readonly false\n'
            'gds read $env(D69_GDS)\n' + text + 'quit -noprompt\n')


def _execute_analog(project, context):
    """Blocking analog component. C-only method evidence never grants row PASS."""
    import librelane_contract as launch
    project = Path(project).resolve()
    attempt = project / 'reports/flow109/D69' / uuid.uuid4().hex
    attempt.mkdir(parents=True)
    record = dict(schema=SCHEMA, step_id='D69', producer='flow109_final_extract',
                  context_sha256=context.get('context_sha256'),
                  component_status='NOT_MEASURED', native_started=False, completed=False,
                  default_row_status='NOT_MEASURED', flow109_acceptance='NOT_MEASURED',
                  whole_flow_acceptance='NOT_MEASURED', qualification='NOT_CLAIMED',
                  component_scope='native_analog_final_gds_capacitance_component',
                  fill_sensitive_parasitics=_fill_extraction_scope({}), executions=[])
    try:
        require_launch_admission(project, 'flow109.D69', {'flow109_context': context})
        data = _analog_inputs(project)
        manifest = data['manifest']
        record.update(input_binding=data, operation_sources=_analog_sources(), execution_context=context,
                      final_gds=manifest['final_gds'], required_nets=data['nets'],
                      corners=manifest['corners'], final_spefs={}, reductions={},
                      extraction_depth='C_ONLY', native_launch=launch.local_image_attestation())
        saved_launch = attempt / 'launch_identity.json'
        shutil.copyfile(record['native_launch']['attestation_path'], saved_launch)
        record['original_launch'] = files._record(project, saved_launch)
        tools = {n: shutil.which(n) for n in ('magic', 'vibeic-final-fill-spef')}
        if not all(tools.values()):
            raise AdmissionRefusal('D69_NATIVE_TOOL_ABSENT', 'Magic and shipped floating-node reducer required')
        record['tools'] = {n: files._record(project, Path(p).resolve()) for n, p in tools.items()}
        wrapper = Path(tools['vibeic-final-fill-spef']).read_text()
        record['tool_inputs'] = [files._record(project, Path(p)) for p in
            re.findall(r'(/[^\s"\']+\.py)', wrapper)]
        if not record['tool_inputs']:
            raise AdmissionRefusal('D69_NATIVE_TOOL_UNBOUND', 'shipped reducer source must be bound')
        for corner, style in manifest['corners'].items():
            folder = attempt / corner; folder.mkdir()
            script = folder / 'extract.tcl'
            script.write_text(_analog_recipe(manifest['top'], style))
            env = {**os.environ, 'D69_MODEL': data['model'],
                   'D69_GDS': str(density._gds_input(project, manifest['final_gds']))}
            reduction = folder / 'reduction.json'
            keep = folder / 'required-nets.txt'
            commands = [[tools['magic'], '-dnull', '-noconsole', str(script)],
                        [tools['vibeic-final-fill-spef'], 'reduce', '--raw', str(folder / 'raw.spef'),
                         '--keep-nets', str(keep), '--output', str(folder / 'final.spef'),
                         '--receipt', str(reduction)]]
            for index, argv in enumerate(commands):
                if index == 1:
                    raw_names = re.findall(r'(?m)^\*D_NET\s+(\S+)', (folder / 'raw.spef').read_text())
                    names = {n.lower(): n for n in raw_names}
                    if len(names) != len(raw_names) or not set(data['nets']) <= names.keys():
                        raise AdmissionRefusal('D69_NATIVE_REQUIRED_NET_ABSENT',
                            str(sorted(set(data['nets']) - names.keys())), status='FAIL')
                    keep.write_text(''.join(names[n] + '\n' for n in data['nets']))
                record['native_started'] = True
                proc = subprocess.run(argv, cwd=folder, env=env, capture_output=True, text=True, timeout=120)
                log = folder / f'command-{index}.log'; log.write_text(proc.stdout + proc.stderr)
                record['executions'].append(dict(corner=corner, argv=argv, returncode=proc.returncode,
                    log=files._record(project, log), recipe=files._record(project, script),
                    environment={k: env[k] for k in ('D69_MODEL', 'D69_GDS')}))
                if proc.returncode:
                    raise AdmissionRefusal('D69_NATIVE_EXTRACT_FAILED', str(log), status='FAIL')
            record['final_spefs'][corner] = files._record(project, folder / 'final.spef')
            record['reductions'][corner] = files._record(project, reduction)
        record['spef_consumer'] = _analog_outputs(project, record)
        if manifest['require_resistance']:
            raise AdmissionRefusal('D69_RESISTANCE_NOT_MEASURED', 'native method is C_ONLY', status='FAIL')
        record.update(component_status='PASS', reason='D69_NATIVE_ANALOG_FINAL_CAPACITANCE_MEASURED')
        _validate_analog(project, record)
    except (AdmissionRefusal, Refusal) as exc:
        record.update(component_status=getattr(exc, 'status', 'NOT_MEASURED'), reason=exc.code, detail=str(exc))
    except (OSError, ValueError, KeyError, TypeError, StopIteration, subprocess.TimeoutExpired) as exc:
        record.update(component_status='NOT_MEASURED', reason='D69_ANALOG_INPUT_OR_NATIVE_UNAVAILABLE', detail=str(exc))
    path = attempt / 'component.json'; write_json(path, record)
    record['receipt'] = files._record(project, path)
    return record


def _validate_analog(project, record, receipt_ref=None):
    require_launch_admission(project, 'flow109.D69', {'flow109_context': record['execution_context']})
    if (record.get('schema') != SCHEMA or record.get('component_status') != 'PASS'
            or record.get('operation_sources') != _analog_sources()
            or record.get('input_binding') != _analog_inputs(project)):
        raise AdmissionRefusal('D69_ANALOG_BINDING_CHANGED', 'original geometry/model/corner/fill inputs changed')
    manifest = record['input_binding']['manifest']
    if (record.get('final_gds') != manifest['final_gds']
            or record.get('required_nets') != record['input_binding']['nets']
            or record.get('corners') != manifest['corners']
            or set(record['final_spefs']) != set(manifest['corners'])
            or set(record['reductions']) != set(manifest['corners'])
            or record.get('extraction_depth') != 'C_ONLY' or manifest['require_resistance']
            or record.get('fill_sensitive_parasitics') != _fill_extraction_scope({})):
        raise AdmissionRefusal('D69_ANALOG_OUTPUT_BINDING_CHANGED', 'scope or declared output identities changed')
    _original_launch(project, record['original_launch'], record['native_launch'])
    for ref in [*record['tools'].values(), *record['tool_inputs']]:
        _bound(project, ref)
    if len(record['executions']) != 2 * len(manifest['corners']):
        raise AdmissionRefusal('D69_NATIVE_EXECUTION_CHANGED', 'one Magic/reducer pair required per corner')
    for execution in record['executions']:
        _bound(project, execution['log']); _bound(project, execution['recipe'])
        if execution['returncode'] != 0:
            raise AdmissionRefusal('D69_NATIVE_EXTRACT_FAILED', str(execution['argv']), status='FAIL')
    for corner, style in manifest['corners'].items():
        pair = [execution for execution in record['executions'] if execution.get('corner') == corner]
        if len(pair) != 2:
            raise AdmissionRefusal('D69_NATIVE_EXECUTION_CHANGED', corner)
        native, reduce = pair
        script = _bound(project, native['recipe'])
        reduction = _analog_read(density._gds_input(project, record['reductions'][corner]))
        if (script.read_text() != _analog_recipe(manifest['top'], style)
                or native['environment'] != {'D69_MODEL': record['input_binding']['model'],
                    'D69_GDS': str(density._gds_input(project, manifest['final_gds']))}
                or Path(native['argv'][0]).resolve() != Path(record['tools']['magic']['path'])
                or native['argv'][1:] != ['-dnull', '-noconsole', str(script)]
                or Path(reduce['argv'][0]).resolve() != Path(record['tools']['vibeic-final-fill-spef']['path'])
                or reduce['argv'][1:] != ['reduce', '--raw', reduction['raw_spef'],
                    '--keep-nets', reduction['keep_nets'], '--output', reduction['output_spef'],
                    '--receipt', str(density._gds_input(project, record['reductions'][corner]))]
                or _analog_read(_bound(project, reduce['log'])) != reduction):
            raise AdmissionRefusal('D69_NATIVE_EXECUTION_CHANGED', corner)
    if record['spef_consumer'] != _analog_outputs(project, record):
        raise AdmissionRefusal('D69_SPEF_CHANGED', 'native output census changed')
    return dict(final_gds=record['final_gds'], final_geometry=record['final_gds'],
                final_spefs=record['final_spefs'], spefs=record['final_spefs'],
                adopted_views={'netlist': manifest['logical_netlist']},
                required_nets=record['required_nets'], corners=record['corners'],
                rc_model=manifest['rc_model'], original_launch=record['original_launch'],
                parasitic_receipt=receipt_ref,
                extraction_depth='C_ONLY', component_parasitics_current=True,
                fill_sensitive_parasitics=record['fill_sensitive_parasitics'],
                flow109_acceptance='NOT_MEASURED')


def _d69_metric_values(project, spefs, required_nets=None):
    """Read the actual retained SPEF bytes with the existing native scanner.

    Capacitance values retain their native unit tokens. Neither a parsed SPEF
    nor the declared corner list proves extractor qualification/correlation.
    """
    import math
    observations = {}
    failures = []
    for corner, ref in spefs.items():
        path = _bound(project, ref)
        facts = scan_spef(path)
        text = path.read_text()
        totals = []
        for name, token in re.findall(r'(?m)^\*D_NET\s+(\S+)\s+(\S+)',text):
            value = float(token)
            if not math.isfinite(value):raise ValueError('D69_NONFINITE_NATIVE_NET_CAPACITANCE')
            totals.append({'net':name,'capacitance':value})
        names = [row['net'].lower() for row in totals]
        required = set(required_nets) if required_nets is not None else None
        bad = (not facts['has_header'] or not facts['has_design'] or not (facts['d_nets'] or facts['r_nets'])
               or facts['negative_caps'] or facts['negative_net_totals']
               or required is not None and (set(names)!=required or len(names)!=len(required)))
        if bad:failures.append(corner)
        observations[corner] = {'source':ref,'facts':facts,'net_capacitances':totals,
            'capacitance_unit_tokens':re.findall(r'(?m)^\*C_UNIT\s+([^\n]+)',text),
            'resistance_unit_tokens':re.findall(r'(?m)^\*R_UNIT\s+([^\n]+)',text)}
        if _sha(path)!=ref['sha256']:raise ValueError('D69_METRIC_SPEF_CHANGED')
    return {'status':'FAIL' if failures else 'NOT_MEASURED','corners':observations,
            'failed_corners':failures,'required_nets':required_nets,
            'reason':'D69_NATIVE_SPEF_CONSUMER_FAILURE' if failures else 'D69_EXTRACTOR_AND_FILL_REFERENCE_UNMEASURED'}


def _d69_metric_observation(project, context, component):
    receipt = component['receipt']
    record = _read(_bound(project, receipt))
    if (record.get('execution_context') or {}).get('context_sha256') != context['context_sha256']:
        raise ValueError('D69_METRIC_CONTEXT_CHANGED')
    current = validate_final_parasitics(project, receipt)
    required = current.get('required_nets')
    observed = _d69_metric_values(project, current['final_spefs'], required)
    observed.update(current_parasitics=current, extraction_depth=record.get('extraction_depth'),
                    inputs=record.get('input_binding',{}).get('inputs',record.get('inputs')),
                    receipt=receipt)
    return observed


def _d69_metric_acceptance(project, context, component):
    import flow109
    ids = ['final_extract.final_extractor_qualification','final_extract.fill_sensitive_reference_correlation',
           'final_extract.final_parasitic_corner_coverage']
    failed = component.get('component_status')=='FAIL'
    result = {'row_id':'D69','status':'NOT_MEASURED','qualification':'NOT_MEASURED','obligations':[]}
    try:
        current = flow109.validate_execution_context(context)
        if current['resolved_row']['id']!='D69' or [o['id'] for o in current['resolved_row']['obligations']]!=ids:
            raise ValueError('D69_METRIC_CONTEXT_UNREGISTERED')
        observed = _d69_metric_observation(project, context, component)
        failed = failed or observed['status']=='FAIL'
        result['native_observation'] = observed
        result['obligations'] = [
            {'id':ids[0],'status':'NOT_MEASURED','reason':'D69_ADOPTED_EXTRACTOR_QUALIFICATION_UNAVAILABLE'},
            {'id':ids[1],'status':'NOT_MEASURED','reason':'D69_CURRENT_FILL_REFERENCE_AND_APPROVED_ERROR_BOUNDS_UNAVAILABLE'},
            {'id':ids[2],'status':'FAIL' if failed else 'NOT_MEASURED','measurement':observed,
             'reason':'D69_NATIVE_PARASITIC_CENSUS_FAILURE' if failed else 'D69_INDEPENDENT_REQUIRED_CORNER_MODEL_POPULATION_UNBOUND'}]
    except (AdmissionRefusal,Refusal,OSError,ValueError,KeyError,TypeError,AttributeError) as exc:
        failed = failed or getattr(exc,'status',None)=='FAIL'
        result['reason'] = str(exc)
        result['obligations'] = [{'id':oid,'status':'FAIL' if failed and oid==ids[2] else 'NOT_MEASURED','reason':str(exc)} for oid in ids]
    if failed:result['status']='FAIL'
    return result

def consume_default_row_completion(project, context, component):
    """Canonical row completion; partial measurements do not qualify the row."""
    accepted = _d69_metric_acceptance(Path(project).resolve(), context, component)
    prior = component.get('metric_acceptance') or {}
    prior_ids = {o.get('id') for o in prior.get('obligations', []) if o.get('status') == 'FAIL'} if isinstance(prior, dict) else set()
    for item in accepted['obligations']:
        if item['id'] in prior_ids and item['status'] != 'FAIL':
            item.update(status='FAIL', reason='D69_PRIOR_MEASURED_FAILURE')
    if (component.get('default_row_status') == 'FAIL' or component.get('metric_acceptance_status') == 'FAIL'
            or isinstance(prior, dict) and prior.get('status') == 'FAIL' or prior_ids):
        accepted['status'] = 'FAIL'
        accepted['prior_failed_obligation_ids'] = sorted(prior_ids)
    # C2: the row is OpenRCX's result. Obligations no tool measures stay named in the record.
    status = ('FAIL' if accepted['status'] == 'FAIL' else
              'PASS' if component.get('component_status') == 'PASS' else 'NOT_MEASURED')
    return {**component, 'step_id': 'D69', 'context_sha256': context['context_sha256'],
        'metric_acceptance': accepted, 'metric_acceptance_status': accepted['status'],
        'default_row_status': status, 'flow109_acceptance': status,
        'completed': status == 'PASS', 'whole_flow_acceptance': 'NOT_MEASURED', 'delivery_accepted': False}
