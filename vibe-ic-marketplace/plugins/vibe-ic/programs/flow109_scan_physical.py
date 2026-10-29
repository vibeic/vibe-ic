"""D36 BLOCKING native leaf for the existing Phase-3 physical owner.

No placement, scan replacement, authority issuance or orchestration lives here.
The owner consumes current placed state, stitches once, then reopens independently
adopted original execution. Component success alone never establishes row PASS.
"""
from __future__ import annotations

import hashlib
import inspect
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid

HERE = Path(__file__).resolve().parent
INPUT = 'input/flow109/D36.json'
EXECUTION = 'reports/phase3/scan_physical/execution.json'
ADOPTED_EXECUTION = 'adopted/scan_physical/native_execution.json'
PURPOSE = 'functional_preserving_physical_scan_stitch'


def fail(code, detail):
    from flow109_metric_acceptance import MetricRefusal
    raise MetricRefusal('D36_' + code, str(detail))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reference(project, path):
    return {'path': str(Path(path).resolve().relative_to(project)), 'sha256': sha(path)}


def bound(project, value):
    from flow109_metric_acceptance import _safe_project_file
    if (not isinstance(value, dict) or set(value) != {'path', 'sha256'}
            or not isinstance(value['path'], str) or Path(value['path']).is_absolute()
            or '..' in Path(value['path']).parts
            or not re.fullmatch('[0-9a-f]{64}', str(value['sha256']))):
        fail('INPUT_UNBOUND', value)
    path = _safe_project_file(project, value['path'])
    if not path.is_file() or not path.stat().st_size or sha(path) != value['sha256']:
        fail('INPUT_STALE', value['path'])
    return path


def operation_sources():
    """Original native producer identity; reader-only repairs do not replay native work."""
    import phase3_one_shot_runner as owner
    functions = (owner.step_scan_physical, run_native, flush_tb, tcl, ident)
    return {fn.__name__: hashlib.sha256(inspect.getsource(fn).encode()).hexdigest()
            for fn in functions} | {'snapshot_script': hashlib.sha256(SNAPSHOT_TCL.encode()).hexdigest()}


def consumer_sources():
    import flow109_metric_acceptance as metrics
    import lec_post_layout_check as parser
    functions = (prepare, upstream, derive_map, check_clock, native_subject, reopen, owner,
                 consume_default_row_completion, metrics.accept_d36)
    return {fn.__name__: hashlib.sha256(inspect.getsource(fn).encode()).hexdigest()
            for fn in functions} | {'model_parser': sha(parser.__file__)}


def tool_readset():
    result = {}
    for name in ('openroad', 'iverilog', 'vvp'):
        binary = shutil.which(name)
        if not binary:
            fail('TOOL_ABSENT', name)
        path = Path(binary).resolve()
        result[name] = {'path': str(path), 'sha256': sha(path)}
    support = Path(result['iverilog']['path']).parent.parent / 'lib/ivl'
    if not support.is_dir() or not (support / 'ivl').is_file() or not (support / 'vvp.tgt').is_file():
        fail('SIMULATOR_SUPPORT_UNBOUND', support)
    result['iverilog_support'] = {str(p.resolve()): sha(p) for p in sorted(support.rglob('*')) if p.is_file()}
    return result


def approved(project, relative, schema):
    import flow109_metric_acceptance as metrics
    authority, doc = metrics._approved_document(project, relative,
        authority='requirements_owner', schema=schema)
    source = json.loads(bound(project, authority['source']).read_text())
    payload = {k: v for k, v in doc.items() if k not in ('schema', 'approval')}
    if source.get('D36', {}).get(relative) != payload:
        fail('AUTHORITY_PAYLOAD_MISMATCH', relative)
    return authority, doc, source


def upstream(project, context):
    """Reopen normal D01/D23/D24/D25/D35 consumers; fixtures must isolate here."""
    import flow109
    import librelane_contract as contract
    import step_output_collector as versions
    source_intent = flow109.dft_source_intent(project, context)
    intent = source_intent['source_binding']['intent']
    if intent.get('requires_scan') is not True:
        fail('SCAN_INTENT_ABSENT', 'D01 requires_scan')
    scan = flow109.physical_d24_binding(project, context, source_intent)
    records = {}
    for step in ('D19', 'D25', 'D35'):
        body, record = flow109._accepted_row(project,
            Path('reports/flow109/default_rows') / (step + '.json'), step)
        records[step] = record
        if step == 'D25' and body.get('metric_acceptance_status', body.get('flow109_acceptance')) != 'PASS':
            fail('D25_PURPOSE_UNMEASURED', 'current functional equivalence required')
    retained = versions.latest_pass(project, '17')
    if not retained or not all(retained.get(k) is True for k in ('current_inputs', 'canonical_pass')):
        fail('PLACED_CURRENT_PASS_ABSENT', 'D35 current native placement')
    handoff_path = project / 'reports/phase3/librelane_placement_handoff.json'
    handoff = json.loads(handoff_path.read_text())
    state = Path(handoff['state'])
    if not state.is_absolute():
        state = project / state
    state = bound(project, reference(project, state))
    if sha(state) != handoff['state_sha256']:
        fail('PLACED_STATE_STALE', 'original state_out')
    native = contract.validate_step_receipt(state.parent, 'OpenROAD.DetailedPlacement')
    views = {}
    for view in ('odb', 'def'):
        row = handoff['views'][view]
        paths = [Path(row[k]) for k in ('source', 'dest')]
        paths = [p if p.is_absolute() else project / p for p in paths]
        for p in paths:
            bound(project, reference(project, p))
        if any(sha(p) != row['source_sha256'] for p in paths) or row['dest_sha256'] != row['source_sha256']:
            fail('PLACED_HANDOFF_STALE', view)
        value = json.loads(state.read_text()).get(view)
        if Path(str(value)).resolve() != paths[0].resolve():
            fail('PLACED_VIEW_FOREIGN', view)
        views[view] = reference(project, paths[1])
    # Bind every original native receipt artifact, not just the copied ODB.
    native_readset = [reference(project, state.parent / name) for name in native['sha256']]
    return {'intent': intent, 'D01': source_intent, 'plan': flow109.dft_plan_reference(source_intent),
            'scan': scan, 'accepted': records, 'placed': views,
            'handoff': reference(project, handoff_path), 'native_readset': native_readset}


def prepare(project, context):
    import flow109
    import librelane_contract as contract
    project = Path(project).resolve()
    current = flow109.validate_execution_context(context)
    if current['resolved_row']['id'] != 'D36' or current['features'].get('physical') is not True:
        fail('CONTEXT_INVALID', 'physical D36 only')
    from flow109_admission import require_launch_admission
    require_launch_admission(project, 'flow109.D36', {'flow109_context': current})
    prior = upstream(project, current)
    if set(prior['placed']) != {'odb', 'def'}:
        fail('PLACED_VIEWS_MISSING', 'current D35 ODB and DEF required')
    for record in prior['placed'].values():
        bound(project, record)
    manifest_path = project / INPUT
    manifest = json.loads(manifest_path.read_text())
    authority, adopted, source = approved(project,
        'requirements/scan_physical/scan_flush_errors.json', 'vibeic.flow109.requirement-authority.v1')
    if (source.get('project') != str(project) or source.get('purpose') != PURPOSE
            or source.get('manifest') != reference(project, manifest_path)
            or manifest.get('schema') != 'vibeic.flow109.d36-input.v1'
            or manifest.get('upstream') != prior or source.get('operation_sources') != operation_sources()):
        fail('SOURCE_AUTHORITY_MISMATCH', 'project/manifest/upstream/current source')
    plan = prior['plan']
    if plan.get('planned_chain_count') != 1:
        fail('CHAIN_COUNT_UNQUALIFIED', 'only the reviewed single-chain endpoint scope is supported')
    limit = plan.get('max_chain_length')
    if type(limit) is not int or limit < 1 or len(prior['scan']['scan_cell_reconciliation']['cells']) > limit:
        fail('PLAN_LIMIT_EXCEEDED', 'complete current population must fit the D01 limit')
    mode = prior['intent']['test_mode']
    ports = prior['intent']['test_port_def']
    if (mode.get('clock_select', {}).get('functional_value') != 0
            or mode.get('clock_select', {}).get('scan_value') != 1
            or mode.get('scan_edge') != 'rising' or mode.get('edge') != 'rising'
            or mode.get('scan_clock') != ports['tck']['native']
            or mode.get('clock_select', {}).get('native') != ports['test']['native']):
        fail('CLOCK_STRATEGY_UNRESOLVED', 'D01 explicit functional/test/tck selection required')
    period = manifest.get('scan_period_ns')
    if type(period) not in (int, float) or not 0 < period < float('inf'):
        fail('SCAN_PROTOCOL_ABSENT', 'approved scan_period_ns; no functional-clock substitution')
    if (manifest.get('scan_protocol') != 'positive_edge_zero_one_alternating_full_chain'
            or source.get('qualification_scope') != {'purpose': PURPOSE, 'clock_mixing': 'no_mix',
                'edge': 'rising', 'planned_chain_count': plan['planned_chain_count'],
                'scan_protocol': manifest['scan_protocol']}
            or source.get('test_output_change') != manifest.get('test_output_change')
            or not isinstance(manifest.get('test_output_change'), dict)
            or manifest['test_output_change'].get('port') != ports['scan_out']['public']):
        fail('PURPOSE_UNQUALIFIED', 'explicit test-output semantics and qualified protocol required')
    launch = contract.local_image_attestation()
    if any(launch.get(k) != source.get('qualified_' + k) for k in ('image_id', 'image')):
        fail('IMAGE_UNQUALIFIED', 'actual image differs')
    tools = tool_readset()
    if tools != source.get('actual_tool_readset'):
        fail('TOOLS_UNQUALIFIED', 'current executable readset')
    inputs = [manifest['liberty'], *manifest['models'], *manifest['D19_mode_authorities'], *manifest['clock_constraints']]
    if not manifest['clock_constraints']:
        fail('CLOCK_CONSTRAINTS_ABSENT', 'actual D19-approved scan-mode SDC required')
    if not manifest['models'] or len(manifest['D19_mode_authorities']) != 2:
        fail('MODEL_OR_MODE_AUTHORITY_ABSENT', 'models and D19 scenario/mode bindings required')
    for record in inputs:
        bound(project, record)
    if (manifest.get('defines') != source.get('qualified_defines')
            or manifest.get('models') != source.get('qualified_models')
            or manifest.get('scan_cells') != source.get('qualified_scan_cells')
            or not manifest.get('scan_cells') or not source.get('qualified_cell_types')):
        fail('MODELS_UNQUALIFIED', 'exact official models/defines/cell semantics required')
    for name, relative, schema in (
            ('scenario_constraints', 'requirements/base_10/scenario_constraints.json', 'vibeic.flow109.requirement-authority.v1'),
            ('mode_library_rc_mapping', 'adopted/base_10/mode_library_rc_mapping.json', 'vibeic.flow109.adopted-reference.v1')):
        if not any(x['path'] == relative for x in manifest['D19_mode_authorities']):
            fail('D19_MODE_AUTHORITY_ABSENT', relative)
        import flow109_metric_acceptance as metrics
        d19_authority, d19_doc = metrics._approved_document(project, relative, authority='requirements_owner', schema=schema)
        expected = json.loads(bound(project, d19_authority['source']).read_text()).get(name)
        if {k: v for k, v in d19_doc.items() if k not in ('schema', 'approval', 'producer_binding')} != expected:
            fail('D19_AUTHORITY_UNBOUND', relative)
    return {'project': project, 'context': current, 'upstream': prior, 'manifest': manifest,
            'manifest_ref': reference(project, manifest_path), 'authority': authority,
            'source': source, 'launch': launch, 'tools': tools}


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


def native_subject(prepared):
    """Actual native inputs, separated from mutable admission/report audit bytes."""
    m, prior = prepared['manifest'], prepared['upstream']
    keys = ('top', 'liberty', 'models', 'defines', 'scan_cells', 'scan_period_ns',
            'scan_protocol', 'clock_constraints', 'test_output_change')
    return {**{key: m[key] for key in keys}, 'placed_odb': prior['placed']['odb'],
            'population': sorted(prior['scan']['scan_cell_reconciliation']['cells'], key=lambda item: item['instance']),
            'ports': prior['intent']['test_port_def'], 'mode': prior['intent']['test_mode'],
            'plan': {k: prior['plan'][k] for k in ('planned_chain_count', 'max_chain_length')},
            'tools': prepared['tools'],
            'image': prepared['source']['qualified_image'],
            'image_id': prepared['source']['qualified_image_id']}


def reopen(prepared):
    """Independent original-execution adoption prevents caller resealing."""
    project = prepared['project']
    pointer = json.loads((project / EXECUTION).read_text())
    path = bound(project, pointer)
    authority, adopted, source = approved(project, ADOPTED_EXECUTION,
        'vibeic.flow109.adopted-reference.v1')
    if (adopted.get('execution') != pointer or source.get('manifest') != prepared['manifest_ref']
            or source.get('project') != str(project) or source.get('purpose') != PURPOSE):
        fail('ORIGINAL_EXECUTION_UNADOPTED', 'exact execution/project/manifest required')
    doc = json.loads(path.read_text())
    if (doc.get('schema') != 'vibeic.flow109.d36-execution.v1'
            or doc.get('project') != str(project) or doc.get('native_subject') != native_subject(prepared)
            or doc.get('sources') != adopted.get('producer_sources')
            or doc.get('tools') != prepared['tools']
            or doc.get('producer') != 'phase3_one_shot_runner.step_scan_physical'
            or doc.get('qualification_source') != adopted.get('qualification_source')):
        fail('EXECUTION_STALE', 'subject/producer/tool readset differs')
    for record in doc['readset']:
        bound(project, record)
    launch = json.loads(bound(project, doc['launch']).read_text())
    ins = launch['container_inspect']
    images = launch['image_inspect']
    if (ins['Id'] != doc['cid'] or ins['Image'] != prepared['source']['qualified_image_id']
            or not any(i['Id'] == ins['Image'] for i in images)
            or launch['image'] != prepared['source']['qualified_image']):
        fail('ORIGINAL_LAUNCH_UNBOUND', 'actual original CID/image')
    outputs = doc['outputs']
    for key in ('before', 'after', 'netlist', 'odb', 'map', 'flush', 'native_log', 'script', 'manifest_snapshot',
                'simulation_log', 'simulation_result', 'testbench', 'compile_log'):
        bound(project, outputs[key])
    manifest = {**prepared['manifest'], 'qualified_cell_types': prepared['source']['qualified_cell_types']}
    chain = derive_map(bound(project, outputs['before']), bound(project, outputs['after']), manifest,
                       prepared['upstream']['intent'], prepared['upstream']['scan']['scan_cell_reconciliation']['cells'])
    if json.loads(bound(project, outputs['map']).read_text()) != chain:
        fail('MAP_CHANGED', 'map differs from original native connectivity')
    original_manifest = bound(project, outputs['manifest_snapshot'])
    original_qualification = json.loads(bound(project, doc['qualification_source']).read_text())
    if (sha(original_manifest) != doc['manifest']['sha256']
            or json.loads(original_manifest.read_text()) != doc['subject_manifest']
            or original_qualification.get('manifest') != doc['manifest']
            or original_qualification.get('operation_sources') != doc['sources']
            or original_qualification.get('actual_tool_readset') != doc['tools']
            or original_qualification.get('project') != str(project)
            or original_qualification.get('purpose') != PURPOSE
            or native_subject({'manifest': doc['subject_manifest'], 'upstream': doc['upstream'],
                               'tools': doc['tools'], 'source': original_qualification}) != doc['native_subject']):
        fail('ORIGINAL_INPUT_PROVENANCE_UNBOUND', 'retain original manifest and reviewed producer qualification')
    raw_log = bound(project, outputs['native_log']).read_text()
    if raw_log.count('D36_EXECUTE_START') != 1 or raw_log.count('D36_EXECUTE_DONE') != 1:
        fail('SKIPPED_NATIVE_EXECUTION', 'actual native entry/exit markers absent')
    required_readset = [*outputs.values(), doc['launch']]
    if any(r not in doc['readset'] for r in required_readset):
        fail('INCOMPLETE_NATIVE_READSET', 'all actual output/launch artifacts required')
    clock = check_clock(bound(project, outputs['netlist']).read_text(),
        bound(project, manifest['liberty']).read_text(), prepared['upstream']['intent'], chain)
    flush = json.loads(bound(project, outputs['flush']).read_text())
    if (flush.get('map') != outputs['map'] or flush.get('models') != manifest['models']
            or flush.get('defines') != manifest['defines'] or flush.get('clock') != clock
            or flush.get('protocol') != manifest['scan_protocol']
            or type(flush.get('errors')) is not int or flush['errors'] < 0
            or type(flush.get('checked_edges')) is not int or flush['checked_edges'] != 8 * chain['population']):
        fail('FLUSH_UNBOUND', 'non-vacuous actual population, clock, models, protocol')
    terminal = re.findall(r'^D36_FLUSH_DONE checked=(\d+) errors=(\d+)$',
        bound(project, outputs['simulation_log']).read_text(), re.M)
    sim_rc = json.loads(bound(project, outputs['simulation_result']).read_text()).get('returncode')
    if (len(terminal) != 1 or list(map(int, terminal[0])) != [flush['checked_edges'], flush['errors']]
            or type(sim_rc) is not int or (sim_rc != 0) != bool(flush['errors'])):
        fail('FLUSH_INCOMPLETE', 'raw actual simulation completion differs')
    if doc.get('native_rc') != 0:
        fail('NATIVE_EXECUTION_INCOMPLETE', 'native rc alone is not a proof')
    return {'execution': pointer, 'chain_map': chain, 'map_reference': outputs['map'],
            'scan_flush_errors': flush['errors'], 'adoption': authority,
            'native_status': 'FAIL' if flush['errors'] else 'PASS'}


def pattern_map_binding(project, expected, context):
    """BLOCKING read-only dependency for existing downstream pattern consumers.

    Reopen current D36 through its normal consumer; an API-only measurement or
    a stale canonical row is insufficient. This does not execute D36 or D52.
    """
    import flow109
    import flow109_metric_acceptance as metrics
    project = Path(project).resolve()
    caller = flow109.validate_execution_context(context)
    plan = flow109.resolve_plan(caller['features'])
    current = flow109.execution_context(plan, 'D36', 'D36')
    measured = metrics.accept_d36(project, current)
    if measured['status'] != 'PASS':
        fail('PATTERN_MAP_UNMEASURED', measured.get('reason'))
    canonical, _ = flow109._accepted_row(project,
        Path('reports/flow109/default_rows/D36.json'), 'D36')
    observed = measured['map_reference']
    if canonical.get('metric_acceptance', {}).get('map_reference') != observed:
        fail('PATTERN_MAP_UNPUBLISHED', 'normal canonical D36 map required')
    if observed != expected:
        fail('PATTERN_MAP_STALE', 'patterns belong to another current D36 map')
    return observed


def execute(project, context):
    """Existing adapter ABI, delegating the native action to its physical owner."""
    import phase3_one_shot_runner as owner
    return owner.step_scan_physical(Path(project).resolve(), context)


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
    project, m, intent = prepared['project'], prepared['manifest'], prepared['upstream']['intent']
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
    path('manifest.json').write_bytes((project / INPUT).read_bytes())
    original_launch = Path(os.environ['VIBEIC_LIBRELANE_LOCAL_ATTESTATION'])
    path('launch.json').write_bytes(original_launch.read_bytes())
    if prepare(project, prepared['context']) != prepared:
        fail('INPUT_CHANGED_DURING_EXECUTION', 'current inputs/source/tools/launch')
    outputs = {k: reference(project, path(v)) for k, v in {
        'manifest_snapshot': 'manifest.json', 'before': 'before.tsv', 'after': 'after.tsv', 'netlist': 'stitched.v', 'odb': 'stitched.odb',
        'map': 'map.json', 'flush': 'flush.json', 'native_log': 'native.log', 'script': 'stitch.tcl',
        'simulation_log': 'simulation.log', 'simulation_result': 'simulation.result.json',
        'testbench': 'tb.v', 'compile_log': 'compile.log'}.items()}
    doc = {'schema': 'vibeic.flow109.d36-execution.v1', 'project': str(project),
        'producer': 'phase3_one_shot_runner.step_scan_physical',
        'qualification_source': prepared['authority']['source'],
        'manifest': prepared['manifest_ref'], 'subject_manifest': m, 'native_subject': native_subject(prepared),
        'upstream': prepared['upstream'], 'sources': operation_sources(), 'tools': prepared['tools'],
        'cid': prepared['launch']['cid'], 'launch': reference(project, path('launch.json')),
        'native_rc': result.returncode, 'outputs': outputs,
        'readset': [reference(project, p) for p in sorted(directory.iterdir()) if p.is_file()]}
    write_json(path('execution.json'), doc)
    write_json(project / EXECUTION, reference(project, path('execution.json')))
    return {'native_status': 'FAIL' if errors else 'PASS', 'execution': reference(project, path('execution.json'))}


def owner(project, context):
    """BLOCKING; unchanged or stale retained execution never silently re-stitches."""
    from _atomic_artefact import write_json
    import flow109
    import flow109_metric_acceptance as metrics
    result = {'step_id': 'D36', 'context_sha256': context['context_sha256'],
              'component_status': 'NOT_MEASURED', 'default_row_status': 'NOT_MEASURED',
              'flow109_acceptance': 'NOT_MEASURED', 'whole_flow_acceptance': 'NOT_MEASURED',
              'delivery_accepted': False, 'completed': False, 'native_started': False}
    try:
        prepared = prepare(project, context)
        if (project / EXECUTION).exists():
            current = reopen(prepared)
            result.update(component_status=current['native_status'], producer_reused=True)
        else:
            parent = flow109.validate_execution_context(json.loads(Path(os.environ[flow109.CONTEXT_ENV]).read_text()))
            attempt = flow109._bound_attempt(project, parent, os.environ.get(flow109.ATTEMPT_ENV))
            if (attempt / 'result.json').exists():
                fail('ATTEMPT_IMMUTABLE', str(attempt))
            result['native_started'] = True
            current = run_native(prepared, attempt / 'D36-native')
            result.update(component_status=current['native_status'], producer_reused=False)
        accepted = metrics.accept_d36(project, context)
        status = 'FAIL' if result['component_status'] == 'FAIL' else accepted['status']
        result.update(default_row_status=status, flow109_acceptance='FAIL' if status == 'FAIL' else 'NOT_MEASURED',
                      completed=False,
                      metric_acceptance=accepted, reason=accepted.get('reason'))
    except (ValueError, OSError, KeyError, TypeError, AttributeError, subprocess.TimeoutExpired) as exc:
        result.update(reason=getattr(exc, 'code', 'D36_NATIVE_UNAVAILABLE'), detail=str(exc))
        if (result['native_started'] and getattr(exc, 'code', '') in (
                'D36_FUNCTIONAL_LOAD_CHANGED', 'D36_NATIVE_POPULATION_MISMATCH', 'D36_SCAN_ENABLE_MISMATCH')):
            result.update(component_status='FAIL', default_row_status='FAIL', flow109_acceptance='FAIL')
    immutable = project / 'reports/phase3/scan_physical/owners' / (uuid.uuid4().hex + '.json')
    write_json(immutable, result)
    write_json(project / 'reports/phase3/scan_physical/owner.json', result)
    return {**result, 'owner_report': reference(project, immutable)}



def consume_default_row_completion(project, context, result):
    """Existing canonical completion ABI: fresh owner and current metrics required."""
    import flow109_metric_acceptance as metrics
    project = Path(project).resolve()
    current = metrics.accept_d36(project, context)
    status, reason = 'NOT_MEASURED', 'D36_OWNER_COMPLETION_UNPROVEN'
    try:
        raw = json.loads(bound(project, result['owner_report']).read_text())
        expected = {key: value for key, value in result.items() if key != 'owner_report'}
        if raw != expected or raw.get('context_sha256') != context['context_sha256']:
            fail('OWNER_REPORT_STALE', 'actual owner report and context differ')
        if raw.get('component_status') == 'FAIL':
            status, reason = 'FAIL', raw.get('reason')
        elif raw.get('default_row_status') == 'PASS' and raw.get('component_status') == 'PASS':
            status, reason = current['status'], current.get('reason')
    except (ValueError, OSError, KeyError, TypeError) as exc:
        reason = getattr(exc, 'code', 'D36_OWNER_REPORT_UNPROVEN')
    return {'step_id': 'D36', 'context_sha256': context['context_sha256'],
            'default_row_status': status, 'completed': status == 'PASS',
            'flow109_acceptance': status, 'whole_flow_acceptance': 'NOT_MEASURED',
            'delivery_accepted': False, 'metric_acceptance': current,
            'owner_report': result.get('owner_report'), 'reason': reason}
