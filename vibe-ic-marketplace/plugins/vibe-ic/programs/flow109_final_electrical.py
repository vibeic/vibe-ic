"""D70 Default bounded component: final RCX SPEFs -> STAPostPNR and SDF."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import uuid

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
        status = timing['verdict']
        result.update(component_status=status, reason='D70_NATIVE_ELECTRICAL_' + status,
                      final_parasitics_receipt=manifest['final_parasitics_receipt'],
                      sta_state=files._record(project, state_path), sta_record=files._record(project, record_path),
                      corners=corners, timing_judgment=timing,
                      sdfs={c: files._record(project, p) for c, p in sdfs.items()},
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
    extract.validate_final_parasitics(project, record['final_parasitics_receipt'])
    folder, state = postroute.stapostpnr_state(project)
    if files._record(project, folder / 'state_out.json') != record['sta_state']:
        raise AdmissionRefusal('D70_STA_STATE_CHANGED', str(folder))
    if signoff.judge_timing(signoff.corner_timing(folder)) != record['timing_judgment']:
        raise AdmissionRefusal('D70_TIMING_CHANGED', str(folder))
    postroute.corner_sdfs(state)
    return {'sta_state': record['sta_state'], 'sdfs': record['sdfs'],
            'component_electrical_current': True, 'flow109_acceptance': 'NOT_MEASURED'}
