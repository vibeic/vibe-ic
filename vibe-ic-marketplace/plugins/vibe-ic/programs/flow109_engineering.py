"""Source-owned bounded engineering evidence; no qualified row or delivery credit."""
import hashlib
import json
from pathlib import Path
import _path_layout as layout


def selected_original(project, context):
    import flow109
    if (layout.rtl_input(project) != 'original'
            or context.get('runtime_tool_uses') is not None
            or context.get('qualification_registry') is not None):
        return False
    current = flow109.validate_execution_context(context)
    return (current.get('resolved_row', {}).get('id') in ('D09', 'D10', 'D11')
            and flow109._canonical_owner_dispatch(current.get('resolved_row', {})) is not None)


def reference(project, path):
    project, path = Path(project).resolve(), Path(path)
    if not path.is_absolute():
        path = project / path
    if (not path.is_file() or any(p.is_symlink() for p in (path, *path.parents))
            or not path.resolve().is_relative_to(project)):
        raise ValueError('ENGINEERING_EVIDENCE_UNBOUND: ' + str(path))
    return {'path': str(path.relative_to(project)),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def subject(project):
    """Read the original authority and complete staged tree, including sidecars."""
    project = Path(project).resolve()
    original = layout.original_input_sources(project)
    rtl = layout.rtl_dir(project)
    entries = sorted(rtl.rglob('*'))
    if any(p.is_symlink() for p in entries):
        raise ValueError('ENGINEERING_SOURCE_SYMLINK')
    staged = [p for p in entries if p.is_file()]
    if not any(p.suffix.lower() in ('.v', '.sv') for p in staged):
        raise ValueError('ENGINEERING_RTL_EMPTY')
    return {'original_sources': [reference(project, p) for p in original],
            'staged_files': [reference(project, p) for p in staged]}


def evidence(project, before, rows):
    if subject(project) != before:
        raise ValueError('ENGINEERING_INPUT_CHANGED')
    records = []
    for row in rows:
        outputs = [reference(project, p) for p in row.output_files]
        if row.status not in ('PASS', 'FAIL') or not outputs:
            raise ValueError('ENGINEERING_CHECK_NOT_MEASURED: ' + row.name)
        records.append({'name': row.name, 'status': row.status, 'outputs': outputs, 'native': dict(row.extras)})
    return {'scope': 'existing_native_component_only',
            'qualification_status': 'NOT_CLAIMED', 'subject': before, 'checks': records}


def consume(project, record, rows):
    if (record.get('scope') != 'existing_native_component_only'
            or record.get('qualification_status') != 'NOT_CLAIMED'
            or record.get('subject') != subject(project)):
        raise ValueError('ENGINEERING_SUBJECT_STALE')
    expected = ['rtl_lint_tool', 'crosslayer_rewrite_fidelity', 'rtl_hygiene', 'rom_init_lint']
    checks = record['checks']
    if [r['name'] for r in checks] != expected:
        raise ValueError('ENGINEERING_REQUIRED_CHECKS_MISSING')
    for check in checks:
        matches = [r for r in rows if r.get('name') == check['name']]
        if (len(matches) != 1 or matches[0].get('status') != check['status']
                or check['status'] not in ('PASS', 'FAIL') or not check['outputs']
                or matches[0].get('extras') != check['native']
                or [reference(project, p) for p in matches[0].get('output_files', [])] != check['outputs']):
            raise ValueError('ENGINEERING_OWNER_CHECK_STALE')
        for ref in check['outputs']:
            if reference(project, ref['path']) != ref:
                raise ValueError('ENGINEERING_OUTPUT_STALE')
    for check in (checks[0], checks[2]):
        paths = [Path(project) / item['path'] for item in check['outputs']]
        contexts = [json.loads(path.read_bytes()) for path in paths if path.name.endswith('context.json')]
        native = check['native']
        if native.get('producer') == 'rtl_hygiene_lint':
            if (len(contexts) != 1 or contexts[0] != native.get('native_context')
                    or type(contexts[0].get('native_returncode')) is not int
                    or contexts[0].get('transport_returncode') != contexts[0]['native_returncode']
                    or not contexts[0].get('files') or not contexts[0].get('input_sha256')):
                raise ValueError('ENGINEERING_NATIVE_EXECUTION_UNPROVEN')
            hashes = contexts[0]['input_sha256']
            expected = {str(Path(project) / item['path']): item['sha256']
                for item in record['subject']['staged_files']
                if Path(item['path']).suffix in ('.v', '.sv', '.vh', '.svh')}
            if hashes != expected:
                raise ValueError('ENGINEERING_NATIVE_INPUT_STALE')
        elif native.get('tool_mode') == 'direct':
            import verilator_lint_gate as lint
            reports = [json.loads(path.read_bytes()) for path in paths if path.suffix == '.json']
            logs = [path for path in paths if path.suffix == '.log']
            if len(reports) != 1 or len(logs) != 1:
                raise ValueError('ENGINEERING_NATIVE_EXECUTION_UNPROVEN')
            report = reports[0]
            parsed = lint.parse_transcript(logs[0].read_text())
            design_paths = [str(Path(project) / item['path']) for item in record['subject']['staged_files']]
            blocked = lint.blocking(parsed['diagnostics'], design_paths)
            status = ('FAIL' if blocked else 'NOT_MEASURED' if report.get('exit_code')
                      or parsed['exiting_errors'] else 'PASS')
            expected = {str(Path(project) / item['path']): item['sha256']
                for item in [*record['subject']['original_sources'],
                    *[item for item in record['subject']['staged_files']
                      if Path(item['path']).suffix.lower() in ('.v', '.sv', '.vh', '.svh', '.h')]]}
            if report.get('input_sha256') != expected:
                raise ValueError('ENGINEERING_NATIVE_INPUT_STALE')
            if (report.get('verdict') != check['status'] or status != check['status']
                    or report.get('command') != native.get('command')
                    or report.get('input_sha256') != native.get('input_sha256')
                    or not native.get('tool_version')):
                raise ValueError('ENGINEERING_NATIVE_EXECUTION_UNPROVEN')
        else:
            raise ValueError('ENGINEERING_NATIVE_EXECUTION_UNPROVEN')
    return 'FAIL' if any(r['status'] == 'FAIL' for r in checks) else 'PASS'
