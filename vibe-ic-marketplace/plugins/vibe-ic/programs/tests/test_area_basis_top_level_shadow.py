"""The canonical area producer must update the field its consumer reads."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest
import _plugin_tree  # noqa: F401
import area_budget_basis_gen as A

P = Path(__file__).resolve().parents[1]


def put(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + '\n')


def fixture(tmp_path, placement, owner=False):
    project = tmp_path / 'project'
    prose = project / 'input/docs/implementation.md'
    prose.parent.mkdir(parents=True)
    prose.write_text('The implementation selects die size 640 x 800 um.\n')
    old = {'status': 'LIMIT', 'max_die_dimensions_um': [320, 240]}
    doc = {'schema': 'vibe-ic/step_0_5ic_answers/1',
           'answers': {'deliverable': 'DIE'},
           'answer_provenance': {'deliverable': {
               'answered_by': 'owner',
               'citation': 'Neutral fixture owner requests standalone DIE.'}}}
    if placement in ('top', 'both'):
        doc['synthesis_area_budget'] = old
    if placement in ('answers', 'both'):
        doc['answers']['synthesis_area_budget'] = old
    if owner:
        doc['answer_provenance']['synthesis_area_budget'] = {
            'answered_by': 'owner', 'citation': 'Neutral owner explicitly fixed this area limit.'}
    answers = project / 'input/step_0_5ic_answers.json'
    put(answers, doc)
    return project, answers, prose


def cli(name, *args):
    return subprocess.run([sys.executable, str(P / name), *map(str, args)],
                          capture_output=True, text=True)


def consume(project):
    answers = project / 'input/step_0_5ic_answers.json'
    gen = cli('tapeout_declaration_gen.py', project, '--answers', answers)
    assert gen.returncode == 0, gen.stdout + gen.stderr
    return cli('tapeout_declaration_check.py', project, '--json', project / 'consumer.json')


@pytest.mark.parametrize('placement', ['top', 'answers', 'both'])
def test_real_producer_and_ordinary_consumer_agree_for_each_supported_location(tmp_path, placement):
    project, answers, _ = fixture(tmp_path, placement)
    report = project / 'area-producer.json'
    result = cli('area_budget_basis_gen.py', project, '--json', report)
    assert result.returncode == 0, result.stdout + result.stderr
    consumer = consume(project)
    assert consumer.returncode == 0, consumer.stdout + consumer.stderr
    doc = json.loads(answers.read_text())
    canonical = doc.get('synthesis_area_budget', doc['answers']['synthesis_area_budget'])
    assert canonical['max_die_dimensions_um'] == [640.0, 800.0]
    assert canonical == doc['answers']['synthesis_area_budget']
    assert json.loads(report.read_text())['other_contradictions'] == 0
    before = answers.read_bytes()
    again = cli('area_budget_basis_gen.py', project, '--json', report)
    assert again.returncode == 0, again.stdout + again.stderr
    assert json.loads(report.read_text())['status'] == 'UNCHANGED'
    assert hashlib.sha256(answers.read_bytes()).digest() == hashlib.sha256(before).digest()


@pytest.mark.parametrize('placement', ['top', 'answers', 'both'])
def test_owner_area_authority_is_never_overwritten(tmp_path, placement):
    project, answers, _ = fixture(tmp_path, placement, owner=True)
    before = answers.read_bytes()
    result = cli('area_budget_basis_gen.py', project)
    assert result.returncode == 1, result.stdout + result.stderr
    assert answers.read_bytes() == before


def test_missing_prose_authority_refuses_and_restored_authority_accepts(tmp_path):
    project, _, prose = fixture(tmp_path, 'answers')
    assert cli('area_budget_basis_gen.py', project).returncode == 0
    assert consume(project).returncode == 0
    text = prose.read_bytes()
    prose.unlink()
    assert consume(project).returncode == 1
    prose.write_bytes(text)
    assert consume(project).returncode == 0


def test_producer_refuses_an_output_its_own_consumer_cannot_rederive(tmp_path, monkeypatch):
    project, answers, _ = fixture(tmp_path, 'top')
    before = answers.read_bytes()
    original = A.apply

    def contradictory(doc, got, reason=''):
        new, revision = original(doc, got, reason)
        new['synthesis_area_budget'] = {'status': 'LIMIT', 'max_die_dimensions_um': [320, 240]}
        return new, revision

    monkeypatch.setattr(A, 'apply', contradictory)
    rc = A.main([str(project)])
    assert rc == 1
    assert answers.read_bytes() == before
