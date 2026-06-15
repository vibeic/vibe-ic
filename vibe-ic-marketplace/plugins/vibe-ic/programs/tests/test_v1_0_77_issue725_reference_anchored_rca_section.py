"""ORGANIC #725 — reference-anchored RCA section present (program-backed guard).

The reference-anchored RCA + minimal-edit + real-check iteration recipe was
appended to agents/ic-expert-agent.md. This test pins it via the generic
skill_doc_section_present_check program.
"""
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "skill_doc_section_present_check.py"
_DOC = _PROGRAMS.parent / "agents/ic-expert-agent.md"


def test_end_state_reference_anchored_section_present():
    cp = subprocess.run(
        [sys.executable, str(_PROG), "--doc", str(_DOC),
         "--marker", "reference-anchored", "--marker", "minimal-edit",
         "--marker", "real-check iteration"],
        capture_output=True, text=True)
    assert cp.returncode == 0, cp.stderr


def test_end_state_guard_fails_when_section_stripped(tmp_path):
    stripped = tmp_path / "ic-expert-agent.md"
    stripped.write_text("# agent\n\nNo RCA recipe here.\n")
    cp = subprocess.run(
        [sys.executable, str(_PROG), "--doc", str(stripped),
         "--marker", "reference-anchored", "--marker", "minimal-edit"],
        capture_output=True, text=True)
    assert cp.returncode == 1


def test_acceptance_grep_equivalent():
    """驗収 (verbatim grep family)."""
    import re
    txt = _DOC.read_text()
    assert re.search(r"reference-anchored|minimal-edit|real-check iteration",
                     txt, re.I)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
