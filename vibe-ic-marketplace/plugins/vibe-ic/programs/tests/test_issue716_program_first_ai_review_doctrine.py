"""ORGANIC #716 — pin the corrected Program First + AI Backup doctrine.

Program emits and freezes its result first. AI reviews that result. An AI FAIL
must prove the prompt-bound issue with an executable test before repair; the
repair must pass the same immutable test, normal gates, and fresh AI review.

The doctrine is captured as guidance in
`skills/benchmark-enhancement-capture/SKILL.md` and pinned by a deterministic
guard `programs/convergence_doctrine_present_check.py` (itself follows the
doctrine — it emits the raw evidence it judged on). This test invokes that guard
end-to-end (present → exit 0; a doctrine-stripped fixture → exit 1).
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent
_PROG = _PROGRAMS / "convergence_doctrine_present_check.py"
# the issue-named artifact (string literal so the defect-artifact gate sees it)
_SKILL = _PLUGIN / "skills/benchmark-enhancement-capture/SKILL.md"

if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))
import convergence_doctrine_present_check as C  # noqa: E402


def test_end_state_doctrine_present_exit0(tmp_path):
    """END-STATE: the guard run against the real skill exits 0 (doctrine
    present) and reports zero missing markers."""
    out = tmp_path / "evidence.json"
    cp = subprocess.run(
        [sys.executable, str(_PROG), "--skill", str(_SKILL),
         "--json", str(out)],
        capture_output=True, text=True)
    assert cp.returncode == 0, cp.stderr
    ev = json.loads(out.read_text())
    assert ev["present"] is True
    assert ev["missing"] == []


def test_end_state_doctrine_stripped_exit1(tmp_path):
    """END-STATE (defect-artifact fixture): a skill copy with the convergence
    doctrine STRIPPED makes the guard FAIL (exit 1) — proving the guard really
    enforces the doctrine, not a trivially-true check."""
    # defect-artifact fixture: a SKILL.md with the convergence doctrine removed
    (tmp_path / "SKILL.md").write_text(
        "# benchmark-enhancement-capture\n\nNo doctrine here.\n")
    stripped = tmp_path / "SKILL.md"
    cp = subprocess.run(
        [sys.executable, str(_PROG), "--skill", str(stripped)],
        capture_output=True, text=True)
    assert cp.returncode == 1
    assert "MISSING" in cp.stderr


def test_acceptance_doctrine_keywords_present():
    """驗收 (verbatim grep family): the doctrine markers are in the skill dir."""
    txt = _SKILL.read_text()
    assert "AI-backup" in txt and "AI REVIEW" in txt
    assert "executable test" in C._flat(txt.replace("**", ""))


def test_program_first_section_pins_proof_before_repair():
    """The binding section pins sequential review and executable proof."""
    ev = C.check(_SKILL)
    assert ev["present"] is True
    assert "program first" in ev["found"]
    assert "executable test" in ev["found"]
    assert "same immutable test" in ev["found"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
