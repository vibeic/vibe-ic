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


def _native_refusal_status(code):
    return 'FAIL' if code == 'LL_STEP_FAILED' else 'NOT_MEASURED'


def operation_sources():
    paths = (Path(__file__), Path(signoff.__file__), Path(postroute.__file__), Path(extract.__file__))
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


def execute(project, context):
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
        required_corners = manifest.get('required_corners')
        required_population = _required_corner_population(required_corners)
        parasitics = extract.validate_final_parasitics(project, manifest.get('final_parasitics_receipt'))
        d69 = _read(files._bound(project, manifest['final_parasitics_receipt']))
        d62 = _read(files._bound(project, d69['d62_receipt']))
        odb = files._bound(project, parasitics['odb']); routed_def = files._bound(project, d62['outputs']['filled.def'])
        netlist = files._bound(project, parasitics['adopted_views']['netlist']); sdc = files._bound(project, parasitics['adopted_views']['sdc'])
        spefs = {signoff.rc_corner(c): files._bound(project, r) for c, r in parasitics['spefs'].items()}
        native = manifest.get('librelane') or {}
        if set(native) != {'image', 'pdk_root', 'pdk'}: raise AdmissionRefusal('D70_NATIVE_CONFIGURATION_ABSENT', 'image/pdk_root/pdk required')
        result['native_started'] = True
        sources = operation_sources()
        sta = signoff.run(project, native['image'], Path(native['pdk_root']), native['pdk'],
                          routed_def=routed_def, routed_odb=odb, netlist=netlist, sdc=sdc,
                          extract=False, time=True, direct_spefs=spefs, lane='flow109-d70-sta')
        corners = signoff.corner_timing(Path(sta['sta'])); timing = signoff.judge_timing(corners)
        state_path = Path(sta['sta']) / 'state_out.json'
        record_path = project / postroute.STEP23_RECORD
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
        if (set(state_spefs) != set(parasitics['final_spefs'])
                or any(Path(str(state_spefs[key])).resolve()
                       != files._bound(project, parasitics['final_spefs'][key]).resolve()
                       for key in state_spefs)):
            raise AdmissionRefusal('D70_FINAL_SPEF_STATE_MISMATCH', 'STA state RC scenes differ from D69')
        final_sdfs = {c: files._record(project, p) for c, p in sdfs.items()}
        state_record = files._record(project, state_path)
        provenance = {'basis': 'D69_final_parasitics',
                      'd69_receipt': manifest['final_parasitics_receipt'],
                      'sta_state': state_record,
                      'declared_corners': required_corners,
                      'spef_by_rc_scene': parasitics['final_spefs']}
        status = timing['verdict']
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


def validate_final_electrical(project, receipt_ref):
    project = Path(project).resolve(); record = _read(files._bound(project, receipt_ref))
    if record.get('schema') != SCHEMA or record.get('component_status') != 'PASS':
        raise AdmissionRefusal('D70_COMPONENT_NOT_ACCEPTED', 'current native STA component PASS required')
    require_launch_admission(project, 'flow109.D70', {'flow109_context': record.get('execution_context')})
    if record.get('operation_sources') != operation_sources():
        raise AdmissionRefusal('D70_OPERATION_SOURCE_CHANGED', 'adapter or retained consumer changed')
    parasitics = extract.validate_final_parasitics(project, record['final_parasitics_receipt'])
    folder, state = postroute.stapostpnr_state(project)
    if files._record(project, folder / 'state_out.json') != record['sta_state']:
        raise AdmissionRefusal('D70_STA_STATE_CHANGED', str(folder))
    if signoff.judge_timing(signoff.corner_timing(folder)) != record['timing_judgment']:
        raise AdmissionRefusal('D70_TIMING_CHANGED', str(folder))
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
            'component_electrical_current': True, 'flow109_acceptance': 'NOT_MEASURED'}
