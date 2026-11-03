"""D64: native finishing XOR on the run's delivered geometry."""
from __future__ import annotations

from pathlib import Path

from _atomic_artefact import write_json

SCHEMA = 'vibeic.flow109.final-geometry.v1'


def execute(project, context):
    """Run the native finishing XOR on the run's pre/sealed/final streams."""
    import librelane_contract as contract
    import librelane_fill_dfm as fill
    import librelane_pv_signoff as pv
    project = Path(project).resolve()
    result = {'schema': SCHEMA, 'step_id': 'D64', 'component_status': 'NOT_MEASURED',
        'default_row_status': 'NOT_MEASURED', 'completed': False, 'native_started': False,
        'context_sha256': context.get('context_sha256')}
    try:
        promotion = fill.validate_default_stream(project)
        pre = contract.project_path(project, promotion['stream'])
        final = contract.project_path(project, promotion['canonical'])
        sealed = (contract.project_path(project, promotion['sealed'])
                  if promotion.get('finishing_status') != 'NOT_APPLICABLE' else None)
        _, core, sources, why, _ = contract._runner_floorplan(project)
        if core is None:
            raise ValueError('native finishing core area unavailable: ' + why)
        scope = {'pre_sha256': contract.digest(pre), 'final_sha256': contract.digest(final),
                 'sealed_sha256': contract.digest(sealed) if sealed else ''}
        report = project / 'reports/phase3/librelane_finishing_xor.json'
        native = contract._load(report) if report.is_file() else {}
        folders = {contract.project_path(project, row['folder'])
                   for row in native.get('metrics', {}).values() if row.get('folder')}
        current = native.get('scope') == scope and bool(folders)
        if current:
            try:
                for folder in folders:
                    fill._current_stage(project, folder / 'state_out.json', 'Vibeic.FinishingXOR')
                    config = contract._load(folder / 'config.json')
                    value = config['VIBEIC_FINISHING_CORE_AREA']
                    values = value.split(',') if isinstance(value, str) else value
                    if [float(v) for v in values] != [float(v) for v in core]:
                        current = False
            except (OSError, ValueError, KeyError, TypeError, contract.Refusal):
                current = False
        if current:
            native = pv.judge_pv(sorted(folders), ('Vibeic.FinishingXOR',), report, scope=scope)
        else:
            pdk = promotion['pdk']
            image = contract.resolve_image(project, record=False)
            root = contract.resolve_pdk_root(project, pdk, image=image)
            if root is None:
                raise ValueError('project PDK root not available: ' + pdk)
            result['native_started'] = True
            native = pv.run_finishing_xor(project, image, Path(root), pdk, pre=pre,
                sealed=sealed, final=final, core=core, core_source=sources['CORE_AREA'])
        status = native['verdict']
        result.update(component_status=status, default_row_status=status,
            flow109_acceptance=status, completed=status == 'PASS', native_step='Vibeic.FinishingXOR',
            native_report=str(report), metrics=native['metrics'], reasons=native.get('reasons', []))
    except (OSError, ValueError, KeyError, TypeError, contract.Refusal) as exc:
        result.update(reason='D64_NATIVE_FINISHING_UNAVAILABLE', detail=str(exc))
    write_json(project / 'reports/flow109/D64/result.json', result)
    return result


def consume_default_row_completion(project, context, component):
    """Completion belongs to the native finishing XOR against zero defects."""
    return component
