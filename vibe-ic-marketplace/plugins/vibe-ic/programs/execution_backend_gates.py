"""Execute the unchanged canonical clauses; retain advisory/conditional facts."""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import execution_backend_snapshot as snap
import execution_modes as em



def program_invocations(row: dict) -> list[dict]:
    """Keep canonical command roles and duplicates; do not evaluate clauses."""
    found = []
    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ('program_exit_zero', 'advisory_program_exit_zero',
                           'optional_program_exit_zero'):
                    spec = value if isinstance(value, dict) else {'command': value}
                    command = spec.get('command')
                    if isinstance(command, str) and command.strip():
                        found.append({'command': command,
                                      'blocking': key == 'program_exit_zero',
                                      'optional': key == 'optional_program_exit_zero',
                                      'condition_files_exist': spec.get('condition_files_exist', [])})
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
    walk(row.get('gate', {}))
    return found


def required_commands(row: dict) -> list[str]:
    """Unconditional program obligations, separate from full row acceptance.

    Optional activation and advisory enforcement are decided only by the real
    canonical consumer. Its overall verdict remains mandatory at validation;
    an absent optional is never fabricated into an executed program PASS.
    """
    commands = [item['command'] for item in program_invocations(row)
                if item['blocking']]
    if str(row['id']) == '20':
        commands.append('hold_area_budget_check')
    return commands


def required_programs(row: dict) -> tuple[str, ...]:
    import shlex
    return tuple(sorted({Path(shlex.split(cmd)[0]).stem
                         for cmd in required_commands(row)}))


def canonical_family_row(step_id: str, *, adapters=None) -> dict | None:
    # A familiar step ID alone does not make another provider this fixed-step
    # family. Use the same bound component/source ownership at context issue
    # and Controller admission; callers inspecting only a row keep the lookup.
    if adapters is not None:
        family_workers = {'producer': 'execution_backend_worker.py',
                          'release-producer': 'execution_release_worker.py'}
        if not adapters or not all(
                len(getattr(arm, 'components', ())) == 1 and
                getattr(arm.components[0], 'name', None) in family_workers and
                str(Path(__file__).resolve().parent /
                    family_workers[arm.components[0].name]) in (getattr(arm, 'source_files', None) or {})
                for arm in adapters):
            return None
    from execution_provider_catalog import BACKEND_ROWS, RELEASE_ROWS
    step_id = str(step_id)
    if step_id in BACKEND_ROWS:
        return BACKEND_ROWS[step_id]['canonical_row']
    if step_id in RELEASE_ROWS:
        return RELEASE_ROWS[step_id]['canonical']
    return None


def evaluate(project: Path, row: dict) -> dict:
    import flow_compliance_check as fcc
    # Capture the actual semantic consumer and its lossless gate ledger. No
    # custom parser substitutes for a declared gate or changes its thresholds.
    start = len(fcc._GATE_LEDGER)
    import execution_policy
    runtime = execution_policy._ordinary_runtime
    scope = {}
    waivers = {}
    if (runtime is not None and runtime.get('policy', {}).get('mode') == 'default'
            and Path(runtime['project']).resolve() == Path(project).resolve()):
        scope = runtime.get('parameters', {})
        if row['id'] in fcc._FPGA_BOARD_STEP_IDS:
            # Reuse the same disclosed-board policy as the final canonical
            # audit. Its synthesized marker yields NOT_MEASURED/excluded,
            # not an authored waiver or an executed PASS.
            fcc._synthesise_fpga_skip_waivers(project, waivers)
    flags = {name: True for name in ('skip_analog', 'skip_hardware')
             if scope.get(name) is True}
    verdict = fcc.check_step(project, row, waivers, **flags)
    if str(row['id']) == '20':
        import hold_area_budget_check as area
        area_rc = area.main([str(project), '--json', str(project / 'reports/phase3/hold_area_budget.json')])
        fcc._record_gate_execution('hold_area_budget_check', area_rc,
                                  'PASS' if area_rc == 0 else 'FAIL' if area_rc == 1 else 'NOT_MEASURED')
        if area_rc:
            verdict.status = 'FAIL' if area_rc == 1 else 'NOT_MEASURED'
    # The selected D49 Flow109 consumer must not reuse a functional-only
    # candidate STA PASS as if shift/capture had been measured.  No other
    # backend selection is affected; a real functional FAIL keeps precedence.
    context_path = os.environ.get('VIBEIC_FLOW109_CONTEXT')
    if str(row['id']) == '23' and context_path:
        try:
            import flow109
            context = flow109.validate_execution_context(json.loads(Path(context_path).read_text()))
            selected = context.get('resolved_rows') or [context.get('resolved_row', {})]
            scan_required = (any(r.get('id') == 'D49' for r in selected)
                             and (context.get('features') or {}).get('requires_scan') is True)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            scan_required = True  # Context cannot prove that the scan obligation is absent.
        if scan_required and verdict.status != 'FAIL':
            from verdict import ReasonClass
            verdict.status = 'NOT_MEASURED'
            verdict.reason_class = ReasonClass.INPUT_ABSENT
            verdict.reasons.append('D49_SCAN_MODES_NOT_ACQUIRED: shift and capture timing unmeasured')
    ledger = fcc._GATE_LEDGER[start:]
    from dataclasses import asdict
    return {'step': asdict(verdict), 'ledger': ledger, 'status': verdict.status,
            'required_commands': required_commands(row)}


def contracts(project: Path, row: dict) -> dict:
    """Resolve canonical any-of/glob contracts to substantive exact file hashes."""
    import flow_compliance_check as fcc
    result = {}
    for spec in row.get('required_outputs', []):
        if fcc._output_not_owed(project, row, spec):
            continue
        files = []
        for pattern in spec.split(' OR '):
            for p in sorted(project.glob(pattern.strip())):
                if p.is_file() and not p.is_symlink() and p.stat().st_size:
                    files.append(str(p.relative_to(project)))
        if not files:
            raise em.Refusal('BACKEND_SUBSTANTIVE_CONTRACT_MISSING', f"{project}: required_outputs glob alternatives {spec!r} yielded no regular nonempty nonlinked files")
        result[spec] = {name: snap.sha(project / name) for name in files}
    return result


def states(binding, gate_result, producer):
    values = {'backend_canonical': 'PASS' if gate_result['status'] == 'PASS' else
              'FAIL' if gate_result['status'] == 'FAIL' else 'NOT_MEASURED',
              'backend_native_substance': 'PASS' if producer == 'PASS' else
              'FAIL' if producer == 'FAIL' else 'NOT_MEASURED'}
    for name in binding['required_gates']:
        if name in values:
            continue
        observed = [x for x in gate_result['ledger'] if x.get('gate') == name
                    and x.get('cmd') in gate_result.get('required_commands', ())]
        # Only unconditional program calls satisfy individual hard obligations.
        # Raw advisory/optional rows remain in the lossless ledger, while
        # backend_canonical carries the complete consumer's actual verdict.
        values[name] = ('FAIL' if any(x.get('rc') == 1 or x.get('verdict') == 'FAIL' for x in observed)
                        else 'PASS' if observed and all(x.get('rc') == 0 and x.get('verdict') == 'PASS' for x in observed)
                        else 'NOT_MEASURED')
    return values
