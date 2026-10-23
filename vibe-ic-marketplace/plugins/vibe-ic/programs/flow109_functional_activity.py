"""D55 component: adopted-netlist GLS activity and a real vector-power consumer.

Uses the existing scoped activity producer and power provenance parser. The
pinned LibreLane STAPostPNR has no VCD/SAIF config; its underlying OpenSTA is
used as a complement, not as the final post-route power/signoff operation.
Complete vector-power measurement remains limited to full-window, single-rail
loads.  The source-declared self-checking GLS path inventories scalar and vector
top ports and consumes existing SDC/Liberty/pad connectivity authority.  All
three complete D55 obligations stay NOT_MEASURED.
"""
from __future__ import annotations

import hashlib
import json
import math
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
import sim_activity_dump as dump
from _ppa import power

SCHEMA = 'vibeic.flow109.functional-activity.v1'
INPUT = 'input/flow109/D55.json'
ROW_INPUT = 'input/flow109/D55-row.json'
ROW_INPUT_SCHEMA = 'vibeic.flow109.functional-activity-row-input.v1'
ROW_SCHEMA = 'vibeic.flow109.functional-activity-default-row.v1'
FREEZE = 'adopted/functional_activity/gls_activity_freeze.json'
PARTIAL_FREEZE = 'adopted/functional_activity/gls_activity_partial.json'
IDENT = re.compile(r'[A-Za-z_][A-Za-z0-9_$]*\Z')
REQUIRED_ROW_OBLIGATIONS = (
    'functional_activity.functional_mission_modes',
    'functional_activity.activity_waveform_bound_identity',
    'functional_activity.load_rail_mapping',
)
PINNED_IMAGE = ('ghcr.io/vibeic/vibeic-eda@sha256:'
                '0fc30ecd1307a11bd7757d1c5710127cd88e245059f29eab8b52e38ba4d60406')


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path):
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise AdmissionRefusal('D55_INVALID_INPUT', str(path))
    return value


def _bound(project, value):
    if not isinstance(value, dict) or not value.get('path') or not value.get('sha256'):
        raise AdmissionRefusal('D55_UNBOUND_INPUT', str(value))
    path = (project / value['path']).resolve()
    if not path.is_file() or _sha(path) != value['sha256']:
        raise AdmissionRefusal('D55_STALE_OR_MISSING_INPUT', str(path))
    return path


def _record(project, path):
    path = Path(path).resolve()
    return {'path': str(path.relative_to(project)) if path.is_relative_to(project) else str(path),
            'sha256': _sha(path)}


def operation_sources():
    from execution_provider_catalog import source_closure
    paths = source_closure({HERE / 'sim_activity_dump.py', HERE / '_ppa/power.py'})
    paths.update((Path(__file__), HERE / 'flow109.py', HERE / 'flow109_admission.py'))
    return {str(p.relative_to(HERE.parent)): _sha(p) for p in sorted(paths)}


def _fail(code, detail):
    raise AdmissionRefusal(code, detail)



def _self_contained_simulation_scope(paths):
    # This component does not yet enumerate transitive Verilog/SDC file I/O.
    # Refuse it before launching instead of hashing only an incomplete root.
    simulation = [paths['adopted_netlist'], *paths['simulation_models'],
                  *(p for key, p in paths.items() if key.startswith('tb:'))]
    for path in simulation:
        text = re.sub(r'//[^\n]*|/\*.*?\*/', '', path.read_text(), flags=re.S)
        if re.search(r'`include\b|\$(?:readmem[hb]|fopen|system|sdf_annotate)\b', text):
            _fail('D55_TRANSITIVE_SIMULATION_INPUT_UNIMPLEMENTED', str(path))
    allowed = {'create_clock', 'set_input_delay', 'set_output_delay', 'set_input_transition',
               'set_clock_uncertainty', 'set_clock_transition'}
    for line in paths['sdc'].read_text().splitlines():
        line = line.partition('#')[0].strip()
        if not line:
            continue
        # Only simple scalar get_ports/get_clocks substitutions; no nested
        # Tcl evaluation, variable expansion, source, read_* or command chain.
        reduced = re.sub(r'\[get_(?:ports|clocks)\s+\{?[A-Za-z_][A-Za-z0-9_]*(?:\s+[A-Za-z_][A-Za-z0-9_]*)*\}?\]', ' object ', line)
        if line.split()[0] not in allowed or re.search(r'[^A-Za-z0-9_.+\s-]', reduced):
            _fail('D55_SDC_SCOPE_UNIMPLEMENTED', line)


def _scenario_prepare(project, context, manifest, sources):
    """Prepare every source-declared scenario and normalize existing authority."""
    paths = {key: _bound(project, manifest.get(key))
             for key in ('adopted_netlist', 'scenario_requirements', 'sdc',
                         'liberty', 'pad_liberty', 'io_connectivity')}
    models = manifest.get('simulation_models')
    if not isinstance(models, list) or not models:
        _fail('D55_FUNCTIONAL_MODELS_ABSENT', 'GLS requires bound functional cell models')
    paths['simulation_models'] = [_bound(project, item) for item in models]
    requirements = _read(paths['scenario_requirements'])
    rows = requirements.get('test_cases')
    if (requirements.get('doc_class') != 'test_cases' or not isinstance(rows, list)
            or not rows or any(not isinstance(row, dict) for row in rows)):
        _fail('D55_SCENARIO_REQUIREMENTS_INVALID', str(paths['scenario_requirements']))
    declared = {row.get('name'): row for row in rows if isinstance(row.get('name'), str)}
    if len(declared) != len(rows):
        _fail('D55_SCENARIO_REQUIREMENTS_INVALID', 'unique named test cases required')
    modes = manifest.get('modes')
    if (not isinstance(modes, dict) or not modes or set(modes) != set(declared)
            or not all(IDENT.fullmatch(str(name)) and isinstance(value, dict)
                       for name, value in modes.items())):
        _fail('D55_REQUIRED_MODE_COVERAGE', 'every declared test case requires a bound driver')
    logical = manifest.get('testbench_dut_module')
    if not IDENT.fullmatch(str(logical or '')):
        _fail('D55_ACTIVITY_BASIS_UNIMPLEMENTED', 'logical testbench DUT module required')
    try:
        ports = dump.module_ports(paths['adopted_netlist'], manifest['top'])
    except (OSError, ValueError) as exc:
        _fail('D55_ADOPTED_PORT_SCOPE_UNIMPLEMENTED', str(exc))
    if any(port['direction'] == 'inout' for port in ports):
        _fail('D55_ADOPTED_PORT_SCOPE_UNIMPLEMENTED', 'inout activity needs a declared direction model')
    for name, value in modes.items():
        row = declared[name]
        if not all(isinstance(row.get(key), str) and row[key].strip()
                   for key in ('stimulus', 'expected', 'evidence')):
            _fail('D55_SCENARIO_REQUIREMENTS_INVALID', name)
        paths['tb:' + name] = _bound(project, value.get('testbench'))
    simulation = [paths['adopted_netlist'], *paths['simulation_models'],
                  *(path for key, path in paths.items() if key.startswith('tb:'))]
    for path in simulation:
        text = re.sub(r'//[^\n]*|/\*.*?\*/', '', path.read_text(), flags=re.S)
        if re.search(r'`include\b|\$(?:readmem[hb]|fopen|system|sdf_annotate)\b', text):
            _fail('D55_TRANSITIVE_SIMULATION_INPUT_UNIMPLEMENTED', str(path))
    authority = _derive_scenario_authority(paths, ports)
    paths['liberties'] = [paths['liberty'], paths['pad_liberty']]
    tools, tool_hashes = _resolve_tools(project, context, manifest)
    inputs = {str(project / INPUT): _sha(project / INPUT)}
    for group in paths.values():
        for path in group if isinstance(group, list) else [group]:
            inputs[str(path)] = _sha(path)
    return {'manifest': manifest, 'requirements': requirements, 'declared': declared,
            'paths': paths, 'inputs': inputs, 'sources': sources, 'tools': tools,
            'ports': ports, 'scenario_mode': True, 'tool_hashes': tool_hashes,
            'loads': authority['external_loads'], 'authority': authority}


def _derive_scenario_authority(paths, ports):
    sdc = paths['sdc'].read_text()
    clocks = re.findall(r'(?m)^\s*create_clock\b.*?-period\s+([0-9.eE+-]+)\s+\[get_ports\s+([A-Za-z_][A-Za-z0-9_$]*)\]', sdc)
    delays = re.findall(r'(?m)^\s*set_output_delay\s+([0-9.eE+-]+)\s+-clock\s+([A-Za-z_][A-Za-z0-9_$]*)\s+\[all_outputs\]', sdc)
    loads = re.findall(r'(?m)^\s*set_load\s+([0-9.eE+-]+)\s+\[all_outputs\]', sdc)
    if len(clocks) != 1 or len(delays) != 1 or len(loads) != 1 or clocks[0][1] != delays[0][1]:
        _fail('D55_SDC_ACTIVITY_AUTHORITY_UNIMPLEMENTED', 'one clock/output-delay/all-output-load declaration required')
    period, output_delay, load = float(clocks[0][0]), float(delays[0][0]), float(loads[0])
    if not all(math.isfinite(value) and value > 0 for value in (period, output_delay, load)) \
            or output_delay >= period / 2:
        _fail('D55_SDC_ACTIVITY_AUTHORITY_INVALID', str((period, output_delay, load)))
    liberty = paths['liberty'].read_text()
    pad_liberty = paths['pad_liberty'].read_text()
    nominal = re.findall(r'(?m)^\s*nom_voltage\s*:\s*([0-9.eE+-]+)\s*;', liberty)
    pad_nominal = re.findall(r'(?m)^\s*nom_voltage\s*:\s*([0-9.eE+-]+)\s*;', pad_liberty)
    default = re.findall(r'default_power_rail\s*:\s*"([A-Za-z_][A-Za-z0-9_$]*)"', pad_liberty)
    rails = {name: float(value) for name, value in re.findall(
        r'power_rail\s*\(\s*"([A-Za-z_][A-Za-z0-9_$]*)"\s*,\s*([0-9.eE+-]+)\s*\)', pad_liberty)}
    cap_units = re.findall(r'capacitive_load_unit\s*\(\s*([0-9.eE+-]+)\s*,\s*\\?\s*"?([A-Za-z]+)"?\s*\)', liberty)
    if (len(nominal) != 1 or len(pad_nominal) != 1 or len(default) != 1
            or len(cap_units) != 1 or default[0] not in rails
            or float(nominal[0]) != float(pad_nominal[0])):
        _fail('D55_RAIL_LIBRARY_MISMATCH', 'selected cell/pad operating conditions do not identify one default rail')
    voltage = float(nominal[0])
    if rails[default[0]] != voltage:
        _fail('D55_RAIL_LIBRARY_MISMATCH', default[0])
    io_text = re.sub(r'//[^\n]*|/\*.*?\*/', '', paths['io_connectivity'].read_text(), flags=re.S)
    output_ports = [port['name'] for port in ports if port['direction'] == 'output']
    mapped = {}
    for port in output_ports:
        instances = [body for body in re.findall(r'\b[A-Za-z_][A-Za-z0-9_$]*\s+(?:\\\S+|[A-Za-z_][A-Za-z0-9_$]*)\s*\((.*?)\)\s*;', io_text, re.S)
                     if re.search(r'\.PAD\s*\(\s*' + re.escape(port) + r'\s*\)', body)]
        if len(instances) != 1 or not re.search(r'\.' + re.escape(default[0])
                                               + r'\s*\(\s*' + re.escape(default[0]) + r'\s*\)', instances[0]):
            _fail('D55_OUTPUT_RAIL_CONNECTIVITY_UNRESOLVED', port)
        mapped[port] = {'rail': default[0], 'capacitance_library_units': load}
    if not mapped:
        _fail('D55_OUTPUT_LOAD_COVERAGE', 'adopted design has no output ports')
    return {'clock': clocks[0][1], 'period_ns': period,
            'gls_sample_offset_ns': output_delay,
            'external_loads': {'rails': {default[0]: {'voltage_v': voltage}},
                               'ports': mapped},
            'source_records': {'sdc': {'path': str(paths['sdc']), 'sha256': _sha(paths['sdc'])},
                               'liberty': {'path': str(paths['liberty']), 'sha256': _sha(paths['liberty'])},
                               'pad_liberty': {'path': str(paths['pad_liberty']), 'sha256': _sha(paths['pad_liberty'])},
                               'io_connectivity': {'path': str(paths['io_connectivity']), 'sha256': _sha(paths['io_connectivity'])}},
            'quotes': {'clock': f'create_clock -period {period} [get_ports {clocks[0][1]}]',
                       'output_delay': f'set_output_delay {output_delay} -clock {delays[0][1]} [all_outputs]',
                       'load': f'set_load {load} [all_outputs]',
                       'default_power_rail': default[0],
                       'nom_voltage_v': voltage,
                       'capacitance_unit': {'scale': float(cap_units[0][0]), 'unit': cap_units[0][1]}}}


def _engineering_native(context):
    row = context.get('resolved_row') or {}
    dispatch = ((row.get('profile') or {}).get('dispatch') or {})
    return (context.get('runtime_tool_uses') is None
            and context.get('qualification_registry') is None
            and context.get('requested_step') == 'D55'
            and context.get('native_step_id') == 'flow109.D55'
            and row.get('id') == 'D55'
            and dispatch.get('adapter') == 'flow109_functional_activity')


def _resolve_tools(project, context, manifest):
    if _engineering_native(context):
        from flow109 import validate_execution_context
        validate_execution_context(context)
        dispatch = context['resolved_row']['profile']['dispatch']
        tools = {}
        hashes = {}
        for tool_id in dispatch['engine_families']:
            executable = shutil.which(dispatch.get('engine_executables', {}).get(tool_id, tool_id))
            if not executable:
                _fail('D55_NATIVE_UNAVAILABLE_OR_UNSUPPORTED', tool_id)
            path = str(Path(executable).resolve())
            tools[tool_id] = path
            hashes[path] = _sha(path)
        return tools, hashes
    tools = {}
    for use in context.get('runtime_tool_uses') or []:
        pdk = _read(_bound(project, use['pdk']))
        if (pdk.get('adopted_netlist') != manifest['adopted_netlist']
                or pdk.get('simulation_models') != manifest['simulation_models']):
            _fail('D55_MODEL_SCOPE_NOT_QUALIFIED', use['use_id'])
        config = _read(_bound(project, use['config']))
        if config != {'schema': SCHEMA, 'basis': 'adopted_netlist_gls',
                      'window': 'self_checking_full_vcd', 'power_consumption': False}:
            _fail('D55_CONFIGURATION_UNIMPLEMENTED', use['use_id'])
        tools[use['tool_id']] = use['executable']['path']
    return tools, {str(Path(path).resolve()): _sha(Path(path).resolve()) for path in tools.values()}


def prepare(project, context):
    if context.get('requested_step') != 'D55' or context.get('native_step_id') != 'flow109.D55':
        _fail('D55_CONTEXT_MISMATCH', 'functional GLS activity component only')
    sources = operation_sources()
    for use in context.get('runtime_tool_uses') or []:
        if use.get('semantics', {}).get('operation_sources') != sources:
            _fail('D55_OPERATION_SOURCE_CHANGED', use['use_id'])
    manifest = _read(project / INPUT)
    if (manifest.get('schema') != SCHEMA or manifest.get('basis') != 'adopted_netlist_gls'
            or not IDENT.fullmatch(str(manifest.get('top', '')))):
        _fail('D55_ACTIVITY_BASIS_UNIMPLEMENTED', 'only declared adopted-netlist GLS is implemented')
    if manifest.get('scenario_requirements') is not None:
        return _scenario_prepare(project, context, manifest, sources)
    paths = {key: _bound(project, manifest.get(key))
             for key in ('adopted_netlist', 'liberty', 'requirements', 'loads', 'sdc')}
    models = manifest.get('simulation_models')
    if not isinstance(models, list) or not models:
        _fail('D55_FUNCTIONAL_MODELS_ABSENT', 'GLS requires bound functional cell models')
    paths['simulation_models'] = [_bound(project, p) for p in models]
    requirements = _read(paths['requirements'])
    if (requirements.get('approval', {}).get('status') != 'APPROVED'
            or requirements.get('approval', {}).get('authority') != 'requirements_owner'
            or not requirements.get('approval', {}).get('source_reference')):
        _fail('D55_REQUIREMENTS_NOT_APPROVED', 'mode/window/load requirements need source authority')
    required = requirements.get('modes')
    modes = manifest.get('modes')
    if (not isinstance(required, dict) or not required or not isinstance(modes, dict)
            or set(required) != set(modes) or not all(IDENT.fullmatch(m) for m in modes)):
        _fail('D55_REQUIRED_MODE_COVERAGE', 'exact approved mode set must be executed')
    for name, spec in required.items():
        if not isinstance(spec, dict) or not isinstance(modes[name], dict):
            _fail('D55_MODE_INVALID', name)
        ports = spec.get('required_ports')
        window = spec.get('window')
        if (not isinstance(ports, list) or not ports or len(set(ports)) != len(ports)
                or not all(IDENT.fullmatch(str(p)) for p in ports)
                or not isinstance(window, dict) or window.get('start_tick') != 0
                or not isinstance(window.get('end_tick'), int) or window['end_tick'] <= 0
                or not re.fullmatch(r'(1|10|100)(s|ms|us|ns|ps|fs)', str(window.get('timescale')))):
            _fail('D55_WINDOW_OR_PORT_SCOPE_UNIMPLEMENTED', name)
        paths['tb:' + name] = _bound(project, modes[name].get('testbench'))
    _self_contained_simulation_scope(paths)
    loads = _read(paths['loads'])
    approved = dict(loads)
    approved.pop('requirements_sha256', None)
    if approved != requirements.get('external_loads') or loads.get('requirements_sha256') != _sha(paths['requirements']):
        _fail('D55_LOAD_REQUIREMENT_MISMATCH', 'no adapter-selected load/rail threshold')
    rails, port_loads = loads.get('rails'), loads.get('ports')
    if not isinstance(rails, dict) or len(rails) != 1 or not isinstance(port_loads, dict) or not port_loads:
        _fail('D55_LOAD_RAIL_SCOPE_UNIMPLEMENTED', 'single-rail explicit output loads required')
    if not all(isinstance(value, dict) for value in rails.values()) or not all(isinstance(value, dict) for value in port_loads.values()):
        _fail('D55_LOAD_INVALID', 'rail/load records must be objects')
    voltage = next(iter(rails.values())).get('voltage_v')
    nominal = re.search(r'\bnom_voltage\s*:\s*([0-9.eE+-]+)', paths['liberty'].read_text())
    if not nominal or not isinstance(voltage, (int, float)) or float(nominal[1]) != voltage:
        _fail('D55_RAIL_LIBRARY_MISMATCH', 'declared supply must match the selected library corner')
    for port, load in port_loads.items():
        cap = load.get('capacitance_library_units')
        if (not IDENT.fullmatch(port) or load.get('rail') not in rails
                or not isinstance(cap, (int, float)) or not math.isfinite(cap) or cap < 0):
            _fail('D55_LOAD_INVALID', port)
    tools = {}
    for use in context['runtime_tool_uses']:
        if _bound(project, use['deck']) != paths['liberty']:
            _fail('D55_LIBRARY_NOT_QUALIFIED', use['use_id'])
        pdk = _read(_bound(project, use['pdk']))
        if pdk.get('liberty') != manifest['liberty'] or pdk.get('simulation_models') != manifest['simulation_models']:
            _fail('D55_MODEL_SCOPE_NOT_QUALIFIED', use['use_id'])
        config = _read(_bound(project, use['config']))
        if config != {'schema': SCHEMA, 'basis': 'adopted_netlist_gls', 'window': 'full_vcd', 'rail_count': 1}:
            _fail('D55_CONFIGURATION_UNIMPLEMENTED', use['use_id'])
        tools[use['tool_id']] = use['executable']['path']
    inputs = {str(project / INPUT): _sha(project / INPUT)}
    for group in paths.values():
        for path in group if isinstance(group, list) else [group]:
            inputs[str(path)] = _sha(path)
    return {'manifest': manifest, 'requirements': requirements, 'loads': loads,
            'paths': paths, 'inputs': inputs, 'sources': sources, 'tools': tools}


def _before(project, context, prepared):
    if _engineering_native(context):
        from flow109 import validate_execution_context
        validate_execution_context(context)
    else:
        require_launch_admission(project, 'flow109.D55', {'flow109_context': context})
    if operation_sources() != prepared['sources']:
        _fail('D55_OPERATION_SOURCE_CHANGED', 'before native launch/publication')
    for path, sha in prepared['inputs'].items():
        if not Path(path).is_file() or _sha(path) != sha:
            _fail('D55_STALE_OR_MISSING_INPUT', path)
    for path, sha in prepared.get('tool_hashes', {}).items():
        if not Path(path).is_file() or _sha(path) != sha:
            _fail('D55_NATIVE_TOOL_CHANGED', path)


def waveform_census(vcd, scope, spec):
    """Measure scalar required DUT ports and the complete VCD time window."""
    text = Path(vcd).read_text()
    header, sep, values = text.partition('$enddefinitions $end')
    if not sep:
        _fail('D55_VCD_HEADER_INVALID', str(vcd))
    scale = re.search(r'\$timescale\s+([^$]+)\$end', header)
    timescale = re.sub(r'\s+', '', scale[1]) if scale else None
    stack, ports = [], {}
    for line in header.splitlines():
        words = line.split()
        if words[:1] == ['$scope']:
            stack.append(words[2])
        elif words[:1] == ['$upscope']:
            stack.pop()
        elif words[:1] == ['$var'] and '/'.join(stack) == scope:
            if words[2] == '1':
                ports[words[4]] = words[3]
    required = spec['required_ports']
    if not set(required) <= set(ports):
        _fail('D55_VCD_REQUIRED_SIGNAL_MISSING', str(sorted(set(required) - set(ports))))
    ticks = [int(v) for v in re.findall(r'^#(\d+)\s*$', values, re.M)]
    if not ticks or timescale != spec['window']['timescale'] or max(ticks) != spec['window']['end_tick']:
        _fail('D55_VCD_WINDOW_MISMATCH', f'{timescale}, end={max(ticks) if ticks else None}')
    result = {}
    for name in required:
        symbol = ports[name]
        states = re.findall(r'^([01xXzZ])' + re.escape(symbol) + r'\s*$', values, re.M)
        if not states or any(s.lower() in ('x', 'z') for s in states):
            _fail('D55_VCD_UNKNOWN_OR_UNOBSERVED_SIGNAL', name)
        result[name] = {'vcd_symbol': symbol, 'observations': len(states),
                        'transitions': sum(a != b for a, b in zip(states, states[1:]))}
    return {'scope': scope, 'window': spec['window'], 'ports': result}


def measured_waveform_census(vcd, scope, required):
    """Measure the full self-checking VCD window, including vector top ports."""
    text = Path(vcd).read_text()
    header, sep, values = text.partition('$enddefinitions $end')
    if not sep:
        _fail('D55_VCD_HEADER_INVALID', str(vcd))
    scale = re.search(r'\$timescale\s+([^$]+)\$end', header)
    timescale = re.sub(r'\s+', '', scale[1]) if scale else None
    stack, ports = [], {}
    for line in header.splitlines():
        words = line.split()
        if words[:1] == ['$scope']:
            stack.append(words[2])
        elif words[:1] == ['$upscope']:
            stack.pop()
        elif words[:1] == ['$var'] and '/'.join(stack) == scope:
            ports[words[4]] = {'width': int(words[2]), 'symbol': words[3]}
    required_names = [port['name'] for port in required]
    missing = set(required_names) - set(ports)
    if missing:
        _fail('D55_VCD_REQUIRED_SIGNAL_MISSING', str(sorted(missing)))
    expected_widths = {port['name']: port['width'] for port in required}
    mismatched = {name: {'expected': expected_widths[name], 'actual': ports[name]['width']}
                  for name in required_names if ports[name]['width'] != expected_widths[name]}
    if mismatched:
        _fail('D55_VCD_REQUIRED_SIGNAL_WIDTH_MISMATCH', str(mismatched))
    # $dumpvars on an adopted module necessarily emits internal nets at the
    # same VCD scope.  They are evidence, but they are not top-level ports.
    ports = {name: ports[name] for name in required_names}
    observations = {name: [] for name in required_names}
    by_symbol = {item['symbol']: name for name, item in ports.items()}
    ticks = []
    for line in values.splitlines():
        if re.fullmatch(r'#\d+', line):
            ticks.append(int(line[1:])); continue
        scalar = re.fullmatch(r'([01xXzZ])(\S+)', line)
        vector = re.fullmatch(r'[bB]([01xXzZ]+)\s+(\S+)', line)
        if scalar and scalar[2] in by_symbol:
            observations[by_symbol[scalar[2]]].append(scalar[1].lower())
        elif vector and vector[2] in by_symbol:
            observations[by_symbol[vector[2]]].append(vector[1].lower())
    if not ticks or max(ticks) <= 0:
        _fail('D55_VCD_WINDOW_MISMATCH', f'{timescale}, end={max(ticks) if ticks else None}')
    result = {}
    for name in required_names:
        states = observations[name]
        first_known = next((index for index, state in enumerate(states)
                            if not (set(state) - {'0', '1'})), None)
        if first_known is None or any(set(state) - {'0', '1'} for state in states[first_known:]):
            _fail('D55_VCD_UNKNOWN_OR_UNOBSERVED_SIGNAL', name)
        known = states[first_known:]
        result[name] = {'vcd_symbol': ports[name]['symbol'], 'width': ports[name]['width'],
                        'observations': len(states),
                        'initial_unknown_observations': first_known,
                        'transitions': sum(a != b for a, b in zip(known, known[1:]))}
    return {'scope': scope,
            'window': {'start_tick': 0, 'end_tick': max(ticks), 'timescale': timescale,
                       'authority': 'measured complete self-checking testbench VCD'},
            'ports': result}


def _word(value):
    return '{' + str(value).replace('\\', '\\\\').replace('{', '\\{').replace('}', '\\}') + '}'


def _power_script(prepared, vcd, scope, output, done):
    paths = prepared['paths']
    liberties = paths.get('liberties', [paths['liberty']])
    text = ''.join('read_liberty ' + _word(liberty) + '\n' for liberty in liberties)
    text += 'read_verilog ' + _word(paths['adopted_netlist'])
    text += '\nlink_design ' + prepared['manifest']['top'] + '\nread_sdc ' + _word(paths['sdc']) + '\n'
    text += 'foreach p [all_inputs] { puts "D55_PORT [get_full_name $p] input" }\n'
    text += 'foreach p [all_outputs] { puts "D55_PORT [get_full_name $p] output" }\n'
    for port, load in prepared['loads']['ports'].items():
        text += f'set_load {load["capacitance_library_units"]} [get_ports {_word(port)}]\n'
        text += f'puts "D55_LOAD {port} {load["capacitance_library_units"]} {load["rail"]}"\n'
    text += power.activity_read_tcl(_word(vcd), scope)
    text += 'puts "POWER_ANALYSIS_MODE: vector_vcd"\n'
    text += 'foreach p [concat [all_inputs] [all_outputs]] { puts "D55_ACTIVITY [get_full_name $p] [get_property $p activity]" }\n'
    text += 'report_activity_annotation -report_annotated\nreport_power -digits 9\n'
    text += f'puts "D55_DONE {done}"\n'
    return 'if {[catch {\n' + text + '\n} err]} { puts "D55_NATIVE_FAIL: $err"; exit 1 }\n'


def _native_port_names(ports):
    result = []
    for port in ports:
        if port['width'] == 1:
            result.append(port['name'])
            continue
        bounds = re.fullmatch(r'\[\s*(-?\d+)\s*:\s*(-?\d+)\s*\]', port['packed'])
        if not bounds:
            _fail('D55_ADOPTED_PORT_SCOPE_UNIMPLEMENTED', str(port))
        first, last = int(bounds[1]), int(bounds[2])
        step = 1 if last >= first else -1
        result.extend(f"{port['name']}[{index}]" for index in range(first, last + step, step))
    return result


def consume_power(report, spec, loads, done):
    text = Path(report).read_text()
    prov = power.activity_provenance(text)
    if (f'D55_DONE {done}' not in text or 'D55_NATIVE_FAIL:' in text or re.search(r'^Error:', text, re.M)
            or prov['corroboration'] != power.CORROBORATED or not prov['annotated_pin_activities']):
        _fail('D55_POWER_ANNOTATION_NOT_MEASURED', prov['reason'])
    ports = dict(re.findall(r'^D55_PORT (\S+) (input|output)$', text, re.M))
    if set(ports) != set(spec['required_ports']):
        _fail('D55_REQUIRED_PORT_CENSUS_MISMATCH', 'all native top ports require explicit observation')
    if {p for p, direction in ports.items() if direction == 'output'} != set(loads['ports']):
        _fail('D55_OUTPUT_LOAD_COVERAGE', 'every native output needs its approved external load')
    activities = {}
    for port, density, duty, origin in re.findall(r'^D55_ACTIVITY (\S+) (\S+) (\S+) (\S+)\s*$', text, re.M):
        activities[port] = {'density_hz': float(density), 'duty': float(duty), 'origin': origin}
    clock_port = spec.get('clock_port')
    invalid_origins = {name: value['origin'] for name, value in activities.items()
                       if value['origin'] != 'vcd'
                       and not (name == clock_port and value['origin'] == 'clock')}
    if set(activities) != set(ports) or invalid_origins:
        _fail('D55_REQUIRED_PORT_NOT_VCD_ANNOTATED', str(activities))
    parsed = power.parse_power_report(text)
    total = parsed.get('total_row')
    if not total or not math.isfinite(total['total_w']) or total['total_w'] <= 0:
        _fail('D55_POWER_TOTAL_NOT_MEASURED', str(total))
    return {'activity_provenance': prov, 'ports': activities, 'power': total,
            'scope': 'component vector-power only; final post-route power adoption NOT_MEASURED'}


def _producer_path(root, name):
    """Resolve paths recorded by the sealed `/work/project` producer."""
    path = Path(name)
    prefix = Path('/work/project')
    if path.is_absolute() and path.is_relative_to(prefix):
        path = root / path.relative_to(prefix)
    elif not path.is_absolute():
        path = root / path
    return path.resolve()


def _producer_record(root, record, label):
    if not isinstance(record, dict) or not record.get('path') or not record.get('sha256'):
        _fail('D55_ROW_EVIDENCE_MISSING', label)
    path = _producer_path(root, record['path'])
    if not path.is_file() or _sha(path) != record['sha256']:
        _fail('D55_ROW_EVIDENCE_STALE', label)
    return path


def _producer_bound(root, value, label):
    if not isinstance(value, dict) or not value.get('path') or not value.get('sha256'):
        _fail('D55_ROW_INPUT_MISSING', label)
    path = _producer_path(root, value['path'])
    if not path.is_file() or _sha(path) != value['sha256']:
        _fail('D55_ROW_INPUT_STALE', label)
    return path


def _row_base(context, status='NOT_MEASURED', reason='D55_ROW_NOT_MEASURED', detail='not consumed'):
    return {'schema': ROW_SCHEMA, 'step_id': 'D55', 'component_status': status,
            'default_row_status': status, 'completed': False, 'reason': reason,
            'detail': detail, 'native_started': False,
            'context_sha256': context.get('context_sha256'),
            'selected_obligations': list(REQUIRED_ROW_OBLIGATIONS),
            'flow109_acceptance': 'NOT_MEASURED',
            'whole_flow_acceptance': 'NOT_MEASURED',
            'whole_ic_acceptance': 'NOT_MEASURED',
            'final_power_adoption': 'NOT_MEASURED'}


def _container_identity(path):
    value = json.loads(path.read_text())
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if not isinstance(value, dict):
        _fail('D55_ROW_NATIVE_AUTHORITY_INVALID', 'container inspect is not one object')
    state, host, config = value.get('State', {}), value.get('HostConfig', {}), value.get('Config', {})
    if (config.get('Image') != PINNED_IMAGE or state.get('ExitCode') != 0
            or state.get('OOMKilled') is not False or host.get('NetworkMode') != 'none'
            or host.get('NanoCpus') != 4_000_000_000
            or host.get('Memory') != 8 * 1024 ** 3
            or host.get('ReadonlyRootfs') is not True):
        _fail('D55_ROW_NATIVE_AUTHORITY_INVALID', 'pinned image/confinement/exit mismatch')
    return {'cid': value.get('Id'), 'image': config['Image'], 'exit_code': state['ExitCode'],
            'oom_killed': state['OOMKilled'], 'network_mode': host['NetworkMode'],
            'nano_cpus': host['NanoCpus'], 'memory_bytes': host['Memory'],
            'readonly_rootfs': host['ReadonlyRootfs'], 'sha256': _sha(path)}


def _authority_identity(value):
    """Compare authority facts without treating an attested RO mount as drift."""
    if not isinstance(value, dict):
        return value
    normalized = dict(value)
    normalized['source_records'] = {
        name: {'sha256': record.get('sha256')}
        for name, record in (value.get('source_records') or {}).items()
        if isinstance(record, dict)
    }
    return normalized


def consume_sealed_default_row(project, context):
    """Re-open an immutable D55 native component as a bounded Default row.

    This consumer never launches simulation or OpenSTA.  It hashes every sealed
    input/output, re-runs the existing authority and power-report consumers, and
    preserves the producer and current consumer identities as distinct records.
    """
    project = Path(project).resolve()
    base = _row_base(context)
    try:
        if context.get('requested_step') != 'D55' or context.get('native_step_id') != 'flow109.D55':
            _fail('D55_ROW_CONTEXT_MISMATCH', 'normal109 D55 caller required')
        row = context.get('resolved_row') or {}
        obligations = tuple(item.get('id') for item in row.get('obligations', [])
                            if isinstance(item, dict))
        if obligations != REQUIRED_ROW_OBLIGATIONS:
            _fail('D55_ROW_OBLIGATIONS_MISMATCH', str(obligations))
        invocation_path = project / ROW_INPUT
        invocation = _read(invocation_path)
        if invocation.get('schema') != ROW_INPUT_SCHEMA:
            _fail('D55_ROW_INVOCATION_INVALID', str(invocation_path))
        root = Path(invocation.get('producer_project', '')).resolve()
        if not root.is_dir():
            _fail('D55_ROW_PRODUCER_MISSING', str(root))
        component_path = _producer_record(root, invocation.get('component'), 'component')
        freeze_path = _producer_record(root, invocation.get('freeze'), 'freeze')
        inspect_path = _producer_record(root, invocation.get('container_inspect'), 'container_inspect')
        if component_path != (root / 'reports/flow109/components/D55.json').resolve() \
                or freeze_path != (root / FREEZE).resolve():
            _fail('D55_ROW_INVOCATION_INVALID', 'canonical component/freeze paths required')
        component, frozen = _read(component_path), _read(freeze_path)
        if (component.get('schema') != SCHEMA or component.get('step_id') != 'D55'
                or component.get('flow109_acceptance') != 'NOT_MEASURED'
                or component.get('final_power_adoption') != 'NOT_MEASURED'):
            _fail('D55_ROW_COMPONENT_INVALID', 'schema/step/scope mismatch')
        raw_path = _producer_path(root, (component.get('receipt') or {}).get('path', ''))
        if not raw_path.is_file() or _read(raw_path) != component:
            _fail('D55_ROW_COMPONENT_STALE', 'canonical and raw component differ')
        attempt_freeze = _producer_record(root, component.get('freeze'), 'attempt freeze')
        if _read(attempt_freeze) != frozen:
            _fail('D55_ROW_FREEZE_STALE', 'canonical and attempt freeze differ')
        if (frozen.get('schema') != SCHEMA or frozen.get('context_sha256') != component.get('context_sha256')
                or frozen.get('flow109_acceptance') != 'NOT_MEASURED'
                or frozen.get('final_power_adoption') != 'NOT_MEASURED'
                or frozen.get('modes') != component.get('modes')
                or frozen.get('inputs') != component.get('inputs')
                or frozen.get('operation_sources') != component.get('operation_sources')):
            _fail('D55_ROW_FREEZE_INVALID', 'component/freeze identity mismatch')

        if component.get('component_status') == 'FAIL':
            return {**base, 'component_status': 'FAIL', 'default_row_status': 'FAIL',
                    'reason': component.get('reason') or 'D55_ROW_NATIVE_FAILED',
                    'detail': 'sealed native component reported FAIL',
                    'producer_component': invocation['component']}
        commands = component.get('commands')
        if not isinstance(commands, list):
            _fail('D55_ROW_COMMAND_RECEIPTS_MISSING', 'native command population absent')
        bad_commands = [index for index, command in enumerate(commands)
                        if not isinstance(command, dict) or command.get('rc') != 0]
        if bad_commands:
            return {**base, 'component_status': 'FAIL', 'default_row_status': 'FAIL',
                    'reason': 'D55_ROW_NATIVE_COMMAND_FAILED',
                    'detail': f'nonzero native command receipts: {bad_commands}',
                    'producer_component': invocation['component']}
        if component.get('component_status') != 'PASS' or not component.get('native_started'):
            _fail(component.get('reason') or 'D55_ROW_COMPONENT_NOT_MEASURED',
                  'sealed native component did not PASS')

        inputs = component.get('inputs')
        if not isinstance(inputs, dict) or not inputs:
            _fail('D55_ROW_INPUTS_MISSING', 'sealed input population absent')
        input_paths = {}
        for name, expected in inputs.items():
            path = _producer_path(root, name)
            if not path.is_file() or _sha(path) != expected:
                _fail('D55_ROW_INPUT_STALE', str(name))
            input_paths[name] = path
        d55_inputs = [path for name, path in input_paths.items()
                      if str(name).endswith('/input/flow109/D55.json')]
        if len(d55_inputs) != 1:
            _fail('D55_ROW_INPUTS_MISSING', 'exact producer D55 manifest required')
        producer_manifest = _read(d55_inputs[0])
        if producer_manifest.get('schema') != SCHEMA:
            _fail('D55_ROW_INPUTS_INVALID', 'producer manifest schema mismatch')
        paths = {key: _producer_bound(root, producer_manifest.get(key), key)
                 for key in ('adopted_netlist', 'scenario_requirements', 'sdc',
                             'liberty', 'pad_liberty', 'io_connectivity')}
        requirements = _read(paths['scenario_requirements'])
        declared = {item.get('name'): item for item in requirements.get('test_cases', [])
                    if isinstance(item, dict) and isinstance(item.get('name'), str)}
        modes = component.get('modes')
        if not isinstance(modes, dict) or set(modes) != set(declared) or frozen.get('modes') != modes:
            _fail('D55_ROW_MODE_COVERAGE_MISMATCH', 'declared and sealed scenarios differ')
        ports = dump.module_ports(paths['adopted_netlist'], producer_manifest.get('top', ''))
        authority = _derive_scenario_authority(paths, ports)
        if (_authority_identity(authority) != _authority_identity(frozen.get('authority'))
                or authority['external_loads'] != frozen.get('external_loads')):
            _fail('D55_ROW_LOAD_RAIL_MAPPING_MISMATCH', 'current authority differs from freeze')

        expected_tools = ('iverilog', 'vvp', 'sta')
        if len(commands) != len(modes) * len(expected_tools):
            _fail('D55_ROW_COMMAND_RECEIPTS_MISSING', 'three native commands required per scenario')
        for index, command in enumerate(commands):
            argv = command.get('argv')
            if not isinstance(argv, list) or not argv \
                    or Path(argv[0]).name != expected_tools[index % len(expected_tools)]:
                _fail('D55_ROW_COMMAND_IDENTITY_INVALID', str(index))
            _producer_record(root, command.get('log'), f'command-{index} log')

        attempt_name = raw_path.parent.name
        native_ports = _native_port_names(ports)
        validated_modes = {}
        for name, evidence in modes.items():
            if evidence.get('requirement') != declared[name]:
                _fail('D55_ROW_MODE_REQUIREMENT_MISMATCH', name)
            activity_path = _producer_record(root, evidence.get('activity'), name + ' activity')
            vcd_path = _producer_record(root, evidence.get('vcd'), name + ' vcd')
            _producer_record(root, evidence.get('power_script'), name + ' power script')
            report_path = _producer_record(root, evidence.get('power_report'), name + ' power report')
            activity_record = _read(activity_path)
            if (activity_record.get('status') != 'PASS' or activity_record.get('vvp_rc') != 0
                    or activity_record.get('vcd_sha256') != _sha(vcd_path)):
                _fail('D55_ROW_ACTIVITY_RECEIPT_INVALID', name)
            consumed = consume_power(report_path, {'required_ports': native_ports,
                'clock_port': authority['clock']}, authority['external_loads'], attempt_name)
            if consumed != evidence.get('consumption'):
                _fail('D55_ROW_POWER_CONSUMER_MISMATCH', name)
            census = evidence.get('census')
            if (not isinstance(census, dict) or census.get('scope') != activity_record.get('scope')
                    or set((census.get('ports') or {})) != {port['name'] for port in ports}
                    or census.get('window', {}).get('authority')
                    != 'measured complete self-checking testbench VCD'):
                _fail('D55_ROW_WAVEFORM_IDENTITY_INVALID', name)
            validated_modes[name] = {'activity': evidence['activity'], 'vcd': evidence['vcd'],
                                     'power_report': evidence['power_report'],
                                     'annotated_pin_activities': consumed['activity_provenance']['annotated_pin_activities'],
                                     'total_w': consumed['power']['total_w']}

        source = component.get('operation_sources')
        if not isinstance(source, dict):
            _fail('D55_ROW_SOURCE_IDENTITY_MISSING', 'producer source closure absent')
        expected_adapter = invocation.get('producer_adapter_sha256')
        if source.get('programs/flow109_functional_activity.py') != expected_adapter:
            _fail('D55_ROW_SOURCE_IDENTITY_STALE', 'producer adapter identity mismatch')
        for relative in ('programs/sim_activity_dump.py', 'programs/_ppa/power.py'):
            if source.get(relative) != _sha(HERE.parent / relative):
                _fail('D55_ROW_SOURCE_IDENTITY_STALE', relative)
        container = _container_identity(inspect_path)
        obligations = [
            {'id': REQUIRED_ROW_OBLIGATIONS[0], 'status': 'PASS',
             'evidence': {'declared_modes': sorted(modes), 'native_command_count': len(commands)}},
            {'id': REQUIRED_ROW_OBLIGATIONS[1], 'status': 'PASS',
             'evidence': {'modes': validated_modes}},
            {'id': REQUIRED_ROW_OBLIGATIONS[2], 'status': 'PASS',
             'evidence': {'authority': authority}},
        ]
        return {**base, 'component_status': 'PASS', 'default_row_status': 'PASS',
                'completed': True, 'reason': 'D55_SUPPORTED_DEFAULT_ROW_COMPLETE',
                'detail': 'sealed current native component passed all declared D55 row consumers',
                'producer_context_sha256': component['context_sha256'],
                'producer_source_head': invocation.get('producer_source_head'),
                'producer_component': {**invocation['component'], 'raw_path': str(raw_path)},
                'producer_freeze': invocation['freeze'], 'producer_operation_sources': source,
                'consumer_source_sha256': {'programs/flow109_functional_activity.py': _sha(__file__),
                    'programs/sim_activity_dump.py': _sha(HERE / 'sim_activity_dump.py'),
                    'programs/_ppa/power.py': _sha(HERE / '_ppa/power.py')},
                'native_authority': container, 'obligations': obligations,
                'input_sha256': inputs, 'native_command_count': len(commands)}
    except AdmissionRefusal as exc:
        return {**base, 'component_status': exc.status, 'default_row_status': exc.status,
                'reason': exc.code, 'detail': str(exc)}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {**base, 'reason': 'D55_ROW_EVIDENCE_INVALID', 'detail': str(exc)}


def _execute_row_invocation(project, context):
    result = consume_sealed_default_row(project, context)
    attempt = project / 'reports/flow109/D55-row' / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    result['receipt'] = {'path': str((attempt / 'completion.json').relative_to(project))}
    write_json(attempt / 'completion.json', result)
    write_json(project / 'reports/flow109/default_rows/D55.json', result)
    return result


def execute(project, context):
    project = Path(project).resolve()
    if (project / ROW_INPUT).is_file():
        return _execute_row_invocation(project, context)
    (project / FREEZE).unlink(missing_ok=True)
    (project / PARTIAL_FREEZE).unlink(missing_ok=True)
    attempt = project / 'reports/flow109/D55' / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    record = {'schema': SCHEMA, 'step_id': 'D55', 'component_status': 'NOT_MEASURED',
              'flow109_acceptance': 'NOT_MEASURED', 'native_started': False,
              'context_sha256': context.get('context_sha256'), 'final_power_adoption': 'NOT_MEASURED',
              'modes': {}, 'commands': []}
    try:
        if not _engineering_native(context):
            require_launch_admission(project, 'flow109.D55', {'flow109_context': context})
        prepared = prepare(project, context)
        record.update(operation_sources=prepared['sources'], inputs=prepared['inputs'])
        def native(argv, cwd):
            if not argv or argv[0] not in prepared['tools']:
                _fail('D55_UNDECLARED_ENGINE', str(argv[0] if argv else None))
            _before(project, context, prepared)
            argv = [prepared['tools'][argv[0]], *argv[1:]]
            record['native_started'] = True
            # Native lifetime belongs to owner/progress supervision; a fixed
            # wall-clock timeout is not evidence that an EDA operation failed.
            result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
            log = attempt / f'command-{len(record["commands"])}.log'
            log.write_text(result.stdout + result.stderr)
            record['commands'].append({'argv': argv, 'rc': result.returncode, 'log': _record(project, log)})
            if result.returncode:
                raise AdmissionRefusal('D55_NATIVE_TOOL_FAILED', str(argv[0]),
                    status='FAIL' if Path(argv[0]).name == 'vvp' else 'NOT_MEASURED')
            return result.returncode, result.stdout, result.stderr
        mode_specs = (prepared['manifest']['modes'] if prepared.get('scenario_mode')
                      else prepared['requirements']['modes'])
        for mode, spec in mode_specs.items():
            folder = attempt / mode
            dump_options = {}
            if prepared.get('scenario_mode'):
                dump_options = {
                    'testbench_dut_module': prepared['manifest']['testbench_dut_module'],
                    'sample_clock': prepared['authority']['clock'],
                    'sample_offset_ns': prepared['authority']['gls_sample_offset_ns']}
            activity = dump.dump([str(prepared['paths']['adopted_netlist']),
                                  *map(str, prepared['paths']['simulation_models'])],
                                 [str(prepared['paths']['tb:' + mode])],
                                 prepared['manifest']['top'], folder, native, **dump_options)
            if activity.get('status') != 'PASS' or activity.get('vvp_rc') != 0:
                _fail('D55_GLS_ACTIVITY_INCOMPLETE', str(activity))
            vcd = Path(activity['vcd'])
            if _sha(vcd) != activity.get('vcd_sha256'):
                _fail('D55_ACTIVITY_GENERATION_STALE', str(vcd))
            for generated in (vcd, folder / dump.MANIFEST):
                prepared['inputs'][str(generated)] = _sha(generated)
            if prepared.get('scenario_mode'):
                census = measured_waveform_census(vcd, activity['scope'], prepared['ports'])
                consumption_spec = {'required_ports': _native_port_names(prepared['ports']),
                                    'clock_port': prepared['authority']['clock']}
            else:
                census = waveform_census(vcd, activity['scope'], spec)
                consumption_spec = spec
            script, report = folder / 'power.tcl', folder / 'power.rpt'
            script.write_text(_power_script(prepared, vcd, activity['scope'], report, attempt.name))
            prepared['inputs'][str(script)] = _sha(script)
            _, out, err = native(['opensta', '-no_splash', '-exit', str(script)], str(folder))
            report.write_text(out + err)
            prepared['inputs'][str(report)] = _sha(report)
            consumed = consume_power(report, consumption_spec, prepared['loads'], attempt.name)
            record['modes'][mode] = {
                **({'requirement': prepared['declared'][mode]} if prepared.get('scenario_mode') else {}),
                'activity': _record(project, folder / dump.MANIFEST),
                'vcd': _record(project, vcd), 'census': census, 'power_script': _record(project, script),
                'power_report': _record(project, report), 'consumption': consumed}
        _before(project, context, prepared)
        record.update(component_status='PASS', reason='D55_GLS_VECTOR_POWER_COMPONENT_MEASURED')
        frozen = {'schema': SCHEMA, 'context_sha256': context['context_sha256'],
            'inputs': prepared['inputs'], 'operation_sources': prepared['sources'],
            'modes': record['modes'], 'external_loads': prepared['loads'],
            **({'authority': prepared['authority']} if prepared.get('scenario_mode') else {}),
            'adopted_netlist': prepared['manifest']['adopted_netlist'],
            'final_power_adoption': 'NOT_MEASURED', 'flow109_acceptance': 'NOT_MEASURED'}
        write_json(attempt / 'freeze.json', frozen)
        write_json(project / FREEZE, frozen)
        record['freeze'] = _record(project, attempt / 'freeze.json')
    except AdmissionRefusal as exc:
        record.update(component_status=exc.status, reason=exc.code, detail=str(exc))
    except (ImportError, OSError, ValueError) as exc:
        record.update(component_status='NOT_MEASURED', reason='D55_NATIVE_UNAVAILABLE_OR_UNSUPPORTED', detail=str(exc))
    record['receipt'] = {'path': str((attempt / 'component.json').relative_to(project))}
    write_json(attempt / 'component.json', record)
    return record
