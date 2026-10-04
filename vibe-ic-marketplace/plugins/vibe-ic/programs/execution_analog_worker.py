"""Isolated analog producer child and substantive fresh artifact consumers.

The child is a passive producer supervised by the existing parent Controller.
It never bootstraps policy, verifies parent authority or adopts a generation.
"""
from __future__ import annotations
# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------

import argparse
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from dataclasses import asdict
import importlib
import io
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import _progress_run
import sys
import time
import uuid

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import execution_modes as em
import _docker_memory as _dmem
from execution_adapters_analog import (ANALOG_STEPS, CONTRACTS, ENGINE_FAMILIES,
    PRODUCERS, PROGRAMS, WORKER, covered, gate_specs, write_json, producer_work_contract)


def hashes(root: Path) -> dict:
    return {str(p.relative_to(root)): em.digest(p) for p in root.rglob('*')
            if p.is_file() and not p.is_symlink()}


def producer_result_observations(value, path='') -> list:
    """Read producer results without granting execution or native admission."""
    observations = []
    def visit(value, path):
        if isinstance(value, dict):
            for key, item in value.items():
                location = path + '/' + key
                if key in ('verdict', 'design_verdict', 'status', 'result', 'raw_sim_verdict', 'lvs') and isinstance(item, str):
                    observations.append(dict(path=location, verdict=item))
                elif key == 'rc' and type(item) is int:
                    observations.append(dict(path=location, rc=item))
                elif key in ('executed', 'simulator_run', 'full_pvt_sweep_executed') and item is False:
                    observations.append(dict(path=location, executed=False))
                visit(item, location)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, path + '/' + str(index))
    visit(value, path)
    return observations


def producer_result_verdict(observations: list) -> str:
    """A measured failure in any complement survives clean sibling results."""
    words = [row['verdict'].strip().upper() for row in observations if 'verdict' in row]
    if any(word in ('FAIL', 'MISMATCH') for word in words) or any(row.get('rc') == 1 for row in observations):
        return 'FAIL'
    if (not words or any(word not in ('PASS', 'MATCH') for word in words)
            or any(('rc' in row and row['rc'] != 0) or row.get('executed') is False
                   for row in observations)):
        return 'NOT_MEASURED'
    return 'PASS'


def producer_work(calls: list, binding: dict, source_files: dict) -> dict:
    """Retain every real complementary result; no best-tool reduction."""
    contract = producer_work_contract(binding['step_id'])
    allowed = contract['entrypoints'] + contract['optional_entrypoints']
    observations = []
    records = []
    for index, call in enumerate(calls):
        entrypoint = call.get('entrypoint', '')
        source = PROGRAMS / (entrypoint.split('.')[0] + '.py')
        name = str(source.resolve())
        if (entrypoint not in allowed or type(call.get('pid')) is not int or call['pid'] <= 0
                or not source.is_file() or source.is_symlink()
                or source_files.get(name) != em.digest(source)
                or call.get('source_sha256') != source_files.get(name)):
            raise em.Refusal('ANALOG_PRODUCER_BRANCH_UNBOUND', entrypoint)
        observed = producer_result_observations(call, str(index))
        observations.extend(observed)
        records.append(dict(entrypoint=entrypoint, pid=call['pid'], source_sha256=source_files[name],
                            actual_result=call, observations=observed))
    verdict = producer_result_verdict(observations)
    incomplete = not records or any(not row['observations'] for row in records)
    block_steps = ('A3', 'A4', 'A5', 'A6', 'A7', 'A8')
    expected_blocks = binding['objective']['blocks'] if binding['step_id'] in block_steps else [None]
    for entrypoint in contract['entrypoints']:
        for block in expected_blocks:
            matching = [call for call in calls if call['entrypoint'] == entrypoint
                        and (block is None or call.get('block') == block)]
            if len(matching) != 1:
                incomplete = True
    if binding['step_id'] == 'A6':
        incomplete |= any(not isinstance(call.get('result', {}).get(part), dict)
                          or call['result'][part].get('executed') is not True
                          for call in calls for part in ('drc', 'lvs'))
    return dict(binding=binding, contract=contract, records=records, complete=not incomplete,
        design_verdict='FAIL' if verdict == 'FAIL' else 'NOT_MEASURED' if incomplete else verdict,
        qualification_is_native_admission=False)


def checked_json(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        raise em.Refusal('ANALOG_SUBSTANTIVE_INPUT_MISSING', str(path))
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise em.Refusal('ANALOG_JSON_OBJECT_REQUIRED', str(path))
    return data


@contextmanager
def _producer_reentry(project: Path, binding: dict):
    """The inner worker has no process-local outer Controller authority.

    Environment, native markers, binding files and producer receipts retain
    integrity facts only. No serialized data can re-enter an issued callable.
    """
    raise em.Refusal('PRODUCTION_CHILD_SCOPE_UNBOUND', 'live outer Controller is process-local')
    yield  # contextmanager shape; the refusal always precedes producer entry


def _gate_status(rc: int | None, report: dict) -> str:
    if rc == 1 or report.get('verdict') in ('FAIL', 'INCOMPLETE'):
        return 'FAIL'
    if rc != 0 or report.get('verdict') != 'PASS':
        return 'NOT_MEASURED'
    if any(f.get('severity') in ('ERROR', 'FAIL') for f in report.get('findings', []) if isinstance(f, dict)):
        return 'FAIL'
    return 'PASS'


def _advisory_record(row: dict, project: Path, report_path: Path | None,
                     rc: int | None, report: dict, stdout: str) -> dict:
    """Use the existing classifier on the actual invocation, never its tier payload."""
    import flow_compliance_check as compliance
    name = shlex.split(row['command'])[0]
    if rc is None:
        return dict(gate=name, command=row['command'], exit_code=None,
                    verdict='NOT_MEASURED', structured_verdict=None,
                    reason_class=None, enforcement='BLOCKING')
    structured = compliance._report_verdict(report)
    execution = compliance._ProgramCheckResult(
        _gate_status(rc, report) == 'PASS', stdout, rc, structured,
        structured or _gate_status(rc, report), compliance._reason_taxonomy.report_reason_class(report))
    # Point the shared reader at this invocation's report, including gates
    # whose canonical command did not originally request a JSON file.
    command = shlex.join([name, '--json', str(report_path)]) if report_path else name
    record = compliance._advisory_execution_record(
        command, sys.maxsize, execution[0], stdout, project, execution)
    record['command'] = row['command']
    return record


def _m1_observation(outputs: Path, binding: dict, calls: list) -> dict | None:
    """Only the current producer and actual native process log speak for M1."""
    path = outputs / 'producer-calls/calls.json'
    raw = outputs / 'producer-calls/native-processes.jsonl'
    if binding['step_id'] != 'M1' or not path.is_file() or not raw.is_file():
        return None
    if path.is_symlink() or raw.is_symlink() or json.loads(path.read_text()) != calls:
        raise em.Refusal('ANALOG_M1_PRODUCER_RECORD_CHANGED', str(path))
    records = [c for c in calls if c.get('entrypoint') == 'mixed_signal_top_lvs_run.run']
    processes = [json.loads(line) for line in raw.read_text().splitlines() if line.strip()]
    script = PROGRAMS / 'mixed_signal_top_lvs_run.py'
    if (len(records) != 1 or not processes or any(
            type(p.get('pid')) is not int or type(p.get('rc')) is not int
            or not p.get('argv') or not p.get('started_ns') or not p.get('ended_ns')
            or p.get('stop') for p in processes)):
        return None
    record, result = records[0], records[0].get('result')
    if (record.get('source_sha256') != em.digest(script) or type(record.get('pid')) is not int
            or not isinstance(result, dict) or type(result.get('rc')) is not int
            or not isinstance(result.get('verdict'), str)):
        return None
    if result['verdict'] == 'PASS' and (result['rc'] != 0 or any(p['rc'] != 0 for p in processes)):
        return None
    raw_files = {str(path): em.digest(path), str(raw): em.digest(raw)}
    if result['verdict'] == 'PASS':
        project = outputs / 'project'
        report_path = project / 'reports/analog/mixed_signal/top_lvs.json'
        if not report_path.is_file() or report_path.is_symlink():
            return None
        measured = checked_json(report_path)
        if measured.get('verdict') != 'PASS' or any(result.get(k) != v for k, v in measured.items()):
            return None
        for relative in (measured.get('lvs_report'), measured.get('extracted_netlist')):
            if not isinstance(relative, str):
                return None
            actual = project / em._relative(relative)
            if (actual.is_symlink() or not actual.is_file() or not actual.stat().st_size
                    or not actual.resolve().is_relative_to(project.resolve())):
                return None
            raw_files[str(actual)] = em.digest(actual)
        raw_files[str(report_path)] = em.digest(report_path)
    return dict(pid=record['pid'], rc=result['rc'], report=result,
                raw_files=raw_files,
                producer_call=record, native_processes=processes)


def retain_producer_observation(observation: dict | None, root: Path) -> dict | None:
    if not observation:
        return None
    raw_files = {}
    for name, expected in observation['raw_files'].items():
        source = Path(name)
        if source.is_symlink() or em.digest(source) != expected:
            raise em.Refusal('ANALOG_M1_PRODUCER_RECORD_CHANGED', name)
        target = root / 'producer-observation' / expected / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if em.digest(source) != expected or em.digest(target) != expected:
            raise em.Refusal('ANALOG_M1_PRODUCER_RECORD_CHANGED', name)
        raw_files[str(target)] = expected
    return {**observation, 'raw_files': raw_files}


def semantic_gates(step: str, project: Path, directory: Path, canonical=False,
                   producer_observation: dict | None = None) -> dict:
    """Existing blocking/advisory/bench-conditional semantics, with raw rc."""
    import shlex
    directory.mkdir(parents=True, exist_ok=True)
    blocking, advisory, external, receipts = {}, {}, [], []
    advisory_records, declared_na = [], []
    for row in gate_specs(step):
        tokens = shlex.split(row['command'])
        name = tokens.pop(0)
        script = PROGRAMS / (name + '.py')
        destination = advisory if row['kind'] == 'advisory_program_exit_zero' else blocking
        destination[name] = 'NOT_MEASURED'
        condition = row.get('condition_files_exist')
        present = [p for expr in (condition or []) for p in project.glob(expr)]
        condition_hashes = {str(p.relative_to(project)): em.digest(p) for p in present if p.is_file()}
        common = dict(gate=name, command=row['command'], kind=row['kind'],
            program_sha256=em.digest(script), condition_files_exist=condition or [],
            condition_input_hashes=condition_hashes, applies=not condition or bool(present))
        if condition and not present:
            why = row.get('absent_condition_reason', '')
            external.append(dict(gate=name, reason=why, condition=condition))
            receipt = dict(common, rc=None, verdict='NOT_MEASURED', raw_files={},
                           reason='SOURCE_DECLARED_CONDITION_ABSENT')
            if row['kind'] == 'advisory_program_exit_zero':
                import flow_compliance_check as compliance
                advisory_records.append(dict(gate=name, command=row['command'], exit_code=None,
                    verdict='NOT_APPLICABLE', structured_verdict=None, enforcement='NOT_RUN_DECLARED',
                    reason_class=compliance._reason_taxonomy.normalise(
                        row.get('absent_condition_reason_class', 'DESIGN_DECLARED_NA'))))
            else:
                declared_na.append(row['command'] + ' — condition_files_exist ' + str(condition)
                    + ' matched 0 path(s), so the program did not run and nothing was checked. '
                    + 'Declared not-applicable: ' + (why.strip() if isinstance(why, str) else ''))
            receipts.append(receipt)
            continue
        if name == 'mixed_signal_top_lvs_run':
            # This canonical advisory clause is itself the native producer.
            # It ran once in native_produce; consumers do not recursively
            # remake the selected GDS or modify their bound upstream INPUT.
            observation = producer_observation or {}
            observed_report = directory / (name + '.observed.json')
            raw_files = dict(observation.get('raw_files', {}))
            if observation:
                write_json(observed_report, observation['report'])
                raw_files[str(observed_report)] = em.digest(observed_report)
            record = _advisory_record(row, project, observed_report if observation else None,
                                     observation.get('rc'), observation.get('report', {}), '')
            advisory_records.append(record)
            destination[name] = ('FAIL' if record['verdict'] == 'FAIL' or record['exit_code'] == 1
                else 'PASS' if record['verdict'] == 'PASS' and record['exit_code'] == 0
                else 'NOT_MEASURED')
            receipts.append(dict(common, rc=observation.get('rc'), verdict=destination[name],
                advisory_record=record, observation=observation,
                raw_files=raw_files, reason='ADVISORY_PRODUCER_NOT_REEXECUTED'))
            continue
        args, report_path = [], directory / (name + '.json')
        i = 0
        while i < len(tokens):
            token = tokens[i]
            if token == '--json':
                report_path = project / tokens[i + 1] if canonical else report_path
                i += 2
                continue
            args.append(str(project) if token == '.' else
                        str(project / token) if token.startswith('phase') else token)
            i += 1
        command = [str(Path(sys.executable).resolve()), str(script), *args, '--json', str(report_path)]
        out, err = directory / (name + '.stdout'), directory / (name + '.stderr')
        try:
            completed = _progress_run.run(command, stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE, text=True,
                                          hard_ceiling_s=120.0)
            rc = completed.returncode
            out.write_text(completed.stdout or '')
            err.write_text(completed.stderr or '')
        except _progress_run.Stalled:
            rc = None
            out.touch(); err.touch()
        report = checked_json(report_path) if report_path.is_file() else {}
        verdict = _gate_status(rc, report)
        record = None
        if row['kind'] == 'advisory_program_exit_zero':
            record = _advisory_record(row, project, report_path, rc, report,
                                      out.read_text(errors='replace'))
            advisory_records.append(record)
            verdict = ('FAIL' if record['verdict'] == 'FAIL' or record['exit_code'] == 1
                else 'PASS' if record['verdict'] == 'PASS' and record['exit_code'] == 0
                else 'NOT_MEASURED')
        destination[name] = verdict
        receipt = {**common, 'argv': command, 'pid': None,
            'rc': rc, 'verdict': verdict, 'program_sha256': em.digest(script),
            'report': report, 'advisory_record': record,
            'report_sha256': em.digest(report_path) if report_path.is_file() else None,
            'stdout_sha256': em.digest(out), 'stderr_sha256': em.digest(err),
            'raw_files': {str(p): em.digest(p) for p in (out, err, report_path) if p.is_file()}}
        write_json(directory / (name + '.receipt.json'), receipt)
        receipts.append(receipt)
    return {'blocking': blocking, 'advisory': advisory, 'external': external, 'receipts': receipts,
            'advisory_gate_records': advisory_records, 'declared_not_applicable': declared_na}


def canonical_report(fresh: dict, binding: dict, project: Path, root: Path,
                     source_files: dict, producer_verdict: str, producer_work: dict | None = None) -> dict:
    """One actual step, classified by F1 and emitted after verdict assessment."""
    import execution_analog_contract as production
    import flow_compliance_check as compliance
    import _flow_yaml
    from execution_adapters_analog import CONTRACT_FILE
    gates = {name: 'NOT_MEASURED' for name in binding['required_gates']}
    gates.update({k: v for k, v in {**fresh['blocking'], **fresh['advisory']}.items() if k in gates})
    if em._hash(dict(source_files)) != binding['objective']['source_manifest_sha256']:
        raise em.Refusal('ANALOG_REPORT_SOURCE_MANIFEST_CHANGED', binding['step_id'])
    sources = [CONTRACT_FILE, PROGRAMS.parent / 'flow/phase1_phase2_phase3.yaml',
        Path(production.__file__).resolve(), Path(compliance.__file__).resolve(),
        *(PROGRAMS / (r['gate'] + '.py') for r in fresh['receipts'])]
    observed_sources = {}
    for path in sources:
        name = str(path.resolve())
        if path.is_symlink() or source_files.get(name) != em.digest(path):
            raise em.Refusal('ANALOG_REPORT_SOURCE_UNBOUND', name)
        observed_sources[name] = em.digest(path)
    raw_files = {}
    for receipt in fresh['receipts']:
        for name, expected in receipt['raw_files'].items():
            path = Path(name)
            if not path.is_relative_to(root) or path.is_symlink() or em.digest(path) != expected:
                raise em.Refusal('ANALOG_GATE_RAW_RECORD_CHANGED', name)
            raw_files[str(path.relative_to(root))] = expected
    executions = []
    for receipt in fresh['receipts']:
        if receipt.get('rc') is None:
            continue  # A nonexecuted clause never receives an execution row.
        advisory = receipt.get('advisory_record')
        executions.append(dict(cmd=receipt['command'], gate=receipt['gate'],
            rc=receipt['rc'], exit_code=receipt['rc'],
            verdict=advisory['verdict'] if advisory else receipt['verdict'],
            structured_verdict=advisory.get('structured_verdict') if advisory else
                compliance._report_verdict(receipt.get('report')),
            reason_class=advisory.get('reason_class') if advisory else
                compliance._reason_taxonomy.report_reason_class(receipt.get('report')),
            pid=receipt.get('pid') or receipt.get('observation', {}).get('pid'),
            program_sha256=receipt['program_sha256'], raw_files=receipt['raw_files']))
    canonical_row = next(row for row in _flow_yaml.load()['steps']
                         if str(row['id']) == binding['step_id'])
    row = dict(id=binding['step_id'], status='NOT_MEASURED', canonical_row=canonical_row,
        advisory_gate_records=fresh['advisory_gate_records'],
        declared_not_applicable=fresh['declared_not_applicable'], execution_records=fresh['receipts'],
        program_execution_records=executions)
    report = dict(schema=1, binding=binding, step_id=binding['step_id'], source_sha=binding['source_sha'],
        source_files=dict(source_files), sources=observed_sources, raw_files=raw_files,
        project_population=hashes(project), gates=gates, fresh=fresh, steps=[row],
        producer_design_verdict=producer_verdict, gate_execution_ledger=executions)
    if producer_work is not None:
        report['producer_work'] = producer_work
    # The classifier's aggregate precondition needs a disposition view. This
    # private view is never issued; the actual report receives only the assessed
    # blocking/producer result, including every failure and nonmeasurement.
    view = {**report, 'steps': [{**row, 'status': 'PASS'}]}
    try:
        primary = production.canonical_gate_obligations(
            binding['step_id'], tuple(binding['required_gates']), gates, view, project=project,
            _program_records=executions)
        status = ('FAIL' if producer_verdict == 'FAIL' or any(gates[g] == 'FAIL' for g in primary)
            else 'PASS' if producer_verdict == 'PASS' and primary and all(gates[g] == 'PASS' for g in primary)
            else 'NOT_MEASURED')
        report['blocking_gates'] = list(primary)
    except em.Refusal as exc:
        status = ('FAIL' if producer_verdict == 'FAIL' or exc.code == 'GATE_FAIL'
                  or any(value == 'FAIL' for value in fresh['blocking'].values()) else 'NOT_MEASURED')
        report.update(blocking_gates=[], classification_refusal=dict(code=exc.code, detail=str(exc)))
    row['status'] = status
    return report


def read_canonical_report(root: Path, binding: dict, relative='canonical-gates.json',
                          expected_sha256: str | None = None) -> dict:
    """Reopen actual issued bytes, their source identity and complete raw population."""
    from execution_analog_contract import canonical_gate_population
    import _flow_yaml
    path = root / em._relative(relative)
    if not path.is_file() or path.is_symlink():
        raise em.Refusal('ANALOG_CANONICAL_REPORT_UNBOUND', relative)
    observed_sha = em.digest(path)
    report = checked_json(path)
    if em.digest(path) != observed_sha or expected_sha256 is not None and observed_sha != expected_sha256:
        raise em.Refusal('ANALOG_CANONICAL_REPORT_CHANGED', relative)
    if (report.get('binding') != binding or report.get('step_id') != binding['step_id']
            or report.get('source_sha') != binding['source_sha']
            or em._hash(report.get('source_files')) != binding['objective']['source_manifest_sha256']
            or set(report.get('gates', {})) != set(binding['required_gates'])
            or not set(canonical_gate_population(binding['step_id'])).issubset(report['gates'])):
        raise em.Refusal('ANALOG_CANONICAL_REPORT_UNBOUND', binding['step_id'])
    rows = report.get('steps')
    current_row = next(row for row in _flow_yaml.load()['steps'] if str(row['id']) == binding['step_id'])
    specs = gate_specs(binding['step_id'])
    fresh = report.get('fresh', {})
    receipts = fresh.get('receipts', [])
    if (not isinstance(rows, list) or len(rows) != 1 or rows[0].get('canonical_row') != current_row
            or rows[0].get('execution_records') != receipts
            or len(receipts) != len(specs) or any(
                r.get('command') != s['command'] or r.get('kind') != s['kind']
                for r, s in zip(receipts, specs))
            or rows[0].get('advisory_gate_records') != fresh.get('advisory_gate_records')
            or rows[0].get('program_execution_records') != report.get('gate_execution_ledger')):
        raise em.Refusal('ANALOG_CANONICAL_REPORT_POPULATION_CHANGED', binding['step_id'])
    for name, expected in report.get('sources', {}).items():
        source = Path(name)
        if (source.is_symlink() or not source.is_file() or em.digest(source) != expected
                or report['source_files'].get(name) != expected):
            raise em.Refusal('ANALOG_REPORT_SOURCE_UNBOUND', name)
    if not report.get('sources') or not isinstance(report.get('raw_files'), dict):
        raise em.Refusal('ANALOG_CANONICAL_REPORT_POPULATION_MISSING', relative)
    for name, expected in report['raw_files'].items():
        raw = root / em._relative(name)
        if raw.is_symlink() or not raw.is_file() or em.digest(raw) != expected:
            raise em.Refusal('ANALOG_GATE_RAW_RECORD_CHANGED', name)
    return report


def report_obligations(report: dict, binding: dict, project: Path) -> tuple[str, ...]:
    from execution_analog_contract import canonical_gate_obligations
    return canonical_gate_obligations(binding['step_id'], tuple(binding['required_gates']),
        report['gates'], report, project=project,
        _program_records=report['steps'][0]['program_execution_records'])


def _call(name: str, argv: list[str], directory: Path) -> dict:
    module = importlib.import_module(name)
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        rc = module.main(argv)
    record = {'entrypoint': name + '.main', 'argv': argv, 'pid': os.getpid(),
              'rc': rc, 'source_sha256': em.digest(Path(module.__file__)),
              'stdout': stdout.getvalue(), 'stderr': stderr.getvalue()}
    write_json(directory / (name + '.json'), record)
    return record


def _decision(inputs: Path, spec: dict, project: Path) -> None:
    if spec['step_id'] not in ('A2', 'A3'):
        return
    decision = checked_json(inputs / 'decision')
    required = ('reviewer', 'rationale', 'blocks', 'input_hashes', 'source_sha')
    if any(k not in decision for k in required) or not decision['reviewer'] or not decision['rationale']:
        raise em.Refusal('ANALOG_AI_DECISION_INCOMPLETE', spec['step_id'])
    source_inputs = {k: v for k, v in spec['input_hashes'].items() if k.startswith('project/')}
    if decision['source_sha'] != spec['source_sha'] or decision['input_hashes'] != source_inputs:
        raise em.Refusal('ANALOG_AI_DECISION_STALE', spec['step_id'])
    if set(decision['blocks']) != set(spec['blocks']):
        raise em.Refusal('ANALOG_AI_BLOCK_POPULATION_CHANGED', spec['step_id'])
    for block in spec['blocks']:
        chosen = decision['blocks'][block]
        if not isinstance(chosen, dict) or not chosen.get('topology') or not chosen.get('sizing_rationale'):
            raise em.Refusal('ANALOG_AI_TOPOLOGY_DECISION_REQUIRED', block)
        if spec['step_id'] == 'A3':
            ir = checked_json(project / f'phase3/analog/{block}/topology.json')
            if em.digest(project / f'phase3/analog/{block}/topology.json') != chosen.get('topology_sha256'):
                raise em.Refusal('ANALOG_AI_TOPOLOGY_CHANGED', block)


def source_produce(inputs: Path, project: Path, spec: dict, records: Path) -> list[dict]:
    records.mkdir(parents=True, exist_ok=True)
    step, params = spec['step_id'], spec['parameters']
    _decision(inputs, spec, project)
    result = []
    for block in spec['blocks']:
        if step == 'A1':
            result.append(_call('analog_a1_spec_emit', [str(project), '--block', block], records))
        elif step == 'A2':
            result.append(_call('analog_a2_topology_emit', [str(project), '--block', block,
                           '--pdk', params['pdk_name']], records))
            path = project / f'phase3/analog/{block}/topology.json'
            if path.is_file():
                ir = checked_json(path)
                chosen = checked_json(inputs / 'decision')['blocks'][block]
                actual = ir.get('topology') or ir.get('topology_name') or ir.get('name')
                if actual != chosen['topology']:
                    raise em.Refusal('ANALOG_AI_TOPOLOGY_NOT_PRODUCED', block + ':' + str(actual))
    return result


def native_produce(inputs: Path, project: Path, spec: dict, records: Path) -> list[dict]:
    """One ordered complementary engine chain; never the parent flow."""
    from execution_analog_local_transport import local_transport
    step, params = spec['step_id'], spec['parameters']
    records.mkdir(parents=True, exist_ok=True)
    result = []
    with local_transport(records / 'native-processes.jsonl', time.monotonic() + params['timeout_s'],
                         project=project, parameters=params):
        if step == 'A6':
            import analog_a6_native_pv as pv
            if not params.get('pv_resolution'):
                raise em.Refusal('ANALOG_SIGNOFF_DECKS_REQUIRED', step)
            for block in spec['blocks']:
                try:
                    result.append({'entrypoint': 'analog_a6_native_pv.run_block_pv', 'pid': os.getpid(),
                        'block': block, 'result': pv.run_block_pv(project, block, {k: str(project / v) if k in ('drc_deck', 'lvs_deck') else v
                            for k, v in params['pv_resolution'].items()}, 'host')})
                except (em.Refusal, OSError, ValueError, KeyError) as exc:
                    entry = producer_work_contract(step)['entrypoints'][0]
                    result.append(dict(entrypoint=entry, block=block, pid=os.getpid(),
                        result={'verdict': 'NOT_MEASURED', 'reason': str(exc)}))
        elif step == 'A7':
            import analog_a7_post_layout_emit as post
            for block in spec['blocks']:
                try:
                    rc = post.run(project, block, 'host', params['image_ref'],
                                  styles=params.get('extraction_styles'))
                    result.append({'entrypoint': 'analog_a7_post_layout_emit.run', 'pid': os.getpid(),
                                   'block': block, 'rc': rc, 'result':
                                   checked_json(project / f'phase3/analog/{block}/pre_vs_post.json')
                                   if (project / f'phase3/analog/{block}/pre_vs_post.json').is_file() else {}})
                except (em.Refusal, OSError, ValueError, KeyError) as exc:
                    entry = producer_work_contract(step)['entrypoints'][0]
                    result.append(dict(entrypoint=entry, block=block, pid=os.getpid(),
                        result={'verdict': 'NOT_MEASURED', 'reason': str(exc)}))
        elif step == 'A8':
            from execution_analog_mixed_worker import characterize
            for block in spec['blocks']:
                try:
                    result.append(_call('analog_a8_hardmacro_emit', [str(project), '--block', block,
                        '--container', 'host', '--pdk-root', str(project / params['pdk_root'])], records))
                    result[-1]['block'] = block
                    result.append(_call('analog_hardmacro_gds_emit', [str(project), '--block', block,
                        '--container', 'host', '--pdk-root', str(project / params['pdk_root'])], records))
                    result[-1]['block'] = block
                    if (project / f'phase3/analog/{block}/characterization_plan.json').is_file():
                        result.append({'block': block, **characterize(project, block, params, records)})
                except (em.Refusal, OSError, ValueError, KeyError) as exc:
                    entry = producer_work_contract(step)['entrypoints'][0]
                    result.append(dict(entrypoint=entry, block=block, pid=os.getpid(),
                        result={'verdict': 'NOT_MEASURED', 'reason': str(exc)}))
        for call in result:
            source = PROGRAMS / (call['entrypoint'].split('.')[0] + '.py')
            call['source_sha256'] = em.digest(source)
            call.setdefault('pid', os.getpid())
        write_json(records / 'calls.json', result)
    return result



def validate_products(outputs: Path, binding: dict, producer: dict, manifest: dict) -> None:
    if producer.get('binding') != binding or manifest.get('binding') != binding:
        raise em.Refusal('ANALOG_PRODUCER_BINDING_CHANGED', binding['step_id'])
    if producer.get('step_id') != binding['step_id'] or producer.get('source_sha') != binding['source_sha']:
        raise em.Refusal('ANALOG_PRODUCER_SOURCE_CHANGED', binding['step_id'])
    if producer.get('native'):
        issued = checked_json(outputs / 'canonical-gates.json')
        branches = checked_json(outputs / 'producer-work.json')
        calls_file = outputs / 'producer-calls/calls.json'
        if (calls_file.is_symlink() or not calls_file.is_file()
                or json.loads(calls_file.read_text()) != producer['calls']
                or branches != producer_work(producer['calls'], binding, issued['source_files'])
                or issued.get('producer_work') != branches):
            raise em.Refusal('ANALOG_PRODUCER_BRANCH_CHANGED', binding['step_id'])
        if branches['design_verdict'] != 'PASS' and not (branches.get('complete') and producer.get('design_verdict') == 'PASS'):
            raise em.Refusal('GATE_FAIL' if branches['design_verdict'] == 'FAIL'
                             else 'GATE_NOT_MEASURED', 'complete producer work: ' + binding['step_id'])
    products = manifest.get('products')
    if not isinstance(products, dict) or not products:
        raise em.Refusal('ANALOG_SUBSTANTIVE_OUTPUT_MISSING', binding['step_id'])
    allowed = tuple(producer['adoption_paths'])
    for rel, expected in products.items():
        em._relative(rel)
        path = outputs / 'project' / rel
        if (not covered(rel, allowed) or path.is_symlink() or not path.is_file()
                or em.digest(path) != expected):
            raise em.Refusal('ANALOG_PRODUCT_CHANGED', rel)
    _substance(outputs / 'project', binding['step_id'], producer['blocks'])


def _substance(project: Path, step: str, blocks: list[str]) -> None:
    for expr in CONTRACTS[step]['canonical_row']['required_outputs']:
        if not any(any(p.is_file() and p.stat().st_size for p in project.glob(alt.strip()))
                   for alt in expr.split(' OR ')):
            raise em.Refusal('ANALOG_SUBSTANTIVE_OUTPUT_MISSING', expr)
    if step == 'A1':
        for block in blocks:
            candidates = [project / f'{phase}/analog/{block}/spec.json' for phase in ('phase3', 'phase1')]
            path = next((p for p in candidates if p.is_file()), candidates[0])
            data = checked_json(path)
            provenance = data.get('_provenance') or {}
            if (not data.get('specs') or provenance.get('fields_defaulted') != []
                    or not (provenance.get('input') or {}).get('sha256')):
                raise em.Refusal('ANALOG_SPEC_NOT_DOCUMENT_BOUND', block)
    if step in ('A3', 'A4', 'A7', 'A8'):
        for block in blocks:
            # Keep upstream/default/stub disclosure; do not upgrade it through
            # the new protocol even when a structural legacy gate returns 0.
            for name in ('netlist_provenance.json', 'corner_results.json', 'pre_vs_post.json'):
                path = project / f'phase3/analog/{block}/{name}'
                if path.is_file():
                    data = checked_json(path)
                    text = json.dumps(data).lower()
                    if 'deterministic_stub' in text or 'structure_only' in text or 'library_default' in text:
                        raise em.Refusal('ANALOG_STRUCTURE_ONLY_NOT_DESIGN_PASS', str(path))
    if step == 'A8':
        for block in blocks:
            hdir = project / f'phase3/analog/hardmacro/{block}'
            if (hdir / 'characterization.json').is_file():
                doc = checked_json(hdir / 'characterization.json')
                if not doc.get('measurements') or doc.get('native_engine') != 'ngspice':
                    raise em.Refusal('ANALOG_LIBERTY_UNCHARACTERIZED', block)
            elif 'interface_timing : false' not in (hdir / f'{block}.lib').read_text():
                raise em.Refusal('ANALOG_UNDECLARED_LIBERTY_TIMING', block)


def validate_outputs(outputs: Path, binding: dict) -> em.Evidence:
    gates = {name: 'NOT_MEASURED' for name in binding['required_gates']}
    result, manifest = checked_json(outputs / 'producer.json'), checked_json(outputs / 'products.json')
    verdict = result.get('design_verdict', 'NOT_MEASURED')
    issued, issued_sha = None, None
    report_path = outputs / 'canonical-gates.json'
    try:
        validate_products(outputs, binding, result, manifest)
        if result.get('native'):
            launch = checked_json(outputs / 'native-launch.json')
            if launch.get('binding') != binding or not launch.get('producer_pid'):
                raise em.Refusal('ANALOG_NATIVE_LAUNCH_NOT_BOUND', binding['step_id'])
            for name in ('native-processes.jsonl',):
                path = outputs / name
                if not path.is_file() or not path.stat().st_size:
                    raise em.Refusal('ANALOG_NATIVE_RAW_RECEIPTS_MISSING', name)
        if not report_path.is_file() or report_path.is_symlink():
            raise em.Refusal('ANALOG_CANONICAL_REPORT_UNBOUND', str(report_path))
        issued_sha = em.digest(report_path)
        issued = read_canonical_report(outputs, binding, expected_sha256=issued_sha)
        # Revalidation must not rewrite PID-bearing issued bytes or their SHA.
        # Keep the new real observations in a separate persistent audit view.
        audit = outputs.parent / ('analog-validation-' + uuid.uuid4().hex)
        audit.mkdir()
        project = audit / 'project'
        shutil.copytree(outputs / 'project', project)
        observation = retain_producer_observation(
            _m1_observation(outputs, binding, result['calls']), audit)
        fresh = semantic_gates(binding['step_id'], project, audit / 'gates',
                               producer_observation=observation)
        current = canonical_report(fresh, binding, project, audit,
                                   issued['source_files'], result['design_verdict'],
                                   producer_work=issued.get('producer_work'))
        write_json(audit / 'canonical-gates.json', current)
        gates.update(current['gates'])
        verdict = current['steps'][0]['status']
        if result['design_verdict'] == 'FAIL':
            verdict = 'FAIL'
        if verdict == 'PASS':
            report_obligations(current, binding, project)
            report_obligations(issued, binding, outputs / 'project')
            # Evidence describes the immutable issued report. Fresh advisory
            # observations remain lossless in the audit report above; their
            # changing PIDs or nonblocking values cannot rewrite that report.
            gates = dict(issued['gates'])
        for rel, expected in manifest['products'].items():
            if em.digest(project / rel) != expected:
                raise em.Refusal('ANALOG_CONSUMER_REWROTE_SELECTED_PRODUCT', rel)
        read_canonical_report(outputs, binding, expected_sha256=issued_sha)
    except em.Refusal as exc:
        verdict = 'FAIL' if verdict == 'FAIL' or exc.code in (
            'GATE_FAIL', 'ANALOG_STRUCTURE_ONLY_NOT_DESIGN_PASS', 'ANALOG_MIXED_SUBSTANCE_FAIL') else 'NOT_MEASURED'
    output_hashes = {'producer.json': em.digest(outputs / 'producer.json'),
                     'products.json': em.digest(outputs / 'products.json')}
    output_hashes.update({'project/' + k: v for k, v in manifest.get('products', {}).items()})
    if report_path.is_file() and not report_path.is_symlink():
        output_hashes['canonical-gates.json'] = issued_sha or em.digest(report_path)
    if issued is not None:
        output_hashes.update(issued['raw_files'])
    if result.get('native'):
        for name in ('native-launch.json', 'native-processes.jsonl',
                     'producer-work.json', 'producer-calls/calls.json'):
            path = outputs / name
            if path.is_file():
                output_hashes[name] = em.digest(path)
    for row in gate_specs(binding['step_id']):
        if row['kind'] != 'program_exit_zero':
            continue
        name = row['command'].split()[0]
        path = outputs / 'observed-gates' / (name + '.json')
        if path.is_file():
            observation = checked_json(path)
            status = _gate_status(observation.get('rc'), observation.get('report', {}))
            if observation.get('binding') != binding:
                status = 'NOT_MEASURED'
            if status == 'FAIL':
                verdict = 'FAIL'; gates[name] = 'FAIL'
            elif status != 'PASS' and verdict != 'FAIL':
                verdict = 'NOT_MEASURED'; gates[name] = 'NOT_MEASURED'
        elif verdict != 'FAIL':
            verdict = 'NOT_MEASURED'
    for path in (outputs / 'observed-gates').glob('*.json'):
        if path.is_file() and not path.is_symlink():
            output_hashes[str(path.relative_to(outputs))] = em.digest(path)
    return em.Evidence(binding, verdict, gates, output_hashes,
                       {'canonical_evidence': 1.0 if verdict == 'PASS' else 0.0,
                        'products': len(manifest.get('products', {}))},
                       detail=json.dumps({'canonical_gate_report': 'canonical-gates.json',
                           'sha256': output_hashes.get('canonical-gates.json')}, sort_keys=True))


def execute(inputs: Path, outputs: Path, native_local=False, *, source_files=None) -> dict:
    # Existing Controller supplies integrity data, not transferable authority.
    # The exec worker has neither the parent's ledger nor the live CLI FD.
    binding = json.loads(os.environ['VIBEIC_EXECUTION_BINDING'])
    objective = binding['objective']
    from execution_adapters_analog import component_sources
    source_files = source_files if source_files is not None else component_sources()
    spec = dict(step_id=binding['step_id'], source_sha=binding['source_sha'],
                source_files=source_files, parameters=objective['parameters'],
                input_hashes=binding['inputs'], blocks=objective['blocks'],
                producer_work_contract=producer_work_contract(binding['step_id']),
                adoption_paths=('phase3/analog', 'phase3/librelane/analog'))
    if native_local or spec['step_id'] not in ('A6', 'A7', 'A8'):
        raise em.Refusal('ANALOG_PASSIVE_COMPONENT_REQUIRED', spec['step_id'])
    if (em._hash(spec['parameters']) != objective['parameters_sha256']
            or em._hash(spec['source_files']) != objective['source_manifest_sha256']
            or {name: value for name, value in hashes(inputs).items()
                    if inputs / name != em.issued_manifest_path(inputs)} != spec['input_hashes']):
        raise em.Refusal('ANALOG_WORKER_INPUT_POPULATION_CHANGED', str(inputs))
    for name, expected in spec['source_files'].items():
        path = Path(name)
        if not path.is_file() or path.is_symlink() or em.digest(path) != expected:
            raise em.Refusal('ADAPTER_SOURCE_MISMATCH', name)
    from execution_analog_installation import worker_parameters
    spec['parameters'] = worker_parameters(inputs, binding, spec['parameters'])
    # Capability locators are not native-process environment variables.
    for name in ('VIBEIC_EXECUTION_CAP_FD', 'VIBEIC_EXECUTION_AUTH_SOCKET',
                 'VIBEIC_EXECUTION_REQUEST'):
        os.environ.pop(name, None)
    project = outputs / 'project'
    if project.exists():
        raise em.Refusal('ANALOG_WORKER_OUTPUT_REUSED', str(project))
    project.mkdir()
    for name, expected in spec['input_hashes'].items():
        target = project / em._relative(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(inputs / name, target)
    before = hashes(project)
    records = outputs / 'producer-calls'
    calls = native_produce(inputs, project, spec, records)
    work = producer_work(calls, binding, spec['source_files'])
    write_json(outputs / 'producer-work.json', work)
    processes = records / 'native-processes.jsonl'
    if processes.is_file():
        shutil.copyfile(processes, outputs / 'native-processes.jsonl')
    write_json(outputs / 'native-launch.json', dict(binding=binding,
        producer_pid=os.getpid(), image_id=spec['parameters']['image_id'],
        scope='passive source component; parent alone authenticates completion'))
    products = {k: v for k, v in hashes(project).items() if before.get(k) != v
                and covered(k, tuple(spec['adoption_paths']))}
    gates = semantic_gates(spec['step_id'], project, outputs / 'producer-gates', canonical=True)
    verdict = work['design_verdict']
    # rc0 is only a completion fact. A8 has no producer verdict field: require
    # every complementary call, substantive fresh products, raw observations
    # and all actual canonical gates before deriving design PASS.
    if (verdict != 'FAIL' and work['complete'] and products and processes.is_file()
            and processes.stat().st_size and all(c.get('rc', 0) == 0 for c in calls)
            and gates['blocking'] and all(v == 'PASS' for v in gates['blocking'].values())):
        verdict = 'PASS'
    report = canonical_report(gates, binding, project, outputs, spec['source_files'], verdict,
                              producer_work=work)
    verdict = report['steps'][0]['status']
    producer = dict(binding=binding, step_id=spec['step_id'], source_sha=spec['source_sha'],
        blocks=spec['blocks'], adoption_paths=spec['adoption_paths'], design_verdict=verdict,
        calls=calls, dispatch=[], gates=gates, external=gates['external'], native=True,
        qualification_is_design_pass=False)
    write_json(outputs / 'producer.json', producer)
    write_json(outputs / 'products.json', dict(binding=binding, products=products))
    write_json(outputs / 'canonical-gates.json', report)
    return producer


def observe_gate(outputs: Path, gate: str) -> dict:
    binding = json.loads(os.environ['VIBEIC_EXECUTION_BINDING'])
    declared = {row['command'].split()[0] for row in gate_specs(binding['step_id'])}
    if gate not in declared or gate not in binding['required_gates']:
        raise em.Refusal('ANALOG_GATE_COMPONENT_UNBOUND', gate)
    directory = outputs / 'observed-gates'
    directory.mkdir(parents=True, exist_ok=True)
    report = directory / (gate + '.report.json')
    command = [str(Path(sys.executable).resolve()), str(PROGRAMS / (gate + '.py')),
               str(outputs / 'project'), '--json', str(report)]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True,
        env={k: v for k, v in os.environ.items() if not k.startswith('VIBEIC_EXECUTION')})
    try:
        stdout, stderr = process.communicate(timeout=120)
        rc = process.returncode
    except subprocess.TimeoutExpired:
        import signal
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        rc = None
    record = dict(binding=binding, argv=command, pid=process.pid, rc=rc,
        report=checked_json(report) if report.is_file() else {}, stdout=stdout, stderr=stderr,
        program_sha256=em.digest(PROGRAMS / (gate + '.py')))
    write_json(directory / (gate + '.json'), record)
    return record


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path)
    parser.add_argument('--outputs', type=Path, required=True)
    parser.add_argument('--native-local', action='store_true')
    parser.add_argument('--observe-gate')
    args = parser.parse_args(argv)
    try:
        if args.observe_gate:
            observe_gate(args.outputs.resolve(), args.observe_gate)
            return 0  # actual gate verdict remains in the bound raw report
        if args.inputs is None:
            raise em.Refusal('ANALOG_FROZEN_INPUTS_REQUIRED', str(args.outputs))
        result = execute(args.inputs.resolve(), args.outputs.resolve(), args.native_local)
        print(json.dumps({'design_verdict': result['design_verdict']}))
        return 0  # worker protocol completed; the parent reconsumes real gates
    except (em.Refusal, OSError, ValueError, KeyError, TypeError) as exc:
        write_json(args.outputs / 'worker-refusal.json', {'status': 'NOT_MEASURED', 'detail': str(exc)})
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
