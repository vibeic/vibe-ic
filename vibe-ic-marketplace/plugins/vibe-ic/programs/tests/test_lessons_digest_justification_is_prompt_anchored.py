"""General defaults remain binding; hidden-answer authority stays out of source.

The corpus audit is static test-time validation. Runtime renderers always deliver
all active lessons; no prose regex may withhold an author's knowledge artifact.
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
    'The oracle requires the opposite of the literal rule.',
    'The golden holds the top value for four clocks, verified against its trace.txt reference.',
    'The description and hidden TB disagree; the TB wins.',
    'When the golden RTL is stripped, the asserted checks ARE the spec.',
    "When prose conflicts with the golden reference model, the index formula must match the reference's placement, not the ambiguous English.",
    'The host scorer confirms the literal golden phase is a guaranteed match.',
    'Use the spec example, a standard reference, or the original golden.',
    'The supplied public golden reference model must match the interface; the golden reference model is authoritative.',
    'Do not use the golden reference model as authoritative; the golden reference model is authoritative.',
    'The supplied note says the oracle expects the inverted output.',
    'The supplied hidden-checker note says the oracle expects the inverted output.',
    "Hidden checkers assert the interface's end-state immediately after the last handshake, with zero grace cycles.",
]
_GOOD = [
    'matching it is spec-faithful, not oracle-fitting.',
    'the SOURCE is the prompt, never the oracle harness.',
    'Tier 1 — VERIFIED blind-absorbable (zero-oracle blind A/B at the real oracle)',
    "the clamp-vs-wrap choice is determined by the spec's overflow language, not by any oracle",
    'The supplied public golden reference model expects a registered output; it is a declared input contract.',
    'The supplied public\ngolden reference model expects a registered output; it is a declared input contract.',
    'Never read the hidden testbench. Derive names from the supplied module header.',
    'Do not assume the golden holds a particular phase.',
    'Use golden_rule as the output name from the provided header.',
    'For unsigned bytes the public maximum is 0xFF; compute the arithmetic oracle independently.',
    'Register read data by DEFAULT unless the spec explicitly requires combinational read.',
    'The same-genre documented default may outrank a relative ambiguity; only explicit contrary input overrides it.',
    'Do NOT implement that literal reading of ambiguous wording; keep the documented default unless the spec explicitly contradicts it.',
    'The supplied public checker asserts the interface end-state; it is a declared input contract.',
    'Do not assume the hidden checker asserts an immediate release; keep the documented default unless explicit contrary input overrides it.',
]


def _section(body):
    return '### Skill: neutral vector datapath\n\n**What to do**: ' + body + '\n'


def _corpus():
    return require_repo(*_PLUGIN, 'agents', 'ic-expert-agent.md')


def _flat(text):
    return ' '.join(re.sub(r'(?m)^\s*>\s?', '', text).split()).lower()


def test_the_digest_actually_parses_into_sections():
    assert len(A._split_skill_sections(_corpus().read_text())) > 150


def test_no_lesson_justifies_itself_with_oracle_behaviour():
    assert A.audit_file(_corpus()) == []
    raw = _corpus().read_text()
    assert 'Prob153_gshare' not in raw and 'host-verified 0/1083' not in raw
    for hidden_binding_claim in [
        'The hidden TB will instantiate that handshake input',
        'The hidden TB drove a `res_ready`',
        'the hidden TB wired `.rst_n(rst_n)`',
        'the hidden TB instantiates by the DIR/FILE name',
        'the hidden testbench may instantiate by EITHER spelling',
        'A hidden TB instantiates a downstream-ready',
        'the hidden TB instantiates the DUT via',
        "the hidden TB's usage",
    ]:
        assert hidden_binding_claim not in raw, hidden_binding_claim


@pytest.mark.parametrize('body', _BAD)
def test_every_forbidden_pattern_is_individually_live(body):
    assert A.audit_text(_section(body)), body


@pytest.mark.parametrize('body', _GOOD)
def test_legitimate_oracle_mentions_are_not_flagged(body):
    assert A.audit_text(_section(body)) == [], body


def _deliver(tmp_path, consumer, prompt='Design a neutral vector datapath transform.'):
    import _lesson_digest as ld
    import ic_expert_backup_pack as pack
    import design_one_shot_runner as runner
    if consumer == 'direct':
        dest = tmp_path / 'direct'
        count = ld.render_lesson_digest(dest)
        return dest, count
    if consumer == 'public-pack':
        dest = tmp_path / 'pack'
        h = pack.assemble(prompt, None, None, [], [], dest)
        return dest, h['dual_track']['track1_general_blind']['n_skills']
    project = tmp_path / 'project'
    docs = project / 'phase1' / 'input_doc'
    docs.mkdir(parents=True)
    (docs / 'L2_architecture.md').write_text(prompt)
    result = runner.step_rtl_gen(project, 'digital_arithmetic_primitive')
    return project / 'phase2' / 'stage1', result.extras['lessons_count']


@pytest.mark.parametrize('consumer', ['direct', 'public-pack', 'rtl-handoff'])
def test_all_checked_in_lessons_are_delivered_without_hidden_answers(tmp_path, consumer):
    dest, count = _deliver(tmp_path, consumer)
    expected = A._split_skill_sections(_corpus().read_text())
    text = (dest / 'lessons.md').read_text()
    actual = A._split_skill_sections(text)
    assert count == len(expected) > 150
    assert [h for h, _ in actual] == [h for h, _ in expected]
    for claim in ['signal_generator', 'tri_gen.txt', 'host scorer confirms',
                  'guaranteed match', 'the MODEL is authoritative', 'the TB wins',
                  'golden holds BOTH', 'reference testbench failed 7 of 20',
                  '46/48 mismatch',
                  'wfull.txt', 'rempty.txt', 'tdata.txt']:
        assert claim not in text, claim
    assert A.audit_text(text) == []


def test_secondary_checked_in_source_is_clean_and_delivered(tmp_path):
    import ic_expert_backup_pack as pack
    source = require_repo(*_PLUGIN, 'agents', 'ic_expert_db', 'ic_expert_db.json')
    db = json.loads(source.read_text())
    assert 'is falsified by official-harness evidence' not in source.read_text()
    assert 'For a priority arbiter checked against a golden scoreboard' not in source.read_text()
    for entry in db['entries']:
        for lesson in entry['lessons']:
            assert A.audit_text(_section(lesson)) == [], entry['ic_class']
    h = pack.assemble('combinational 2D matrix transform flattened bus rotation padding',
                      None, None, [], [], tmp_path)
    assert any(c['ic_class'] == 'matrix-transform-comb' for c in h['db_classes'])
    text = (tmp_path / 'ic_expert_db.md').read_text()
    assert 'conflicts with the golden reference model' not in text


@pytest.mark.parametrize('requirement', [
    'No further release-latency requirement is supplied.',
    'The claim must remain asserted for two clocks after the final beat.',
])
def test_ping_pong_release_default_and_explicit_override_are_delivered(tmp_path, requirement):
    import ic_expert_backup_pack as pack
    prompt = ('Design a ping-pong double-buffer claim/activate stream interface. '
              'Complete the final valid-ready beat and release handshake controller. ' + requirement)
    handoff = pack.assemble(prompt, None, None, [], [], tmp_path)
    assert any(c['ic_class'] == 'ping-pong-buffer' for c in handoff['db_classes'])
    assert handoff['dual_track']['track1_general_blind']['n_skills'] == 218
    source = json.loads(require_repo(*_PLUGIN, 'agents', 'ic_expert_db', 'ic_expert_db.json').read_text())
    lesson = next(e for e in source['entries'] if e['ic_class'] == 'ping-pong-buffer')['lessons'][1]
    assert lesson in (tmp_path / 'ic_expert_db.md').read_text()
    assert A.audit_text(_section(lesson)) == []
    text = _flat(lesson)
    assert 'release default is the same clock edge' in text
    assert 'only an explicit contrary release-latency or claim-hold requirement overrides' in text
    assert 'hidden checkers' not in text and 'zero grace cycles' not in text


@pytest.mark.parametrize('consumer', ['direct', 'public-pack', 'rtl-handoff'])
def test_static_finding_does_not_filter_runtime_knowledge(tmp_path, monkeypatch, consumer):
    import _lesson_digest as ld
    body = _BAD[4]
    source = tmp_path / 'neutral-source.md'
    source.write_text(_section(body))
    assert A.audit_file(source), 'the static negative control must be live'
    render = ld.render_lesson_digest
    monkeypatch.setattr(ld, 'render_lesson_digest', lambda dest: render(dest, source))
    dest, count = _deliver(tmp_path, consumer)
    assert count == 1
    assert body in (dest / 'lessons.md').read_text()


def test_section_4e_keeps_default_force_and_emits_on_real_conflict():
    text = _corpus().read_text().split('## Captured by benchmark-enhancement-capture — 2026-06-15 (#716', 1)[1]
    text = _flat(text.split('### Skill:', 1)[0])
    assert 'ambiguity resolves toward the present same-genre convention' in text
    assert 'only an explicit, unambiguous contrary input sentence' in text
    assert 'record the conflict and chosen interpretation, and emit rtl' in text
    assert 'the author does not ask anyone' in text


@pytest.mark.parametrize('title,required', [
    ('power-up determinism', ['initial <reg> = 0;', 'separate', 'explicit contrary initial value']),
    ('FIFO / double-buffer', ['registered read data', 'registered full/empty', 'n-1', 'only explicit contrary']),
    ('async FIFO gray pointer', ['bin2gray(waddr_bin)', 'current', 'only an explicit contrary']),
    ('odd-ratio clock divider', ['pre-increment decode default', 'intermediate outputs high', 'explicit contrary']),
    ('clock divider conventions', ['cnt==(mul2/2)+1', 'current counter', 'explicit waveform/reset/phase']),
    ('port-name authority', ['interface header wins', 'public instantiation', 'emit rtl']),
    ("Don't-care grouping", ['canonical minimal-sop', 'default', 'explicit contrary']),
    ('K-map axis convention', ['column-first default', 'explicit axis labels', 'emit rtl']),
])
def test_general_defaults_and_explicit_override_reach_real_digest(tmp_path, title, required):
    dest, _ = _deliver(tmp_path, 'direct')
    sections = A._split_skill_sections((dest / 'lessons.md').read_text())
    body = _flat(next(body for heading, body in sections if title.lower() in heading.lower()))
    for instruction in required:
        assert instruction in body, (title, instruction)


@pytest.mark.parametrize('title,required', [
    ('infer downstream-ready', ['paired', 'ready', 'valid &&', 'explicit supplied interface header wins']),
    ('active-low reset naming', ['default', 'rst_n', 'declared `reset_n`', 'supplied interface header wins']),
    ('module name —', ['stem', 'default', 'supplied interface header wins']),
    ('misspelled leaf name', ['alias wrapper', 'preserve every port and parameter', 'supplied interface header wins']),
    ('optional handshake port', ['always-ready', 'no equivalent ready port', 'supplied interface header wins']),
    ('parameter.*case-sensitive', ['parameter <name>', 'preserving exact case', 'supplied interface header wins']),
    ('conflicting.*interface sources', ['interface header wins', 'emit rtl without asking a human']),
])
def test_interface_defaults_use_declared_sources_in_real_digest(tmp_path, title, required):
    dest, _ = _deliver(tmp_path, 'direct')
    sections = A._split_skill_sections((dest / 'lessons.md').read_text())
    body = _flat(next(body for heading, body in sections if re.search(title, heading, re.I)))
    for instruction in required + ['default', 'explicit contrary input overrides', 'public instantiation', 'emit rtl']:
        assert instruction in body, (title, instruction)
    assert 'hidden tb' not in body and 'hidden testbench' not in body


@pytest.mark.parametrize('startup', [
    pytest.param('Startup is unspecified.', id='silent-default'),
    pytest.param('The reset-less output register must start at binary 1 before the first clock.', id='explicit-one'),
])
def test_direct_author_skill_keeps_default_and_explicit_override(tmp_path, startup):
    import design_one_shot_runner as runner
    source = require_repo(*_PLUGIN, 'skills', 'spec-to-rtl', 'SKILL.md')
    docs = tmp_path / 'project' / 'phase1' / 'input_doc'
    docs.mkdir(parents=True)
    (docs / 'L2_architecture.md').write_text('Design a neutral vector datapath transform. ' + startup)
    result = runner.step_rtl_gen(tmp_path / 'project', 'digital_arithmetic_primitive')
    staged = Path(result.extras['fallback_skill_path'])
    assert staged.read_bytes() == source.read_bytes()
    text = _flat(staged.read_text())
    assert 'initial <reg> = 0;' in text
    assert 'only an explicit contrary initial value overrides it' in text
    assert 'preserve a supplied nonzero startup value' in text
    quality = text.split('## quality bar', 1)[1].split('## honest history', 1)[0]
    assert 'initial-zero block by default' in quality
    assert 'explicit contrary startup value overrides this default' in quality
    waveform = text.split('## "read the simulation waveform" tables', 1)[1].split('## ', 1)[0]
    assert 'first defined output transition' in waveform
    assert 'early x rows are not an extra register stage' in waveform
    assert 'prob098_circuit7' not in waveform and '58/123' not in waveform
    interface = text.split('it checks (1) module-name-case', 1)[1].split('6c.', 1)[0]
    assert 'supplied interface header case-exactly' in interface
    assert 'the interface header wins' in interface and 'public instantiation' in interface
    assert 'canonical id stem the harness uses' not in interface
    assert 'uses the documented canonical event/edge-counting default' in text
    assert 'counts the way a hidden scorer counts' not in text


@pytest.mark.parametrize('initial,expected_changes', [('', 1), ("initial q = 1'b1;", 0)])
def test_general_startup_convention_matches_real_hygiene_consumer(tmp_path, initial, expected_changes):
    import rtl_hygiene_lint as hygiene
    path = tmp_path / 'neutral.v'
    original = ('module neutral(input clk, input d, output reg q);\n'
                + initial + '\nalways @(posedge clk) q <= d;\nendmodule\n')
    path.write_text(original)
    changed, _ = hygiene.autofix_uninit_registered_output(path)
    assert changed == expected_changes
    if initial:
        assert path.read_text() == original
    else:
        assert re.search(r'\binitial\s+begin\s+q\s*=\s*0\s*;', path.read_text())
        assert not hygiene.rule_uninit_registered_output(path.read_text(), str(path))


def test_inactive_history_is_not_an_author_lesson(tmp_path):
    import _lesson_digest as ld
    source = tmp_path / 'corpus.md'
    source.write_text(_section(_GOOD[9]) + '\n### ~~Skill: retired~~\n' + _BAD[4]
                      + '\n## Audit history\n' + _BAD[5])
    assert A.audit_file(source) == []
    assert ld.render_lesson_digest(tmp_path / 'render', source) == 1
    text = (tmp_path / 'render' / 'lessons.md').read_text()
    assert '0xFF' in text and _BAD[4] not in text and _BAD[5] not in text
