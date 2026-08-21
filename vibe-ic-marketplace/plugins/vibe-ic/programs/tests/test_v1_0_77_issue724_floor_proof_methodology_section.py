"""ORGANIC #724 — methodology FLOOR-proof section present (program-backed guard).

The FLOOR-proof doctrine (never declare a benchmark-defect FLOOR without the
"original-RTL-also-fails" proof) was appended to
skills/open-benchmark-methodology/SKILL.md. This test pins it via the generic
skill_doc_section_present_check program so a future edit cannot silently drop it.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "skill_doc_section_present_check.py"
_DOC = _PROGRAMS.parent / "skills/open-benchmark-methodology/SKILL.md"


def test_end_state_floor_proof_section_present():
    """END-STATE: the guard exits 0 — the FLOOR-proof markers are present."""
    args = [sys.executable, str(_PROG), "--doc", str(_DOC),
            "--marker", "FLOOR-proof", "--marker", "mutually-exclusive",
            "--marker", "original"]
    cp = subprocess.run(args, capture_output=True, text=True)
    assert cp.returncode == 0, cp.stderr


def test_end_state_guard_fails_when_section_stripped(tmp_path):
    """END-STATE (defect-artifact fixture): a doc copy WITHOUT the section makes
    the guard FAIL (exit 1) — proving it really enforces the doctrine."""
    # defect-artifact fixture: a methodology SKILL.md WITHOUT the FLOOR section
    (tmp_path / "SKILL.md").write_text(
        "# methodology\n\nNo FLOOR doctrine here.\n")
    stripped = tmp_path / "SKILL.md"
    cp = subprocess.run(
        [sys.executable, str(_PROG), "--doc", str(stripped),
         "--marker", "FLOOR-proof", "--marker", "mutually-exclusive"],
        capture_output=True, text=True)
    assert cp.returncode == 1
    assert "missing" in cp.stderr.lower()


def test_acceptance_grep_equivalent():
    """驗收 (verbatim grep family): the markers are in the methodology skill."""
    txt = _DOC.read_text()
    import re
    assert re.search(r"original.*RTL.*also fail|FLOOR-proof|mutually.exclusive",
                     txt, re.I)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
