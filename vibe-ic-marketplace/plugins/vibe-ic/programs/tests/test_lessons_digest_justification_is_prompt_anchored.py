"""Author lessons take their authority from declared inputs, never hidden answers.

Exercise the existing corpus audit, actual renders, and both public handoffs.
Fixtures are neutral prose; real-source tests read the checked-in author assets.
"""
import json
import re
from pathlib import Path

import pytest

import lessons_corpus_consistency_check as A
from _hostpaths import require_repo

_PLUGIN = ('vibe-ic-marketplace', 'plugins', 'vibe-ic')
_BAD = [
    'The oracle expects the inverted polarity.',
    'Observed oracle-FAIL, so invert the output.',
    'Three sweeps failed the oracle while passing their own TBs.',
    'Do NOT implement that literal reading.',
    'The golden holds the top value for four clocks, verified against its trace.txt reference.',
    'The description and hidden TB disagree; the TB wins.',
    'When the golden RTL is stripped, the asserted checks ARE the spec.',
    "When prose conflicts with the golden reference model, the index formula must match the reference's placement, not the ambiguous English.",
    'The host scorer confirms the literal golden phase is a guaranteed match.',
    'Use the spec example, a standard reference, or the original golden.',
]
_GOOD = [
    'matching it is spec-faithful, not oracle-fitting.',
    'the SOURCE is the prompt, never the oracle harness.',
    'is a faithful-transcription rule, not a hidden-oracle peek.',
    'Tier 1 — VERIFIED blind-absorbable (zero-oracle blind A/B at the real oracle)',
    "the clamp-vs-wrap choice is determined by the spec's overflow language, not by any oracle",
    'The supplied public golden reference model expects a registered output; it is a declared input contract.',
    'Never read the hidden testbench. Derive names from the supplied module header.',
    'Do not assume the golden holds a particular phase.',
    'A public testbench supplied as normative input defines the sampling edge.',
    'Use golden_rule as the output name from the provided header.',
    'For unsigned bytes the public maximum is 0xFF; compute the arithmetic oracle independently.',
]


def _section(body):
    return '### Skill: neutral vector datapath\n\n**What to do**: ' + body + '\n'


def _corpus():
    return require_repo(*_PLUGIN, 'agents', 'ic-expert-agent.md')


def test_the_digest_actually_parses_into_sections():
    assert len(A._split_skill_sections(_corpus().read_text())) > 150


def test_no_lesson_justifies_itself_with_oracle_behaviour():
    assert A.audit_file(_corpus()) == []


@pytest.mark.parametrize('body', _BAD)
def test_every_forbidden_pattern_is_individually_live(body):
    # audit_text already exists on the base: a missed finding is a VALUE failure.
    assert A.audit_text(_section(body)), body


@pytest.mark.parametrize('body', _GOOD)
def test_legitimate_oracle_mentions_are_not_flagged(body):
    assert A.audit_text(_section(body)) == [], body


def test_rendered_checked_in_author_sources_do_not_supply_hidden_answers(tmp_path):
    import _lesson_digest as ld
    import ic_expert_backup_pack as pack
    assert ld.render_lesson_digest(tmp_path / 'direct', _corpus()) > 150
    text = (tmp_path / 'direct' / 'lessons.md').read_text()
    # These actual source assertions failed on the pre-fix render, rather than
    # importing a new predicate and calling its absence a negative control.
    for claim in ['host scorer confirms', 'guaranteed match', 'the MODEL is authoritative',
                  'the TB wins', 'golden holds BOTH', 'verified against its']:
        assert claim not in text, claim
    h = pack.assemble('combinational 2D matrix transform flattened bus rotation padding',
                      None, None, [], [], tmp_path / 'pack')
    assert h['dual_track']['track1_general_blind']['n_skills'] > 150
    assert (tmp_path / 'pack' / 'lessons.md').read_text() == text
    assert any(c['ic_class'] == 'matrix-transform-comb' for c in h['db_classes'])
    db = (tmp_path / 'pack' / 'ic_expert_db.md').read_text()
    assert 'conflicts with the golden reference model' not in db


def test_direct_author_skill_derives_pipeline_from_supplied_waveform():
    path = require_repo(*_PLUGIN, 'skills', 'spec-to-rtl', 'SKILL.md')
    text = path.read_text().split('## "Read the simulation waveform" tables', 1)[1]
    text = text.split('\n## ', 1)[0]
    assert 'waveform_table_conformance_check.py' in text
    assert not re.search(r'\bProb\d+\w*|scores?\s+[~≈]?\d+/\d+', text)


def _tainted_source(tmp_path, monkeypatch, surface):
    import _lesson_digest as ld
    import ic_expert_db_query as db
    if surface == 'lessons.md':
        source = tmp_path / 'neutral-corpus.md'
        source.write_text(_section(_BAD[4]))
        real_render = ld.render_lesson_digest
        monkeypatch.setattr(ld, 'render_lesson_digest',
                            lambda out: real_render(out, source))
    else:
        source = tmp_path / 'neutral-db.json'
        source.write_text(json.dumps({'entries': [{
            'ic_class': 'neutral-vector-datapath', 'lesson_count': 1,
            'lessons': [_BAD[7] + ' vector datapath transform.']}]}))
        monkeypatch.setattr(db, '_DEFAULT_DB', source)


@pytest.mark.parametrize('surface', ['lessons.md', 'ic_expert_db.md'])
@pytest.mark.parametrize('consumer', ['public-pack', 'rtl-handoff'])
def test_contaminated_source_is_withheld_with_named_consumer_reason(
        tmp_path, monkeypatch, surface, consumer):
    import ic_expert_backup_pack as pack
    import design_one_shot_runner as runner
    _tainted_source(tmp_path, monkeypatch, surface)
    prompt = 'Design a neutral vector datapath transform with registered outputs.'
    if consumer == 'public-pack':
        dest = tmp_path / 'pack'
        dest.mkdir()
        (dest / surface).write_text('stale producer knowledge')
        result = pack.assemble(prompt, None, None, [], [], dest)
        other = 'track2_db_informed' if surface == 'lessons.md' else 'track1_general_blind'
        assert result['dual_track'][other]['context']
    else:
        project = tmp_path / 'project'
        docs = project / 'phase1' / 'input_doc'
        docs.mkdir(parents=True)
        (docs / 'L2_architecture.md').write_text(prompt)
        dest = project / 'phase2' / 'stage1'
        dest.mkdir(parents=True)
        (dest / surface).write_text('stale producer knowledge')
        # The public step stages and publishes through its real output boundary.
        step = runner.step_rtl_gen(project, 'digital_arithmetic_primitive')
        result = step.extras or {}
    artifact = dest / surface
    assert not artifact.exists(), artifact.read_text()
    if consumer == 'rtl-handoff':
        assert 'AUTHOR_LESSON_ORACLE_AUTHORITY' in step.detail
    refusals = result.get('knowledge_source_refusals', [])
    assert any(r['reason_class'] == 'AUTHOR_LESSON_ORACLE_AUTHORITY'
               and r['surface'] == surface for r in refusals), refusals
    if consumer == 'public-pack':
        assert json.loads((dest / 'ic_expert_agent_handoff.json').read_text()) == result
    assert 'trace.txt' not in json.dumps(refusals)


def test_inactive_sections_cannot_taint_a_render(tmp_path):
    import _lesson_digest as ld
    source = tmp_path / 'corpus.md'
    source.write_text(_section(_GOOD[-1]) + '\n### ~~Skill: retired~~\n' + _BAD[4]
                      + '\n## Audit history\n' + _BAD[5])
    assert A.audit_file(source) == []
    assert ld.render_lesson_digest(tmp_path / 'out', source) == 1
    text = (tmp_path / 'out' / 'lessons.md').read_text()
    assert '0xFF' in text and 'golden holds' not in text


@pytest.mark.parametrize('body,allowed', [(_BAD[4], False), (_BAD[7], False),
                                        (_GOOD[5], True), (_GOOD[-1], True)])
def test_existing_db_consistency_boundary_uses_same_authority_contract(tmp_path, body, allowed):
    import ic_expert_db_consistency_check as dbcheck
    path = tmp_path / 'db.json'
    path.write_text(json.dumps({'entries': [{
        'ic_class': 'neutral-vector', 'lesson_count': 1, 'lessons': [body]}]}))
    report = dbcheck.check(path)
    assert report['pass'] is allowed, report
