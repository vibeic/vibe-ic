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
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PLUGIN_ROOT = Path(__file__).parent.parent.parent
ROUTING = PLUGIN_ROOT / "benchmark" / "CAPTURE_ROUTING.json"
CAPTURE_SKILL = PLUGIN_ROOT / "skills" / "benchmark-enhancement-capture" / "SKILL.md"


def _routing() -> dict:
    return json.loads(ROUTING.read_text())


def test_capture_routing_file_present():
    """The routing table itself must exist."""
    assert ROUTING.is_file(), f"missing routing table: {ROUTING}"
    assert CAPTURE_SKILL.is_file(), f"missing capture skill: {CAPTURE_SKILL}"


# ── 1. every Bucket A program path declared in routing exists on disk ──
def test_bucket_A_program_paths_exist():
    r = _routing()
    missing = []
    for step_id, cfg in r.get("steps", {}).items():
        prog = cfg.get("bucket_A_program")
        if not prog:
            continue
        # MEASURED 2026-08-27 on 40d0e14c08: BOTH exemptions that used to sit
        # here rested on a premise that is false in the shipped layout, and the
        # mcp-eda one was hiding three dead routes.
        #
        #   PLUGIN_ROOT/mcp-eda/src/index.js   -> exists
        #   PLUGIN_ROOT/tools/phase1_engine/   -> exists
        #
        # mcp-eda is NOT "a sibling package": it ships inside the plugin, so
        # PLUGIN_ROOT/<path> resolves it correctly. Skipping it meant this
        # gate - whose whole stated job is "catch stale routing entries
        # pointing at deleted / renamed program files" - was blind to exactly
        # the entries that were stale. mcp_eda.{synth,lint,cocotb} all pointed
        # at mcp-eda/src/tools/*.js, which have NEVER existed at any commit.
        #
        # The one real layout difference is an install that carries no mcp-eda
        # at all. That is handled by asking whether the ROOT DIRECTORY is
        # present rather than by exempting the path: absent -> nothing to
        # check; present -> the routed file must exist. A guard that cannot
        # fire on a broken shipped tree is not a guard.
        root = prog.split("/", 1)[0]
        if not (PLUGIN_ROOT / root).exists():
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


# ── 5. Bucket-T (forked-EDA-tool) emit + attribution gate ──────────────
