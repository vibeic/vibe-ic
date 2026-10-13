"""Execute the unchanged canonical clauses; retain advisory/conditional facts."""
from __future__ import annotations
import json
import sys
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import execution_backend_snapshot as snap
import execution_modes as em


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
    ledger = fcc._GATE_LEDGER[start:]
    from dataclasses import asdict
    return {'step': asdict(verdict), 'ledger': ledger, 'status': verdict.status}


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
            raise em.Refusal('BACKEND_SUBSTANTIVE_CONTRACT_MISSING', spec)
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
        observed = [x for x in gate_result['ledger'] if x.get('gate') == name]
        # Preserve raw advisory FAIL too. F1 must not demand a fake PASS for a
        # program the canonical policy explicitly makes advisory/conditional.
        values[name] = ('FAIL' if any(x.get('rc') == 1 or x.get('verdict') == 'FAIL' for x in observed)
                        else 'PASS' if observed and all(x.get('rc') == 0 and x.get('verdict') == 'PASS' for x in observed)
                        else 'NOT_MEASURED')
    return values
