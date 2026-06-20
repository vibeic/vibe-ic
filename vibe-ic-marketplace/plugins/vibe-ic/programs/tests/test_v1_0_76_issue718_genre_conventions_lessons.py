"""ORGANIC #718 — encode the #716 dual-track-recovered spec-faithful genre
conventions into the blind-authoring lessons corpus.

The conventions a #716 independent blind-solve used to recover designs that
single-track authoring abandoned as FLOORs lived only in the dual-track agents'
reasoning, so fresh clean-room rounds re-failed the SAME recoverable problems.
They are now durably encoded as `### Skill:` sections in
`agents/ic-expert-agent.md`, which `benchmark_dispatch.py --setup` renders into
each run's `lessons.md` (a MUST-READ for every blind author) via
`_render_lesson_digest`.

§4-E / no-cheating (the load-bearing axis): the conventions are GENERAL
design-class defaults ("unless the spec states otherwise"), NOT hidden-oracle
answers — no problem identifiers, no per-problem solutions.
"""
import re
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import benchmark_dispatch as BD  # noqa: E402

# The new genre-convention markers (substrings that must survive rendering).
_CONVENTION_MARKERS = [
    "clock divider conventions",
    "async FIFO",
    "Gray pointer LAGS",
    "serial↔parallel converters",
    "barrel shifter",
    "edge / pulse detector",
    "IEEE-754 float multiply",
    "bug-fix tasks",
    "branch predictor (gshare-class)",
    "serial 2's-complementer",
    "K-map → mux decomposition",
    # 2026-06-20 v1.1.31 clean-room triage: the existing serial / clock-divider
    # sections existed yet first-pass authors still mis-timed them — strengthen
    # with the load-bearing phase/timing detail the blind triage rediscovered.
    "Reactive (not predictive), ungated valid",
    "Half-integer dual-edge OR structure",
]


def test_genre_conventions_present_in_expert_agent():
    """The conventions are authored as ACTIVE `### Skill:` sections."""
    txt = BD.EXPERT_AGENT_MD.read_text()
    for mk in _CONVENTION_MARKERS:
        assert mk in txt, f"missing genre convention: {mk!r}"


def test_conventions_render_into_lessons_digest(tmp_path):
    """END-STATE: `_render_lesson_digest` stages the conventions into the run's
    lessons.md that every blind author reads."""
    n = BD._render_lesson_digest(tmp_path)
    assert n > 0
    lessons = (tmp_path / "lessons.md").read_text()
    for mk in _CONVENTION_MARKERS:
        assert mk in lessons, f"convention not rendered into lessons.md: {mk!r}"


def test_conventions_are_spec_faithful_general_not_oracle():
    """§4-E no-cheating: each new convention is phrased as a GENERAL default
    ('unless the spec states otherwise') and carries NO problem-specific
    identifier (no Prob###, no cvdp_copilot_, no per-problem answer)."""
    txt = BD.EXPERT_AGENT_MD.read_text()
    # locate the #718 section
    idx = txt.find("2026-06-15 (#716 dual-track genre conventions, #718)")
    assert idx != -1
    section = txt[idx:]
    # the spec-faithful guard wording (an "unless the spec/prose …" conditional)
    # appears on most conventions — they are DEFAULTS, never absolutes.
    guard_clauses = re.findall(r"unless the (?:spec|prose)\b", section)
    assert len(guard_clauses) >= 6, len(guard_clauses)
    assert "§4-E" in section
    # NO hidden-oracle / problem-specific identifiers leaked into the lessons
    assert not re.search(r"Prob\d{2,}", section), "problem-ID leaked"
    assert "cvdp_copilot_" not in section
    # not a per-problem answer table — phrased as design-CLASS conventions
    assert "design class" in section.lower() or "genre" in section.lower()


def test_render_excludes_retired_strikethrough_skills(tmp_path):
    """Regression: retired `### ~~Skill:` sections are NOT rendered as active
    lessons (the digest extracts only live `### Skill:` sections)."""
    fake = tmp_path / "expert.md"
    fake.write_text(
        "# x\n\n### Skill: live one\n\nbody-live\n\n"
        "### ~~Skill: retired one~~ → NOW A PROGRAM\n\nbody-retired\n")
    run = tmp_path / "run"
    run.mkdir()
    BD._render_lesson_digest(run, expert_md=fake)
    out = (run / "lessons.md").read_text()
    assert "live one" in out and "body-live" in out
    assert "retired one" not in out and "body-retired" not in out


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
