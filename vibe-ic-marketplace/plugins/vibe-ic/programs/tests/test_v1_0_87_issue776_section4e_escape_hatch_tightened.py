"""ORGANIC #776 — §4-E carve-out TIGHTENED (program-backed doctrine guard).

The §4-E carve-out ("apply a genre-convention lesson unless the spec states
otherwise", #741/#749) was being weaponized as an ESCAPE HATCH to UNDER-apply a
correct lesson on AMBIGUOUS prose (a real r12 PASS → r13 FAIL regression:
signal_generator peak-hold dropped via a "spec governs" argument the spec never
made). The fix rewords §4-E to "explicit-contradiction → MUST deviate" (NOT
"ambiguity → may drop"; ambiguity resolves TOWARD the present lesson) in
agents/ic-expert-agent.md, plus an anti-pattern note on the triangle/peak-hold
lesson. This test pins the tightened doctrine via the generic
skill_doc_section_present_check program so a future edit cannot silently drop it.

§4-E no-leak (original intent preserved): a GENUINELY explicit contrary spec must
STILL be allowed to deviate — pinned by the 'no-leak' marker.
"""
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "skill_doc_section_present_check.py"
_DOC = _PROGRAMS.parent / "agents/ic-expert-agent.md"

# the load-bearing markers of the tightened §4-E doctrine.
_MARKERS = [
    "TIGHTENED",
    "explicit-contradiction",
    "ambiguity resolves TOWARD the present lesson",
    "ANTI-PATTERN",
    "no-leak",
]


def test_end_state_section4e_tightened_present():
    """END-STATE: the guard exits 0 — every tightened-§4-E marker is present."""
    args = [sys.executable, str(_PROG), "--doc", str(_DOC)]
    for m in _MARKERS:
        args += ["--marker", m]
    cp = subprocess.run(args, capture_output=True, text=True)
    assert cp.returncode == 0, cp.stderr


def test_end_state_guard_fails_when_doctrine_stripped(tmp_path):
    """END-STATE (defect-artifact fixture): a doc copy WITHOUT the tightened
    doctrine makes the guard FAIL (exit 1) — it really enforces the rewording."""
    (tmp_path / "agent.md").write_text(
        "# agent\n\n> conventional choice is Y unless the spec states otherwise.\n")
    cp = subprocess.run(
        [sys.executable, str(_PROG), "--doc", str(tmp_path / "agent.md"),
         "--marker", "explicit-contradiction",
         "--marker", "ambiguity resolves TOWARD the present lesson"],
        capture_output=True, text=True)
    assert cp.returncode == 1
    assert "missing" in cp.stderr.lower()


def test_triangle_lesson_carries_antipattern_note():
    """The triangle/peak-hold lesson carries the §4-E anti-pattern note so the
    specific weaponized case is documented at the lesson site."""
    txt = _DOC.read_text()
    # locate the triangle lesson, assert the anti-pattern + #776 are near it.
    i = txt.find("hold the peak for one cycle")
    assert i != -1
    window = txt[i:i + 2000]
    assert "ANTI-PATTERN" in window and "#776" in window


def test_noleak_explicit_contrary_spec_still_deviates_marker():
    """§4-E NO-LEAK: the doctrine still PERMITS deviating on a genuinely explicit
    contrary spec — the tightening removes only the 'argue ambiguity' escape."""
    txt = _DOC.read_text()
    assert "GENUINELY explicit contrary spec" in txt


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
