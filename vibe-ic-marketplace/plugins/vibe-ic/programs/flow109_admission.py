"""Per-use qualification consumed immediately before flow109 native dispatch.

Legacy execution has no flow109 context and retains its existing contract.
The registry is a pre-established, reviewed qualification input. This reader
checks its bindings; it does not assess reference measurements or grant tool
qualification. Arbitrary hashed files are not native qualification evidence.
This reader never creates qualification records or updates historical receipts.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


class AdmissionRefusal(ValueError):
    def __init__(self, code, detail, *, use_id=None, status='NOT_MEASURED'):
        self.code, self.status = code, status
        self.report = {'status': status, 'reason': code, 'detail': detail,
                       'use_id': use_id, 'native_started': False}
        super().__init__(f'{code}: {detail}')


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _read(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise AdmissionRefusal('QUALIFICATION_INPUT_ABSENT', str(exc)) from exc


def _artifact(project, record, *, use_id, optional=False):
    if optional and isinstance(record, dict) and record.get('applicable') is False:
        if isinstance(record.get('reason'), str) and record['reason'].strip():
            return
    if not isinstance(record, dict) or not record.get('path') or not record.get('sha256'):
        raise AdmissionRefusal('QUALIFICATION_ARTIFACT_UNBOUND', 'path and sha256 required', use_id=use_id)
    path = Path(record['path'])
    path = path if path.is_absolute() else project / path
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise AdmissionRefusal('QUALIFICATION_INPUT_ABSENT', str(path), use_id=use_id) from exc
    if digest != record['sha256']:
        raise AdmissionRefusal('QUALIFICATION_STALE', str(path), use_id=use_id)


def require_admission(project, context):
    """Require source-owned use inventory and exact, current per-use evidence."""
    from flow109 import validate_execution_context
    project = Path(project)
    try:
        context = validate_execution_context(context)
    except ValueError as exc:
        raise AdmissionRefusal('FLOW109_CONTEXT_INVALID', str(exc)) from exc
    expected = context['resolved_row']['tool_uses']
    runtime = context.get('runtime_tool_uses')
    if not isinstance(runtime, list) or not runtime or not expected:
        raise AdmissionRefusal('QUALIFICATION_RUNTIME_ABSENT', 'nonempty per-use runtime identities required')
    ids = [x.get('use_id') for x in runtime if isinstance(x, dict)]
    if len(ids) != len(runtime) or len(set(ids)) != len(ids) or set(ids) != {x['use_id'] for x in expected}:
        raise AdmissionRefusal('QUALIFICATION_USE_MISMATCH', 'runtime inventory differs from source-owned uses')
    registry_path = context.get('qualification_registry')
    if not isinstance(registry_path, str) or not registry_path:
        raise AdmissionRefusal('QUALIFICATION_REGISTRY_ABSENT', 'qualification registry required')
    registry = _read(project / registry_path)
    if not isinstance(registry, dict) or registry.get('schema') != 'vibeic.flow109.qualifications.v1' or not isinstance(registry.get('uses'), list):
        raise AdmissionRefusal('QUALIFICATION_REGISTRY_INVALID', registry_path)
    qualified = []
    for use in expected:
        uid = use['use_id']
        actual = next(x for x in runtime if x['use_id'] == uid)
        matches = [x for x in registry['uses'] if isinstance(x, dict) and x.get('use_id') == uid]
        if len(matches) != 1:
            raise AdmissionRefusal('QUALIFICATION_USE_ABSENT', uid, use_id=uid)
        reference = matches[0]
        if reference.get('status') != 'QUALIFIED':
            raise AdmissionRefusal('QUALIFICATION_' + str(reference.get('status', 'ABSENT')), uid, use_id=uid)
        if actual.get('qualification_sha256') != canonical_sha(reference):
            raise AdmissionRefusal('QUALIFICATION_STALE', 'per-use qualification digest changed', use_id=uid)
        identity = {k: v for k, v in actual.items() if k != 'qualification_sha256'}
        required = {'use_id', 'tool_id', 'version', 'build_sha256', 'executable', 'config', 'pdk', 'deck', 'corner', 'semantics'}
        if not required <= identity.keys() or any(not identity[k] for k in required):
            raise AdmissionRefusal('QUALIFICATION_IDENTITY_INCOMPLETE', uid, use_id=uid)
        if identity != reference.get('identity') or identity['tool_id'] != use['tool_id']:
            raise AdmissionRefusal('QUALIFICATION_IDENTITY_MISMATCH', uid, use_id=uid)
        semantics = identity['semantics']
        if (not isinstance(semantics, dict) or semantics.get('purpose') != use['purpose']
                or semantics.get('native_steps') != use['native_steps']):
            raise AdmissionRefusal('QUALIFICATION_SCOPE_MISMATCH', uid, use_id=uid)
        for key in ('config', 'pdk', 'deck'):
            _artifact(project, identity[key], use_id=uid, optional=key in ('pdk', 'deck'))
        executable = identity['executable']
        _artifact(project, executable, use_id=uid)
        if executable['sha256'] != identity['build_sha256']:
            raise AdmissionRefusal('QUALIFICATION_BUILD_MISMATCH', uid, use_id=uid)
        # The identity must name the executable the current launch environment
        # resolves, not another qualified binary sitting elsewhere on disk.
        binary = shutil.which(use.get('executable_name', identity['tool_id']))
        if not binary or Path(binary).resolve() != Path(executable['path']).resolve():
            raise AdmissionRefusal('QUALIFICATION_RUNTIME_UNSUPPORTED', identity['tool_id'], use_id=uid)
        evidence = reference.get('reference_evidence')
        if not isinstance(evidence, list) or not evidence:
            raise AdmissionRefusal('QUALIFICATION_REFERENCE_ABSENT', uid, use_id=uid)
        for artifact in evidence:
            _artifact(project, artifact, use_id=uid)
        qualified.append({'use_id': uid, 'qualification_sha256': actual['qualification_sha256']})
    return {'status': 'PASS', 'reason': 'QUALIFICATION_BINDINGS_CURRENT', 'uses': qualified,
            'context_sha256': context['context_sha256'], 'native_started': False}


def admit_context(project, context):
    try:
        return require_admission(project, context)
    except AdmissionRefusal as exc:
        return exc.report


def require_launch_admission(project, step_id, params=None):
    """Shared actual-launch seam; absence preserves legacy behavior."""
    context = (params or {}).get('flow109_context')
    path = os.environ.get('VIBEIC_FLOW109_CONTEXT')
    if context is None and path:
        context = _read(path)
    if context is None:
        return None
    if (isinstance(context, dict)
            and context.get('schema') == 'vibeic.flow109.execution-window.v1'):
        from flow109 import component_context
        try:
            context = component_context(context, native_step_id=str(step_id))
        except ValueError as exc:
            raise AdmissionRefusal('FLOW109_NATIVE_STEP_MISMATCH', str(step_id)) from exc
    if not isinstance(context, dict) or str(context.get('native_step_id')) != str(step_id):
        raise AdmissionRefusal('FLOW109_NATIVE_STEP_MISMATCH', str(step_id))
    return require_admission(project, context)
