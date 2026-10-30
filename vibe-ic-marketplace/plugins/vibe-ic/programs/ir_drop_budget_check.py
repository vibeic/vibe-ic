#!/usr/bin/env python3
"""ir_drop_budget_check.py — numeric IR-drop budget gate for tapeout sign-off.

The tapeout-checklist skill's power-integrity row requires:

    Static IR-drop < budget (typical 5-10% of Vdd)

The existing `eda_report_audit --mode ir_drop` (= ir_drop_report_check.py)
only confirms that *some* voltage-drop value APPEARS in the report
(presence + tool-authenticity). It never computes the actual budget
`budget_mV = pct * Vdd * 1000` and never compares the measured worst-case
drop against it. `ir_drop_triage_classify.py` classifies hotspot CAUSES
but likewise does no Vdd-budget pass/fail.

This program closes that gap with a deterministic numeric threshold:

    PASS iff  max_drop_mV  <  pct * Vdd * 1000      (strictly under budget)

It reads the worst-case static IR drop from an IR-drop report. Two
schemas are accepted:

  1. JSON  — any of these keys (mV unless a *_pct / *_percent key is used):
       max_ir_drop_mv / worst_ir_drop_mv / max_drop_mv / ir_drop_mv
       max_ir_drop_pct / worst_ir_drop_percent (% of Vdd)
     plus a supply-voltage key:  vdd / vdd_v / supply_voltage_v / nominal_vdd_v
  2. Plain .rpt — scrapes the largest "<num> mV" OR "<num> % Vdd" token.

Honest-failure rules (NO vacuous pass on absence / garbage):
  * report file absent / unreadable                      → FAIL (rc=1)
  * present but no drop value can be extracted           → FAIL (rc=1)
  * drop given in mV but no Vdd available to size budget  → FAIL (rc=1)
  * measured drop >= budget                              → FAIL (rc=1)
  * measured drop  <  budget                             → PASS (rc=0)
  * project/report path not found at all                 → rc=2 (IO/arg)

There is no SKIP path: any design that reaches IR sign-off has a power
grid and therefore a measurable worst-case drop; a missing report is a
missing-evidence FAIL, not a not-applicable SKIP.

Usage:
    python3 ir_drop_budget_check.py <report> [--vdd V] [--budget-pct P]
                                    [--json OUT]
    <report> may be a JSON file, a .rpt file, or a directory (the program
    then searches for *ir*.json / *ir*.rpt / *voltage_drop* under it).

main(argv) -> int : 0 PASS / 1 FAIL / 2 IO-or-arg error.

chip-AGNOSTIC: reads only generic IR-report schemas; no design knowledge.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Default budget: 10% of Vdd is the loosest commonly-cited static budget;
# the skill says "typical 5-10% Vdd". 10% is the permissive default so the
# gate never FAILs a design that a stricter house rule would also pass.
_DEFAULT_BUDGET_PCT = 10.0

_DROP_MV_KEYS = (
    "max_ir_drop_mv", "worst_ir_drop_mv", "max_drop_mv", "ir_drop_mv",
    "max_voltage_drop_mv", "worst_voltage_drop_mv",
)
_DROP_PCT_KEYS = (
    "max_ir_drop_pct", "worst_ir_drop_pct", "max_ir_drop_percent",
    "worst_ir_drop_percent", "ir_drop_pct_vdd",
)
_VDD_KEYS = (
    "vdd", "vdd_v", "supply_voltage_v", "nominal_vdd_v", "vdd_volts",
)


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _extract_from_json(data: Any) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Return (drop_mv, drop_pct, vdd_v) — any may be None if absent."""
    drop_mv: Optional[float] = None
    drop_pct: Optional[float] = None
    vdd_v: Optional[float] = None
    if not isinstance(data, dict):
        return None, None, None
    # Allow a nested summary dict (common in our report payloads).
    scopes = [data]
    for k in ("summary", "ir_drop", "static_ir_drop", "power_integrity"):
        sub = data.get(k)
        if isinstance(sub, dict):
            scopes.append(sub)
    for scope in scopes:
        for k in _DROP_MV_KEYS:
            if drop_mv is None and k in scope:
                drop_mv = _num(scope[k])
        for k in _DROP_PCT_KEYS:
            if drop_pct is None and k in scope:
                drop_pct = _num(scope[k])
        for k in _VDD_KEYS:
            if vdd_v is None and k in scope:
                vdd_v = _num(scope[k])
    return drop_mv, drop_pct, vdd_v


_MV_RE = re.compile(r"([-+]?\d+(?:\.\d+)?)\s*mV", re.I)
_PCT_VDD_RE = re.compile(r"([-+]?\d+(?:\.\d+)?)\s*%\s*(?:of\s*)?Vdd", re.I)
_VDD_RE = re.compile(r"\bVdd\b\s*[=:]\s*([-+]?\d+(?:\.\d+)?)\s*V?", re.I)


def _extract_from_text(text: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    mv_vals = [float(m) for m in _MV_RE.findall(text)]
    pct_vals = [float(m) for m in _PCT_VDD_RE.findall(text)]
    vdd_m = _VDD_RE.search(text)
    drop_mv = max(mv_vals) if mv_vals else None
    drop_pct = max(pct_vals) if pct_vals else None
    vdd_v = float(vdd_m.group(1)) if vdd_m else None
    return drop_mv, drop_pct, vdd_v


def _discover_report(path: Path) -> Optional[Path]:
    if path.is_file():
        return path
    if path.is_dir():
        patterns = ["*ir*drop*.json", "*ir*.json", "*ir*drop*.rpt",
                    "*ir*.rpt", "*voltage_drop*", "*power_grid*.rpt"]
        for pat in patterns:
            hits = sorted(path.rglob(pat))
            if hits:
                return hits[0]
    return None


def evaluate(report_path: Path, vdd_arg: Optional[float],
             budget_pct: float) -> Tuple[bool, Dict[str, Any]]:
    """Return (passed, report_dict). passed=False on any honest-failure."""
    rep: Dict[str, Any] = {
        "program": "ir_drop_budget_check",
        "version": "1.0.0",
        "report_path": str(report_path),
        "budget_pct": budget_pct,
        "findings": [],
    }

    raw: Optional[str] = None
    try:
        raw = report_path.read_text(errors="replace")
    except OSError as exc:
        rep["findings"].append({"severity": "ERROR", "rule": "READ_FAIL",
                                "message": f"cannot read report: {exc}"})
        rep["pass"] = False
        return False, rep

    drop_mv = drop_pct = vdd_v = None
    if report_path.suffix.lower() == ".json":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            rep["findings"].append({"severity": "ERROR", "rule": "BAD_JSON",
                                    "message": f"unparseable JSON: {exc}"})
            rep["pass"] = False
            return False, rep
        drop_mv, drop_pct, vdd_v = _extract_from_json(data)
    else:
        drop_mv, drop_pct, vdd_v = _extract_from_text(raw)

    # CLI Vdd overrides / supplies the supply voltage.
    if vdd_arg is not None:
        vdd_v = vdd_arg

    if drop_mv is None and drop_pct is None:
        rep["findings"].append({
            "severity": "ERROR", "rule": "NO_DROP_VALUE",
            "message": "no worst-case IR-drop value (mV or %Vdd) found in report"})
        rep["pass"] = False
        return False, rep

    # Reduce to a single measured %-of-Vdd for the budget comparison.
    measured_pct: Optional[float] = None
    measured_mv: Optional[float] = drop_mv
    if drop_pct is not None:
        measured_pct = drop_pct
        if measured_mv is None and vdd_v is not None:
            measured_mv = drop_pct / 100.0 * vdd_v * 1000.0
    elif drop_mv is not None:
        if vdd_v is None:
            rep["findings"].append({
                "severity": "ERROR", "rule": "NO_VDD",
                "message": ("drop given in mV but no Vdd available to size the "
                            "budget; pass --vdd or include a vdd key")})
            rep["pass"] = False
            return False, rep
        measured_pct = drop_mv / (vdd_v * 1000.0) * 100.0

    budget_mv = (budget_pct / 100.0 * vdd_v * 1000.0) if vdd_v is not None else None

    rep["measured"] = {
        "drop_mv": measured_mv,
        "drop_pct_vdd": round(measured_pct, 4) if measured_pct is not None else None,
        "vdd_v": vdd_v,
    }
    rep["budget"] = {"budget_pct": budget_pct, "budget_mv": budget_mv}

    passed = measured_pct < budget_pct
    if not passed:
        rep["findings"].append({
            "severity": "ERROR", "rule": "IR_DROP_OVER_BUDGET",
            "message": (f"measured worst-case IR drop {measured_pct:.3f}% Vdd "
                        f">= budget {budget_pct:.3f}% Vdd"
                        + (f" ({measured_mv:.2f} mV >= {budget_mv:.2f} mV)"
                           if measured_mv is not None and budget_mv is not None
                           else ""))})
    rep["pass"] = passed
    return passed, rep


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("report", help="IR-drop report file or project/report dir")
    ap.add_argument("--vdd", type=float, default=None,
                    help="supply voltage in Volts (overrides report vdd key)")
    ap.add_argument("--budget-pct", type=float, default=_DEFAULT_BUDGET_PCT,
                    help=f"static IR budget as %% of Vdd (default {_DEFAULT_BUDGET_PCT})")
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    in_path = Path(args.report)
    report_path = _discover_report(in_path)
    if report_path is None:
        print(f"ERROR: no IR-drop report found at {in_path}", file=sys.stderr)
        return 2

    if args.budget_pct <= 0:
        print("ERROR: --budget-pct must be positive", file=sys.stderr)
        return 2

    passed, rep = evaluate(report_path, args.vdd, args.budget_pct)
    out = json.dumps(rep, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out + "\n")
    print(out)
    return 0 if passed else 1



def _d57_inputs(project):
    """Reuse the canonical row-input and existing bound-measurement inputs."""
    import hashlib
    import math
    from flow109_analog_floorplan import bound_file
    inputs = {}
    def remember(path):
        path = Path(path)
        if not path.is_file() or any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError('D57_INPUT_ABSENT_OR_SYMLINK: ' + str(path))
        inputs[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        return path
    config_path = remember(project / 'input/flow109/D57.json')
    cfg = json.loads(config_path.read_text())
    paths = {key: remember(bound_file(project, cfg.get(key)))
             for key in ('netlist', 'testbench', 'bindings')}
    source, nodes = cfg.get('source_node'), cfg.get('required_nodes')
    if (not isinstance(source, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.:#/$-]*', source)
            or not isinstance(nodes, list) or not nodes or len(set(nodes)) != len(nodes)
            or any(not isinstance(n, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.:#/$-]*', n) for n in nodes)
            or source in nodes):
        raise ValueError('D57_SOURCE_OR_REQUIRED_NODES_INVALID')
    args = cfg.get('arguments') or {}
    budget = args.get('budget_pct')
    if type(budget) not in (int, float) or not math.isfinite(budget) or budget <= 0:
        raise ValueError('D57_EXPLICIT_BUDGET_REQUIRED')
    if set(args) != {'budget_pct'}:
        raise ValueError('D57_NATIVE_SOURCE_REFERENCE_REQUIRED_NO_SCALAR_OVERRIDE')
    vdd = None
    bindings = json.loads(paths['bindings'].read_text())
    kind = (bindings.get('analysis') or {}).get('kind')
    if kind not in ('OP', 'TRAN'):
        raise ValueError('D57_NATIVE_OP_OR_TRAN_REQUIRED')
    probes = bindings.get('capture') if kind == 'TRAN' else {
        k: v.get('expression') for k, v in (bindings.get('measurements') or {}).items()}
    mapped = {}
    for label, expression in (probes or {}).items():
        match = re.fullmatch(r'(?i)v\(([A-Za-z_][A-Za-z0-9_.:#/$-]*)\)', str(expression))
        if not match or match[1] in mapped.values():
            raise ValueError('D57_ONE_NATIVE_VOLTAGE_PER_NODE_REQUIRED')
        mapped[label] = match[1]
    if set(mapped.values()) != {source, *nodes}:
        raise ValueError('D57_REQUIRED_NODE_COVERAGE_MISSING')
    if any(row.get('unit') != 'V' for row in (bindings.get('measurements') or {}).values()):
        raise ValueError('D57_VOLTAGE_UNITS_REQUIRED')
    return dict(config=cfg, paths=paths, bindings=bindings, kind=kind, probes=mapped,
                source=source, nodes=nodes, budget_pct=budget, vdd=vdd, inputs=inputs)


def _d57_grade(project, data, record, work):
    """Read fresh producer/log/capture facts; an unbound scalar is never IR proof."""
    import math
    import numpy as np
    import analog_bound_measurements as measured
    import analog_native_sim as sim
    import analog_real_corner_sweep as sweep
    if not isinstance(record, dict) or record.get('bindings') != data['bindings']:
        raise ValueError('D57_NATIVE_BINDINGS_CHANGED')
    valid, reason = measured.validate_consumed_inputs(project, record.get('native_inputs'))
    if not valid:
        raise ValueError('D57_NATIVE_INPUTS_UNBOUND: ' + reason)
    views = record['native_inputs']
    for role, path in data['paths'].items():
        view = views.get(role) or {}
        if view.get('path') != str(path.resolve()) or view.get('sha256') != data['inputs'][str(path)]:
            raise ValueError('D57_DECLARED_INPUT_NOT_CONSUMED: ' + role)
    if not any(role.startswith('include:') and view.get('sha256') == views['netlist']['sha256']
               for role, view in views.items()):
        raise ValueError('D57_NETWORK_NOT_IN_EXECUTED_CLOSURE')
    if any(not Path(v['path']).is_file() or measured.sha(Path(v['path'])) != v['sha256'] for v in views.values()):
        raise ValueError('D57_NATIVE_SOURCE_CHANGED')
    executions = record.get('executions') or []
    if not executions:
        raise ValueError('D57_NATIVE_EXECUTION_ABSENT')
    for execution in executions:
        log = Path(execution.get('log') or '__missing__')
        if not log.is_file() or execution.get('log_sha256') != measured.sha(log):
            raise ValueError('D57_NATIVE_LOG_CHANGED')
    transcript = '\n'.join(sim._log_text(e) for e in executions)
    if any(e.get('returncode') != 0 for e in executions) or any(sweep._scan_analysis_failures(transcript)):
        return {'status': 'FAIL', 'reason': 'D57_NATIVE_VOLTAGE_CAPTURE_FAILED'}
    if record.get('status') != 'PASS':
        raise ValueError('D57_NATIVE_MEASUREMENTS_INCOMPLETE')
    actual = {k.casefold(): v for k, v in sweep.native_meas_rows(transcript).items()}
    for match in sweep._MEAS_LINE_RE.finditer(transcript):
        for key, value in sweep._KV_RE.findall(match.group(1)):
            actual.setdefault(key.casefold(), float(value))
    if not actual or any(actual.get(k.casefold()) != v for k, v in record.get('measurements', {}).items()):
        raise ValueError('D57_NATIVE_VALUES_ABSENT_OR_CHANGED')
    if data['kind'] == 'OP':
        values = {node: np.array([actual[label.casefold()]]) for label, node in data['probes'].items()}
        samples, window = 1, None
    else:
        capture = record.get('capture') or {}
        path = Path(capture.get('path') or '__missing__')
        if not path.is_file() or capture.get('sha256') != measured.sha(path):
            raise ValueError('D57_NATIVE_CAPTURE_CHANGED')
        names = path.read_text().splitlines()[0].split()
        expected = ['time'] + ['bound_' + key for key in data['probes']]
        if names != expected:
            raise ValueError('D57_NATIVE_CAPTURE_NODE_COVERAGE_CHANGED')
        curve = np.loadtxt(path, skiprows=1, ndmin=2)
        analysis = data['bindings']['analysis'];window = [analysis.get('start_s', 0.), analysis['stop_s']]
        if (curve.shape[1] != len(names) or len(curve) < 2 or not np.all(np.isfinite(curve))
                or np.any(np.diff(curve[:, 0]) <= 0) or curve[0, 0] > window[0] or curve[-1, 0] < window[1]):
            raise ValueError('D57_NATIVE_CAPTURE_WINDOW_OR_VALUES_INVALID')
        values = {node: curve[:, i+1] for i, node in enumerate(data['probes'].values())}
        samples = len(curve)
    if any(not np.all(np.isfinite(v)) for v in values.values()):
        raise ValueError('D57_NONFINITE_NATIVE_VOLTAGE')
    source = values[data['source']]
    reference = data['vdd']
    if reference is None:
        if not np.all(source == source[0]):
            raise ValueError('D57_VARIABLE_SOURCE_REQUIRES_DECLARED_VDD_REFERENCE')
        reference = float(source[0])
    if not math.isfinite(reference) or reference <= 0:
        raise ValueError('D57_POSITIVE_VOLTAGE_REFERENCE_REQUIRED')
    drops = {n: float(np.max(source-values[n]))*1000 for n in data['nodes']}
    if any(v < 0 for v in drops.values()):
        raise ValueError('D57_NEGATIVE_DROP_UNSUPPORTED')
    report = work/'native_ir_drop.json'
    report.write_text(json.dumps({'max_ir_drop_mv': max(drops.values()), 'vdd_v': reference,
                                 'sampled_nodes': drops, 'sample_count': samples,
                                 'source_node': data['source'], 'window_s': window,
                                 'scope': 'native sampled-node maximum only; not full routed-grid/mission coverage'}, indent=2)+'\n')
    passed, answer = evaluate(report, reference, data['budget_pct'])
    return {'status': 'PASS' if passed else 'FAIL', 'reason': 'D57_NATIVE_IR_BUDGET_COMPARED',
            'native_report': str(report), 'budget_result': answer, 'sample_count': samples,
            'node_drops_mv': drops, 'source_node': data['source'], 'vdd_reference_v': reference,
            'required_nodes': data['nodes'], 'sampled_nodes': sorted(drops), 'window_s': window,
            'scope': 'selected source/node/window voltage-drop component only'}


def execute(project, context):
    """D57 analog entry: existing bound producer + unchanged numeric comparator."""
    import uuid
    import hashlib
    import librelane_contract as launch
    from flow109_admission import require_launch_admission, AdmissionRefusal
    from analog_native_flow import NativeCommands
    project = Path(project).resolve(strict=True)
    work = project/'reports/flow109/D57'/uuid.uuid4().hex;work.mkdir(parents=True)
    result = dict(step_id='D57', context_sha256=context.get('context_sha256'),
                  component_status='NOT_MEASURED', default_row_status='NOT_MEASURED', completed=False,
                  native_started=False, outputs=[], executions=[], qualification='NOT_CLAIMED',
                  flow109_acceptance='NOT_MEASURED', whole_flow_acceptance='NOT_MEASURED', delivery_accepted=False)
    try:
        if (context.get('requested_step') != 'D57' or context.get('native_step_id') != 'flow109.D57'
                or context.get('resolved_row', {}).get('profile', {}).get('id') != 'analog_die'):
            raise ValueError('D57_CONTEXT_INVALID')
        result['launch_admission'] = require_launch_admission(project, 'flow109.D57', {'flow109_context': context})
        result['native_launch'] = launch.local_image_attestation()
        data = _d57_inputs(project);result['inputs'] = data['inputs']
        destination = work/'measurements';destination.mkdir()
        runner = NativeCommands(project, work, '', result['native_launch']['image'])
        args = [str(project)]
        for key in ('netlist', 'testbench', 'bindings'):
            args += ['--'+key, str(data['paths'][key])]
        args += ['--out', str(destination), '--container', '', '--image', result['native_launch']['image']]
        result['native_started'] = True
        execution = runner('analog_bound_measurements.py', args)
        result['executions'].append(execution)
        path = destination/'result.json'
        if not path.is_file():
            raise ValueError('D57_NATIVE_RECEIPT_ABSENT')
        record = json.loads(path.read_text())
        answer = _d57_grade(project, data, record, work)
        result['measurement'] = answer
        result['component_status'] = answer['status'];result['reason'] = answer['reason']
        if (_d57_inputs(project) != data or
                any(hashlib.sha256(Path(p).read_bytes()).hexdigest() != digest for p, digest in data['inputs'].items())):
            result['component_status']='NOT_MEASURED';result['reason']='D57_CURRENT_INPUT_CHANGED'
        result['outputs']=[str(p) for p in work.rglob('*') if p.is_file()]
    except (AdmissionRefusal, OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        result.update(component_status='NOT_MEASURED', reason=str(exc))
    result['scope']='Native selected-node IR component only; routed grid, physical extraction, mission coverage and Flow109 metrics remain independently unproved'
    (work/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__ == "__main__":
    sys.exit(main())
