"""General defaults remain binding; hidden-answer authority stays out of source.

The corpus audit is static test-time validation. Runtime renderers always deliver
all active lessons; no prose regex may withhold an author's knowledge artifact.
"""
import json
import re
from pathlib import Path

import pytest

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




def _corpus():
    return require_repo(*_PLUGIN, 'agents', 'ic-expert-agent.md')


def _flat(text):
    return ' '.join(re.sub(r'(?m)^\s*>\s?', '', text).split()).lower()
















def test_multimodule_partition_lesson_uses_task_declared_names(tmp_path):
    import ic_expert_backup_pack as pack
    prompt = ('Preserve named modules in separate module.sv files; '
              'never merge one named module into another file.')
    handoff = pack.assemble(prompt, None, None, [], [], tmp_path)
    assert any(c['ic_class'] == 'fsm-controller' for c in handoff['db_classes'])
    source = json.loads(require_repo(*_PLUGIN, 'agents', 'ic_expert_db', 'ic_expert_db.json').read_text())
    lesson = next(e for e in source['entries'] if e['ic_class'] == 'fsm-controller')['lessons'][13]
    text = (tmp_path / 'ic_expert_db.md').read_text()
    assert lesson in text
    for answer_marker in ['0006', 'elevator_control_system', 'floor_to_seven_segment', 'Binary2BCD']:
        assert answer_marker not in prompt
        assert answer_marker not in text
    instruction = _flat(lesson)
    assert 'each task-declared module exactly once in its own <module>.sv file' in instruction
    assert 'only from the supplied task/interface contract' in instruction
    assert 'default on silent or ambiguous file-layout input' in instruction
    assert 'only an explicit contrary file-partition requirement overrides' in instruction






def test_section_4e_keeps_default_force_and_emits_on_real_conflict():
    text = _corpus().read_text().split('## Captured by benchmark-enhancement-capture — 2026-06-15 (#716', 1)[1]
    text = _flat(text.split('### Skill:', 1)[0])
    assert 'ambiguity resolves toward the present same-genre convention' in text
    assert 'only an explicit, unambiguous contrary input sentence' in text
    assert 'record the conflict and chosen interpretation, and emit rtl' in text
    assert 'the author does not ask anyone' in text






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
