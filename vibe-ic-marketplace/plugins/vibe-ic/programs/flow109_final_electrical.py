"""D70 Default bounded component: final RCX SPEFs -> STAPostPNR and SDF."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import uuid

import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _atomic_artefact import write_json
from flow109_admission import AdmissionRefusal, require_launch_admission
import flow109_final_extract as extract
import librelane_fill_stream as files
import librelane_postroute as postroute
import librelane_signoff as signoff
from librelane_contract import Refusal, _load, digest

SCHEMA = 'vibeic.flow109.final-electrical.v1'
INPUT = 'input/flow109/D70.json'
OWNER_INPUT_SCHEMA = 'vibeic.flow109.final-electrical-owner-input.v1'
OWNER_RECORD_SCHEMA = 'vibeic.flow109.final-electrical-owner-binding.v1'
OWNER_INPUT = 'input/flow109/D70-power-ir.json'


def _native_refusal_status(code):
    return 'FAIL' if code == 'LL_STEP_FAILED' else 'NOT_MEASURED'


def operation_sources():
    paths = (Path(__file__), Path(signoff.__file__), Path(postroute.__file__), Path(extract.__file__),
             HERE / 'flow109_final_perc.py')
    return {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def _read(path):
    try: value = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc: raise AdmissionRefusal('D70_REQUIRED_INPUT_ABSENT', str(path)) from exc
    if not isinstance(value, dict): raise AdmissionRefusal('D70_REQUIRED_INPUT_INVALID', str(path))
    return value


def _required_corner_population(value):
    """Return the declared scene population, rejecting absent/duplicate names."""
    if (not isinstance(value, list) or not value
            or not all(isinstance(corner, str) and corner for corner in value)
            or len(value) != len(set(value))):
        raise AdmissionRefusal('D70_REQUIRED_CORNERS_ABSENT',
                               'nonempty unique required_corners required')
    return set(value)


def _retained_sta(project, manifest, parasitics):
    """Reopen an explicitly selected native producer; never fall back to a run.

    Reuse is limited to this carrier's exact final physical/logical inputs.
    The existing producer receipt, timing readers and SDF export consumer own
    the evidence. Export availability says nothing about simulator annotation.
    """
    from librelane_contract import validate_step_receipt
    path = files._bound(project, manifest.get('retained_sta_state'))
    if not path.is_relative_to(project) or path.name != 'state_out.json':
        raise AdmissionRefusal('D70_RETAINED_STA_FOREIGN', str(path))
    folder, state = path.parent, _read(path)
    receipt = validate_step_receipt(folder, 'OpenROAD.STAPostPNR')
    expected = {'nl': parasitics['adopted_views']['netlist'],
                'sdc': parasitics['adopted_views']['sdc'],
                'def': parasitics['filled_def'], 'odb': parasitics['odb']}
    timed = receipt['input'].get('state_files') or {}
    for role, reference in expected.items():
        source = files._bound(project, reference)
        if (Path(str(state.get(role) or '')).resolve() != source
                or timed.get(str(source)) != digest(source)):
            raise AdmissionRefusal('D70_RETAINED_STA_BASIS_MISMATCH', role)
    spefs = state.get('spef') or {}
    scenes = {signoff.rc_corner(key): value for key, value in spefs.items()}
    if (len(scenes) != len(spefs) or set(scenes) != set(parasitics['final_spefs'])
            or any(Path(str(scenes[key])).resolve() != files._bound(project, ref)
                   or timed.get(str(files._bound(project, ref))) != ref['sha256']
                   for key, ref in parasitics['final_spefs'].items())):
        raise AdmissionRefusal('D70_RETAINED_STA_BASIS_MISMATCH', 'final SPEF scenes')
    _required_corner_population(manifest.get('required_corners'))
    _metric_digital_basis(project, {
        'manifest': files._record(project, project / INPUT),
        'final_parasitics_receipt': manifest['final_parasitics_receipt'],
        'required_corners': manifest['required_corners']}, native_state=(folder, state))
    # Timing observations must belong to the original receipt, not newly
    # supplied report text beside a valid SDF. Preserve every measured failure.
    evidence = ['config.json']
    if (folder / 'metrics.json').exists():
        evidence.append('metrics.json')
    for corner in manifest['required_corners']:
        evidence.extend(str(Path(corner) / name) for name in
                        ('sta.log', signoff.CORNER_REPORT, 'unpropagated.rpt'))
    for name in evidence:
        source = folder / name
        if not source.is_file() or receipt['sha256'].get(name) != digest(source):
            raise AdmissionRefusal('D70_RETAINED_STA_EVIDENCE_UNBOUND', name)
    exports = postroute.bind_stapostpnr_sdfs(folder, state,
        expected_netlist=files._bound(project, expected['nl']))
    return folder, state, exports


def execute(project, context):
    if context.get("resolved_row", {}).get("profile", {}).get("id") == "analog_die":
        return _execute_analog(project, context)
    project = Path(project).resolve(); attempt = project / 'reports/flow109/D70' / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    result = {'schema': SCHEMA, 'step_id': 'D70', 'component_status': 'NOT_MEASURED',
              'flow109_acceptance': 'NOT_MEASURED', 'native_started': False,
              'unmeasured_obligations': ['final_mission_scenario_coverage', 'final_timing_si_targets',
                  'final_analog_mission_targets', 'final_ir_em_thermal_aging_targets',
                  'final_sdf_annotation', 'thermal_temperature_gradient_targets',
                  'thermal_aware_em_timing_feedback', 'signal_em_targets',
                  'power_signal_coupled_integrity', 'mission_aging_degradation'],
              'context_sha256': context.get('context_sha256')}
    try:
        require_launch_admission(project, 'flow109.D70', {'flow109_context': context})
        manifest = _read(project / INPUT)
        if manifest.get('schema') != SCHEMA: raise AdmissionRefusal('D70_REQUIRED_INPUT_INVALID', 'schema')
        result['manifest'] = files._record(project, project / INPUT)
        required_corners = manifest.get('required_corners')
        required_population = _required_corner_population(required_corners)
        parasitics = extract.validate_final_parasitics(project, manifest.get('final_parasitics_receipt'))
        d69 = _read(files._bound(project, manifest['final_parasitics_receipt']))
        odb = files._bound(project, parasitics['odb'])
        routed_def = files._bound(project, parasitics['filled_def'])
        netlist = files._bound(project, parasitics['adopted_views']['netlist']); sdc = files._bound(project, parasitics['adopted_views']['sdc'])
        spefs = {signoff.rc_corner(c): files._bound(project, r) for c, r in parasitics['spefs'].items()}
        native = manifest.get('librelane') or {}
        if set(native) != {'image', 'pdk_root', 'pdk'}: raise AdmissionRefusal('D70_NATIVE_CONFIGURATION_ABSENT', 'image/pdk_root/pdk required')
        sources = operation_sources()
        if 'retained_sta_state' in manifest:
            folder, _, exports = _retained_sta(project, manifest, parasitics)
            sta = {'sta': str(folder)}
            result.update(native_reused=True, retained_sta_state=manifest['retained_sta_state'],
                          retained_sta_receipt=files._record(project, folder / 'vibeic_receipt.json'),
                          sdf_export=exports)
        else:
            result['native_started'] = True
            sta = signoff.run(project, native['image'], Path(native['pdk_root']), native['pdk'],
                              routed_def=routed_def, routed_odb=odb, netlist=netlist, sdc=sdc,
                              extract=False, time=True, direct_spefs=spefs, lane='flow109-d70-sta')
        corners = signoff.corner_timing(Path(sta['sta'])); timing = signoff.judge_timing(corners)
        state_path, record_path = Path(sta['sta']) / 'state_out.json', project / postroute.STEP23_RECORD
        write_json(record_path, {'step': 'OpenROAD.STAPostPNR', 'mode': 'librelane',
            'spef_producer': 'flow109.D69', 'sta_state': str(state_path),
            'sta_state_sha256': digest(state_path), 'corners': corners, 'judgment': timing})
        _, state = postroute.stapostpnr_state(project); sdfs = postroute.corner_sdfs(state)
        if (required_population != set(corners) or required_population != set(sdfs)
                or required_population != set(state.get('sdf') or {})):
            raise AdmissionRefusal('D70_FINAL_CORNER_STATE_MISMATCH',
                                   'declared corners must exactly match timing and state SDF population')
        if (Path(str(state.get('nl') or '')).resolve() != netlist.resolve()
                or Path(str(state.get('sdc') or '')).resolve() != sdc.resolve()):
            raise AdmissionRefusal('D70_ADOPTED_VIEW_STATE_MISMATCH', 'STA state netlist/SDC differ')
        state_spefs = state.get('spef') or {}
        by_corner = {signoff.rc_corner(key): value for key, value in state_spefs.items()}
        expected = parasitics['final_spefs']
        if (len(by_corner) != len(state_spefs) or set(by_corner) != set(expected)
                or any(Path(str(by_corner[key])).resolve()
                       != files._bound(project, expected[key]).resolve() for key in by_corner)):
            raise AdmissionRefusal('D70_FINAL_SPEF_STATE_MISMATCH', 'STA state RC scenes differ from D69')
        final_sdfs = {c: files._record(project, p) for c, p in sdfs.items()}
        state_record = files._record(project, state_path)
        provenance = {'basis': 'D69_final_parasitics',
                      'd69_receipt': manifest['final_parasitics_receipt'],
                      'sta_state': state_record,
                      'declared_corners': required_corners,
                      'spef_by_rc_scene': parasitics['final_spefs']}
        status = timing['verdict']
        scan_required = (context.get('features') or {}).get('requires_scan') is True
        if scan_required:
            coverage = (manifest.get('scan_timing_coverage') or {
                'status': 'NOT_MEASURED', 'reason': 'D70_RETAINED_SCAN_COVERAGE_ABSENT'}
                if result.get('native_reused') else
                signoff.run_scan_timing(project, context, 'D70', native, state))
            scan_current = signoff.validate_scan_timing(project, context, coverage, state)
            # Preserve a valid measured failure, including when later coverage
            # becomes unmeasured. The raw acquisitions remain retained.
            scan_status = ('FAIL' if coverage['status'] == 'FAIL' or scan_current['status'] == 'FAIL'
                           else scan_current['status'])
            status = ('FAIL' if status == 'FAIL' or scan_status == 'FAIL' else
                      'PASS' if status == scan_status == 'PASS' else 'NOT_MEASURED')
            result['scan_timing_coverage'] = coverage
            result['scan_timing_readback'] = scan_current
        else:
            result['scan_timing_coverage'] = {'status': 'NOT_APPLICABLE', 'reason': 'requires_scan is false'}
        result.update(component_status=status, reason='D70_NATIVE_ELECTRICAL_' + status,
                      producer='flow109_final_electrical', sdf_role='final',
                      final_parasitics_receipt=manifest['final_parasitics_receipt'],
                      d69_receipt=manifest['final_parasitics_receipt'],
                      netlist=parasitics['adopted_views']['netlist'],
                      sdc=parasitics['adopted_views']['sdc'],
                      required_corners=required_corners,
                      sta_state=state_record, sta_record=files._record(project, record_path),
                      corners=corners, timing_judgment=timing,
                      sdfs=final_sdfs, final_sdfs=final_sdfs,
                      sdf_provenance=provenance,
                      ir_status='NOT_MEASURED', execution_context=context)
        result['operation_sources'] = sources
    except AdmissionRefusal as exc: result.update(component_status=exc.status, reason=exc.code, detail=str(exc))
    except Refusal as exc: result.update(
        component_status=_native_refusal_status(exc.code),
        reason=exc.code, detail=str(exc))
    except Exception as exc: result.update(component_status='NOT_MEASURED', reason='D70_NATIVE_UNAVAILABLE_OR_UNSUPPORTED', detail=str(exc))
    path = attempt / 'component.json'; write_json(path, result); result['receipt'] = files._record(project, path)
    return result


def validate_final_electrical(project, receipt_ref, *, require_pass=True):
    project = Path(project).resolve(); record = _read(files._bound(project, receipt_ref))
    if record.get('profile') == 'analog_die':
        return validate_analog_mission(project, receipt_ref, require_pass=require_pass)
    if (record.get('schema') != SCHEMA
            or record.get('component_status') not in (('PASS',) if require_pass else ('PASS', 'FAIL'))):
        raise AdmissionRefusal('D70_COMPONENT_NOT_ACCEPTED', 'current native STA component PASS required')
    require_launch_admission(project, 'flow109.D70', {'flow109_context': record.get('execution_context')})
    if record.get('operation_sources') != operation_sources():
        raise AdmissionRefusal('D70_OPERATION_SOURCE_CHANGED', 'adapter or retained consumer changed')
    parasitics = extract.validate_final_parasitics(project, record['final_parasitics_receipt'])
    if record.get('native_reused') is True:
        manifest_path = files._bound(project, record.get('manifest'))
        manifest = _read(manifest_path)
        if (manifest_path != project / INPUT
                or manifest.get('final_parasitics_receipt') != record['final_parasitics_receipt']
                or manifest.get('retained_sta_state') != record.get('retained_sta_state')):
            raise AdmissionRefusal('D70_FINAL_INPUT_CHANGED', 'retained producer selection differs')
        retained, _, exports = _retained_sta(project, manifest, parasitics)
        if (exports != record.get('sdf_export')
                or files._record(project, retained / 'vibeic_receipt.json') != record.get('retained_sta_receipt')
                or files._record(project, retained / 'state_out.json') != record.get('sta_state')):
            raise AdmissionRefusal('D70_FINAL_OUTPUT_BINDING_MISMATCH', 'retained STA export changed')
    folder, state = postroute.stapostpnr_state(project)
    if files._record(project, folder / 'state_out.json') != record['sta_state']:
        raise AdmissionRefusal('D70_STA_STATE_CHANGED', str(folder))
    if signoff.judge_timing(signoff.corner_timing(folder)) != record['timing_judgment']:
        raise AdmissionRefusal('D70_TIMING_CHANGED', str(folder))
    scan_status = 'PASS'
    if ((record.get('execution_context') or {}).get('features') or {}).get('requires_scan') is True:
        current = signoff.validate_scan_timing(project, record['execution_context'],
            record.get('scan_timing_coverage') or {}, state)
        scan_status = current['status']
        if current['status'] != 'PASS' and (require_pass or current['status'] != 'FAIL'):
            raise AdmissionRefusal('D70_SCAN_TIMING_FAIL' if current['status'] == 'FAIL' else 'D70_SCAN_MODES_NOT_ACQUIRED',
                'declared shift/capture timing is ' + current['status'], status=current['status'])
    state_sdfs = postroute.corner_sdfs(state)
    required_population = _required_corner_population(record.get('required_corners'))
    expected_sdfs = {corner: files._record(project, path)
                     for corner, path in state_sdfs.items()}
    if (record.get('producer') != 'flow109_final_electrical'
            or record.get('sdf_role') != 'final'
            or record.get('d69_receipt') != record.get('final_parasitics_receipt')
            or record.get('final_sdfs') != record.get('sdfs')
            or record.get('final_sdfs') != expected_sdfs
            or required_population != set(state_sdfs)
            or required_population != set(state.get('sdf') or {})
            or record.get('netlist') != parasitics['adopted_views']['netlist']
            or record.get('sdc') != parasitics['adopted_views']['sdc']):
        raise AdmissionRefusal('D70_FINAL_OUTPUT_BINDING_MISMATCH', 'final receipt aliases/state drifted')
    provenance = record.get('sdf_provenance') or {}
    if (provenance.get('basis') != 'D69_final_parasitics'
            or provenance.get('d69_receipt') != record.get('d69_receipt')
            or provenance.get('sta_state') != record.get('sta_state')
            or provenance.get('declared_corners') != record.get('required_corners')
            or provenance.get('spef_by_rc_scene') != parasitics['final_spefs']):
        raise AdmissionRefusal('D70_FINAL_PROVENANCE_MISMATCH', 'D69/state/corner provenance drifted')
    return {'sta_state': record['sta_state'], 'sdfs': record['sdfs'],
            'final_sdfs': record['final_sdfs'], 'required_corners': record['required_corners'],
            'timing_status': 'FAIL' if 'FAIL' in (scan_status, record['timing_judgment']['verdict']) else record['timing_judgment']['verdict'],
            'component_electrical_current': True, 'flow109_acceptance': 'NOT_MEASURED'}


def _same_record(project, observed, expected, code, label):
    """Require the same current bytes while allowing validated transport moves."""
    try:
        observed_path = files._bound(project, observed)
        expected_path = files._bound(project, expected)
    except (KeyError, TypeError, OSError, Refusal) as exc:
        raise AdmissionRefusal(code, label) from exc
    # Both paths were reopened and hashed by `_bound`.  Literal path equality
    # would reject an otherwise safe project relocation already admitted by
    # the owners' transport seam; byte identity remains mandatory.
    if observed.get('sha256') != expected.get('sha256'):
        raise AdmissionRefusal(code, label)


def _owner_component(project, ref, step):
    path = files._bound(project, ref)
    value = _read(path)
    if (value.get('schema') != 'vibeic/backend-result/2'
            or value.get('step_id') != step
            or value.get('verdict') not in ('PASS', 'FAIL')):
        raise AdmissionRefusal('D70_OWNER_COMPONENT_INVALID', f'{step}: {path}')
    return value


def _activity_binding(project, manifest, expected_netlist):
    """Reopen D55's approved scenario/load/rail freeze without upgrading it.

    D55 power is vector annotated, but the final STAPostPNR and PDNSim owners
    do not consume that VCD.  The returned binding therefore proves the
    applicable activity authority exists; it never labels final power/IR as
    dynamic or mission complete.
    """
    import flow109_functional_activity as activity
    component_ref = manifest.get('d55_activity_component')
    freeze_ref = manifest.get('d55_activity_freeze')
    component = _read(files._bound(project, component_ref))
    freeze = _read(files._bound(project, freeze_ref))
    if (component.get('schema') != activity.SCHEMA or component.get('step_id') != 'D55'
            or component.get('component_status') != 'PASS'
            or component.get('freeze') != freeze_ref
            or freeze.get('schema') != activity.SCHEMA):
        raise AdmissionRefusal('D70_D55_ACTIVITY_INVALID', 'current PASS component/freeze required')
    _same_record(project, freeze.get('adopted_netlist'), expected_netlist,
                 'D70_D55_ACTIVITY_BASIS_MISMATCH', 'adopted netlist')
    modes = freeze.get('modes')
    authority = freeze.get('authority')
    loads = freeze.get('external_loads')
    if (not isinstance(modes, dict) or not modes
            or not isinstance(authority, dict)
            or not isinstance(loads, dict) or not loads.get('rails') or not loads.get('ports')):
        raise AdmissionRefusal('D70_D55_ACTIVITY_AUTHORITY_MISSING',
                               'scenarios, rail mapping and external loads required')
    if any(not isinstance(row, dict) or not row.get('activity') or not row.get('consumption')
           for row in modes.values()):
        raise AdmissionRefusal('D70_D55_ACTIVITY_AUTHORITY_MISSING',
                               'each scenario requires activity and consumption records')
    return {'component': component_ref, 'freeze': freeze_ref,
            'modes': sorted(modes), 'authority': authority,
            'external_loads': loads,
            'scope': ('approved D55 functional scenarios/load/rail mapping; '
                      'not consumed by final vectorless STAPostPNR or quasistatic IR')}


def _power_binding(project, record, parasitics, manifest):
    """Consume the existing D56 current-power owner on the final STA state."""
    import _opensta_current as current
    component = _owner_component(project, manifest.get('d56_power_component'), '33')
    try:
        receipt = current.power_binding(project)
    except (OSError, ValueError, KeyError, TypeError, Refusal) as exc:
        raise AdmissionRefusal('D70_D56_POWER_INVALID', str(exc)) from exc
    inputs = {row.get('role'): row for row in receipt.get('inputs') or []
              if isinstance(row, dict)}
    for role, expected in (('netlist', record['netlist']), ('sdc', record['sdc']),
                           ('tool_state', record['sta_state'])):
        row = inputs.get(role)
        observed = ({'path': row.get('path'), 'sha256': row.get('sha256')}
                    if isinstance(row, dict) else None)
        _same_record(project, observed, expected, 'D70_D56_POWER_BASIS_MISMATCH', role)
    spef = inputs.get('spef')
    observed_spef = ({'path': spef.get('path'), 'sha256': spef.get('sha256')}
                     if isinstance(spef, dict) else None)
    if observed_spef not in list(parasitics['final_spefs'].values()):
        raise AdmissionRefusal('D70_D56_POWER_BASIS_MISMATCH', 'final SPEF scene')
    return {'component': manifest['d56_power_component'],
            'receipt': files._record(project, project / 'reports/phase3/power.current.json'),
            'verdict': component['verdict'], 'scope': 'vectorless static STAPostPNR power',
            'activity_consumed': False, 'dynamic_power_status': 'NOT_MEASURED'}


def _ir_binding(project, parasitics, manifest):
    """Consume D57 only when its native solve used the exact final basis."""
    import em_current_density_check as current
    component = _owner_component(project, manifest.get('d57_ir_component'), '24')
    checked = current.validate_primary_ir(project)
    if not checked.get('valid'):
        raise AdmissionRefusal('D70_D57_IR_INVALID', str(checked.get('reason')))
    doc_path = project / 'reports/phase3/ir_drop_librelane.json'
    doc = _read(doc_path)
    native_record = doc.get('record') or {}
    inputs = (native_record.get('selected_inputs')
              if native_record.get('input_mode') == 'current_stapostpnr_odb'
              else doc.get('inputs')) or {}
    expected = {'def': parasitics['filled_def'],
                'netlist': parasitics['adopted_views']['netlist'],
                'sdc': parasitics['adopted_views']['sdc']}
    for role, value in expected.items():
        _same_record(project, inputs.get(role), value,
                     'D70_D57_IR_BASIS_MISMATCH', role)
    if inputs.get('spef') not in list(parasitics['final_spefs'].values()):
        raise AdmissionRefusal('D70_D57_IR_BASIS_MISMATCH', 'final SPEF scene')
    odb = inputs.get('odb')
    final_odb = parasitics['odb']
    try:
        files._bound(project, final_odb)
        odb_matches = (isinstance(odb, dict)
                       and odb.get('sha256') == final_odb.get('sha256'))
    except (KeyError, TypeError, OSError, Refusal):
        odb_matches = False
    if not odb_matches:
        raise AdmissionRefusal('D70_D57_FINAL_ODB_NOT_CONSUMED',
                               'D57 bridge/native basis is not the adopted D69 final ODB')
    return {'component': manifest['d57_ir_component'],
            'receipt': files._record(project, doc_path),
            'verdict': checked['verdict'], 'scope': 'static IR only',
            'dynamic_ir_status': 'NOT_MEASURED',
            'dynamic_ir_reason': ('Vibeic.TransientIR is quasistatic without a bound '
                                  'D55 waveform/current trace; it is not dynamic IR'),
            'signal_em_status': 'NOT_MEASURED'}


def bind_power_ir_owners(project, receipt_ref, input_path=OWNER_INPUT):
    """Publish additive final-basis owner evidence after D70/D56/D57 finish.

    The original D70 receipt is immutable.  Measured owner FAIL dominates;
    otherwise missing dynamic IR, signal EM and mission-limit consumption keep
    the combined D70 obligation NOT_MEASURED even when static evidence is
    current.
    """
    project = Path(project).resolve()
    attempt = project / 'reports/flow109/D70-power-ir' / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    result = {'schema': OWNER_RECORD_SCHEMA, 'step_id': 'D70',
              'component_status': 'NOT_MEASURED', 'binding_status': 'NOT_MEASURED',
              'flow109_acceptance': 'NOT_MEASURED', 'whole_flow_acceptance': 'NOT_MEASURED',
              'whole_ic_acceptance': 'NOT_MEASURED',
              'full_final_geometry_qualification': 'NOT_MEASURED',
              'dynamic_power_status': 'NOT_MEASURED', 'dynamic_ir_status': 'NOT_MEASURED',
              'signal_em_status': 'NOT_MEASURED', 'thermal_status': 'NOT_MEASURED',
              'aging_status': 'NOT_MEASURED'}
    try:
        validate_final_electrical(project, receipt_ref)
        record = _read(files._bound(project, receipt_ref))
        manifest = _read(project / input_path)
        if manifest.get('schema') != OWNER_INPUT_SCHEMA or manifest.get('d70_component') != receipt_ref:
            raise AdmissionRefusal('D70_OWNER_INPUT_INVALID', 'schema/current D70 component')
        features = (record.get('execution_context') or {}).get('features') or {}
        for name in ('thermal', 'aging'):
            if features.get('requires_' + name) is False:
                result[name + '_status'] = 'NOT_APPLICABLE'
        if not features.get('requires_ir') and not features.get('requires_em'):
            raise AdmissionRefusal('D70_POWER_IR_NOT_APPLICABLE',
                                   'selected profile requires neither IR nor EM')
        parasitics = extract.validate_final_parasitics(project, record['final_parasitics_receipt'])
        activity = _activity_binding(project, manifest, record['netlist'])
        power = _power_binding(project, record, parasitics, manifest)
        ir = _ir_binding(project, parasitics, manifest)
        measured_fail = any(row.get('verdict') == 'FAIL' for row in (power, ir))
        result.update(binding_status='CURRENT', activity=activity, power=power, ir=ir,
                      static_power_status=('FAIL' if power['verdict'] == 'FAIL' else 'MEASURED'),
                      static_ir_status=ir['verdict'],
                      component_status='FAIL' if measured_fail else 'NOT_MEASURED',
                      reason=('D70_APPLICABLE_OWNER_MEASURED_FAIL' if measured_fail else
                              'D70_STATIC_POWER_IR_CURRENT_DYNAMIC_EM_UNMEASURED'),
                      d70_component=receipt_ref,
                      unmeasured_obligations=['final_mission_scenario_coverage',
                          'final_ir_em_thermal_aging_targets', 'dynamic_power',
                          'dynamic_ir', 'signal_em'])
    except AdmissionRefusal as exc:
        result.update(component_status=exc.status, reason=exc.code, detail=str(exc))
    except (OSError, ValueError, KeyError, TypeError, Refusal) as exc:
        result.update(reason='D70_OWNER_EVIDENCE_INVALID', detail=str(exc))
    path = attempt / 'owner-binding.json'
    write_json(path, result)
    result['receipt'] = files._record(project, path)
    return result


def _analog_basis(project, reference):
    """Only D69's final analog owner can authenticate a final mission basis."""
    files._bound(project, reference)
    basis = extract.validate_final_parasitics(project, reference)
    if (basis.get('component_parasitics_current') is not True
            or basis.get('extraction_depth') != 'RC'
            or (basis.get('fill_sensitive_parasitics') or {}).get('status') != 'PASS'):
        raise AdmissionRefusal('D70_FINAL_ANALOG_BASIS_UNQUALIFIED',
                               'current qualified final RC required; C_ONLY and D47 cannot substitute')
    # The current C_ONLY D69 interface has no simulator-ready final RC view.
    # Only its owner-validated projection may provide that view in future.
    netlists = basis.get('simulation_netlists')
    if (not isinstance(netlists, dict) or not netlists
            or set(netlists) != set(basis.get('final_spefs') or {})):
        raise AdmissionRefusal('D70_FINAL_SIMULATION_NETLIST_UNAVAILABLE',
                               'D69-bound per-corner simulator-ready RC netlists required')
    for view in netlists.values():
        files._bound(project, view)
    return basis


def _analog_inputs(project, manifest, basis):
    import math
    import corner_yield_vs_spec_check as limits
    if manifest.get('schema') != SCHEMA or not isinstance(manifest.get('mission'), str) or not manifest['mission'].strip():
        raise AdmissionRefusal('D70_ANALOG_MISSION_ABSENT', 'explicit mission required')
    corners = _required_corner_population(manifest.get('required_corners'))
    scenarios = manifest.get('scenarios')
    if (not isinstance(scenarios, list) or not scenarios
            or any(not isinstance(s, dict) or not isinstance(s.get('id'), str) or not s['id'] for s in scenarios)
            or len({s['id'] for s in scenarios}) != len(scenarios)):
        raise AdmissionRefusal('D70_ANALOG_SCENARIOS_ABSENT', 'nonempty unique mission scenarios required')
    if {s.get('corner') for s in scenarios} != corners or not corners <= set(basis['simulation_netlists']):
        raise AdmissionRefusal('D70_ANALOG_CORNER_COVERAGE_MISSING', 'each declared corner requires a final-basis scenario')
    import flow109_analog_model_check as models
    requirements = _read(files._bound(project, manifest.get('model_requirements')))
    report = _read(files._bound(project, manifest.get('model_report')))
    if not requirements.get('required_smokes') or models.consume(project, requirements, report)['verdict'] != 'PASS':
        raise AdmissionRefusal('D70_ANALOG_MODEL_EVIDENCE_UNAVAILABLE', 'current declared native model smokes required')
    declared_models = manifest.get('models') or {}
    smokes = requirements['required_smokes']
    for corner in corners:
        selected = declared_models.get(corner)
        if not isinstance(selected, list) or not selected:
            raise AdmissionRefusal('D70_ANALOG_MODELS_ABSENT', corner)
        for model in selected:
            files._bound(project, model)
            section = model.get('section')
            if (section is not None and (not isinstance(section, str) or not section.strip())
                    or not any(row['corner'] == corner
                               and row['model']['sha256'] == model['sha256']
                               and row['model'].get('section') == section for row in smokes)):
                raise AdmissionRefusal('D70_ANALOG_MODEL_CORNER_UNQUALIFIED',
                                       corner + ': selected library section must match the qualified smoke')
    resolved = []
    for setting in scenarios:
        paths = {key: files._bound(project, setting.get(key)) for key in ('testbench', 'bindings', 'load', 'spec')}
        binding = _read(paths['bindings']); analysis = binding.get('analysis') or {}
        temperature = analysis.get('temperature_c')
        if type(temperature) not in (int, float) or not math.isfinite(temperature):
            raise AdmissionRefusal('D70_ANALOG_TEMPERATURE_ABSENT', setting['id'])
        bounds = limits._spec_limits(_read(paths['spec']))
        if (not bounds or set(bounds) != set(binding.get('measurements') or {})
                or any(not math.isfinite(v) for limit in bounds.values() for v in limit.values() if v is not None)
                or any(limit['min'] is not None and limit['max'] is not None and limit['min'] > limit['max'] for limit in bounds.values())):
            raise AdmissionRefusal('D70_ANALOG_EXPLICIT_LIMITS_ABSENT', setting['id'])
        resolved.append((setting, paths, binding, bounds))
    return resolved


def _analog_native_values(project, record, binding, expected):
    """Reopen actual producer input closure and raw measurements, not scalar status."""
    import math
    import shlex
    import analog_bound_measurements as measured
    import analog_native_sim as sim
    import analog_real_corner_sweep as sweep
    valid, reason = measured.validate_consumed_inputs(project, record.get('native_inputs'))
    if not valid:
        raise AdmissionRefusal('D70_ANALOG_NATIVE_INPUT_CHANGED', reason)
    views = record['native_inputs']
    for view in views.values():
        files._bound(project, view)
    for name in ('netlist', 'testbench', 'bindings'):
        if views.get(name) != expected[name]:
            raise AdmissionRefusal('D70_ANALOG_INPUT_NOT_CONSUMED', name)
    included = list(v for k, v in views.items() if k.startswith('include:'))
    for required in [expected['netlist'], expected['load'], *expected['models']]:
        if not any(v['path'] == required['path'] and v['sha256'] == required['sha256'] for v in included):
            raise AdmissionRefusal('D70_ANALOG_MODEL_OR_LOAD_NOT_CONSUMED', required['path'])
        section = required.get('section')
        if section is not None:
            found = False
            for view in views.values():
                for line in Path(view['path']).read_text(errors='replace').splitlines():
                    if not line.lstrip().lower().startswith('.lib '):
                        continue
                    tokens = shlex.split(line, comments=True)
                    if len(tokens) == 3 and tokens[0].lower() == '.lib':
                        path = (Path(view['path']).parent / tokens[1]).resolve()
                        found |= str(path) == required['path'] and tokens[2] == section
            if not found:
                raise AdmissionRefusal('D70_ANALOG_MODEL_SECTION_NOT_CONSUMED', str(section))
    if record.get('bindings') != binding or not record.get('executions'):
        raise AdmissionRefusal('D70_ANALOG_NATIVE_RECEIPT_INVALID', 'bindings/execution absent')
    for execution in record['executions']:
        files._bound(project, {'path': execution.get('log'), 'sha256': execution.get('log_sha256')})
    transcript = '\n'.join(sim._log_text(e) for e in record['executions'])
    if any(e.get('returncode') != 0 for e in record['executions']) or any(sweep._scan_analysis_failures(transcript)):
        return 'FAIL', {}
    if record.get('status') != 'PASS' or (record.get('temperature') or {}).get('matched') is not True:
        raise AdmissionRefusal('D70_ANALOG_NATIVE_MEASUREMENT_INCOMPLETE', record.get('detail', ''))
    values = {k.casefold(): v for k, v in sweep.native_meas_rows(transcript).items()}
    for match in sweep._MEAS_LINE_RE.finditer(transcript):
        for key, value in sweep._KV_RE.findall(match.group(1)):
            values.setdefault(key.casefold(), float(value))
    if any(name not in values or not math.isfinite(values[name]) or record.get('measurements', {}).get(name) != values[name]
           for name in binding['measurements']):
        raise AdmissionRefusal('D70_ANALOG_RAW_MEASUREMENT_MISSING', 'finite named native values required')
    return 'PASS', {name: values[name] for name in binding['measurements']}


def _execute_analog(project, context):
    import librelane_contract as launch
    import analog_bound_measurements as measured
    import corner_yield_vs_spec_check as limits
    from analog_native_flow import NativeCommands
    project = Path(project).resolve()
    attempt = project / 'reports/flow109/D70' / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    result = dict(schema=SCHEMA, step_id='D70', profile='analog_die', component_status='NOT_MEASURED',
                  completed=False, qualification='NOT_CLAIMED', flow109_acceptance='NOT_MEASURED',
                  whole_flow_acceptance='NOT_MEASURED', delivery_accepted=False, native_started=False,
                  context_sha256=context.get('context_sha256'), execution_context=context, scenarios=[],
                  unmeasured_obligations=['final_thermal_aging_signal_em', 'full_final_mission_signoff'])
    measured_failure = False
    try:
        require_launch_admission(project, 'flow109.D70', {'flow109_context': context})
        result['native_launch'] = launch.local_image_attestation()
        manifest_path = project / INPUT
        manifest_ref = files._record(project, manifest_path); manifest = _read(manifest_path)
        basis = _analog_basis(project, manifest.get('final_parasitics_receipt'))
        scenarios = _analog_inputs(project, manifest, basis)
        result.update(final_parasitics_receipt=manifest['final_parasitics_receipt'], manifest=manifest_ref,
                      operation_sources=operation_sources())
        run = NativeCommands(project, attempt, '', result['native_launch']['image'])
        statuses = []
        for index, (setting, paths, binding, bounds) in enumerate(scenarios):
            netlist = files._bound(project, basis['simulation_netlists'][setting['corner']])
            expected = {key: {'path': str(path.resolve()), 'sha256': digest(path)} for key, path in paths.items()}
            expected['netlist'] = {'path': str(netlist), 'sha256': digest(netlist)}
            expected['models'] = [{**model, 'path': str(files._bound(project, model))} for model in manifest['models'][setting['corner']]]
            destination = attempt / ('mission-' + str(index))
            argv = [str(project), '--netlist', str(netlist), '--testbench', str(paths['testbench']),
                    '--bindings', str(paths['bindings']), '--out', str(destination), '--container', '',
                    '--image', result['native_launch']['image']]
            result['native_started'] = True
            execution = run('analog_bound_measurements.py', argv)
            record_path = destination / 'result.json'; record = _read(record_path)
            status, values = _analog_native_values(project, record, binding, expected)
            violations = [name for name, bound in bounds.items() if name in values and limits._violates(values[name], bound['min'], bound['max'])]
            if violations: status = 'FAIL'
            measured_failure |= status == 'FAIL'; statuses.append(status)
            result['scenarios'].append(dict(id=setting['id'], corner=setting['corner'], status=status,
                values=values, violations=violations, native_receipt=files._record(project, record_path),
                expected_inputs=expected, execution=execution))
        # A valid functional result cannot satisfy unsupported coupled obligations.
        unsupported = [key for key in ('thermal', 'aging', 'signal_em', 'em') if manifest.get(key) is not None]
        result['unsupported_requirements'] = unsupported
        _analog_inputs(project, manifest, basis)
        if files._record(project, manifest_path) != manifest_ref or _analog_basis(project, manifest['final_parasitics_receipt']) != basis:
            raise AdmissionRefusal('D70_ANALOG_CURRENT_BASIS_CHANGED', 'mission/final extraction changed during acquisition')
        result['component_status'] = 'FAIL' if measured_failure else 'NOT_MEASURED' if unsupported else 'PASS'
        result['reason'] = 'D70_ANALOG_MISSION_' + result['component_status']
    except Exception as exc:
        result.update(component_status='FAIL' if measured_failure else 'NOT_MEASURED',
                      reason=getattr(exc, 'code', 'D70_ANALOG_MISSION_UNAVAILABLE'), detail=str(exc))
    result['outputs'] = [str(p) for p in attempt.rglob('*') if p.is_file()]
    path = attempt / 'component.json'; write_json(path, result); result['receipt'] = files._record(project, path)
    return result


def validate_analog_mission(project, receipt_ref, *, require_pass=True):
    """Current final extraction and raw mission values remain independently bound."""
    import corner_yield_vs_spec_check as limits
    project = Path(project).resolve(); record = _read(files._bound(project, receipt_ref))
    if (record.get('schema') != SCHEMA or record.get('step_id') != 'D70' or record.get('profile') != 'analog_die'
            or record.get('component_status') not in (('PASS',) if require_pass else ('PASS', 'FAIL', 'NOT_MEASURED'))
            or record.get('operation_sources') != operation_sources()):
        raise AdmissionRefusal('D70_ANALOG_COMPONENT_NOT_CURRENT', 'current native mission component required')
    require_launch_admission(project, 'flow109.D70', {'flow109_context': record.get('execution_context')})
    manifest_path = files._bound(project, record['manifest'])
    if manifest_path != project / INPUT:
        raise AdmissionRefusal('D70_ANALOG_MISSION_INPUT_FOREIGN', 'current project D70 input required')
    manifest = _read(manifest_path)
    if record.get('final_parasitics_receipt') != manifest.get('final_parasitics_receipt'):
        raise AdmissionRefusal('D70_ANALOG_FINAL_BASIS_CHANGED', 'final receipt differs')
    if require_pass and any(manifest.get(key) is not None for key in ('thermal', 'aging', 'signal_em', 'em')):
        raise AdmissionRefusal('D70_ANALOG_UNSUPPORTED_MISSION_REQUIREMENT', 'functional values cannot close coupled requirements')
    basis = _analog_basis(project, record['final_parasitics_receipt'])
    scenarios = _analog_inputs(project, manifest, basis)
    if len(scenarios) != len(record.get('scenarios') or []):
        raise AdmissionRefusal('D70_ANALOG_SCENARIO_COVERAGE_CHANGED', 'scenario population differs')
    observations = []
    for (setting, paths, binding, bounds), observed in zip(scenarios, record['scenarios']):
        expected = {key: {'path': str(path.resolve()), 'sha256': digest(path)} for key, path in paths.items()}
        netlist = files._bound(project, basis['simulation_netlists'][setting['corner']])
        expected['netlist'] = {'path': str(netlist), 'sha256': digest(netlist)}
        expected['models'] = [{**model, 'path': str(files._bound(project, model))} for model in manifest['models'][setting['corner']]]
        native = _read(files._bound(project, observed['native_receipt']))
        status, values = _analog_native_values(project, native, binding, expected)
        violations = [name for name, bound in bounds.items() if name in values
                      and limits._violates(values[name], bound['min'], bound['max'])]
        if violations:
            status = 'FAIL'
        if (observed.get('id') != setting['id'] or observed.get('corner') != setting['corner']
                or observed.get('status') != status or observed.get('values') != values
                or (require_pass and status != 'PASS')):
            raise AdmissionRefusal('D70_ANALOG_MISSION_CHANGED', setting['id'])
        observations.append({'scenario': setting['id'], 'corner': setting['corner'],
                             'status': status, 'values': values, 'bounds': bounds,
                             'units': {name: row.get('unit') for name, row in binding['measurements'].items()},
                             'inputs': expected, 'native_receipt': observed['native_receipt']})
    return {'component_electrical_current': True, 'flow109_acceptance': 'NOT_MEASURED',
            'scenarios': observations, 'manifest': record['manifest'],
            'scope': 'final analog functional mission component only'}


# The same registry operators and authority documents as the shared metric
# consumer. Unsupported producers have explicit bindings that refuse to measure.
METRIC_BINDINGS = {
    'final_mission_scenario_coverage': 'covers_all',
    'final_timing_si_targets': 'within_declared_bounds',
    'final_analog_mission_targets': 'within_declared_bounds',
    'final_ir_em_thermal_aging_targets': 'within_declared_bounds',
    'final_sdf_annotation': 'covers_all',
    'thermal_temperature_gradient_targets': 'within_declared_bounds',
    'thermal_aware_em_timing_feedback': 'covers_all',
    'aged_timing_margin_targets': 'within_declared_bounds',
    'aged_analog_margin_targets': 'within_declared_bounds',
    'aging_mission_coverage': 'covers_all',
}


def _metric_analog_authority(project, name, observed):
    """Use approved limits only when they are the limits the native owner used."""
    import flow109_metric_acceptance as metrics
    relative = 'requirements/final_electrical/' + name + '.json'
    authority, body = metrics._approved_document(project, relative,
        authority='requirements_owner', schema=metrics.AUTHORITY_SCHEMA)
    expected = {row['scenario']: row['bounds'] for row in observed['scenarios']}
    units = {row['scenario']: row['units'] for row in observed['scenarios']}
    if body.get('limits') != expected or body.get('units') != units:
        raise AdmissionRefusal('D70_ANALOG_LIMIT_AUTHORITY_DIFFERS',
                               'approved scenario limits/units must equal consumed spec/bindings')
    return authority, body


def _metric_digital_basis(project, record, *, native_state=None):
    """Bind native functional timing's libraries, RC inputs and configuration."""
    import fnmatch
    from librelane_contract import validate_step_receipt
    manifest_path = files._bound(project, record['manifest'])
    if manifest_path != project / INPUT:
        raise AdmissionRefusal('D70_FINAL_INPUT_FOREIGN', 'current project D70 input required')
    manifest = _read(manifest_path)
    if manifest.get('final_parasitics_receipt') != record['final_parasitics_receipt']:
        raise AdmissionRefusal('D70_FINAL_INPUT_CHANGED', 'manifest final parasitics differ')
    folder, state = native_state if native_state is not None else postroute.stapostpnr_state(project)
    receipt = validate_step_receipt(folder, 'OpenROAD.STAPostPNR')
    inputs = receipt['input']; config = _load(folder / 'config.json')
    if (inputs.get('config') != digest(folder / 'config.json')
            or set(config.get('STA_CORNERS') or []) != set(record['required_corners'])
            or inputs.get('image') != (manifest.get('librelane') or {}).get('image')):
        raise AdmissionRefusal('D70_NATIVE_CONFIG_CHANGED', 'image/config/corner identity differs')
    timed = inputs.get('state_files') or {}
    for path in [state.get('nl'), state.get('sdc'), *(state.get('spef') or {}).values()]:
        if not path or not Path(path).is_file() or timed.get(path) != digest(Path(path)):
            raise AdmissionRefusal('D70_NATIVE_TIMED_INPUT_CHANGED', str(path))
    libraries = inputs.get('liberty_files') or {}
    declared = config.get('CELL_LIBS') or config.get('LIB') or {}
    if not libraries or not isinstance(declared, dict):
        raise AdmissionRefusal('D70_NATIVE_LIBRARIES_ABSENT', 'per-corner native libraries required')
    for corner in record['required_corners']:
        matches = [group for pattern, group in declared.items() if fnmatch.fnmatchcase(corner, pattern)]
        if len(matches) != 1 or not matches[0] or any(path not in libraries for path in matches[0]):
            raise AdmissionRefusal('D70_NATIVE_LIBRARY_CORNER_MISMATCH', corner)
    for path, expected in {**(inputs.get('config_files') or {}), **libraries}.items():
        host = signoff._liberty_host_path(project, path, inputs.get('image'))
        if host is None or digest(host) != expected:
            raise AdmissionRefusal('D70_NATIVE_LIBRARY_OR_CONFIG_CHANGED', path)
    return {'manifest': record['manifest'], 'native_receipt': files._record(project, folder / 'vibeic_receipt.json'),
            'state_files': timed, 'liberty_files': libraries, 'configuration': inputs['config']}


def _metric_prerequisites(project, context, record):
    """Reuse accepted rows on this carrier; D69's current component is insufficient."""
    import flow109
    import flow109_final_perc as pv
    plan = flow109.resolve_plan(context['features'], context['step_profiles'])
    selected = {row['id'] for row in plan['rows']}
    accepted, missing = {}, []
    for step in context['resolved_row']['acceptance_deps']:
        if step not in selected:
            continue
        try:
            body, reference = flow109._accepted_row(project,
                Path('reports/flow109/default_rows') / (step + '.json'), step)
            original = _read(project / 'reports/flow109/requests' / (body['context_sha256'] + '.json'))
            if (original.get('features') != context['features']
                    or flow109.digest({k: v for k, v in original.items() if k != 'context_sha256'}) != body['context_sha256']
                    or step not in {r['id'] for r in original.get('resolved_rows', [original.get('resolved_row', {})])}):
                raise AdmissionRefusal('D70_PREREQUISITE_SELECTION_FOREIGN', step)
            for key in ('receipt', 'canonical_receipt'):
                if key in body:
                    flow109._current_project_ref(project, body[key], 'D70_PREREQUISITE_RECEIPT_CHANGED')
            if step == 'D69' and body.get('receipt') != record['final_parasitics_receipt']:
                raise AdmissionRefusal('D70_ACCEPTED_D69_DIFFERS', 'accepted row is not the consumed final extraction')
            if step == 'D65':
                basis = extract.validate_final_parasitics(project, record['final_parasitics_receipt'])
                final_def = basis.get('filled_def')
                if not final_def:
                    raise AdmissionRefusal('D70_D65_FINAL_GEOMETRY_BINDING_UNAVAILABLE', 'D69 final DEF required by current D65 owner')
                files._bound(project, final_def)
                native = _read(files._bound(project, body['canonical_receipt']))
                binding = pv._canonical_step31_bindings(native, final_def['sha256'])
                inputs = native['current_step_declared_producers']['input_identity']['files']
                for name, sha in inputs.items():
                    files._bound(project, {'path': name, 'sha256': sha})
                for view in (basis['final_gds'], basis['adopted_views']['netlist']):
                    files._bound(project, view)
                    if view['sha256'] not in inputs.values():
                        raise AdmissionRefusal('D70_D65_FINAL_SUBJECT_DIFFERS', view['path'])
                for name, sha in binding['outputs'].items():
                    files._bound(project, {'path': name, 'sha256': sha})
            accepted[step] = reference
        except (flow109.Flow109Error, AdmissionRefusal, Refusal, OSError, KeyError, TypeError, ValueError) as exc:
            missing.append({'step': step, 'reason': getattr(exc, 'code', 'D70_PREREQUISITE_NOT_CURRENT'),
                            'detail': str(exc)})
    return {'status': 'NOT_MEASURED' if missing else 'PASS',
            'accepted_dependencies': accepted, 'missing': missing}


def accept_metric_obligations(project, context, component):
    """BLOCKING metric readback; native component PASS alone never signs off D70.

    Read the existing final producer and approved requirement documents. No
    launch, inferred empty requirement set, SI/thermal/aging surrogate, or new
    receipt system is introduced. Same-carrier prerequisite acceptance remains
    a separate, unresolved requirement of the existing row owner.
    """
    import flow109
    import flow109_metric_acceptance as metrics
    project = Path(project).resolve()
    result = {'schema': metrics.SCHEMA, 'row_id': 'D70', 'status': 'NOT_MEASURED',
              'metric_status': 'NOT_MEASURED', 'delivery_blocked': True,
              'obligations': [], 'unselected_obligations': [],
              'scope': 'current final electrical metrics only; prerequisite acceptance remains required'}
    try:
        flow109.validate_execution_context(context)
        row = context['resolved_row']
        if row['id'] != 'D70':
            raise AdmissionRefusal('D70_METRIC_CONTEXT_INVALID', 'D70 selection required')
        declared = row['obligations']
        if ({item['id'] for item in declared} != {'final_electrical.' + name for name in METRIC_BINDINGS}
                or len(declared) != len(METRIC_BINDINGS)):
            raise AdmissionRefusal('D70_METRIC_OBLIGATIONS_UNREGISTERED', 'exact registry population required')
    except (flow109.Flow109Error, AdmissionRefusal, KeyError, TypeError, ValueError) as exc:
        result.update(reason=getattr(exc, 'code', 'D70_METRIC_CONTEXT_INVALID'), detail=str(exc))
        return result
    selected = []
    for obligation in declared:
        if flow109.predicate(obligation['when'], context['features']):
            selected.append(obligation)
        else:
            result['unselected_obligations'].append({'id': obligation['id'],
                'when': obligation['when'], 'reason': 'validated feature predicate is false'})
    observed = record = None
    failure = None
    try:
        reference = flow109._current_project_ref(project, component.get('receipt'), 'D70_METRIC_COMPONENT_FOREIGN')
        record = _read(files._bound(project, reference))
        if (record.get('step_id') != 'D70' or record.get('execution_context') != context
                or record.get('context_sha256') != context['context_sha256']):
            raise AdmissionRefusal('D70_METRIC_COMPONENT_FOREIGN', 'exact execution context required')
        for name in ('manifest', 'final_parasitics_receipt'):
            flow109._current_project_ref(project, record.get(name), 'D70_METRIC_CARRIER_INPUT_FOREIGN')
        analog = row['profile']['id'] == 'analog_die'
        observed = (validate_analog_mission(project, reference, require_pass=False) if analog else
                    validate_final_electrical(project, reference, require_pass=False))
        if not analog:
            observed['native_basis'] = _metric_digital_basis(project, record)
    except (flow109.Flow109Error, AdmissionRefusal, Refusal, OSError, KeyError, TypeError, ValueError) as exc:
        failure = {'reason': getattr(exc, 'code', 'D70_METRIC_NATIVE_EVIDENCE_INVALID'), 'detail': str(exc)}
    for obligation in selected:
        name = obligation['metric']; operator = METRIC_BINDINGS[name]
        item = {'id': obligation['id'], 'metric': name, 'operator': operator,
                'status': 'NOT_MEASURED'}
        expectation = obligation['expectation']
        relative = 'requirements/final_electrical/' + name + '.json'
        correct = (expectation.get('operator') == operator and
                   (expectation.get('required_set_ref') == relative + '#/required_items'
                    if operator == 'covers_all' else
                    expectation.get('bounds_ref') == relative + '#/limits'
                    and expectation.get('unit_ref') == relative + '#/units'))
        if not correct:
            item['reason'] = 'D70_METRIC_EXPECTATION_UNREGISTERED'
        elif failure:
            item.update(failure)
        elif name == 'final_timing_si_targets':
            item.update(status='FAIL' if observed['timing_status'] == 'FAIL' else 'NOT_MEASURED',
                        reason=('D70_NATIVE_FUNCTIONAL_OR_SCAN_TIMING_FAIL'
                                if observed['timing_status'] == 'FAIL' else 'D70_SI_PRODUCER_UNAVAILABLE'),
                        timing=observed)
        elif name in ('final_mission_scenario_coverage', 'final_analog_mission_targets') and analog:
            try:
                scenes = observed['scenarios']
                consumed = {str(files._bound(project, record['manifest'])): record['manifest']['sha256']}
                for scene in scenes:
                    for key, view in scene['inputs'].items():
                        for value in view if key == 'models' else [view]:
                            consumed[str(files._bound(project, value))] = value['sha256']
                identity = {'producer': component['receipt'], 'checker': operation_sources(),
                    'tool_execution': {row['scenario']: row['native_receipt'] for row in scenes},
                    'consumed_inputs': consumed, 'requirements': {'path': relative},
                    'configuration': {'context_sha256': context['context_sha256'], 'manifest': record['manifest']}}
                if name == 'final_mission_scenario_coverage':
                    authority, _ = metrics._approved_authority(project, relative + '#/required_items',
                                                               ('scenario', 'corner'))
                    value = [{key: scene[key] for key in ('scenario', 'corner')} for scene in scenes]
                    measurement = {'status': 'MEASURED', 'value': value, 'identity': identity}
                    identity['requirements'] = authority
                    status, detail = metrics.evaluate_operator(operator, measurement, authority)
                    item.update(status=status, detail=detail, measurement=measurement, authority=authority)
                elif any(scene['status'] == 'FAIL' for scene in scenes):
                    item.update(status='FAIL', reason='D70_NATIVE_ANALOG_MISSION_FAIL', scenarios=scenes)
                else:
                    authority, body = _metric_analog_authority(project, name, observed)
                    identity['requirements'] = authority
                    checks = []
                    for scene in scenes:
                        for metric, value in scene['values'].items():
                            measurement = {'status': 'MEASURED', 'value': value,
                                'unit': scene['units'][metric], 'identity': identity}
                            bound = {'status': 'APPROVED', 'limits': body['limits'][scene['scenario']][metric],
                                     'unit': body['units'][scene['scenario']][metric]}
                            status, detail = metrics.evaluate_operator(operator, measurement, bound)
                            checks.append({'scenario': scene['scenario'], 'corner': scene['corner'],
                                'metric': metric, 'status': status, 'detail': detail, 'measurement': measurement})
                    statuses = [check['status'] for check in checks]
                    item.update(status='FAIL' if 'FAIL' in statuses else 'PASS' if statuses and
                                all(status == 'PASS' for status in statuses) else 'NOT_MEASURED',
                                checks=checks, authority=authority)
            except (metrics.MetricRefusal, AdmissionRefusal, Refusal, OSError, KeyError, TypeError, ValueError) as exc:
                item.update(reason=getattr(exc, 'code', 'D70_METRIC_AUTHORITY_INVALID'), detail=str(exc))
        elif name == 'final_ir_em_thermal_aging_targets' and not analog:
            try:
                manifest = _read(project / OWNER_INPUT)
                if (manifest.get('schema') != OWNER_INPUT_SCHEMA
                        or manifest.get('d70_component') != component['receipt']):
                    raise AdmissionRefusal('D70_OWNER_INPUT_INVALID', 'current final component required')
                basis = extract.validate_final_parasitics(project, record['final_parasitics_receipt'])
                activity = _activity_binding(project, manifest, record['netlist'])
                power = _power_binding(project, record, basis, manifest)
                ir = _ir_binding(project, basis, manifest)
                failed = any(owner.get('verdict') == 'FAIL' for owner in (power, ir))
                item.update(status='FAIL' if failed else 'NOT_MEASURED',
                            reason='D70_APPLICABLE_OWNER_MEASURED_FAIL' if failed
                                   else 'D70_COUPLED_RELIABILITY_PRODUCER_UNAVAILABLE',
                            static_owners={'activity': activity, 'power': power, 'ir': ir},
                            dynamic_ir_status='NOT_MEASURED', signal_em_status='NOT_MEASURED')
            except (AdmissionRefusal, Refusal, OSError, KeyError, TypeError, ValueError) as exc:
                item.update(reason=getattr(exc, 'code', 'D70_OWNER_EVIDENCE_INVALID'), detail=str(exc))
        else:
            reasons = {'final_mission_scenario_coverage': 'D70_FINAL_ACTIVITY_MISSION_NOT_CONSUMED',
                       'final_sdf_annotation': 'D70_SDF_GENERATION_IS_NOT_ANNOTATION',
                       'final_ir_em_thermal_aging_targets': 'D70_COUPLED_RELIABILITY_PRODUCER_UNAVAILABLE',
                       'thermal_temperature_gradient_targets': 'D70_THERMAL_PRODUCER_UNAVAILABLE',
                       'thermal_aware_em_timing_feedback': 'D70_THERMAL_FEEDBACK_PRODUCER_UNAVAILABLE',
                       'aged_timing_margin_targets': 'D70_AGED_TIMING_PRODUCER_UNAVAILABLE',
                       'aged_analog_margin_targets': 'D70_AGED_ANALOG_PRODUCER_UNAVAILABLE',
                       'aging_mission_coverage': 'D70_AGING_PRODUCER_UNAVAILABLE'}
            item['reason'] = reasons.get(name, 'D70_REQUIRED_NATIVE_PRODUCER_UNAVAILABLE')
        result['obligations'].append(item)
    statuses = [item['status'] for item in result['obligations']]
    result['metric_status'] = ('FAIL' if 'FAIL' in statuses else 'PASS' if statuses and
                              all(status == 'PASS' for status in statuses) else 'NOT_MEASURED')
    upstream = (_metric_prerequisites(project, context, record) if observed is not None else
                {'status': 'NOT_MEASURED', 'reason': 'D70_CURRENT_NATIVE_BASIS_UNAVAILABLE'})
    status = ('FAIL' if result['metric_status'] == 'FAIL' else 'PASS'
              if result['metric_status'] == upstream['status'] == 'PASS'
              and record.get('component_status') == 'PASS' else 'NOT_MEASURED')
    result.update(status=status, delivery_blocked=status != 'PASS', prerequisites=upstream,
                  reason='D70_MEASURED_METRIC_FAILURE' if result['metric_status'] == 'FAIL'
                         else 'ALL_APPLICABLE_METRICS_AND_PREREQUISITES_PASS' if status == 'PASS'
                         else 'D70_SELECTED_PREREQUISITE_ACCEPTANCE_UNPROVEN',
                  required_acceptance_dependencies=[dep for dep in row['acceptance_deps']
                      if dep in {r['id'] for r in flow109.resolve_plan(context['features'], context['step_profiles'])['rows']}])
    if status == 'PASS':
        from flow109_admission import require_admission
        try:
            result['qualification_admission'] = require_admission(project, context)
            result['qualification'] = 'PASS'
        except AdmissionRefusal as exc:
            result.update(status='NOT_MEASURED', delivery_blocked=True, reason=exc.code,
                          qualification='NOT_MEASURED', qualification_admission=exc.report)
    return result


def consume_default_row_completion(project, context, component):
    """Use the existing adapter completion seam; whole-IC acceptance is separate."""
    acceptance = accept_metric_obligations(project, context, component)
    status = 'FAIL' if component.get('component_status') == 'FAIL' else acceptance['status']
    result = {**component, 'step_id': 'D70', 'context_sha256': context['context_sha256'],
            'metric_acceptance': acceptance, 'metric_acceptance_status': acceptance['metric_status'],
            'default_row_status': status, 'flow109_acceptance': status, 'completed': status == 'PASS',
            'whole_flow_acceptance': 'NOT_MEASURED', 'delivery_accepted': False}
    if 'qualification' in acceptance:
        result['qualification'] = acceptance['qualification']
    return result
