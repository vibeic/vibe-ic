"""v1.1.6 (owner directive 2026-06-17) — the core-agent-loop SHIPS via the
PR-METHOD (verified bundle → worktree off origin/main → ONE PR to vibeic/vibe-ic
base main → gatekeeper machine gates → gated squash self-merge), SUPERSEDING the
old direct `git push origin main`.

This pins the doctrine into the core-agent-loop SKILL.md so a future edit cannot
silently revert the loop to direct-push. The end-state is asserted by invoking
the real `skill_doc_section_present_check.py` program (a marker-presence gate)
against the SKILL.md, exactly as the #724/#725 doctrine-section tests do.

chip-AGNOSTIC: markdown marker presence; no chip / vendor / SKU literal.
"""
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
SKILL = (PROGRAMS.parent / "skills" / "core-agent-loop" / "SKILL.md")
_CHECK = PROGRAMS / "skill_doc_section_present_check.py"

# The PR-method doctrine markers that MUST be present in the Step-3 ship section.
_PR_METHOD_MARKERS = [
    "PR-method",
    "verified bundle",
    "candidate.patch",
    "worktree",
    "gatekeeper_review.py",
    "gh pr create",
    "--base main",
    "squash",
]


def _run_marker_check(markers):
    cmd = [sys.executable, str(_CHECK), "--doc", str(SKILL)]
    for m in markers:
        cmd += ["--marker", m]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_v116_skill_documents_pr_method_section():
    # END-STATE via the real program: every PR-method marker present → rc 0.
    r = _run_marker_check(_PR_METHOD_MARKERS)
    assert r.returncode == 0, (r.stdout + r.stderr)


def test_v116_marker_check_is_a_real_gate_negative():
    # sanity: a marker that is NOT in the doc makes the gate FAIL (rc 1), so a
    # green result above is meaningful, not vacuous.
    r = _run_marker_check(["this-marker-is-not-in-the-skill-doc-xyz"])
    assert r.returncode == 1, r.stdout


def test_v116_direct_push_is_no_longer_the_default_instruction():
    # the loop must no longer instruct a bare `git push origin main` as the ship
    # step; the only surviving mention is the explicit "does NOT push directly".
    text = SKILL.read_text()
    # the Step-3 ship section opens by forbidding the direct push.
    assert "does NOT `git push origin main` directly" in text
    # the cron template step (c) routes through the PR-method, not a bare push.
    assert "SHIP via the PR-METHOD" in text


def test_v116_version_is_1_1_6_or_higher():
    import json
    v = json.loads(
        (PROGRAMS.parent / ".claude-plugin" / "plugin.json").read_text()
    )["version"]
    parts = tuple(int(x) for x in v.split("."))
    assert parts >= (1, 1, 6), v


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
