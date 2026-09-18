#!/usr/bin/env python3
"""vibe-ic — a spare-cell PASS whose keep-attribute half never ran (#562).

`evaluate_preservation` returns PASS iff nothing was removed AND every survivor
carries its keep attribute. The second half only runs when some artefact CAN
carry that attribute; when none can, `all_keep_attr_intact` is vacuously true and
the PASS is indistinguishable on paper from one that checked and found everything
tagged.

That is the shape this whole issue is about — an absence rendering as a pass — so
the rule re-adjudicates it to VACUOUS_PASS rather than leaving a reader to infer
it from a field they would have to know to look for.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"scp_{name}", PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"scp_{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


S = _load("spare_cell_preservation_check")


def _decide(record):
    return S.RECORD_ADJUDICATION.rules[0].decide(record)


def test_a_pass_whose_keep_check_never_ran_is_superseded():
    """THE defect: PASS on a run where no artefact could carry a keep attribute."""
    sup = _decide({"verdict": "PASS", "keep_check_applied": False})
    assert sup is not None, "a vacuous PASS was left standing"
    assert sup.would_issue == "VACUOUS_PASS"
    assert "keep_check_applied" in sup.because


def test_a_pass_that_DID_check_still_stands():
    """The rule must not supersede a real PASS — otherwise every preserved run
    becomes debt and the register stops meaning anything."""
    assert _decide({"verdict": "PASS", "keep_check_applied": True}) is None


def test_a_fail_is_left_alone():
    """Only a PASS can over-claim; a FAIL already says less than it proved."""
    for v in ("FAIL", "VACUOUS_PASS", "SKIPPED-CONDITION"):
        assert _decide({"verdict": v, "keep_check_applied": False}) is None, v


def test_the_rule_requires_both_fields_it_reads():
    """`requires` makes undecidability explicit: a record lacking these is
    reported UNDECIDABLE rather than quietly passed over, and `decide` is only
    called once both are present."""
    assert set(S.RECORD_ADJUDICATION.rules[0].requires) == {
        "verdict", "keep_check_applied"}


def test_the_declaration_points_at_the_function_that_decides():
    """A declaration aimed at the wrong function fingerprints someone else's
    logic — and aimed at `main` it would fingerprint the whole CLI, so an
    unrelated flag would report RULES_UNREVIEWED and train the guard to be
    ignored."""
    d = S.RECORD_ADJUDICATION
    assert d.gate == "spare_cell_preservation_check"
    assert d.decision_roots == ("evaluate_preservation",)
    assert hasattr(S, "evaluate_preservation")


def test_the_digest_is_a_real_fingerprint():
    """An empty digest makes the drift guard silently useless: it would never
    report RULES_UNREVIEWED, so a verdict change could land with the rules never
    re-read."""
    d = S.RECORD_ADJUDICATION.decision_digest
    assert len(d) == 64 and all(c in "0123456789abcdef" for c in d), d


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))

# Input-derived producer evidence: an insertion obligation is not an IO plan.
# All files here are neutral synthetic inputs; no native EDA or design oracle.
def _insertion_project(tmp_path, fault=None):
    import hashlib
    import json
    pnr = tmp_path / 'phase3/stage3/pnr'
    pnr.mkdir(parents=True)
    wrapper = pnr / 'chip_top_io.v'
    wrapper.write_text('module neutral(); core logic0(); endmodule\n')
    names = [f'reserve_{i}' for i in range(6)]
    optional = ['future_alpha', 'future_beta']  # no pad/name heuristics
    plan = {'count': 6, 'instances': [{'name': n, 'type': 'inverter'} for n in names],
            'spare_pads': [{'name': n, 'kind': 'input'} for n in optional],
            'insertion_observed': {'observed': True, 'markers': ['SPARE_FIRM_LOCKED']},
            'insertion_provenance': {
                'version': 1, 'status': 'OBSERVED',
                'required_insertions': names[:],
                'planned_not_inserted': optional[:],
                'wrapper': {'path': 'phase3/stage3/pnr/chip_top_io.v',
                            'read_status': 'READ',
                            'sha256': hashlib.sha256(wrapper.read_bytes()).hexdigest()}}}
    present = names[:]
    if fault in ('removed', 'false_exclusion'):
        present.remove(names[0])
    if fault == 'false_exclusion':
        plan['insertion_provenance']['planned_not_inserted'].append(names[0])
        plan['insertion_provenance']['required_insertions'].remove(names[0])
    elif fault == 'missing_provenance':
        del plan['insertion_provenance']
    elif fault == 'comment_only':
        wrapper.write_text('// module neutral(); endmodule\n')
        plan['insertion_provenance']['wrapper']['sha256'] = hashlib.sha256(wrapper.read_bytes()).hexdigest()
    elif fault == 'malformed_row':
        plan['spare_pads'].append(None)
    elif fault == 'missing_source':
        wrapper.unlink()
    elif fault == 'empty_source':
        wrapper.write_text('')
        plan['insertion_provenance']['wrapper']['sha256'] = hashlib.sha256(b'').hexdigest()
    elif fault == 'wrong_hash':
        plan['insertion_provenance']['wrapper']['sha256'] = '0' * 64
    elif fault == 'unreadable_source':
        wrapper.unlink()
        wrapper.mkdir()
    elif fault == 'wrapper_contradiction':
        wrapper.write_text('module neutral(); pad future_alpha(); endmodule\n')
        plan['insertion_provenance']['wrapper']['sha256'] = hashlib.sha256(wrapper.read_bytes()).hexdigest()
    elif fault == 'final_contradiction':
        present.append(optional[0])
    elif fault == 'duplicate':
        plan['insertion_provenance']['planned_not_inserted'].append(optional[0])
    elif fault == 'unknown_name':
        plan['insertion_provenance']['planned_not_inserted'].append('unrecorded')
    elif fault in ('inserted_pad', 'removed_pad'):
        wrapper.write_text('module neutral(); pad future_alpha(); endmodule\n')
        prov = plan['insertion_provenance']
        prov['wrapper']['sha256'] = hashlib.sha256(wrapper.read_bytes()).hexdigest()
        prov['planned_not_inserted'].remove(optional[0])
        prov['required_insertions'].append(optional[0])
        if fault == 'inserted_pad':
            present.append(optional[0])
    (pnr / 'spare_cells.json').write_text(json.dumps(plan))
    (pnr / 'neutral_pnr.v').write_text('module neutral();\n' + ''.join(
        f'(* keep = 1 *) cell {n} ();\n' for n in present) + 'endmodule\n')
    (pnr / 'routed.def').write_text('DESIGN neutral ;\nCOMPONENTS %d ;\n' % len(present)
        + ''.join(f'- {n} cell + FIXED ( 0 0 ) N ;\n' for n in present)
        + 'END COMPONENTS\nEND DESIGN\n')
    return tmp_path


def test_planned_only_names_are_not_deleted_instances(tmp_path):
    project = _insertion_project(tmp_path)
    assert S.main([str(project)]) == 0
    result = S.audit(project)
    assert result['verdict'] == 'PASS'
    assert result['inserted'] == result['survived'] == 6
    assert result['removed'] == []
    assert result['insertion_provenance']['planned_not_inserted'] == ['future_alpha', 'future_beta']


@pytest.mark.parametrize('fault', ['removed', 'false_exclusion', 'missing_provenance',
    'missing_source', 'empty_source', 'wrong_hash', 'unreadable_source',
    'wrapper_contradiction', 'final_contradiction', 'duplicate', 'unknown_name', 'removed_pad', 'comment_only', 'malformed_row'])
def test_insertion_provenance_bad_inputs_remain_refused(tmp_path, fault):
    project = _insertion_project(tmp_path, fault)
    result = S.audit(project)
    assert result['verdict'] == 'FAIL'
    assert S.main([str(project)]) == 1
    if fault in ('removed', 'false_exclusion'):
        assert any(x['name'] == 'reserve_0' for x in result['removed'])
    elif fault == 'removed_pad':
        assert any(x['name'] == 'future_alpha' for x in result['removed'])
    else:
        assert result.get('insertion_provenance', {}).get('status') != 'VERIFIED'


def test_actually_inserted_pad_is_kept_in_inventory(tmp_path):
    project = _insertion_project(tmp_path, 'inserted_pad')
    result = S.audit(project)
    assert result['verdict'] == 'PASS'
    assert result['inserted'] == result['survived'] == 7
    assert result['insertion_provenance']['planned_not_inserted'] == ['future_beta']


def _run_actual_provenance_call(project, plan):
    import ast
    import phase3_one_shot_runner as R
    tree = ast.parse((PROGRAMS / 'phase3_one_shot_runner.py').read_text())
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                and isinstance(n.value, ast.Call)
                and isinstance(n.value.func, ast.Name)
                and n.value.func.id == '_spare_insertion_provenance')
    block = ast.Module(body=[node], type_ignores=[])
    exec(compile(block, 'runner-provenance-call', 'exec'), {
        'spare_plan': plan, 'out_dir': project / 'phase3/stage3/pnr',
        '_spare_insertion_provenance': R._spare_insertion_provenance})
    return R


def test_producer_record_reaches_owning_consumer(tmp_path):
    import json
    project = _insertion_project(tmp_path)
    pnr = project / 'phase3/stage3/pnr'
    plan = json.loads((pnr / 'spare_cells.json').read_text())
    del plan['insertion_provenance']
    R = _run_actual_provenance_call(project, plan)
    log = pnr / 'insertion.log'
    log.write_text('SPARE_FIRM_LOCKED: 6 instances\nSPARE_TIEOFF_CONNECTED 6 of 6\n')
    _note, written = R._emit_step18_spare_record(project, pnr, log, plan, 300, .02, '')
    assert written
    saved = json.loads((pnr / 'spare_cells.json').read_text())
    assert saved['insertion_provenance'] == plan['insertion_provenance']
    assert S.audit(project)['verdict'] == 'PASS'


def test_no_optional_plan_needs_no_wrapper_provenance(tmp_path):
    import json
    project = _insertion_project(tmp_path)
    pnr = project / 'phase3/stage3/pnr'
    plan = json.loads((pnr / 'spare_cells.json').read_text())
    plan['spare_pads'] = []
    del plan['insertion_provenance']
    (pnr / 'chip_top_io.v').unlink()
    _run_actual_provenance_call(project, plan)
    (pnr / 'spare_cells.json').write_text(json.dumps(plan))
    assert S.main([str(project)]) == 0


def test_inserted_pad_disagreement_is_not_exempt(tmp_path):
    project = _insertion_project(tmp_path, 'inserted_pad')
    d = project / 'phase3/stage3/pnr/routed.def'
    d.write_text(d.read_text().replace('- future_alpha cell + FIXED ( 0 0 ) N ;\n', ''))
    result = S.audit(project)
    assert result['verdict'] == 'FAIL'
    assert any('future_alpha' in x['spares'] for x in result['artefact_agreement']['disagreements'])
