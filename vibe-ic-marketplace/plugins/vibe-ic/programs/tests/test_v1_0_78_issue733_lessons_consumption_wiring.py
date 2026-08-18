"""ORGANIC #733 — the #718 genre-convention lessons digest is STAGED but not
CONSUMED: the blind-author instructions / dispatch never directed the author to
READ + keyword-match + APPLY it, so fresh authors fell into the digest's own
named anti-patterns and the #716 recovered-floor gain was never realized.

This pins the consumption-WIRING: both Shape-B and Shape-C blind instructions,
AND the benchmark_dispatch lessons-digest header, must carry a MANDATORY
read+genre-match+apply directive with the §4-E "unless the spec states
otherwise" guard. (#718 fixed the CONTENT; this fixes the WIRING.)
"""
import re
import sys
from pathlib import Path

import pytest

_PLUGIN = Path(__file__).resolve().parents[2]
_SHAPE_B = _PLUGIN / "benchmark" / "blind_instructions_shape_b.md"
_SHAPE_C = _PLUGIN / "benchmark" / "blind_instructions_shape_c.md"
_DISPATCH = _PLUGIN / "programs" / "benchmark_dispatch.py"


def _flat(t: str) -> str:
    return re.sub(r"\s+", " ", t.lower())


@pytest.mark.parametrize("doc", [_SHAPE_B, _SHAPE_C])
def test_blind_instructions_direct_read_and_apply(doc):
    low = _flat(doc.read_text())
    assert "lessons.md" in low
    assert "keyword-match" in low or "keyword match" in low
    assert "apply" in low
    # §4-E no-leak guard MUST be present
    assert "unless the spec states otherwise" in low
    # the consumption-wiring marker
    assert "#733" in doc.read_text()


def test_dispatch_header_states_consume_contract():
    txt = _DISPATCH.read_text()
    assert "#733" in txt
    low = _flat(txt)
    assert "keyword-match" in low and "apply" in low
    assert "unless the spec states otherwise" in low


def test_rendered_lessons_header_carries_directive(tmp_path):
    """END-STATE: _render_lesson_digest writes a lessons.md whose header carries
    the MANDATORY consume directive (so the staged file itself tells the author
    to read+match+apply)."""
    sys.path.insert(0, str(_PLUGIN / "programs"))
    import benchmark_dispatch as BD
    # a minimal expert md with one ### Skill: section so the digest is non-empty
    expert = tmp_path / "ic-expert-agent.md"
    expert.write_text("# x\n\n### Skill: demo\n\nbody line\n")
    run = tmp_path / "run"
    run.mkdir()
    n = BD._render_lesson_digest(run, expert_md=expert)
    assert n >= 1
    low = _flat((run / "lessons.md").read_text())
    assert "#733" in (run / "lessons.md").read_text()
    assert "keyword-match" in low and "unless the spec states otherwise" in low


def test_negative_stripped_instructions_detected(tmp_path):
    """A stripped instructions copy WITHOUT the directive fails the same check —
    proving the assertion is real (not vacuous)."""
    stripped = tmp_path / "blind.md"
    stripped.write_text("# instructions\n\nAuthor the design from the prompt.\n")
    low = _flat(stripped.read_text())
    assert not ("lessons.md" in low and "keyword-match" in low
                and "unless the spec states otherwise" in low)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
