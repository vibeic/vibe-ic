"""Native GLS waveforms and OpenSTA vector-power measurements."""
from __future__ import annotations
import json
import math
from pathlib import Path
import re
import shutil
import subprocess

from _atomic_artefact import write_json
import sim_activity_dump as dump
from _ppa import power

_PICOFARADS = {'ff': '0.001', 'pf': '1', 'nf': '1000'}


class NativeError(ValueError):
    def __init__(self, code, detail, *, status='NOT_MEASURED'):
        self.code, self.status = code, status
        super().__init__(f'{code}: {detail}')


def _read(path):
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise NativeError('D55_INVALID_INPUT', str(path))
    return value


def _fail(code, detail):
    raise NativeError(code, detail)


def _derive_scenario_authority(paths, ports):
    sdc = paths['sdc'].read_text()
    clock_lines = re.findall(r'(?m)^[ \t]*create_clock\b[^\n]*', sdc)
    clock = re.fullmatch(
        r'\s*create_clock(?:\s+-name\s+(?P<name_before>[A-Za-z_][A-Za-z0-9_$]*))?'
        r'\s+-period\s+(?P<period>[0-9.eE+-]+)'
        r'(?:\s+-name\s+(?P<name_after>[A-Za-z_][A-Za-z0-9_$]*))?'
        r'\s+\[get_ports\s+(?P<port>[A-Za-z_][A-Za-z0-9_$]*)\]\s*',
        clock_lines[0]) if len(clock_lines) == 1 else None
    delays = re.findall(r'(?m)^\s*set_output_delay\s+([0-9.eE+-]+)\s+-clock\s+([A-Za-z_][A-Za-z0-9_$]*)\s+\[all_outputs\]', sdc)
    loads = re.findall(r'(?m)^\s*set_load\s+([0-9.eE+-]+)\s+\[all_outputs\]', sdc)
    if (clock is None or (clock['name_before'] and clock['name_after'])
            or len(delays) != 1 or len(loads) != 1):
        _fail('D55_SDC_ACTIVITY_AUTHORITY_UNIMPLEMENTED', 'one clock/output-delay/all-output-load declaration required')
    clock_port = clock['port']
    clock_name = clock['name_before'] or clock['name_after'] or clock_port
    if clock_name != delays[0][1]:
        _fail('D55_SDC_ACTIVITY_AUTHORITY_UNIMPLEMENTED', 'output delay must reference the declared clock name')
    period, output_delay, load = float(clock['period']), float(delays[0][0]), float(loads[0])
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
    clock_ports = [port for port in ports if port['name'] == clock_port]
    if (len(clock_ports) != 1 or clock_ports[0]['direction'] != 'input'
            or clock_ports[0]['width'] != 1):
        _fail('D55_SDC_ACTIVITY_AUTHORITY_UNIMPLEMENTED', 'clock must target one declared scalar input port')
    return {'clock': clock_port, 'period_ns': period,
            'gls_sample_offset_ns': output_delay,
            'external_loads': {'rails': {default[0]: {'voltage_v': voltage}},
                               'ports': mapped},
            'quotes': {'clock': clock_lines[0].strip(),
                       'output_delay': f'set_output_delay {output_delay} -clock {delays[0][1]} [all_outputs]',
                       'load': f'set_load {load} [all_outputs]',
                       'default_power_rail': default[0],
                       'nom_voltage_v': voltage,
                       'capacitance_unit': {'scale': float(cap_units[0][0]), 'unit': cap_units[0][1]}}}


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
    if paths.get('spef'):
        text += 'read_spef ' + _word(paths['spef']) + '\n'
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


def _finite(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'D55_LOAD_VALUE_INVALID: {label}')
    return float(value)


def measured_load_rail_mapping(authority):
    """The implementation's loads in physical units: SDC set_load scaled by the
    Liberty capacitive_load_unit, and each output's pad rail with its voltage."""
    from decimal import Decimal
    unit = (authority.get('quotes') or {}).get('capacitance_unit') or {}
    factor = _PICOFARADS.get(str(unit.get('unit', '')).lower())
    if factor is None:
        raise ValueError('D55_LOAD_UNIT_UNSUPPORTED: ' + str(unit))
    scale = Decimal(str(_finite(unit.get('scale'), 'capacitance unit scale'))) * Decimal(factor)
    loads = authority['external_loads']
    return {'rails': {rail: {'voltage_v': _finite(item['voltage_v'], rail)}
                      for rail, item in loads['rails'].items()},
            'ports': {port: {'rail': item['rail'], 'capacitance_pf': float(
                          Decimal(str(_finite(item['capacitance_library_units'], port))) * scale)}
                      for port, item in loads['ports'].items()}}


def _load_reference(reference):
    """Same typed shape as the measurement; integers and floats compare as numbers."""
    if (not isinstance(reference, dict) or set(reference) != {'rails', 'ports'}
            or not isinstance(reference['rails'], dict) or not isinstance(reference['ports'], dict)
            or not reference['rails'] or not reference['ports']):
        raise ValueError('D55_LOAD_REFERENCE_SHAPE: rails and ports required')
    rails, ports = {}, {}
    for rail, item in reference['rails'].items():
        if not isinstance(item, dict) or set(item) != {'voltage_v'}:
            raise ValueError('D55_LOAD_REFERENCE_SHAPE: ' + str(rail))
        rails[rail] = {'voltage_v': _finite(item['voltage_v'], rail)}
    for port, item in reference['ports'].items():
        if (not isinstance(item, dict) or set(item) != {'rail', 'capacitance_pf'}
                or item['rail'] not in rails):
            raise ValueError('D55_LOAD_REFERENCE_SHAPE: ' + str(port))
        ports[port] = {'rail': item['rail'], 'capacitance_pf': _finite(item['capacitance_pf'], port)}
    return {'rails': rails, 'ports': ports}


def _execute_native_cases(project, context):
    """Run this State's authored GLS benches, then consume VCD in OpenSTA."""
    import time
    import librelane_contract as ll
    import sdf_gate_sim as sgs
    started = time.monotonic()
    result = {'component_status': 'NOT_MEASURED', 'native_started': False, 'modes': {}}
    output = project / 'reports/phase3/functional_activity.json'
    try:
        state = context.get('state')
        config = context.get('config')
        if not isinstance(state, dict) or not isinstance(config, dict):
            selected = _read(project / 'reports/phase3/sta_postpnr_signoff.json')
            state_path = Path(selected['sta_state'])
            state, config = _read(state_path), _read(state_path.with_name('config.json'))
        manifest = context.get('gls') or _read(project / 'phase3/librelane/29-config/gls/gls_manifest.json')
        if manifest.get('not_a_subject'):
            result['unmeasured_obligations'] = manifest['not_a_subject']
        corner = context.get('corner') or config['DEFAULT_CORNER']
        import fnmatch
        from librelane_signoff import rc_corner
        pdk_root = Path(context.get('pdk_root') or __import__('os').environ.get('VIBEIC_LIBRELANE_PDK_ROOT') or config['PDK_ROOT'])
        def material(raw):
            path = Path(raw)
            if path.is_file():
                return path
            parts = path.parts
            index = parts.index(config['PDK'])
            return pdk_root.joinpath(*parts[index:])
        libraries = config.get('CELL_LIBS') or config.get('LIB') or {}
        if isinstance(libraries, dict):
            liberties = [material(path) for pattern, paths in libraries.items()
                         if fnmatch.fnmatch(corner, pattern) for path in paths]
        else:
            liberties = list(map(material, libraries))
        for pattern, paths in (config.get('PAD_LIBS') or {}).items():
            if fnmatch.fnmatch(corner, pattern):
                liberties.extend(map(material, paths))
        spef = (state.get('spef') or {}).get(rc_corner(corner)) or (state.get('spef') or {}).get(corner)
        if not liberties or not spef:
            raise NativeError('D55_NATIVE_INPUT_ABSENT', 'Liberty and corner SPEF are required')
        ports = dump.module_ports(Path(state['nl']), config['DESIGN_NAME'])
        wrapper = _read(project / sgs.CHIP_TOP_RECORD_REL)
        paths = {'adopted_netlist': Path(state['nl']), 'sdc': Path(config.get('SIGNOFF_SDC_FILE') or state['sdc']),
                 'spef': Path(spef),
                 'liberty': liberties[0], 'liberties': liberties,
                 'pad_liberty': liberties[-1],
                 'io_connectivity': project / wrapper['chip_top_verilog']}
        authority = _derive_scenario_authority(paths, ports)
        prepared = {'paths': paths, 'loads': authority['external_loads'],
                    'manifest': {'top': config['DESIGN_NAME']}}
        folder = project / 'phase3/librelane/functional-activity'
        folder.mkdir(parents=True, exist_ok=True)
        for case in manifest['cases']:
            work = folder / case['id']
            work.mkdir(parents=True, exist_ok=True)
            bench = work / 'bench.v'
            bench_text = Path(case['testbench']).read_text().replace(
                manifest['sdf_placeholder'], str(state['sdf'][corner]))
            unchanged_bench = bench.is_file() and bench.read_text() == bench_text
            if not unchanged_bench:
                bench.write_text(bench_text)
            transcripts = []
            def native(argv, cwd):
                if argv[0] == 'iverilog':
                    argv = [argv[0], *sgs._IVERILOG_FLAGS.split(), *argv[2:]]
                elif argv[0] == 'vvp':
                    argv = [argv[0], *argv[1:], '-sdf-info']
                proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
                result['native_started'] = True
                (work / (Path(argv[0]).name + '.log')).write_text(proc.stdout + proc.stderr)
                transcripts.append(proc.stdout + proc.stderr)
                return proc.returncode, proc.stdout, proc.stderr
            activity = dump.dump([state['nl'], *manifest['models'], manifest['stubs']],
                                 [str(bench)], config['DESIGN_NAME'], work, native)
            simulation_text = transcripts[-1] if transcripts else ''
            parsed = sgs.parse_l10_case_stdout(simulation_text)
            if activity.get('status') != 'PASS' or activity.get('vvp_rc') != 0 or parsed.get('verdict') != 'PASS':
                raise NativeError('D55_GLS_FAILED', str(activity),
                    status='FAIL' if parsed.get('verdict') == 'FAIL' else 'NOT_MEASURED')
            script, report = work / 'power.tcl', work / 'power.rpt'
            done = case['id']
            script.write_text(_power_script(prepared, Path(activity['vcd']), activity['scope'], report, done))
            proc = subprocess.run([shutil.which('sta') or shutil.which('opensta'),
                                   '-no_splash', '-exit', str(script)], capture_output=True, text=True)
            report.write_text(proc.stdout + proc.stderr)
            if proc.returncode:
                raise NativeError('D55_POWER_TOOL_FAILED', str(report))
            measured = consume_power(report, {'required_ports': _native_port_names(ports),
                                      'clock_port': authority['clock']}, prepared['loads'], done)
            groups = power.parse_power_report(report.read_text())['rows']
            pad = sum(g['total_w'] for g in groups if g['group'].lower() == 'pad')
            result['modes'][case['id']] = {**measured, 'activity': activity,
                'vector_non_pad_mw': (measured['power']['total_w'] - pad) * 1000,
                'report': str(report)}
            write_json(output, result)
        if not result['modes'] or manifest.get('not_a_subject'):
            raise NativeError('D55_SCENARIO_POPULATION_INCOMPLETE', str(manifest.get('not_a_subject')))
        result.update(component_status='PASS')
    except (NativeError, OSError, ValueError, KeyError, TypeError) as exc:
        status = getattr(exc, 'status', 'NOT_MEASURED')
        result.update(component_status=status,
                      reason=getattr(exc, 'code', 'D55_NATIVE_INPUT_UNAVAILABLE'), detail=str(exc))
    result['wall_seconds'] = time.monotonic() - started
    write_json(output, result)
    return result


def execute(project, context):
    return _execute_native_cases(Path(project).resolve(), context)
