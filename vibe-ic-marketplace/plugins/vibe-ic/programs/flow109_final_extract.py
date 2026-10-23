"""D69 Default native component: final filled ODB -> OpenROAD.RCX -> SPEF consumer."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import uuid

import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _atomic_artefact import write_json
from flow109_admission import AdmissionRefusal, require_launch_admission
import flow109_density_fill as density
import librelane_fill_stream as files
import librelane_signoff as signoff
from librelane_contract import Refusal, _load
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


def _native_refusal_status(code):
    return 'FAIL' if code == 'LL_STEP_FAILED' else 'NOT_MEASURED'


def operation_sources():
    paths = (Path(__file__), Path(signoff.__file__), Path(files.__file__),
             Path(density.__file__), Path(__file__).with_name('spef_extraction_check.py'))
    return {str(path.resolve()): _sha(path) for path in paths}


def execute(project, context):
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
        d62 = density.validate_filled_odb(project, manifest.get('d62_receipt'))
        bridge = files.validate_bridge(project, manifest.get('stream_bridge'))
        if bridge['d62_receipt'] != manifest['d62_receipt'] or bridge['odb'] != d62['odb']:
            raise AdmissionRefusal('D69_FINAL_GEOMETRY_MISMATCH', 'stream-out and D62 ODB differ')
        native = manifest.get('librelane') or {}
        if set(native) != {'image', 'pdk_root', 'pdk'}:
            raise AdmissionRefusal('D69_NATIVE_CONFIGURATION_ABSENT', 'image/pdk_root/pdk required')
        odb, d62_path = _bound(project, bridge['odb']), _bound(project, manifest['d62_receipt'])
        d62doc = _read(d62_path)
        routed_def = _bound(project, d62doc['outputs']['filled.def'])
        views = manifest.get('adopted_views') or {}
        if set(views) != {'netlist', 'sdc'}:
            raise AdmissionRefusal('D69_ADOPTED_VIEWS_ABSENT', 'netlist and SDC required')
        netlist = _bound(project, views['netlist']); sdc = _bound(project, views['sdc'])
        basis = {str(p): _sha(p) for p in (odb, routed_def, netlist, sdc, d62_path)}
        sources = operation_sources()
        result['native_started'] = True
        run = signoff.run(project, native['image'], Path(native['pdk_root']), native['pdk'],
                          routed_def=routed_def, routed_odb=odb, netlist=netlist, sdc=sdc,
                          extract=True, time=False, lane='flow109-d69')
        binding = signoff.bind_rcx_spefs(Path(run['rcx']), Path(run['rcx']) / 'state_in.json')
        scans = {corner: scan_spef(Path(path)) for corner, path in run['spef'].items()}
        bad = {c: f for c, f in scans.items() if not f['has_header'] or not f['has_design']
               or not (f['d_nets'] or f['r_nets']) or f['negative_caps'] or f['negative_net_totals']}
        if bad:
            raise AdmissionRefusal('D69_SPEF_CONSUMER_FAILED', str(bad), status='FAIL')
        final_spefs = {c: files._record(project, Path(p)) for c, p in run['spef'].items()}
        result.update(component_status='PASS', reason='D69_FINAL_FILLED_ODB_RCX_MEASURED',
                      producer='flow109_final_extract',
                      d62_receipt=manifest['d62_receipt'], stream_bridge=manifest['stream_bridge'],
                      adopted_views=views, inputs=basis,
                      operation_sources=sources,
                      final_geometry=bridge['odb'],
                      rcx_state=files._record(project, Path(run['rcx']) / 'state_out.json'),
                      rcx_receipt=files._record(project, Path(run['rcx']) / 'vibeic_receipt.json'),
                      spefs=final_spefs, final_spefs=final_spefs,
                      spef_consumer=scans, rcx_binding=binding, execution_context=context)
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
    if record.get('schema') != SCHEMA or record.get('component_status') != 'PASS':
        raise AdmissionRefusal('D69_COMPONENT_NOT_ACCEPTED', 'current native RCX receipt required')
    require_launch_admission(project, 'flow109.D69', {'flow109_context': record.get('execution_context')})
    if record.get('operation_sources') != operation_sources():
        raise AdmissionRefusal('D69_OPERATION_SOURCE_CHANGED', 'adapter or retained consumer changed')
    d62 = density.validate_filled_odb(project, record['d62_receipt'])
    bridge = files.validate_bridge(project, record['stream_bridge'])
    if bridge['d62_receipt'] != record['d62_receipt'] or bridge['odb'] != d62['odb']:
        raise AdmissionRefusal('D69_FINAL_GEOMETRY_MISMATCH', 'stream-out and D62 ODB differ')
    if (record.get('producer') != 'flow109_final_extract'
            or record.get('final_geometry') != bridge['odb']
            or record.get('final_spefs') != record.get('spefs')):
        raise AdmissionRefusal('D69_FINAL_OUTPUT_BINDING_MISMATCH', 'final ODB/SPEF aliases drifted')
    for path, sha in record['inputs'].items():
        if not Path(path).is_file() or _sha(path) != sha:
            raise AdmissionRefusal('D69_INPUT_CHANGED', path)
    state = _read(_bound(project, record['rcx_state']))
    for corner, ref in record['spefs'].items():
        path = _bound(project, ref); facts = scan_spef(path)
        if facts != record['spef_consumer'][corner] or str(path) != state.get('spef', {}).get(corner):
            raise AdmissionRefusal('D69_SPEF_CHANGED', corner)
    signoff.bind_rcx_spefs(_bound(project, record['rcx_state']).parent,
                           _bound(project, record['rcx_state']).parent / 'state_in.json')
    return {'odb': bridge['odb'], 'd62_receipt': record['d62_receipt'],
            'adopted_views': record['adopted_views'],
            'spefs': record['spefs'], 'final_geometry': record['final_geometry'],
            'final_spefs': record['final_spefs'], 'parasitic_receipt': receipt_ref,
            'component_parasitics_current': True, 'flow109_acceptance': 'NOT_MEASURED'}
