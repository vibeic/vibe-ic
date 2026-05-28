"""tests/test_capture_routing_consistency.py — v0.1.35

Integration / consistency gates for the closed-loop enhancement-capture flow.

Four cases:
  1. Every Bucket A program path declared in CAPTURE_ROUTING.json EXISTS on disk
     (or is explicitly null). Catches stale routing entries pointing at deleted
     / renamed program files.
  2. Every Bucket B skill path declared in CAPTURE_ROUTING.json EXISTS on disk.
     Catches stale routing entries pointing at deleted / renamed skill files.
  3. The fallback default_routing.bucket_B_skill_file EXISTS (so unknown-step
     fallback is always safe).
  4. End-to-end smoke: a 4-record recoveries.json (one per bucket) drives
     enhancement_emit.py to emit Bucket A + B + C + D outputs, and the per-step
     routing places Bucket B into the right target skill file.

These gates run alongside the existing tests/ integration set, so a routing
table that drifts away from the actual skill / program inventory FAILs CI
before it ships.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).parent.parent
ROUTING = PLUGIN_ROOT / "benchmark-harness" / "CAPTURE_ROUTING.json"
EMIT_PROGRAM = PLUGIN_ROOT / "programs" / "enhancement_emit.py"
CAPTURE_SKILL = PLUGIN_ROOT / "skills" / "benchmark-enhancement-capture" / "SKILL.md"


def _routing() -> dict:
    return json.loads(ROUTING.read_text())


def test_capture_routing_file_present():
    """The routing table itself must exist."""
    assert ROUTING.is_file(), f"missing routing table: {ROUTING}"
    assert EMIT_PROGRAM.is_file(), f"missing emit program: {EMIT_PROGRAM}"
    assert CAPTURE_SKILL.is_file(), f"missing capture skill: {CAPTURE_SKILL}"


# ── 1. every Bucket A program path declared in routing exists on disk ──
def test_bucket_A_program_paths_exist():
    r = _routing()
    missing = []
    for step_id, cfg in r.get("steps", {}).items():
        prog = cfg.get("bucket_A_program")
        if not prog:
            continue
        # path is relative to plugin root; some referenced files live under
        # mcp-eda-server/ which may or may not be at the same root depending
        # on install layout. We check existence at PLUGIN_ROOT/<path>
        # AND skip mcp-eda-server references (they live in a sibling package).
        if prog.startswith("mcp-eda-server/"):
            continue
        if prog.startswith("tools/phase1_engine/"):
            # tools/ may live at the repo root above plugins/vibe-ic
            continue
        candidate = PLUGIN_ROOT / prog
        if not candidate.is_file():
            missing.append(f"{step_id} → {prog}")
    assert not missing, (
        "Bucket A programs in CAPTURE_ROUTING.json missing on disk:\n  "
        + "\n  ".join(missing)
        + "\nFix: either add the program or null out the routing entry."
    )


# ── 2. every Bucket B skill path declared in routing exists on disk ──
def test_bucket_B_skill_paths_exist():
    r = _routing()
    missing = []
    for step_id, cfg in r.get("steps", {}).items():
        sk = cfg.get("bucket_B_skill_file")
        if not sk:
            continue
        candidate = PLUGIN_ROOT / sk
        if not candidate.is_file():
            missing.append(f"{step_id} → {sk}")
    assert not missing, (
        "Bucket B skill files in CAPTURE_ROUTING.json missing on disk:\n  "
        + "\n  ".join(missing)
        + "\nFix: either add the skill SKILL.md or update the routing entry."
    )


# ── 3. default_routing fallback skill MUST exist ──
def test_default_routing_skill_exists():
    r = _routing()
    fb = r.get("default_routing", {}).get("bucket_B_skill_file")
    assert fb, "default_routing.bucket_B_skill_file is missing"
    assert (PLUGIN_ROOT / fb).is_file(), (
        f"fallback skill {fb} declared in default_routing must exist on disk"
    )


# ── 4. end-to-end smoke: full 4-bucket emit through the program ──
def test_end_to_end_emit_smoke(tmp_path):
    recs = [
        {"step": "phase2.rtl_gen", "design": "smokeA", "bucket": "A",
         "rule_name": "smoke-rule", "docstring": "doc",
         "expected_signal": "WARN", "fix_action": "do x"},
        {"step": "phase3.pnr_setup_repair", "design": "smokeB", "bucket": "B",
         "skill_title": "Smoke B", "pattern": "p", "when": "w",
         "what": "x", "example": "e", "generality": "g"},
        {"step": "analog.A4_corner_sweep", "design": "smokeC", "bucket": "C",
         "title": "Smoke backlog C", "pattern": "p", "suggested_fix": "f",
         "backlog_slug": "smoke-c", "backlog_type": "enhancement",
         "severity": "P3", "component": "x", "session_context": "test"},
        {"step": "phase2.rtl_gen", "design": "smokeD", "bucket": "D",
         "why_discard": "smoke discard reason"},
    ]
    rec_file = tmp_path / "recoveries.json"
    rec_file.write_text(json.dumps(recs))
    out_dir = tmp_path / "out"
    r = subprocess.run(
        [sys.executable, str(EMIT_PROGRAM),
         "--records", str(rec_file), "--out-dir", str(out_dir)],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, f"emit failed: {r.stderr}\n{r.stdout}"
    summary = json.loads((out_dir / "summary.json").read_text())

    # all four buckets present in totals
    assert summary["totals"] == {"A": 1, "B": 1, "C": 1, "D": 1}, summary

    # Bucket B targeted sta-review (per routing)
    assert any(e["target"] == "skills/sta-review/SKILL.md"
               for e in summary.get("bucket_B_files", [])), summary

    # Bucket A targeted rtl_hygiene_lint.py (per routing for phase2.rtl_gen)
    assert any("rtl_hygiene_lint" in f for f in summary.get("bucket_A_files", [])), summary

    # Bucket C emitted ORGANIC-*.yaml
    assert any(f.startswith("ORGANIC-") for f in summary.get("bucket_C_files", [])), summary

    # Bucket D emitted with the discard reason
    d_path = Path(summary["bucket_D_file"])
    assert "smoke discard reason" in d_path.read_text()
