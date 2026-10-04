"""Existing analog canonical gate population and evidence consumers.

Port only the donor's domain-required contract helpers; no execution issuer.
"""
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
from pathlib import Path
import shlex
import execution_modes as em

def _canonical_gate_clauses(step_id: str) -> dict:
    import _flow_yaml
    declared = next((item for item in _flow_yaml.load()['steps']
                     if str(item['id']) == step_id), None)
    if declared is None:
        raise em.Refusal('UNKNOWN_CANONICAL_STEP', step_id)
    rules = {}
    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for key in ('all_of', 'any_of'):
                if isinstance(node.get(key), (dict, list)):
                    walk(node[key])
            for kind in ('program_exit_zero', 'optional_program_exit_zero',
                         'advisory_program_exit_zero'):
                if kind not in node:
                    continue
                spec = node[kind]
                spec = {'command': spec} if isinstance(spec, str) else spec
                if not isinstance(spec, dict) or not isinstance(spec.get('command'), str):
                    raise em.Refusal('CANONICAL_GATE_MALFORMED', step_id)
                tokens = shlex.split(spec['command'])
                if not tokens:
                    raise em.Refusal('CANONICAL_GATE_MALFORMED', step_id)
                rules.setdefault(Path(tokens[0]).stem, []).append((kind, spec))
    walk(declared['gate'])
    return rules


def canonical_gate_population(step_id: str, additional: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Full source-owned coverage, independently of current applicability.

    Factories declare this population at prepare, then produce lossless actual
    dispositions. No caller can remove a mandatory/advisory/optional clause.
    """
    row = next((item for item in em.load_portfolio()['steps'] if item['id'] == step_id), None)
    if row is None:
        raise em.Refusal('UNKNOWN_CANONICAL_STEP', step_id)
    return tuple(dict.fromkeys((*row['mandatory_gate_programs'],
                               *_canonical_gate_clauses(step_id), *additional)))


def canonical_gate_obligations(step_id: str, required: tuple[str, ...], gates: dict,
                               report: dict, *, project: Path | None = None,
                               _program_records: list | None = None) -> tuple[str, ...]:
    """Blocking view of a bound current canonical report; values stay intact.

    Conditional absence is checked against the real bound project, using only
    source-owned conditions. Actual advisory records retain rc/verdict/reason;
    a live refusal steps aside only on the canonical two-source agreement.
    Missing records, unknown enforcement and actual aggregate FAIL refuse.
    """
    import flow_compliance_check as compliance
    if not isinstance(report, dict) or not isinstance(gates, dict):
        raise em.Refusal('GATE_NOT_MEASURED', 'canonical disposition missing')
    rows = report.get('steps', ())
    matched_rows = [item for item in rows if isinstance(item, dict)
                    and str(item.get('id')) == step_id] if isinstance(rows, (list, tuple)) else []
    if len(matched_rows) != 1 or matched_rows[0].get('status') not in ('PASS', 'FAIL'):
        raise em.Refusal('GATE_NOT_MEASURED', 'current canonical step disposition missing')
    row = matched_rows[0]
    if row['status'] == 'FAIL':
        raise em.Refusal('GATE_FAIL', step_id)
    rules = _canonical_gate_clauses(step_id)
    if not set(rules).issubset(required):
        raise em.Refusal('REQUIRED_GATES_DROPPED', step_id)
    records = row.get('advisory_gate_records', [])
    if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
        raise em.Refusal('GATE_NOT_MEASURED', 'invalid actual advisory records')
    blocking = []
    def executed(command, *, absent=False, advisory=None):
        if _program_records is None:
            return
        actual = [item for item in _program_records if item['cmd'] == command]
        if absent:
            if actual:
                raise em.Refusal('EVIDENCE_UNBOUND', 'absent clause reported execution: ' + command)
            return
        if len(actual) != 1:
            raise em.Refusal('GATE_NOT_MEASURED', 'canonical execution missing or duplicated: ' + command)
        observed = actual[0]
        if advisory is not None:
            if any(observed.get(key) != advisory.get(key)
                   for key in ('verdict', 'exit_code', 'structured_verdict', 'reason_class')):
                raise em.Refusal('EVIDENCE_UNBOUND', 'advisory execution record changed: ' + command)
        elif observed['verdict'] != 'PASS' or observed['exit_code'] != 0:
            raise em.Refusal('GATE_FAIL' if observed['verdict'] == 'FAIL'
                             else 'GATE_NOT_MEASURED', command)
    for name in required:
        clauses = rules.get(name, [])
        if not clauses or any(kind == 'program_exit_zero' for kind, _ in clauses):
            for kind, spec in clauses:
                if kind == 'program_exit_zero':
                    executed(spec['command'])
            blocking.append(name)
            continue
        observations = []
        for kind, spec in clauses:
            command = spec['command']
            patterns = spec.get('condition_files_exist')
            absent = False
            if patterns is not None:
                if (not isinstance(patterns, list) or not patterns
                        or any(not isinstance(pat, str) or not pat or Path(pat).is_absolute()
                               or '..' in Path(pat).parts for pat in patterns)
                        or project is None or not Path(project).is_dir()):
                    raise em.Refusal('GATE_NOT_MEASURED', 'conditional population unbound: ' + name)
                absent = not any(next(Path(project).glob(pat), None) is not None for pat in patterns)
            if absent:
                why = spec.get('absent_condition_reason')
                if not isinstance(why, str) or len(why.strip()) < compliance._MIN_ABSENT_CONDITION_REASON:
                    raise em.Refusal('GATE_NOT_MEASURED', 'conditional declaration missing: ' + name)
            if kind == 'optional_program_exit_zero':
                if not absent:
                    executed(command)
                    blocking.append(name)
                    break
                disclosures = row.get('declared_not_applicable', [])
                if (not isinstance(disclosures, list) or not any(isinstance(item, str)
                        and item.startswith(command + ' — condition_files_exist ')
                        and item.endswith('Declared not-applicable: ' + why.strip()) for item in disclosures)
                        or gates.get(name) not in ('NOT_MEASURED', 'NOT_APPLICABLE')):
                    raise em.Refusal('GATE_NOT_MEASURED', 'conditional disposition missing: ' + name)
                observations.append(dict(verdict='NOT_APPLICABLE', exit_code=None))
                executed(command, absent=True)
                continue
            matching = [record for record in records if record.get('gate') == name
                        and record.get('command') == command]
            if len(matching) != 1:
                raise em.Refusal('GATE_NOT_MEASURED', 'advisory disposition missing or duplicated: ' + name)
            record = matching[0]
            executed(command, absent=absent, advisory=record)
            enforcement, rc = record.get('enforcement'), record.get('exit_code')
            verdict = record.get('verdict')
            if not isinstance(verdict, str) or (rc is not None and type(rc) is not int):
                raise em.Refusal('GATE_NOT_MEASURED', 'advisory execution untyped: ' + name)
            norm = verdict.strip().upper().replace('_', '-')
            reason = compliance._reason_taxonomy.normalise(record.get('reason_class'))
            if absent:
                expected_reason = spec.get('absent_condition_reason_class', 'DESIGN_DECLARED_NA')
                if (enforcement != 'NOT_RUN_DECLARED' or verdict != 'NOT_APPLICABLE' or rc is not None
                        or reason != compliance._reason_taxonomy.normalise(expected_reason)
                        or reason not in compliance._reason_taxonomy.SKIP_ELIGIBLE):
                    raise em.Refusal('GATE_NOT_MEASURED', 'unbound conditional disposition: ' + name)
            elif enforcement == 'BLOCKING':
                if rc is None or not compliance._gate_is_two_source_advisory(name):
                    blocking.append(name)
                    break
            elif enforcement == 'DISCLOSED_INCOMPLETE':
                if (rc is None or (norm not in compliance._ADVISORY_INCOMPLETE_VERDICTS
                        and norm != 'BLOCKED' and reason not in compliance._reason_taxonomy.INCOMPLETE)
                        or (norm in compliance._ADVISORY_REFUSAL_VERDICTS
                            and reason != compliance._reason_taxonomy.ZERO_DENOMINATOR)):
                    raise em.Refusal('GATE_NOT_MEASURED', 'advisory incomplete disposition unbound: ' + name)
            elif enforcement == 'DISCLOSED_SKIP':
                if rc is None or norm not in compliance._ADVISORY_SKIP_VERDICTS or reason not in compliance._reason_taxonomy.SKIP_ELIGIBLE:
                    raise em.Refusal('GATE_NOT_MEASURED', 'advisory skip disposition unbound: ' + name)
            elif enforcement == 'PASSED':
                if rc != 0 or norm not in compliance._ADVISORY_PASS_VERDICTS:
                    raise em.Refusal('GATE_NOT_MEASURED', 'advisory pass disposition unbound: ' + name)
            elif enforcement == 'NON_BLOCKING_ADVISORY':
                if rc is None or not (norm in compliance._ADVISORY_NONBLOCKING_VERDICTS
                        or rc == 0 and norm not in compliance._ADVISORY_REFUSAL_VERDICTS):
                    raise em.Refusal('GATE_NOT_MEASURED', 'advisory disposition unbound: ' + name)
            else:
                raise em.Refusal('GATE_NOT_MEASURED', 'unknown advisory enforcement: ' + name)
            observations.append(record)
        else:
            # F2's measured_program_gates truthfully retains NOT_MEASURED for
            # an advisory FAIL under aggregate PASS. Its exact ledger-derived
            # projection is already checked by the semantic-report adapter.
            if _program_records is not None:
                continue
            expected = ('FAIL' if any(item.get('verdict') == 'FAIL' or item.get('exit_code') == 1
                                     for item in observations)
                        else 'PASS' if all(item.get('verdict') == 'PASS' and item.get('exit_code') == 0
                                          for item in observations) else 'NOT_MEASURED')
            if gates.get(name) != expected and not (expected == 'NOT_MEASURED'
                    and all(item.get('verdict') == 'NOT_APPLICABLE' for item in observations)
                    and gates.get(name) == 'NOT_APPLICABLE'):
                raise em.Refusal('EVIDENCE_UNBOUND', 'actual gate verdict changed: ' + name)
    return tuple(dict.fromkeys(blocking))
