"""Native OpenROAD scan stitching, connectivity readback and GLS flush."""
from __future__ import annotations
import itertools
import json
from pathlib import Path
import re
import shutil
import subprocess
import uuid


class NativeError(ValueError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(f'{code}: {detail}')


def fail(code, detail):
    raise NativeError('D36_' + code, str(detail))


def bound(project, value):
    raw = value.get('path') if isinstance(value, dict) else value
    if not isinstance(raw, str) or not raw:
        fail('INPUT_ABSENT', value)
    path = Path(raw)
    path = (path if path.is_absolute() else project / path).resolve()
    if not path.is_file() or not path.stat().st_size:
        fail('INPUT_ABSENT', path)
    return path


def reference(project, path):
    return str(Path(path).resolve())


SNAPSHOT_TCL = r'''
proc d36_snapshot {path} {
 set f [open $path w]
 set b [ord::get_db_block]
 foreach i [$b getInsts] {
  puts $f [join [list CELL [$i getName] [[$i getMaster] getName] [$i getPlacementStatus] [$i getLocation]] "\t"]
  foreach p [$i getITerms] {
   set n [$p getNet]; set nn ""; if {$n != "NULL"} {set nn [$n getName]}
   puts $f [join [list PIN [$i getName] [[$p getMTerm] getName] $nn [$p getIoType]] "\t"]
  }
 }
 foreach p [$b getBTerms] {
  set n [$p getNet];set nn "";if {$n != "NULL"} {set nn [$n getName]}
  puts $f [join [list BTERM [$p getName] [$p getId] [$p getIoType] $nn] "\t"]
 }
 close $f
}
'''


def snapshot(path):
    cells, pins, ports = {}, {}, {}
    for raw in Path(path).read_text().splitlines():
        item = raw.split('\t')
        if item[0] == 'CELL' and len(item) == 5:
            if item[1] in cells:
                fail('DUPLICATE_NATIVE_INSTANCE', item[1])
            cells[item[1]] = {'cell': item[2], 'placement': item[3], 'xy': item[4]}
        elif item[0] == 'PIN' and len(item) == 5:
            key = (item[1], item[2])
            if key in pins:
                fail('DUPLICATE_NATIVE_PIN', key)
            pins[key] = (item[3], item[4])
        elif item[0] == 'BTERM' and len(item) == 5:
            if item[1] in ports:
                fail('DUPLICATE_NATIVE_PORT', item[1])
            ports[item[1]] = {'id': item[2], 'direction': item[3], 'net': item[4]}
        else:
            fail('NATIVE_CENSUS_INVALID', raw)
    if not cells or not pins or not ports:
        fail('ZERO_NATIVE_POPULATION', path)
    return cells, pins, ports


def derive_map(before_path, after_path, manifest, intent, population):
    """Complete database census; no supplied chain count/order is authoritative."""
    a, ap, ab = snapshot(before_path)
    b, bp, bb = snapshot(after_path)
    if a != b or ap.keys() != bp.keys() or ab.keys() != bb.keys():
        fail('NATIVE_POPULATION_MISMATCH', 'all original cells/pins/ports must survive')
    if any(c['placement'] not in ('PLACED', 'FIRM', 'LOCKED') for c in a.values()):
        fail('PLACED_POPULATION_UNRESOLVED', 'all native instances must be placed')
    definitions = manifest['scan_cells']
    if set(c['cell'] for c in b.values()) - set(manifest['qualified_cell_types']):
        fail('UNKNOWN_NATIVE_CELL', 'live cell not in qualification')
    scan = {name: definitions[c['cell']] for name, c in a.items() if c['cell'] in definitions}
    if (not scan or not population or len(population) != len({item['instance'] for item in population})
            or {(n, a[n]['cell']) for n in scan} != {(item['instance'], item['cell']) for item in population}):
        fail('SCAN_POPULATION_MISMATCH', 'complete D23/D24 current scan population')
    ports = {role: entry['public'] for role, entry in intent['test_port_def'].items()}
    for role, name in ports.items():
        direction = 'OUTPUT' if role == 'scan_out' else 'INPUT'
        if name not in ab or ab[name]['direction'] != direction or bb[name]['direction'] != direction:
            fail('ENDPOINT_DIRECTION_MISMATCH', name)
    for name in ab:
        expected = {**ab[name], 'net': bb[name]['net']} if name == ports['scan_out'] else ab[name]
        if bb[name] != expected:
            fail('FUNCTIONAL_PORT_CHANGED', name)
    allowed = {(n, d[k]) for n, d in scan.items() for k in ('si', 'se')}
    if any(ap[k] != bp[k] for k in ap if k not in allowed):
        fail('FUNCTIONAL_LOAD_CHANGED', 'D/CLK/Q and every original functional load')
    enable_net = bb[ports['scan_enable']]['net']
    if any(bp[(n, d['se'])][0] != enable_net for n, d in scan.items()):
        fail('SCAN_ENABLE_MISMATCH', 'all scan cells require same declared enable')
    order, net = [], bb[ports['scan_in']]['net']
    while True:
        choices = [n for n, d in scan.items() if bp[(n, d['si'])][0] == net]
        if not choices:
            break
        if len(choices) != 1 or choices[0] in order:
            fail('CHAIN_BRANCH_OR_CYCLE', choices)
        name = choices[0]
        order.append(name)
        net = bp[(name, scan[name]['q'])][0]
    if set(order) != set(scan) or net != bb[ports['scan_out']]['net']:
        fail('CHAIN_INCOMPLETE', 'unmatched cell or endpoint; no zero/partial chain acceptance')
    return {'chains': [{'scan_in': ports['scan_in'], 'scan_out': ports['scan_out'],
                        'cells': [{'instance': n, 'cell': a[n]['cell'], **scan[n]} for n in order]}],
            'endpoints': {'before': ab[ports['scan_out']], 'after': bb[ports['scan_out']]},
            'population': len(scan), 'clock_mode': intent['test_mode']}


def check_clock(netlist, liberty, intent, chain):
    """Prove every actual clock cone selects clk/test0 and tck/test1.

    This uses native Liberty Boolean functions, not a clock pin's spelling.
    Unknown cells, unresolved leaves, loops or ambiguous drivers refuse.
    """
    from lec_post_layout_check import _parse_netlist_instances, _parse_liberty_pins, _LibertyFn
    instances = _parse_netlist_instances(netlist)
    library = _parse_liberty_pins(liberty)
    drivers = {}
    for _, (cell, pins) in instances.items():
        if cell not in library:
            fail('CLOCK_MODEL_MISSING', cell)
        for pin, expr in library[cell]['outputs'].items():
            net = pins.get(pin)
            if not net or net in drivers:
                fail('CLOCK_DRIVER_AMBIGUOUS', net)
            drivers[net] = (expr, pins, library[cell]['inputs'])
    aliases = dict(re.findall(r'\bassign\s+([\w$]+)\s*=\s*([\w$]+)\s*;', netlist))
    def evaluate(net, values, trail=()):
        if net in values:
            return values[net]
        if net in ("1'b0", "1'b1"):
            return net == "1'b1"
        if net in trail or net is None:
            fail('CLOCK_CONE_UNRESOLVED', net)
        if net in aliases:
            return evaluate(aliases[net], values, (*trail, net))
        if net not in drivers:
            fail('CLOCK_CONE_UNRESOLVED', net)
        expr, pins, inputs = drivers[net]
        if not isinstance(expr, str):
            fail('CLOCK_MODEL_UNSUPPORTED', net)
        fn = _LibertyFn(expr)
        if ''.join(fn.toks) != re.sub(r'\s+', '', expr):
            fail('CLOCK_MODEL_UNSUPPORTED', expr)
        return fn({p: evaluate(pins.get(p), values, (*trail, net)) for p in inputs})
    roles = intent['test_port_def']
    functional, test, scan = intent['test_mode']['clock'], roles['test']['public'], roles['tck']['public']
    for entry in chain['chains'][0]['cells']:
        if entry['instance'] not in instances or instances[entry['instance']][0] != entry['cell']:
            fail('CLOCK_SUBJECT_MISMATCH', entry['instance'])
        pins = instances[entry['instance']][1]
        for select, clk, tck in itertools.product((False, True), repeat=3):
            actual = evaluate(pins.get(entry['clk']), {functional: clk, test: select, scan: tck})
            if actual != (tck if select else clk):
                fail('CLOCK_SELECTION_UNPROVEN', entry['instance'])
    return {'functional': functional, 'scan': scan, 'select': test, 'truth_rows_per_cell': 8}


def tcl(value):
    value = str(value)
    if any(c in value for c in '{}\n\r'):
        fail('SCRIPT_PATH_UNSUPPORTED', value)
    return '{' + value + '}'


def ident(value):
    return value if re.fullmatch(r'[A-Za-z_][\w$]*', value) else '\\' + value + ' '


def flush_tb(top, ports, intent, chain, period):
    """Drive actual declared scan clocks; zero-fill makes no powerup assumption."""
    roles = {r: d['public'] for r, d in intent['test_port_def'].items()}
    groups = {}
    for name, definition in ports.items():
        m = re.fullmatch(r'([A-Za-z_][\w$]*)\[(\d+)\]', name)
        base, index = (m[1], int(m[2])) if m else (name, None)
        group = groups.setdefault(base, {'direction': definition['direction'], 'bits': []})
        if group['direction'] != definition['direction'] or group['direction'] not in ('INPUT', 'OUTPUT'):
            fail('SIMULATION_PORT_UNSUPPORTED', name)
        group['bits'].append(index)
    declarations, connects = [], []
    for name, group in groups.items():
        bits = group['bits']
        if bits == [None]:
            width = ''
        elif None in bits or sorted(bits) != list(range(max(bits) + 1)):
            fail('SIMULATION_BUS_UNSUPPORTED', name)
        else:
            width = f'[{max(bits)}:0] '
        kind = 'reg' if group['direction'] == 'INPUT' else 'wire'
        declarations.append(f'{kind} {width}{ident(name)}' + (' = 0;' if kind == 'reg' else ';'))
        connects.append(f'.{ident(name)}({ident(name)})')
    for role, name in roles.items():
        if name not in groups or groups[name]['bits'] != [None]:
            fail('SIMULATION_ROLE_UNSUPPORTED', role)
    n = chain['population']
    entries = chain['chains'][0]['cells']
    checks = '\n'.join(f'if (dut.{ident(e["instance"])}.{ident(e["q"])} !== expected[{i}]) errors=errors+1;'
                       for i, e in enumerate(entries))
    mode = intent['test_mode']
    reset = mode['reset']
    if reset['signal'] not in groups:
        fail('RESET_PORT_ABSENT', reset['signal'])
    scan_clock, enable, scan_in, scan_out, select = (ident(roles[r]) for r in
        ('tck', 'scan_enable', 'scan_in', 'scan_out', 'test'))
    return ('`timescale 1ns/1ps\nmodule tb;\n' + '\n'.join(declarations)
        + f'\n{ident(top)} dut(' + ','.join(connects) + ');\n'
        + f'''reg [{n-1}:0] expected; integer i,p,errors=0,checked=0;reg bit_in;
 task pulse;begin #{period/2};{scan_clock}=1;#{period/2};{scan_clock}=0;end endtask
 initial begin
 {select}=1;{enable}=1;{ident(reset['signal'])}={reset['shift_value']};{scan_in}=0;
 // Pre-fill only: arbitrary prestate is outside the comparison boundary.
 for(i=0;i<{n};i=i+1) pulse;
 expected=0;
 for(p=0;p<4;p=p+1) for(i=0;i<{2*n};i=i+1) begin
  bit_in=(p==0)?0:(p==1)?1:(p==2)?(i%2):!(i%2);
  if({scan_out} !== expected[{n-1}]) errors=errors+1;
  {scan_in}=bit_in;pulse;
  expected=(expected<<1)|bit_in;
  {checks}
  if({scan_out} !== expected[{n-1}]) errors=errors+1;
  checked=checked+1;
 end
 $display("D36_FLUSH_DONE checked=%0d errors=%0d",checked,errors);
 if(errors) $fatal(1,"D36 scan flush mismatch");
 $finish;end\nendmodule\n''')


def run_native(prepared, directory):
    """Only the physical owner calls this once for a new approved subject."""
    from _atomic_artefact import write_json
    project, m, intent = prepared['project'], prepared['plan'], prepared['upstream']['intent']
    directory.mkdir(exist_ok=False)
    def path(name):
        return directory / name
    def run(name, argv):
        write_json(path(name + '.argv.json'), argv)
        result = subprocess.run(argv, capture_output=True, text=True, timeout=600)
        path(name + '.log').write_text(result.stdout + result.stderr)
        write_json(path(name + '.result.json'), {'returncode': result.returncode})
        return result
    roles = {r: d['public'] for r, d in intent['test_port_def'].items()}
    script = path('stitch.tcl')
    script.write_text('read_db ' + tcl(bound(project, prepared['upstream']['placed']['odb']))
        + '\nread_liberty ' + tcl(bound(project, m['liberty'])) + '\n'
        + ''.join('read_sdc ' + tcl(bound(project, r)) + '\n' for r in m['clock_constraints']) + SNAPSHOT_TCL
        + '\nd36_snapshot ' + tcl(path('before.tsv'))
        + '\nset_dft_config -max_chains ' + str(prepared['upstream']['plan']['planned_chain_count'])
        + ' -max_length ' + str(prepared['upstream']['plan']['max_chain_length']) + ' -clock_mixing no_mix'
        + ' -scan_enable_name_pattern ' + tcl(roles['scan_enable'])
        + ' -scan_in_name_pattern ' + tcl(roles['scan_in'])
        + ' -scan_out_name_pattern ' + tcl(roles['scan_out'])
        + '\nreport_dft_config\nreport_dft_plan -verbose\nputs D36_EXECUTE_START\nexecute_dft_plan\nputs D36_EXECUTE_DONE\n'
        + 'd36_snapshot ' + tcl(path('after.tsv')) + '\nwrite_db ' + tcl(path('stitched.odb'))
        + '\nwrite_verilog ' + tcl(path('stitched.v')) + '\n')
    # Actual clock selection is checked before stitching as well as on reopen.
    # Read the placed database's native netlist without altering placement.
    pre = path('preflight.tcl')
    pre.write_text('read_db ' + tcl(bound(project, prepared['upstream']['placed']['odb']))
        + '\n' + SNAPSHOT_TCL + '\nd36_snapshot ' + tcl(path('preflight.tsv'))
        + '\nwrite_verilog ' + tcl(path('placed.v')) + '\n')
    loaded = run('preflight', [prepared['tools']['openroad']['path'], '-no_init', '-exit', str(pre)])
    if loaded.returncode != 0:
        fail('PLACED_NATIVE_READ_REFUSED', 'preflight.log')
    population = prepared['upstream']['scan']['scan_cell_reconciliation']['cells']
    cells, _, ports = snapshot(path('preflight.tsv'))
    if set(c['cell'] for c in cells.values()) - set(prepared['source']['qualified_cell_types']):
        fail('UNKNOWN_NATIVE_CELL', 'placed live models must be qualified before stitching')
    expected = {(c['instance'], c['cell']) for c in population}
    actual = {(n, c['cell']) for n, c in cells.items() if c['cell'] in m['scan_cells']}
    if not expected or actual != expected:
        fail('SCAN_POPULATION_MISMATCH', 'current placed D23/D24 scan population')
    if any(c['placement'] not in ('PLACED', 'FIRM', 'LOCKED') for c in cells.values()):
        fail('PLACED_POPULATION_UNRESOLVED', 'unplaced native input')
    for role, name in roles.items():
        expected_direction = 'OUTPUT' if role == 'scan_out' else 'INPUT'
        if name not in ports or ports[name]['direction'] != expected_direction:
            fail('ENDPOINT_DIRECTION_MISMATCH', name)
    clock_chain = {'chains': [{'cells': [{'instance': c['instance'], 'cell': c['cell'],
                          **m['scan_cells'][c['cell']]} for c in population]}]}
    clock = check_clock(path('placed.v').read_text(), bound(project, m['liberty']).read_text(), intent, clock_chain)
    result = run('native', [prepared['tools']['openroad']['path'], '-no_init', '-exit', str(script)])
    if result.returncode != 0:
        fail('NATIVE_EXECUTION_REFUSED', 'native.log')
    chain = derive_map(path('before.tsv'), path('after.tsv'),
        {**m, 'qualified_cell_types': prepared['source']['qualified_cell_types']}, intent, population)
    write_json(path('map.json'), chain)
    _, _, ports = snapshot(path('after.tsv'))
    path('tb.v').write_text(flush_tb(m['top'], ports, intent, chain, m['scan_period_ns']))
    compile_argv = [prepared['tools']['iverilog']['path'], '-g2012', '-s', 'tb', '-o', str(path('scan.vvp'))]
    if any(not re.fullmatch(r'[A-Za-z_]\w*', d) for d in m['defines']):
        fail('DEFINE_UNSUPPORTED', 'literal preprocessor defines required')
    compile_argv += ['-D' + d for d in m['defines']]
    compile_argv += [str(bound(project, r)) for r in m['models']] + [str(path('stitched.v')), str(path('tb.v'))]
    compile_run = run('compile', compile_argv)
    if compile_run.returncode != 0:
        fail('MODEL_ELABORATION_REFUSED', 'compile.log')
    sim = run('simulation', [prepared['tools']['vvp']['path'], str(path('scan.vvp'))])
    matched = re.findall(r'^D36_FLUSH_DONE checked=(\d+) errors=(\d+)$', path('simulation.log').read_text(), re.M)
    if len(matched) != 1:
        fail('FLUSH_INCOMPLETE', 'missing native terminal census')
    edges, errors = map(int, matched[0])
    if (sim.returncode != 0) != bool(errors) or edges != 8 * chain['population']:
        fail('FLUSH_INCOMPLETE', 'returncode/census mismatch')
    write_json(path('flush.json'), {'map': reference(project, path('map.json')), 'models': m['models'],
        'defines': m['defines'], 'clock': clock, 'protocol': m['scan_protocol'],
        'checked_edges': edges, 'errors': errors})
    outputs = {name: str(path(name)) for name in
               ('before.tsv', 'after.tsv', 'stitched.v', 'stitched.odb', 'map.json', 'flush.json',
                'native.log', 'stitch.tcl', 'simulation.log', 'simulation.result.json', 'tb.v', 'compile.log')}
    report = {'native_status': 'FAIL' if errors else 'PASS',
              'native_rc': result.returncode, 'checked_edges': edges, 'errors': errors,
              'population': chain['population'], 'outputs': outputs}
    write_json(path('execution.json'), report)
    return report


def prepare(project, context):
    project = Path(project).resolve()
    plan = context['plan']
    upstream = context['upstream']
    if not isinstance(plan, dict) or not isinstance(upstream, dict):
        raise ValueError('native scan plan and prior native design views are required')
    for field in ('liberty', 'clock_constraints', 'top', 'scan_cells', 'defines',
                  'models', 'scan_period_ns', 'scan_protocol'):
        if field not in plan:
            raise ValueError('native scan plan is missing ' + field)
    from lec_post_layout_check import _parse_liberty_pins
    library = _parse_liberty_pins(bound(project, plan['liberty']).read_text())
    tools = {}
    for name in ('openroad', 'iverilog', 'vvp'):
        path = shutil.which(name)
        if path is None:
            raise ValueError('native tool is unavailable: ' + name)
        tools[name] = {'path': path}
    return {'project': project, 'plan': plan, 'upstream': upstream, 'tools': tools,
            'source': {'qualified_cell_types': sorted(library)}}


def execute(project, context):
    project = Path(project).resolve()
    directory = project / 'reports/native_tools/scan_physical' / uuid.uuid4().hex
    directory.parent.mkdir(parents=True, exist_ok=True)
    try:
        report = run_native(prepare(project, context), directory)
        return {**report, 'component_status': report['native_status']}
    except (NativeError, OSError, ValueError, KeyError, TypeError) as exc:
        return {'component_status': 'NOT_MEASURED', 'reason': str(exc)}
