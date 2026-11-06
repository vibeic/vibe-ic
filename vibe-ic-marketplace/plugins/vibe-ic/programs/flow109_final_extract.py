"""D69 native owner: final State -> OpenROAD.RCX min/nom/max SPEFs for STA.

The final-fill tool's net totals sit beside the result as a comparison only.
"""
from __future__ import annotations

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
import librelane_fill_stream as files
import librelane_signoff as signoff
from librelane_contract import Refusal
from spef_extraction_check import scan_spef


class ExtractionError(ValueError):
    def __init__(self, code, detail, *, status='NOT_MEASURED'):
        self.code, self.status = code, status
        super().__init__(f'{code}: {detail}')


SCHEMA = 'vibeic.flow109.final-extract.v1'


def _read(path):
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise ExtractionError('D69_REQUIRED_INPUT_ABSENT', str(path)) from exc
    if not isinstance(value, dict):
        raise ExtractionError('D69_REQUIRED_INPUT_INVALID', str(path))
    return value


def _record(project, path):
    path = Path(path).resolve()
    return {'path': str(path.relative_to(project)) if path.is_relative_to(project) else str(path)}


def _bound(project, ref):
    from librelane_contract import project_path
    value = ref.get('path') if isinstance(ref, dict) else ref
    if not isinstance(value, str) or not value:
        raise ExtractionError('D69_NATIVE_VIEW_UNAVAILABLE', str(ref))
    path = project_path(Path(project), value)
    if not path.is_file():
        raise ExtractionError('D69_NATIVE_VIEW_ABSENT', str(path))
    return path


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
                           'log': _record(project, log)}
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
        corners[corner] = {'fill_totals': _record(project, fill_path),
            'common_nets': len(common), 'only_openrcx': len(set(openrcx) - set(fill)),
            'only_fill': len(set(fill) - set(openrcx)),
            'openrcx_total_pf': sum(openrcx[n] for n in common),
            'fill_total_pf': sum(fill[n] for n in common),
            'fill_over_openrcx': {'min': ratios[0], 'median': ratios[len(ratios) // 2],
                                  'max': ratios[-1]}}
    return {**comparison, 'status': 'MEASURED', 'tool_status': receipt.get('status'), 'corners': corners}


def execute(project, context):
    if context.get('resolved_row', {}).get('profile', {}).get('id') == 'analog_die' or context.get('analog'):
        return _execute_analog(project, context)
    from _prestream_native import signoff_inputs, final_state
    import librelane_contract as contract
    project = Path(project).resolve()
    attempt = project / 'reports/flow109/D69' / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    result = {'schema': SCHEMA, 'step_id': 'D69', 'component_status': 'NOT_MEASURED',
              'native_started': False}
    try:
        views = signoff_inputs(project, 'gds', 'odb', 'def', 'netlist', 'sdc')
        config_path = context.get('config_path') or final_state(project, streamed=True).parent / 'config.json'
        config = contract._load(contract.project_path(project, config_path))
        pdk = config['PDK']
        image = contract.resolve_image(project)
        root = contract.resolve_pdk_root(project, pdk, image=image)
        if not root:
            raise ExtractionError('D69_PDK_ROOT_UNAVAILABLE', pdk)
        result['native_started'] = True
        run = signoff.run(project, image, Path(root), pdk,
                          routed_def=views['def'], routed_odb=views['odb'],
                          netlist=views['netlist'], sdc=views['sdc'],
                          extract=True, time=False, lane='flow109-d69')
        binding = signoff.bind_rcx_spefs(Path(run['rcx']), Path(run['rcx']) / 'state_in.json')
        scans = {signoff.rc_corner(pattern): scan_spef(Path(path)) for pattern, path in run['spef'].items()}
        bad = {c: f for c, f in scans.items() if not f['has_header'] or not f['has_design']
               or not (f['d_nets'] or f['r_nets']) or f['negative_caps'] or f['negative_net_totals']}
        if bad:
            raise ExtractionError('D69_SPEF_CONSUMER_FAILED', str(bad), status='FAIL')
        final_spefs = {signoff.rc_corner(pattern): _record(project, Path(path))
                       for pattern, path in run['spef'].items()}
        comparison = {'status': 'NOT_RUN', 'reason': 'FILL_COMPARISON_OFF'}
        if context.get('fill_net_comparison') is True:
            try:
                comparison = _fill_net_comparison(project, attempt, views['gds'], views['def'], final_spefs)
            except (OSError, ValueError, KeyError, TypeError, Refusal) as exc:
                comparison = {'status': 'NOT_MEASURED', 'reason': 'FILL_COMPARISON_UNAVAILABLE', 'detail': str(exc)}
        result.update(component_status='PASS', reason='D69_FINAL_STATE_RCX_MEASURED',
                      producer='flow109_final_extract',
                      component_scope='final_filled_odb_rcx_component_only',
                      adopted_views={name: _record(project, views[name]) for name in ('netlist', 'sdc')},
                      final_geometry=_record(project, views['odb']),
                      final_gds=_record(project, views['gds']), final_def=_record(project, views['def']),
                      rcx_state=_record(project, Path(run['rcx']) / 'state_out.json'),
                      spefs=final_spefs, final_spefs=final_spefs,
                      spef_consumer=scans, rcx_binding=binding, fill_net_comparison=comparison)
    except ExtractionError as exc:
        result.update(component_status=exc.status, reason=exc.code, detail=str(exc))
    except Refusal as exc:
        result.update(component_status=_native_refusal_status(exc.code), reason=exc.code, detail=str(exc))
    except Exception as exc:
        result.update(component_status='NOT_MEASURED', reason='D69_NATIVE_UNAVAILABLE_OR_UNSUPPORTED', detail=str(exc))
    path = attempt / 'component.json'
    write_json(path, result)
    result['report'] = _record(project, path)
    return result


def validate_final_parasitics(project, report):
    project = Path(project).resolve()
    record = _read(_bound(project, report))
    if record.get('component_scope') == 'native_analog_final_gds_capacitance_component':
        return _validate_analog(project, record, report)
    spefs = record['final_spefs']
    observed = _d69_metric_values(project, spefs)
    if observed['status'] == 'FAIL':
        raise ExtractionError('D69_SPEF_CONSUMER_FAILED', str(observed['failed_corners']), status='FAIL')
    return {'odb': record['final_geometry'], 'filled_def': record['final_def'],
            'adopted_views': record['adopted_views'], 'spefs': spefs, 'final_spefs': spefs,
            'final_geometry': record['final_geometry'], 'final_gds': record['final_gds'],
            'fill_net_comparison': record.get('fill_net_comparison')}


def _analog_read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ExtractionError('D69_REQUIRED_INPUT_INVALID', 'duplicate key ' + key)
            result[key] = value
        return result
    value = json.loads(Path(path).read_text(), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ExtractionError('D69_REQUIRED_INPUT_INVALID', str(path))
    return value


def _analog_inputs(project, options):
    """Read native final GDS, logical nets and extraction-model styles."""
    import analog_a7_post_layout_emit as a7
    import analog_pdk_availability as resolver
    from declared_pdk_is_the_pdk_used_check import declared_target
    manifest = options
    paths = {key: _bound(project, manifest.get(key)) for key in ('final_gds', 'logical_netlist')}
    top = manifest.get('top')
    if not isinstance(top, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]*', top):
        raise ExtractionError('D69_TOP_INVALID', 'explicit top required')
    text = paths['logical_netlist'].read_text()
    definitions = re.findall(r'(?im)^\s*\.subckt\s+(\S+)', text)
    if definitions != [top] or re.search(r'(?im)^\s*\.(?:inc|include|lib)\b', text):
        raise ExtractionError('D69_NET_CENSUS_UNSUPPORTED', 'one flat adopted logical subcircuit required')
    ports, internal = a7.rcx_nets(text, top)
    nets = sorted(ports | internal)
    if not nets or any(not re.fullmatch(r'[A-Za-z0-9_!./:$-]+', n) for n in nets):
        raise ExtractionError('D69_NET_CENSUS_UNSUPPORTED', 'complete logical net census required')
    target, target_source = declared_target(project)
    facts = resolver.resolve_pdk(target)
    if not facts.get('available'):
        raise ExtractionError('D69_INSTALLED_MODEL_ABSENT', 'declared PDK must resolve in this runtime')
    model = _bound(project, manifest.get('rc_model'))
    directory = model.parent
    if model.suffix != '.tech':
        raise ExtractionError('D69_MODEL_UNSUPPORTED', 'native Magic extraction technology required')
    closure, pending = set(), [model]
    while pending:
        path = pending.pop()
        if path in closure:
            continue
        if not path.is_file():
            raise ExtractionError('D69_MODEL_CLOSURE_UNSUPPORTED', str(path))
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
        raise ExtractionError('D69_CORNERS_INVALID', 'explicit native extraction styles and RC requirement required')
    technology = [p for p in directory.rglob('*') if p.is_file()]
    if len(technology) > 512 or sum(p.stat().st_size for p in technology) > 67108864:
        raise ExtractionError('D69_MODEL_CLOSURE_UNSUPPORTED', str(directory))
    return {'manifest': manifest, 'nets': nets, 'model': str(model),
            'declared_target': target, 'declared_target_source': target_source}


def _analog_outputs(project, record):
    """Consume the shipped reducer and the complete adopted net census."""
    required = set(record['required_nets'])
    scans = {}
    for corner, ref in record['final_spefs'].items():
        reduction = _analog_read(_bound(project, record['reductions'][corner]))
        path = _bound(project, ref)
        for key in ('raw_spef', 'keep_nets', 'output_spef'):
            _bound(project, reduction[key])
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
            raise ExtractionError('D69_ANALOG_PARASITIC_CENSUS_FAILED', corner, status='FAIL')
        scans[corner] = facts
    return scans


def _analog_recipe(top, style):
    import magic_extract_spice_emit as recipe
    text = recipe.build_extraction_tcl(top, 'raw.spef',
        recipe.MagicResimExtractOptions(extract_style=style, extresist=False))
    text = text.replace('ext2spice -o raw.spef', 'ext2spice format spef\next2spice -o raw.spef')
    if not recipe.validate_extraction_tcl(text).passed:
        raise ExtractionError('D69_NATIVE_RECIPE_INVALID', style)
    return ('drc off\ntech load $env(D69_MODEL)\ngds readonly false\n'
            'gds read $env(D69_GDS)\n' + text + 'quit -noprompt\n')


def _execute_analog(project, context):
    """Blocking analog component. C-only method evidence never grants row PASS."""
    project = Path(project).resolve()
    attempt = project / 'reports/flow109/D69' / uuid.uuid4().hex
    attempt.mkdir(parents=True)
    record = dict(schema=SCHEMA, step_id='D69', producer='flow109_final_extract',
                  component_status='NOT_MEASURED', native_started=False, completed=False,
                  default_row_status='NOT_MEASURED', flow109_acceptance='NOT_MEASURED',
                  whole_flow_acceptance='NOT_MEASURED', qualification='NOT_CLAIMED',
                  component_scope='native_analog_final_gds_capacitance_component',
                  fill_sensitive_parasitics=_fill_extraction_scope({}), executions=[])
    try:
        data = _analog_inputs(project, context['analog'])
        manifest = data['manifest']
        record.update(input_binding=data,
                      final_gds=manifest['final_gds'], required_nets=data['nets'],
                      corners=manifest['corners'], final_spefs={}, reductions={},
                      extraction_depth='C_ONLY')
        tools = {n: shutil.which(n) for n in ('magic', 'vibeic-final-fill-spef')}
        if not all(tools.values()):
            raise ExtractionError('D69_NATIVE_TOOL_ABSENT', 'Magic and shipped floating-node reducer required')
        record['tools'] = {n: _record(project, Path(p).resolve()) for n, p in tools.items()}
        for corner, style in manifest['corners'].items():
            folder = attempt / corner; folder.mkdir()
            script = folder / 'extract.tcl'
            script.write_text(_analog_recipe(manifest['top'], style))
            env = {**os.environ, 'D69_MODEL': data['model'],
                   'D69_GDS': str(_bound(project, manifest['final_gds']))}
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
                        raise ExtractionError('D69_NATIVE_REQUIRED_NET_ABSENT',
                            str(sorted(set(data['nets']) - names.keys())), status='FAIL')
                    keep.write_text(''.join(names[n] + '\n' for n in data['nets']))
                record['native_started'] = True
                proc = subprocess.run(argv, cwd=folder, env=env, capture_output=True, text=True, timeout=120)
                log = folder / f'command-{index}.log'; log.write_text(proc.stdout + proc.stderr)
                record['executions'].append(dict(corner=corner, argv=argv, returncode=proc.returncode,
                    log=_record(project, log), recipe=_record(project, script),
                    environment={k: env[k] for k in ('D69_MODEL', 'D69_GDS')}))
                if proc.returncode:
                    raise ExtractionError('D69_NATIVE_EXTRACT_FAILED', str(log), status='FAIL')
            record['final_spefs'][corner] = _record(project, folder / 'final.spef')
            record['reductions'][corner] = _record(project, reduction)
        record['spef_consumer'] = _analog_outputs(project, record)
        if manifest['require_resistance']:
            raise ExtractionError('D69_RESISTANCE_NOT_MEASURED', 'native method is C_ONLY', status='FAIL')
        record.update(component_status='PASS', reason='D69_NATIVE_ANALOG_FINAL_CAPACITANCE_MEASURED')
        _validate_analog(project, record)
    except (ExtractionError, Refusal) as exc:
        record.update(component_status=getattr(exc, 'status', 'NOT_MEASURED'), reason=exc.code, detail=str(exc))
    except (OSError, ValueError, KeyError, TypeError, StopIteration, subprocess.TimeoutExpired) as exc:
        record.update(component_status='NOT_MEASURED', reason='D69_ANALOG_INPUT_OR_NATIVE_UNAVAILABLE', detail=str(exc))
    path = attempt / 'component.json'; write_json(path, record)
    record['report'] = _record(project, path)
    return record


def _validate_analog(project, record, report=None):
    manifest = record['input_binding']['manifest']
    if (set(record['final_spefs']) != set(manifest['corners'])
            or set(record['reductions']) != set(manifest['corners'])):
        raise ExtractionError('D69_ANALOG_CORNER_POPULATION_INCOMPLETE', str(manifest['corners']))
    if record.get('extraction_depth') != 'C_ONLY' or manifest['require_resistance']:
        raise ExtractionError('D69_RESISTANCE_NOT_MEASURED', 'native method is C_ONLY', status='FAIL')
    _analog_outputs(project, record)
    return dict(final_gds=record['final_gds'], final_geometry=record['final_gds'],
                final_spefs=record['final_spefs'], spefs=record['final_spefs'],
                adopted_views={'netlist': manifest['logical_netlist']},
                required_nets=record['required_nets'], corners=record['corners'],
                rc_model=manifest['rc_model'], extraction_depth='C_ONLY')


def _d69_metric_values(project, spefs, required_nets=None):
    """Read the actual retained SPEF bytes with the existing native scanner.

    Capacitance values retain their native unit tokens. Neither a parsed SPEF
    nor the declared corner list proves extractor qualification/correlation.
    """
    import math
    if not isinstance(spefs, dict) or not spefs:
        raise ExtractionError('D69_NATIVE_SPEF_ABSENT', 'RCX SPEF paths required')
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
    return {'status':'FAIL' if failures else 'PASS','corners':observations,
            'failed_corners':failures,'required_nets':required_nets,
            'reason':'D69_NATIVE_SPEF_CONSUMER_FAILURE' if failures else 'D69_NATIVE_SPEF_MEASURED'}
