"""Saturating-counter genre lesson — a counter/accumulator the spec describes
as having NO upper limit / that CANNOT overflow / that counts INDEFINITELY
toward a threshold should SATURATE at its max value, NOT wrap (modulo) — unless
the spec explicitly states wrapping/modulo/ring-counter behaviour.

This is an AI-recovered, spec-faithful GENRE convention delivered through the
ALREADY-WIRED #733 lessons-consumption path: it is authored as an ACTIVE
`### Skill:` section in `agents/ic-expert-agent.md` (which
the general solve initializer renders into each run's `lessons.md` via
`_render_lesson_digest`), and the keyword `saturating counter / no upper limit
/ cannot overflow` is added to the genre keyword list in BOTH Shape-B and
Shape-C blind instructions so the #733 consume directive routes a matching spec
to the lesson.

It is a LESSON (advisory authoring guidance), NOT a hard emit-gate — so it
cannot false-block a correct design or fabricate a pass.

§4-E / no-cheating (the load-bearing axis, mirrors test_v1_0_76_issue718):
the convention is a GENERAL design-class default with an explicit "unless the
spec states otherwise" guard — NOT a hidden-oracle answer. It carries NO
problem identifier (no Prob###, no cvdp_copilot_) and names NO benchmark /
testbench / oracle literal (no "lemming", no problem-specific behaviour).
"""
import re
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import benchmark_dispatch as BD  # noqa: E402

_PLUGIN = _PROGRAMS.parent
_SHAPE_B = _PLUGIN / "benchmark" / "blind_instructions_shape_b.md"
_SHAPE_C = _PLUGIN / "benchmark" / "blind_instructions_shape_c.md"

# The new lesson's stable markers (substrings that must survive rendering).
_LESSON_TITLE = "### Skill: saturating counter"
_LESSON_MARKERS = [
    "saturating counter",
    "SATURATES",
    "no upper limit",
    "cannot overflow",
]
# the keyword that routes a matching spec to the lesson via the #733 directive
_KEYWORD = "saturating counter /\nno upper limit / cannot overflow"


def test_lesson_present_in_expert_agent():
    """The convention is authored as an ACTIVE `### Skill:` section."""
    txt = BD.EXPERT_AGENT_MD.read_text()
    assert _LESSON_TITLE in txt, "saturating-counter `### Skill:` section missing"
    for mk in _LESSON_MARKERS:
        assert mk in txt, f"missing lesson marker: {mk!r}"


def test_lesson_renders_into_lessons_digest(tmp_path):
    """END-STATE: `_render_lesson_digest` stages the lesson into the run's
    lessons.md that every blind author reads."""
    n = BD._render_lesson_digest(tmp_path)
    assert n > 0
    lessons = (tmp_path / "lessons.md").read_text()
    assert _LESSON_TITLE in lessons, "lesson not rendered into lessons.md"
    for mk in _LESSON_MARKERS:
        assert mk in lessons, f"lesson marker not rendered: {mk!r}"


@pytest.mark.parametrize("doc", [_SHAPE_B, _SHAPE_C])
def test_keyword_routes_to_lesson_in_blind_instructions(doc):
    """The genre keyword list in BOTH blind instructions includes the
    saturating-counter keyword, so the #733 consume directive routes a matching
    spec to the lesson."""
    txt = doc.read_text()
    assert _KEYWORD in txt, f"saturating-counter keyword missing from {doc.name}"
    # it lives inside the #733 MANDATORY consume directive (not loose prose)
    assert "#733" in txt
    assert "KEYWORD-MATCH" in txt


def test_lesson_is_spec_faithful_general_not_oracle():
    """§4-E no-cheating: the convention is a GENERAL default ('unless the spec
    states otherwise') and leaks NO problem-specific identifier or oracle
    literal (mirrors test_v1_0_76_issue718's leak-check)."""
    txt = BD.EXPERT_AGENT_MD.read_text()
    idx = txt.find(_LESSON_TITLE)
    assert idx != -1
    # bound the section to the next `### ` heading so we check only this lesson
    nxt = txt.find("\n### ", idx + len(_LESSON_TITLE))
    section = txt[idx:nxt] if nxt != -1 else txt[idx:]
    # the spec-faithful guard wording — it is a DEFAULT, never an absolute
    assert "unless the spec states otherwise" in section, "no-leak guard missing"
    # NO hidden-oracle / problem-specific identifiers leaked
    assert not re.search(r"Prob\d{2,}", section), "problem-ID leaked"
    assert "cvdp_copilot_" not in section
    # NO benchmark / oracle literal leaked (no problem name, no TB token).
    # ("oracle" as the abstract meta-word — "not by any oracle" — is the §4-E
    # vocabulary the #718 block itself uses; we ban concrete leaked LITERALS,
    # not that meta-word.)
    low = section.lower()
    for banned in ("lemming", "prob155", "testbench.v", "verified_"):
        assert banned not in low, f"oracle/problem literal leaked: {banned!r}"
    # phrased as a design-CLASS convention, not a per-problem answer
    assert "general" in low and "counter" in low


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
