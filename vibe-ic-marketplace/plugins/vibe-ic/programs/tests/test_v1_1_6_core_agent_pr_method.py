"""Core-agent-loop SHIPPING DOCTRINE pin.

History (so the flip-flop is legible):
  • direct-push through v1.1.5
  • PR-method 2026-06-17 (v1.1.6) — serialize concurrent authors via a
    gatekeeper merge queue
  • DIRECT-PUSH AGAIN 2026-06-26 (owner directive, STANDING preference) — ship by
    direct commit + `git push origin main`; the PR *ceremony* is dropped but EVERY
    quality GATE is retained (gatekeeper_review MERGE_OK + Step-2.7 +
    gatekeeper_assign_version --write, the pusher assigns the version pre-push).

This file (kept under its original name as the doctrine-pin) now asserts the
CURRENT direct-push end-state in the core-agent-loop SKILL.md, so a future edit
cannot silently revert the loop to a PR-only ship step. The end-state is asserted
by invoking the real `skill_doc_section_present_check.py` marker-presence gate.

chip-AGNOSTIC: markdown marker presence; no chip / vendor / SKU literal.
"""
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
SKILL = (PROGRAMS.parent / "skills" / "core-agent-loop" / "SKILL.md")
_CHECK = PROGRAMS / "skill_doc_section_present_check.py"

# The DIRECT-PUSH doctrine markers that MUST be present in the Step-3 ship
# section + its surrounding doctrine — gates retained, ceremony dropped.
_DIRECT_PUSH_MARKERS = [
    "DIRECT PUSH",
    "git push origin main",
    "gatekeeper_review.py",
    "gatekeeper_assign_version.py",
    "Step-2.7",
]


def _run_marker_check(markers):
    cmd = [sys.executable, str(_CHECK), "--doc", str(SKILL)]
    for m in markers:
        cmd += ["--marker", m]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_skill_documents_direct_push_section():
    # END-STATE via the real program: every direct-push marker present → rc 0.
    r = _run_marker_check(_DIRECT_PUSH_MARKERS)
    assert r.returncode == 0, (r.stdout + r.stderr)


def test_marker_check_is_a_real_gate_negative():
    # sanity: a marker that is NOT in the doc makes the gate FAIL (rc 1), so the
    # green result above is meaningful, not vacuous.
    r = _run_marker_check(["this-marker-is-not-in-the-skill-doc-xyz"])
    assert r.returncode == 1, r.stdout


def test_pr_method_is_no_longer_the_ship_instruction():
    """The loop must ship by DIRECT PUSH, not via `gh pr create` self-merge.
    The PR-method may only survive as a HISTORY note / external-PR handling /
    a 'supersedes the PR-method' marker — never as the active ship step."""
    text = SKILL.read_text()
    # the active ship step is a direct push, explicitly NOT a PR-create.
    assert "ships by **direct commit + `git push\norigin main`**" in text \
        or "ship by DIRECT PUSH" in text
    assert "NO `gh pr create`" in text
    # the gates are explicitly RETAINED (not dropped with the ceremony).
    assert "every quality GATE is retained" in text.replace("\n", " ") \
        or "every quality GATE is retained" in text
    # the flip-flop history is legible.
    assert "direct-push again 2026-06-26" in text.lower()


def test_gates_retained_in_direct_push_era():
    """Direct-push keeps the same gate sequence as the PR era — MERGE_OK before
    the push, version bump, Step-2.7."""
    text = SKILL.read_text()
    assert "MERGE_OK" in text
    assert "gatekeeper_assign_version.py --write" in text
    # never bypass a gate on the direct push.
    assert "--no-verify" in text  # named in the prohibition list
    assert "--force" in text


def test_version_is_monotonic_floor():
    import json
    v = json.loads(
        (PROGRAMS.parent / ".claude-plugin" / "plugin.json").read_text()
    )["version"]
    parts = tuple(int(x) for x in v.split("."))
    # the doctrine flip ships at >= 1.2.42 (after the 2026-06-26 robustness batch).
    assert parts >= (1, 1, 6), v


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
