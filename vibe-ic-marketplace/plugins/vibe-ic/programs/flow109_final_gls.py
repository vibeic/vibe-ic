"""D71 final-SDF gate replay on the adopted D44 netlist.

This is a component boundary, not final or whole-flow acceptance.  It consumes
an exact D44 common-netlist baseline and a D70 receipt whose SDF role is
explicitly ``final``.  Candidate/STAPostPNR SDFs are not aliases for that
receipt.  The existing ``Vibeic.GateLevelSim`` step executes Icarus/vvp, the
existing ``sdf_gate_sim`` readers judge every scenario/corner transcript, and
``post_layout_sim_check`` reads back the published result.

The implemented Icarus scope is deliberately small: applied SDF delays plus a
self-checking functional verdict.  A requirement for setup/hold, recovery,
removal, width, period, pulse or other timing-check semantics is refused rather
than inferred from a functionally passing replay.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import time
import inspect
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
from flow109_admission import AdmissionRefusal, require_launch_admission
import post_layout_sim_check as postcheck
import sdf_gate_sim as sgs
import flow109_final_lec as final_lec
import flow109_final_extract as final_extract
import flow109_final_electrical as final_electrical

SCHEMA = 'vibeic.flow109.final-gls.v1'
D70_SCHEMA = 'vibeic.flow109.final-electrical.v1'
INPUT = 'input/flow109/D71.json'
D44_BASELINE = 'adopted/final_lec/sta_lvs_release_netlist_mapping.json'
SUPPORTED_REQUIRED_BEHAVIORS = frozenset({'sdf_delay_annotation', 'functional_self_check'})
LIMITATIONS = [
    'Icarus/vvp only; no alternate or commercial simulator result is implied.',
    'Only observed SDF delay application and declared self-checking functional scenarios are accepted.',
    'Setup/hold, recovery/removal, width/period, pulse rejection, min/typ/max sweep semantics and other timing checks are not qualified by this component.',
    'D71 component PASS is not D69/D70, final-row, signoff, whole-flow or whole-IC acceptance.',
]
IDENT = re.compile(r'[A-Za-z_][A-Za-z0-9_$]*\Z')


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path, code='D71_INPUT_INVALID'):
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise AdmissionRefusal(code, str(path)) from exc
    if not isinstance(value, dict):
        raise AdmissionRefusal(code, str(path))
    return value


def _bound(project, value, code='D71_INPUT_UNBOUND'):
    if not isinstance(value, dict) or not value.get('path') or not value.get('sha256'):
        raise AdmissionRefusal(code, str(value))
    path = Path(value['path'])
    path = path if path.is_absolute() else Path(project) / path
    try:
        actual = _sha(path)
    except OSError as exc:
        raise AdmissionRefusal(code, str(path)) from exc
    if actual != value['sha256']:
        raise AdmissionRefusal(code, str(path))
    return path.resolve()


def _record(project, path):
    path = Path(path).resolve()
    return {'path': str(path.relative_to(project)) if path.is_relative_to(project) else str(path),
            'sha256': _sha(path)}


def operation_sources():
    from execution_provider_catalog import source_closure
    sys.path.insert(0, str(HERE / 'librelane_plugins'))
    from librelane_plugin_vibeic import GateLevelSim
    paths = source_closure({HERE / 'sdf_gate_sim.py', HERE / 'post_layout_sim_check.py'})
    paths.update({Path(__file__), HERE / 'flow109_admission.py', HERE / 'full_stack_functional_tb.py',
                  Path(inspect.getsourcefile(GateLevelSim))})
    return {str(path.relative_to(HERE.parent)): _sha(path) for path in sorted(paths)}


def _same_record(a, b):
    return isinstance(a, dict) and isinstance(b, dict) and a == b


def _same_population(a, b):
    return (isinstance(a, list) and isinstance(b, list) and bool(a) and bool(b)
            and len(a) == len(set(a)) and len(b) == len(set(b)) and set(a) == set(b))


def _sdf_census(path, top):
    text = Path(path).read_text(errors='replace')
    if text.count('(') != text.count(')') or not re.search(r'\(SDFVERSION\s+"3\.0"\)', text):
        raise AdmissionRefusal('D71_FINAL_SDF_CORRUPT', str(path))
    design = re.search(r'\(DESIGN\s+"([^"]+)"\)', text)
    if not design or design.group(1) != top:
        raise AdmissionRefusal('D71_FINAL_SDF_WRONG_NETLIST', str(path))
    cells = len(re.findall(r'\(CELL\s*(?=\()', text))
    delays = len(re.findall(r'\((?:IOPATH|INTERCONNECT)\b', text))
    if not re.search(r'\(TIMESCALE\s+[^)]+\)', text) or not cells or not delays:
        raise AdmissionRefusal('D71_FINAL_SDF_INCOMPLETE', str(path))
    return {'sdfversion': '3.0', 'design': top, 'cells': cells, 'delay_records': delays,
            'sha256': _sha(path)}


ENGINEERING_SCOPE = 'engineering_native_component'


def _engineering_admission(context, manifest):
    if manifest.get('execution_scope') != ENGINEERING_SCOPE:
        return False
    from flow109 import source_owned_native_admission
    admitted = source_owned_native_admission(context)
    if not admitted or not admitted.get('admitted'):
        raise AdmissionRefusal('D71_ENGINEERING_OWNER_REQUIRED', 'source-owned existing-native admission required')
    return True


def _engineering_components(project, d69, d70):
    """Reopen existing RCX and final-SDF component consumers, not final PV.

    Engineering simulation consumes the exact native views and receipts. It
    asserts no final-fill geometry/qualification acceptance or resource-policy
    equivalence to the historical PV job.
    """
    from librelane_contract import validate_step_receipt
    signoff, postroute = final_electrical.signoff, final_electrical.postroute
    for record, module, label in [(d69, final_extract, 'D69'), (d70, final_electrical, 'D70')]:
        if record.get('operation_sources') != module.operation_sources():
            raise AdmissionRefusal(label + '_OPERATION_SOURCE_CHANGED', 'existing component source changed')
    for path, digest in d69.get('inputs', {}).items():
        _bound(project, {'path': path, 'sha256': digest})
    if not d69.get('inputs'):
        raise AdmissionRefusal('D71_FINAL_EXTRACTION_INPUTS_ABSENT', 'native RCX readset required')
    for value in (d69.get('retained_geometry') or {}).values():
        _bound(project, value)
    rcx_state = _bound(project, d69.get('rcx_state'))
    _bound(project, d69.get('rcx_receipt'))
    binding = signoff.bind_rcx_spefs(rcx_state.parent, rcx_state.parent / 'state_in.json')
    if binding != d69.get('rcx_binding'):
        raise AdmissionRefusal('D71_FINAL_RCX_BINDING_CHANGED', str(rcx_state))
    rcx = _read(rcx_state)
    if d69.get('final_spefs') != d69.get('spefs'):
        raise AdmissionRefusal('D71_FINAL_PARASITIC_PROVENANCE_UNBOUND', 'SPEF aliases differ')
    for corner, ref in d69['final_spefs'].items():
        path = _bound(project, ref)
        if str(path) != rcx.get('spef', {}).get(corner) or final_extract.scan_spef(path) != d69['spef_consumer'][corner]:
            raise AdmissionRefusal('D71_FINAL_SPEF_CHANGED', corner)
    folder, state = postroute.stapostpnr_state(project)
    if _record(project, folder / 'state_out.json') != d70.get('sta_state'):
        raise AdmissionRefusal('D70_STA_STATE_CHANGED', str(folder))
    export = postroute.bind_stapostpnr_sdfs(folder, state,
                 expected_netlist=_bound(project, d70.get('netlist')))
    if (signoff.judge_timing(signoff.corner_timing(folder)) != d70.get('timing_judgment')
            or d70.get('final_sdfs') != d70.get('sdfs')
            or {c: _record(project, p) for c, p in postroute.corner_sdfs(state).items()} != d70.get('final_sdfs')
            or d70.get('netlist') != d69.get('adopted_views', {}).get('netlist')
            or d70.get('sdc') != d69.get('adopted_views', {}).get('sdc')
            or d70.get('d69_receipt') != d70.get('final_parasitics_receipt')):
        raise AdmissionRefusal('D70_FINAL_OUTPUT_BINDING_MISMATCH', 'native STA/SDF identity changed')
    dependencies = [rcx_state, rcx_state.parent / 'state_in.json', rcx_state.parent / 'vibeic_receipt.json',
                    folder / 'state_out.json', folder / 'state_in.json', folder / 'config.json',
                    folder / 'vibeic_receipt.json']
    for lane, step in [(rcx_state.parent, 'OpenROAD.RCX'), (folder, 'OpenROAD.STAPostPNR')]:
        receipt = validate_step_receipt(lane, step)
        dependencies += [lane / rel for rel in receipt['sha256']]
    return ({'final_geometry': d69['final_geometry'], 'final_spefs': d69['final_spefs']},
            {'sta_state': d70['sta_state'], 'final_sdfs': d70['final_sdfs'],
             'required_corners': d70['required_corners']}, dependencies)


def engineering_bench_text(project, source, module, top, *, observation_schedule=None,
                           netlist=None, sdc=None, sdfs=None):
    """Existing arithmetic emitter owns any final-SDF observation rescheduling."""
    text = Path(source).read_text()
    instance = sgs._tb_dut_instance(text, top)
    if not instance:
        raise AdmissionRefusal('D71_SCENARIO_INVALID', 'actual native top instance absent')
    observation = None
    if observation_schedule is not None:
        if observation_schedule != 'native_sta_output_deadline':
            raise AdmissionRefusal('D71_OBSERVATION_UNSUPPORTED', str(observation_schedule))
        import arith_oracle_tb_gen as arith
        plan = arith._scenario_header(Path(source))
        import testbench_gen as tb_producer
        original_body = text
        prefix = '// ' + tb_producer.ORACLE_GENERATED_MARKER + '_emit_case_arithmetic_scenario\n'
        if original_body.startswith(prefix):
            original_body = original_body[len(prefix):]
        if (plan is None or arith.emit_arithmetic_scenario_module(module, plan, dut_module=top) != original_body):
            raise AdmissionRefusal('D71_EXISTING_ARITHMETIC_PRODUCER_REQUIRED', str(source))
        declared = sgs.declared_dut_binding(Path(project), plan['spec']['top'], Path(netlist).read_text())
        deadline = sgs._postlayout_output_deadline(Path(project), plan, declared,
                                                  Path(netlist), Path(sdc), list(sdfs or []))
        updated = json.loads(json.dumps(plan))
        updated['observation'].update(sample_offset_ns=deadline['sample_offset_ns'],
                                      postlayout_deadline=deadline)
        # The oracle, framing/serial latency, input population and stimulus
        # clock are unchanged. The existing emitter snapshots observer args
        # while the original negedge driver continues without skipped cycles.
        for key in plan:
            if key != 'observation' and updated[key] != json.loads(json.dumps(plan[key])):
                raise AdmissionRefusal('D71_SCENARIO_CONTRACT_CHANGED', key)
        if updated['observation']['clock_period_ns'] != plan['observation']['clock_period_ns']:
            raise AdmissionRefusal('D71_SCENARIO_CONTRACT_CHANGED', 'clock period')
        text = arith.emit_arithmetic_scenario_module(module, updated, dut_module=top)
        observation = {'original': plan['observation'], 'final': updated['observation'],
                       'framing': plan['framing'], 'transactions': plan['transactions'],
                       'comparisons': plan['comparisons'],
                       'producer': 'arith_oracle_tb_gen.emit_arithmetic_scenario_module'}
    return sgs.inject_sdf_annotation(text, module, instance, sgs.SDF_PLACEHOLDER), observation


def _engineering_bench(project, requirements, scenario, item, top, *, native_observation=None):
    catalog_path = _bound(project, requirements.get('source_catalog'))
    catalog = _read(catalog_path)
    if (catalog.get('schema') != 'vibeic.full_stack_functional.v1'
            or catalog.get('program') != 'full_stack_functional_tb'):
        raise AdmissionRefusal('D71_EXISTING_SCENARIO_SOURCE_REQUIRED', str(catalog_path))
    entries = [row for row in catalog.get('cases', []) if row.get('name') == scenario]
    if len(entries) != 1 or entries[0].get('state') != 'passed':
        raise AdmissionRefusal('D71_EXISTING_SCENARIO_SOURCE_REQUIRED', scenario)
    row = entries[0]
    source = _bound(project, item.get('source_testbench'))
    if (source.name != Path(str(row.get('tb', ''))).name
            or _sha(source) != row.get('tb_sha256')):
        raise AdmissionRefusal('D71_SOURCE_TESTBENCH_CHANGED', scenario)
    text = source.read_text()
    instance = sgs._tb_dut_instance(text, top)
    module = sgs._TB_MODULE_RE.search(text)
    if not instance or not module or module.group(1) != item.get('module'):
        raise AdmissionRefusal('D71_SCENARIO_INVALID', scenario)
    annotated = _bound(project, item.get('testbench'))
    expected, _observation = engineering_bench_text(project, source, item['module'], top,
        observation_schedule=item.get('observation_schedule'), **(native_observation or {}))
    if annotated.read_text() != expected:
        raise AdmissionRefusal('D71_TESTBENCH_DERIVATION_CHANGED', scenario)
    return [catalog_path, source]


def prepare(project, context):
    project = Path(project).resolve()
    if context.get('requested_step') != 'D71' or context.get('native_step_id') != 'flow109.D71':
        raise AdmissionRefusal('D71_CONTEXT_MISMATCH', 'final GLS adapter only')
    sources = operation_sources()
    for use in context.get('runtime_tool_uses') or []:
        if use.get('semantics', {}).get('operation_sources') != sources:
            raise AdmissionRefusal('D71_OPERATION_SOURCE_CHANGED', use.get('use_id'))
    manifest = _read(project / INPUT)
    engineering = _engineering_admission(context, manifest)
    extra_inputs = []
    top = str(manifest.get('top') or '')
    if manifest.get('schema') != SCHEMA or not IDENT.fullmatch(top):
        raise AdmissionRefusal('D71_INPUT_INVALID', 'schema/top')

    # D44 owns the adopted final logical subject.  Re-open both the baseline
    # and its current D44 component instead of accepting a caller's PASS word.
    d44_authority = final_lec.validate_common_baseline(project, manifest.get('d44_component'))
    if d44_authority.get('baseline') != manifest.get('d44_baseline'):
        raise AdmissionRefusal('D71_D44_ADOPTED_NETLIST_UNBOUND', 'D44 current baseline differs')
    baseline_path = _bound(project, d44_authority['baseline'])
    if baseline_path != (project / D44_BASELINE).resolve():
        raise AdmissionRefusal('D71_D44_BASELINE_NOT_CANONICAL', str(baseline_path))
    baseline = _read(baseline_path)
    d44_path = _bound(project, manifest.get('d44_component'))
    d44 = _read(d44_path)
    proof_path = _bound(project, baseline.get('proof'))
    proof = _read(proof_path)
    declared_partitions = proof.get('declared_partitions')
    if (baseline.get('producer') != 'flow109_final_lec'
            or baseline.get('mapping') != 'same_logical_bytes'
            or d44.get('schema') != 'vibeic.flow109.final-lec.v1'
            or d44.get('component_status') != 'PASS'
            or not _same_record(d44.get('common_baseline'), manifest.get('d44_baseline'))
            or not _same_record(d44.get('proof_receipt'), baseline.get('proof'))
            or proof.get('verdict') != 'PASS'
            or not isinstance(declared_partitions, list) or not declared_partitions
            or set(declared_partitions) != set(proof.get('partitions') or {})
            or proof.get('non_equivalent_points') or proof.get('unproven_points')
            or proof.get('xbits_partitions')):
        raise AdmissionRefusal('D71_D44_ADOPTED_NETLIST_UNBOUND', str(d44_path))
    netlist = _bound(project, baseline.get('adopted_netlist'))
    if any(_sha(_bound(project, rec)) != _sha(netlist)
           for rec in (baseline.get('consumer_netlists') or {}).values()):
        raise AdmissionRefusal('D71_D44_CONSUMER_NETLIST_DIFFERS', str(baseline_path))

    # D70 must say final, bind the current D69 extraction receipt, and name
    # these exact netlist/SDC/SDF bytes.  A D49/candidate receipt cannot meet
    # this shape and is refused by name even if its files happen to exist.
    d70_path = _bound(project, manifest.get('d70_receipt'))
    d70 = _read(d70_path)
    if (d70.get('schema') != D70_SCHEMA or d70.get('step_id') != 'D70'
            or d70.get('component_status') != 'PASS'
            or d70.get('sdf_role') != 'final'
            or d70.get('producer') != 'flow109_final_electrical'):
        raise AdmissionRefusal('D71_FINAL_TIMING_RECEIPT_REQUIRED', str(d70_path))
    d69_path = _bound(project, d70.get('d69_receipt'))
    d69 = _read(d69_path)
    if (d69.get('schema') != 'vibeic.flow109.final-extract.v1'
            or d69.get('step_id') != 'D69'
            or d69.get('producer') != 'flow109_final_extract'
            or d69.get('component_status') != 'PASS'):
        raise AdmissionRefusal('D71_FINAL_EXTRACTION_RECEIPT_REQUIRED', str(d69_path))
    if engineering:
        d69_authority, d70_authority, extra_inputs = _engineering_components(project, d69, d70)
    else:
        d69_authority = final_extract.validate_final_parasitics(project, d70.get('d69_receipt'))
        d70_authority = final_electrical.validate_final_electrical(project, manifest.get('d70_receipt'))
    final_geometry = _bound(project, d69.get('final_geometry'))
    final_spefs = d69.get('final_spefs')
    provenance = d70.get('sdf_provenance')
    if (not isinstance(final_spefs, dict) or not final_spefs
            or not isinstance(provenance, dict)
            or provenance.get('basis') != 'D69_final_parasitics'
            or not _same_record(provenance.get('d69_receipt'), d70.get('d69_receipt'))
            or provenance.get('spef_by_rc_scene') != final_spefs
            or provenance.get('sta_state') != d70.get('sta_state')
            or not _same_population(provenance.get('declared_corners'),
                                    d70.get('required_corners'))
            or d69_authority.get('final_geometry') != d69.get('final_geometry')
            or d69_authority.get('final_spefs') != final_spefs
            or d70_authority.get('sta_state') != d70.get('sta_state')
            or d70_authority.get('final_sdfs') != d70.get('final_sdfs')
            or not _same_population(d70_authority.get('required_corners'),
                                    d70.get('required_corners'))):
        raise AdmissionRefusal('D71_FINAL_PARASITIC_PROVENANCE_UNBOUND', str(d70_path))
    spef_paths = [_bound(project, record) for record in final_spefs.values()]
    sdc = _bound(project, d70.get('sdc'))
    if not _same_record(d70.get('netlist'), baseline.get('adopted_netlist')):
        raise AdmissionRefusal('D71_D70_NETLIST_DIFFERS_FROM_D44', str(d70_path))

    requirements_path = _bound(project, manifest.get('requirements'))
    requirements = _read(requirements_path)
    approval = requirements.get('approval') or {}
    if not engineering and (approval.get('status') != 'APPROVED'
            or approval.get('authority') != 'requirements_owner'
            or not approval.get('source_reference')):
        raise AdmissionRefusal('D71_REQUIREMENTS_NOT_APPROVED', str(requirements_path))
    corners = requirements.get('required_corners')
    scenarios = requirements.get('required_scenarios')
    behaviors = requirements.get('required_timing_behaviors')
    if (not isinstance(corners, list) or not corners or len(corners) != len(set(corners))
            or not all(IDENT.fullmatch(str(item)) for item in corners)
            or not isinstance(scenarios, list) or not scenarios
            or len(scenarios) != len(set(scenarios))
            or not all(IDENT.fullmatch(str(item)) for item in scenarios)
            or not isinstance(behaviors, list) or not behaviors):
        raise AdmissionRefusal('D71_REQUIRED_POPULATION_INVALID', str(requirements_path))
    unsupported = sorted(set(behaviors) - SUPPORTED_REQUIRED_BEHAVIORS)
    if unsupported:
        raise AdmissionRefusal('D71_REQUIRED_TIMING_BEHAVIOR_UNSUPPORTED', ', '.join(unsupported))
    if set(behaviors) != SUPPORTED_REQUIRED_BEHAVIORS:
        raise AdmissionRefusal('D71_REQUIRED_TIMING_BEHAVIOR_INCOMPLETE', str(behaviors))
    if ((not engineering and not _same_population(d70.get('required_corners'), corners))
            or not set(corners) <= set(d70.get('required_corners') or [])
            or set(d70.get('final_sdfs') or {}) != set(d70.get('required_corners') or [])):
        raise AdmissionRefusal('D71_FINAL_CORNER_BINDING_MISMATCH', str(d70_path))

    state_path = _bound(project, d70.get('sta_state'))
    state = _read(state_path)
    if (set(state.get('sdf') or {}) != set(d70.get('required_corners') or [])
            or Path(str(state.get('nl') or '')).resolve() != netlist
            or Path(str(state.get('sdc') or '')).resolve() != sdc
            or set(state.get('spef') or {}) != set(final_spefs)
            or any(Path(str(state['spef'][scene])).resolve()
                   != _bound(project, final_spefs[scene]) for scene in final_spefs)):
        raise AdmissionRefusal('D71_FINAL_STATE_IDENTITY_MISMATCH', str(state_path))

    sdfs, census = {}, {}
    for corner in corners:
        path = _bound(project, d70['final_sdfs'][corner])
        if Path(str(state['sdf'].get(corner) or '')).resolve() != path:
            raise AdmissionRefusal('D71_FINAL_STATE_IDENTITY_MISMATCH', corner)
        sdfs[corner] = path
        census[corner] = _sdf_census(path, top)
    declared = manifest.get('scenarios')
    if not isinstance(declared, dict) or set(declared) != set(scenarios):
        raise AdmissionRefusal('D71_REQUIRED_SCENARIO_COVERAGE', str(scenarios))
    cases = []
    for name in scenarios:
        item = declared[name]
        if not isinstance(item, dict) or not IDENT.fullmatch(str(item.get('module') or '')):
            raise AdmissionRefusal('D71_SCENARIO_INVALID', name)
        if engineering:
            extra_inputs += _engineering_bench(project, requirements, name, item, top,
                native_observation={'netlist': netlist, 'sdc': sdc,
                                    'sdfs': [_bound(project, ref) for ref in d70['final_sdfs'].values()]})
        bench = _bound(project, item.get('testbench'))
        text = bench.read_text(errors='replace')
        if (text.count(sgs.SDF_PLACEHOLDER) != 1
                or not re.search(r'(?:GATE_SIM_RESULT\s+|\[TB\s+' + re.escape(name)
                                 + r'\]\s+(?:PASS|FAIL))', text)):
            raise AdmissionRefusal('D71_SCENARIO_NOT_SELF_CHECKING', name)
        cases.append({'id': name, 'module': item['module'], 'testbench': str(bench)})
    models = manifest.get('models')
    if not isinstance(models, list) or not models:
        raise AdmissionRefusal('D71_CELL_MODELS_ABSENT', 'nonempty exact model population required')
    model_paths = [_bound(project, value) for value in models]
    used = sgs.netlist_used_cells(netlist.read_text(errors='replace'))
    closure = sgs.verilog_model_closure(model_paths, used)
    if set(map(str, closure.get('files') or [])) != set(map(str, model_paths)):
        raise AdmissionRefusal('D71_MODEL_CLOSURE_MISMATCH', str(closure))

    operation = _bound(project, manifest.get('operation_config'))
    expected_operation = {'schema': SCHEMA, 'operation': 'Vibeic.GateLevelSim',
        'compile_flags': sgs._IVERILOG_FLAGS, 'runtime_flags': ['-sdf-info']}
    if _read(operation) != expected_operation:
        raise AdmissionRefusal('D71_OPERATION_CONFIG_UNSUPPORTED', str(operation))
    model_bundle = _bound(project, manifest.get('model_bundle'))
    if _read(model_bundle) != {'models': models, 'model_closure': 'exact'}:
        raise AdmissionRefusal('D71_MODEL_BUNDLE_MISMATCH', str(model_bundle))
    for use in context.get('runtime_tool_uses') or []:
        if (_bound(project, use.get('config')) != operation
                or _bound(project, use.get('pdk')) != model_bundle
                or _bound(project, use.get('deck')) != requirements_path
                or use.get('corner') != ','.join(corners)):
            raise AdmissionRefusal('D71_QUALIFICATION_SCOPE_MISMATCH', use.get('use_id'))
    paths = [*extra_inputs, project / INPUT, baseline_path, d44_path, proof_path, d70_path, d69_path,
             final_geometry, *spef_paths, netlist, sdc, state_path,
             requirements_path, operation, model_bundle, *sdfs.values(), *model_paths,
             *(Path(case['testbench']) for case in cases)]
    return {'engineering': engineering, 'manifest': manifest, 'top': top, 'netlist': netlist, 'sdc': sdc,
            'sdfs': sdfs, 'sdf_census': census, 'requirements': requirements,
            'cases': cases, 'models': model_paths, 'model_closure': closure,
            'sources': sources, 'inputs': {str(path): _sha(path) for path in paths},
            'd44_baseline': manifest['d44_baseline'], 'd70_receipt': manifest['d70_receipt'],
            'd69_receipt': d70['d69_receipt']}


def _before(project, context, prepared):
    require_launch_admission(project, 'flow109.D71', {'flow109_context': context})
    if operation_sources() != prepared['sources']:
        raise AdmissionRefusal('D71_OPERATION_SOURCE_CHANGED', 'before actual native launch/readback')
    for path, digest in prepared['inputs'].items():
        if not Path(path).is_file() or _sha(path) != digest:
            raise AdmissionRefusal('D71_INPUT_CHANGED', path)


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
               'source_self_check': scored, 'stdout_sha256': _sha(path) if path.is_file() else None,
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
             'sdf source       : D70 final electrical receipt bound to D69 final extraction',
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
           'final_sdfs': copied, 'd44_baseline': prepared['d44_baseline'],
           'd70_receipt': prepared['d70_receipt'], 'd69_receipt': prepared['d69_receipt'],
           'native_step': _record(project, attempt / 'native/gls_runs.json'),
           'limitations': LIMITATIONS, 'judge': judged,
           'execution_scope': ENGINEERING_SCOPE if prepared.get('engineering') else 'final_gls_component',
           'full_row_acceptance': 'NOT_MEASURED'}
    write_json(sim_dir / 'results.json', doc)
    flag = sim_dir / 'pass.flag'
    if (not prepared.get('engineering') and judged.get('verdict') == 'PASS' and not population['missing']
            and population['all_functional_pass'] and population['all_corners_annotated']):
        write_text(flag, f"PASS {len(expected)} final corner/scenario observation(s)\n")
    elif flag.exists():
        flag.unlink()
    findings, stats = postcheck.audit(publication_root)
    checker = postcheck.build_report(findings, stats, str(project))
    write_json(attempt / 'post_layout_sim_check.json', checker)
    doc['post_layout_sim_check'] = _record(project, attempt / 'post_layout_sim_check.json')
    doc['results_log'] = _record(project, sim_dir / 'results.log')
    doc['results_json'] = _record(project, sim_dir / 'results.json')
    return doc, checker


def run_native_cases(step, state, manifest, *, workers=1, native_run=None):
    """Bound independent existing GateLevelSim calls; only this thread publishes the index."""
    if type(workers) is not int or not 1 <= workers <= 4:
        raise AdmissionRefusal('D71_CASE_WORKERS_INVALID', str(workers))
    from librelane.state import DesignFormat
    from librelane_plugin_vibeic import GateLevelSim
    native_run = native_run or GateLevelSim.run
    root = Path(step.step_dir)
    cases = sorted(manifest['cases'], key=lambda case: case['id'])
    if len({case['id'] for case in cases}) != len(cases):
        raise AdmissionRefusal('D71_DUPLICATE_CASE', 'native output ownership must be unique')
    sdfs = state[DesignFormat.SDF]
    jobs = [(corner, case) for corner in sorted(sdfs) for case in cases]

    def one(job):
        corner, case = job
        folder = root / 'case_runs' / corner / case['id']
        folder.mkdir(parents=True, exist_ok=False)
        case_manifest = {**manifest, 'cases': [case]}
        manifest_path = folder / 'manifest.json'
        write_json(manifest_path, case_manifest)
        child = SimpleNamespace(config={**step.config, 'VIBEIC_GLS_MANIFEST': str(manifest_path)},
                                step_dir=str(folder), _run=step._run)
        child_state = {**state, DesignFormat.SDF: {corner: sdfs[corner]}}
        started = time.time_ns()
        argv_calls = []
        def logged_run(argv, log, limit, cwd=None):
            resources = str(log) + '.resources.txt'
            # GNU time observes each unchanged native invocation; _run still
            # owns subprocess cwd, timeout, transcript and return status.
            timed = ['/usr/bin/time', '-f', 'max_rss_kib=%M\nuser_s=%U\nsystem_s=%S\nelapsed_s=%e',
                     '-o', resources, '--', *argv]
            call = {'argv': list(argv), 'executed_argv': timed, 'log': str(log),
                    'cwd': str(cwd) if cwd else None, 'resources': resources}
            argv_calls.append(call)
            rc = step._run(timed, log, limit, cwd=cwd)
            call['returncode'] = rc
            return rc
        child._run = logged_run
        try:
            native_run(child, child_state)
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
        rows = list(pool.map(one, jobs))
    rows.sort(key=lambda row: (row['corner'], row['case']))
    write_json(root / 'gls_runs.json', {'manifest': step.config['VIBEIC_GLS_MANIFEST'],
        'netlist': str(state[DesignFormat.NETLIST]), 'runs': rows, 'case_workers': workers})
    return rows


def execute(project, context):
    project = Path(project).resolve()
    attempt = project / 'reports/flow109/D71' / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    record = {'schema': SCHEMA, 'step_id': 'D71', 'component_status': 'NOT_MEASURED',
              'flow109_acceptance': 'NOT_MEASURED', 'native_started': False,
              'metric_acceptance_status': 'UNIMPLEMENTED',
              'context_sha256': context.get('context_sha256'), 'limitations': LIMITATIONS}
    try:
        require_launch_admission(project, 'flow109.D71', {'flow109_context': context})
        prepared = prepare(project, context)
        record.update(operation_sources=prepared['sources'], inputs=prepared['inputs'],
                      sdf_readback=prepared['sdf_census'],
                      execution_scope=ENGINEERING_SCOPE if prepared.get('engineering') else 'final_gls_component',
                      full_row_acceptance='NOT_MEASURED')
        manifest_dir = attempt / 'manifest'
        manifest_dir.mkdir()
        stubs = manifest_dir / 'phys_cell_stubs.v'
        write_text(stubs, '// D71 exact model closure is complete; no generated cell behavior.\n')
        manifest = {'compile_flags': sgs._IVERILOG_FLAGS, 'top': prepared['top'],
                    'netlist': str(prepared['netlist']), 'cases': prepared['cases'],
                    'not_a_subject': [], 'models': list(map(str, prepared['models'])),
                    'stubs': str(stubs), 'sdf_placeholder': sgs.SDF_PLACEHOLDER,
                    'model_closure': prepared['model_closure']}
        manifest_path = manifest_dir / 'gls_manifest.json'
        write_json(manifest_path, manifest)
        _before(project, context, prepared)
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
        _before(project, context, prepared)
        workers = prepared['manifest'].get('case_workers', 1)
        if workers != 1 and not prepared.get('engineering'):
            raise AdmissionRefusal('D71_CASE_WORKERS_ENGINEERING_ONLY', str(workers))
        run_native_cases(step, state, manifest, workers=workers)
        _before(project, context, prepared)
        judged = sgs.judge_tool_arm(attempt / 'native', manifest)
        if prepared.get('engineering'):
            judged = engineering_transcript_readback(attempt / 'native', judged)
        published, checker = _publish(project, prepared, judged, attempt)
        record.update(native={'manifest': _record(project, manifest_path),
                              'runs': _record(project, attempt / 'native/gls_runs.json')},
                      result=published, checker=checker)
        population = published['annotation_population']
        if (judged.get('verdict') == 'PASS' and checker['verdict'] == 'PASS'
                and not population['missing'] and population['all_functional_pass']
                and population['all_corners_annotated']):
            if prepared.get('engineering'):
                record.update(component_status='NOT_MEASURED', engineering_component_status='PASS',
                              full_row_acceptance='NOT_MEASURED', requirements_authority='NOT_MEASURED',
                              reason='D71_ENGINEERING_GLS_MEASURED_FINAL_ACCEPTANCE_UNMEASURED')
            else:
                record.update(component_status='PASS', reason='D71_FINAL_GLS_COMPONENT_MEASURED')
        else:
            record.update(component_status='FAIL', engineering_component_status='FAIL' if prepared.get('engineering') else None,
                          reason='D71_NATIVE_GLS_FAILED')
    except AdmissionRefusal as exc:
        record.update(component_status=exc.status, reason=exc.code, detail=str(exc))
    except Exception as exc:
        record.update(component_status='NOT_MEASURED', reason='D71_NATIVE_UNAVAILABLE_OR_UNSUPPORTED',
                      detail=f'{type(exc).__name__}: {exc}')
    path = attempt / 'component.json'
    write_json(path, record)
    record['receipt'] = _record(project, path)
    return record
