"""Normal area-basis dispatch; transparent technology/transport SOFTWARE fixtures."""
import copy
import json
from pathlib import Path

import pytest
import execution_policy as policy
import phase1_one_shot_runner as owner
import phase1_doc_one_shot_runner as docs
import area_budget_basis_gen as area
import _tapeout_declaration as td
from programs.tests._route_fixture import stage_owner_route
from _hostpaths import require_repo

KEY = 'synthesis_area_budget'


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + '\n')


def subject(project, *, record='program', text=None):
    source = project / 'input/docs/L9_CONSTRAINTS.md'
    source.parent.mkdir(parents=True, exist_ok=True)
    if text is None:
        text = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs', 'tests',
                            'fixtures', 'phase1_local', 'core_die_role_preservation',
                            'L9_CONSTRAINTS.md').read_text()
    source.write_text(text)
    doc = {'schema': 'vibe-ic/step_0_5ic_answers/1',
           'answers': {'deliverable': 'DIE', 'top_cell': 'neutral_top'},
           'operator_template': {'absent_reason': 'Neutral software input explicitly supplies no operator template or purchased shuttle slot.'},
           'answer_provenance': {'deliverable': {'answered_by': 'owner', 'citation': 'Neutral owner selects DIE delivery, not numerical dimensions.'},
                                 'top_cell': {'answered_by': 'owner', 'citation': 'Neutral owner names the top cell.'}}}
    if record:
        doc['answers'][KEY] = {'status': 'LIMIT', 'max_die_dimensions_um': [1300, 1300]}
        doc['answer_provenance'][KEY] = ({'answered_by': 'program', 'producer': area.PROGRAM,
            'derived_from_attested': {'deliverable': 'DIE'}, 'inputs': ['input/docs/L9_CONSTRAINTS.md'],
            'inputs_sha256': td.derived_inputs_sha256(project, ['input/docs/L9_CONSTRAINTS.md'])}
            if record == 'program' else {'answered_by': 'owner', 'citation': 'Neutral owner explicitly sets this numeric outer DIE limit.'})
    path = project / 'input/step_0_5ic_answers.json'
    put(path, doc)
    stage_owner_route(project, 'ic')
    policy.bootstrap(project, parameters={'skip_analog': True}, phase1_only=True)
    return path, doc


def normal_caller(project, monkeypatch, *, merged_input=None, fault_rc=None):
    """Actual dispatcher/ABG/ingest/transcriber/declaration, no native probes.

    Fetch is an explicitly UNAVAILABLE technology fixture. Second-site tests
    stage a historical merged-input transport carrier after the real answer
    transcription; no declaration output or producer result is mocked.
    """
    callbacks, area_calls = [], []
    real_transport = owner._wd.run_host_supervised
    real_area = area.main

    def transport(argv, **kwargs):
        name = Path(argv[1]).name
        callbacks.append(name)
        if name == 'submission_template_fetch.py':
            put(project / owner._ST_FETCH_REPORT_REL, {
                'scope': 'SOFTWARE_UNAVAILABLE_TECHNOLOGY_FIXTURE', 'technology': {}})
            return owner._wd.SupervisedResult(0, 'SOFTWARE: no technology measurement\n', '', 'natural')
        result = real_transport(argv, **kwargs)
        if name == 'submission_template_answers.py' and merged_input is not None:
            put(project / owner._MERGED_ANSWERS_REL, merged_input)
        return result

    def actual_area(argv):
        path = Path(argv[argv.index('--answers') + 1])
        before = json.loads(path.read_text())
        rc = real_area(argv) if fault_rc is None else fault_rc
        area_calls.append({'path': str(path.relative_to(project)), 'before': before,
                           'after': json.loads(path.read_text()), 'rc': rc})
        return rc

    monkeypatch.setattr(owner._wd, 'run_host_supervised', transport)
    monkeypatch.setattr(area, 'main', actual_area)
    rc = owner._run_step_0_5ic(project)
    return rc, callbacks, area_calls


def current_l19(project):
    path = project / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json'
    put(path, {'doc_id': 'L19', 'fields': {'die_area_budget_um': None,
          'floorplan_hints': [], 'constraints_present': False}})
    docs._post_emit_floorplan_contract(project)
    return json.loads(path.read_text())


def without_area(doc):
    doc = copy.deepcopy(doc)
    doc.get('answers', {}).pop(KEY, None)
    doc.pop(KEY, None)
    doc.get('answer_provenance', {}).pop(KEY, None)
    doc.pop('answer_revisions', None)
    return doc


@pytest.mark.parametrize('seam', ['design_before_answers', 'merged_before_declaration'])
def test_actual_owner_withdraws_stale_program_limit_before_l19(tmp_path, monkeypatch, seam):
    project = tmp_path / 'subject'
    path, stale = subject(project)
    merged = None
    if seam == 'merged_before_declaration':
        # First seam has no program derivation. Historical merged source is
        # an explicit TEST_ONLY input carrier for the second real caller seam.
        clean = without_area(stale)
        put(path, clean)
        merged = stale
    before = json.loads(path.read_text())
    rc, callbacks, calls = normal_caller(project, monkeypatch, merged_input=merged)
    declaration = td.load(project / td.DECLARATION_REL)[0]
    l19 = current_l19(project)
    observed = {'scope': 'SOFTWARE_NORMAL_CALLER', 'seam': seam, 'caller_rc': rc,
                'callbacks': callbacks, 'area_calls': calls, 'declaration': declaration, 'l19': l19}
    (tmp_path / 'OBSERVATION.json').write_text(json.dumps(observed, indent=2))
    assert td.area_budget_resolution(declaration)['status'] == 'UNSET', observed
    assert td.answer(declaration, KEY) == td.NOT_DETERMINED
    assert l19['fields']['die_area_budget_um'] is None
    assert len(calls) == 1 and calls[0]['rc'] == 2
    expected_source = (owner._ST.DESIGN_ANSWERS_REL if seam == 'design_before_answers'
                       else owner._MERGED_ANSWERS_REL)
    assert calls[0]['path'] == expected_source
    assert without_area(json.loads(path.read_text())) == without_area(before)
    assert 'tapeout_declaration_gen.py' in callbacks


def test_owner_numeric_answer_and_route_are_not_rederived(tmp_path, monkeypatch):
    project = tmp_path / 'subject'
    path, doc = subject(project, record='owner')
    before = path.read_bytes()
    _, _, calls = normal_caller(project, monkeypatch)
    assert calls == []
    assert path.read_bytes() == before
    assert td.answer(td.load(project / td.DECLARATION_REL)[0], KEY) == doc['answers'][KEY]


def test_absent_unknown_record_does_not_dispatch_or_write_a_derivation(tmp_path, monkeypatch):
    project = tmp_path / 'subject'
    path, _ = subject(project, record=None)
    before = path.read_bytes()
    _, _, calls = normal_caller(project, monkeypatch)
    assert calls == [] and path.read_bytes() == before
    assert td.area_budget_resolution(td.load(project / td.DECLARATION_REL)[0])['status'] == 'UNSET'
    assert not (project / 'reports/phase1/area_budget_basis_design.json').exists()
    assert not (project / 'reports/phase1/area_budget_basis.json').exists()


def test_stable_valid_program_record_is_not_rewritten(tmp_path, monkeypatch):
    project = tmp_path / 'subject'
    path, _ = subject(project, record=None, text='Outer die hard limit: 1600 x 1500 um.\n')
    assert area.main([str(project)]) == 0
    before, mtime = path.read_bytes(), path.stat().st_mtime_ns
    _, _, calls = normal_caller(project, monkeypatch)
    assert path.read_bytes() == before and path.stat().st_mtime_ns == mtime
    assert all(call['before'] == call['after'] for call in calls)
    assert td.answer(td.load(project / td.DECLARATION_REL)[0], KEY)['max_die_dimensions_um'] == [1600, 1500]


def test_actual_withdrawal_error_stops_dependent_producers(tmp_path, monkeypatch):
    project = tmp_path / 'subject'
    path, _ = subject(project)
    before = path.read_bytes()
    rc, callbacks, calls = normal_caller(project, monkeypatch, fault_rc=1)
    assert (rc, len(calls)) == (1, 1)
    assert path.read_bytes() == before
    assert 'submission_template_answers.py' not in callbacks
    assert 'tapeout_declaration_gen.py' not in callbacks
