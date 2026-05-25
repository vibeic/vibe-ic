#!/usr/bin/env python3
"""Wave 75 — tests for eda_phase23_completion_audit (v0.109 tool).

This is the SOLE acceptance gate for Phase 2+3 completion claims; the
contract is documented in CLAUDE.md rule #11. Tests verify:

Positive: tool wraps phase23_completion_self_audit_check.py (the
          gate referenced in CLAUDE.md), with --json output piped back.
Negative: missing project_dir is not silently defaulted (zod required).
Edge   : exit code 0 → phase23_complete:true; non-zero → false.
SKIP   : description forbids skipping — claims without this audit
         are explicitly called out as a process violation.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_JS = ROOT / "src" / "index.js"
# Wave 82: vibe-ic-d / vibe-ic-core merged into vibe-ic. Try the
# merged path first; fall back to the legacy split for older checkouts.
_MERGED = (ROOT / ".." / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
           / "programs" / "phase23_completion_self_audit_check.py").resolve()
_LEGACY = (ROOT / ".." / "vibe-ic-marketplace" / "plugins" / "vibe-ic-d"
           / "programs" / "phase23_completion_self_audit_check.py").resolve()
GATE = _MERGED if _MERGED.exists() else _LEGACY


def _slice():
    src = INDEX_JS.read_text()
    idx = src.find('"eda_phase23_completion_audit"')
    assert idx > 0
    return src[idx: idx + 4000]


def test_tool_registered():
    assert '"eda_phase23_completion_audit"' in INDEX_JS.read_text()


def test_project_dir_is_required():
    """Negative: project_dir must be required (no default). A default
    would let an agent forget to pass it and silently audit the wrong
    tree — exactly the failure mode CLAUDE.md rule #11 forbids."""
    w = _slice()
    i = w.find("project_dir")
    line = w[i: i + 250]
    assert ".default(" not in line, "project_dir must be required"


def test_dispatches_to_canonical_gate_script():
    """Positive: must execSync the canonical
    phase23_completion_self_audit_check.py — NOT a re-implementation."""
    w = _slice()
    assert "phase23_completion_self_audit_check.py" in w, (
        "tool must delegate to the canonical gate, not re-implement"
    )
    assert "execSync" in w


def test_uses_json_output_mode():
    """Edge: must invoke gate with --json - so structured Overall/PASS/
    FAIL data round-trips back to the agent."""
    w = _slice()
    assert "--json" in w


def test_phase23_complete_field_derived_from_exit_code():
    """Positive: exit_code===0 → phase23_complete:true. This is the
    single field downstream gates / human reviewers should branch on.
    A regression that always returns true would defeat the gate."""
    w = _slice()
    assert "phase23_complete" in w
    assert "exitCode === 0" in w or "exitCode == 0" in w


def test_description_forbids_skipping():
    """SKIP_NOT_APPLICABLE: the description must explicitly call out
    that individual gate PASSes are insufficient (CLAUDE.md rule #11).
    A regression that softens the language risks agents skipping."""
    w = _slice()
    desc_terms = [
        "SOLE",
        "necessary but insufficient",
        "Phase 2+3",
    ]
    desc_lower = w.lower()
    matched = sum(1 for t in desc_terms if t.lower() in desc_lower)
    assert matched >= 2, (
        f"description must reinforce the SOLE-gate contract; "
        f"matched only {matched}/3 strict terms"
    )


def test_canonical_gate_exists_on_disk():
    """SKIP-equivalent: if the gate script is missing the tool would
    fail at runtime; surface that at test time."""
    assert GATE.exists(), (
        f"canonical gate {GATE} missing — phase23 audit tool would "
        f"fail at runtime"
    )
