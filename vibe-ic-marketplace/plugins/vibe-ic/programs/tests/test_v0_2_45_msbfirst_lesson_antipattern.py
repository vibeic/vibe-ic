"""v0.2.45 MSB-first serial-load lesson anti-pattern regressions.

Pins ORGANIC-20260605-msbfirst-lesson-antipattern-rewrite (#414): a lesson
that states a direction convention in prose-only form inverts under
paraphrase — two independent digest-primed single-shot authors produced the
REVERSED implementation while citing the lesson's title. The rewrite adds
the structure that already fixed the hysteresis lesson: an explicit
ANTI-PATTERN block (shown wrong form + why it bit-reverses), a 4-bit numeric
worked trace, and the one-line correct idiom.

Also pins that the lesson corpus sync (field-capture superset) keeps the
digest rendering the rewritten section, so Shape-C single-shot authors
receive the anti-pattern (acceptance verified live: digest-primed blind
single-shot on the shift-and-count class chose the correct direction,
hidden-TB 0-mismatch).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import benchmark_dispatch as bd  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent.parent
LESSON_MD = PLUGIN / "agents" / "ic-expert-agent.md"


def _msb_section() -> str:
    txt = LESSON_MD.read_text()
    start = txt.index("### Skill: MSB-first serial load")
    end = txt.find("\n### ", start + 1)
    return txt[start:end if end != -1 else len(txt)]


def test_lesson_has_antipattern_block():
    sec = _msb_section()
    assert "ANTI-PATTERN" in sec
    # the shown wrong form: new bit concatenated at the MSB end
    assert "{serial_in, q[W-1:1]}" in sec
    assert "bit-REVERSED" in sec or "bit-reversing" in sec


def test_lesson_has_numeric_worked_trace():
    sec = _msb_section()
    assert "4-bit worked trace" in sec
    assert "{b3,b2,b1,b0}" in sec        # correct end state
    assert "{b0,b1,b2,b3}" in sec        # wrong form's reversed end state


def test_lesson_has_one_line_correct_idiom():
    sec = _msb_section()
    assert "{q[W-2:0], serial_in}" in sec
    assert "shifts LEFT" in sec


def test_lesson_states_mechanical_check():
    # the paraphrase-proof discriminator authors can apply mechanically
    sec = _msb_section()
    assert "concatenated at the MSB end" in sec


def test_digest_renders_rewritten_lesson(tmp_path):
    n = bd._render_lesson_digest(tmp_path)
    assert n > 0
    digest = (tmp_path / "lessons.md").read_text()
    assert "MSB-first serial load" in digest
    assert "ANTI-PATTERN" in digest
    assert "{b0,b1,b2,b3}" in digest
