#!/usr/bin/env python3
"""v1.2.97 — lock the owner directive (2026-07-03):

    "entry of benchmark and general ic design should be the same."

The open-benchmark-methodology SKILL.md must carry an explicit BINDING RULE 0
stating that a benchmark problem is solved through the SAME entry point a
general IC design uses (vibe_ic_one_shot_runner -> phase1 -> phase2 spec-to-rtl
WAIVE -> runner gates), and that a bespoke benchmark-only authoring harness is
forbidden. This test fails if that rule is removed or weakened, so the doctrine
cannot silently regress.

Run:
    python3 -m pytest plugins/vibe-ic/programs/tests/test_v1_2_97_benchmark_entry_equals_general_entry.py
"""
from __future__ import annotations
from pathlib import Path

from _plugin_tree import plugin_path

SKILL = plugin_path("skills") / "open-benchmark-methodology" / "SKILL.md"


def test_rule0_entry_equivalence_present():
    text = SKILL.read_text(encoding="utf-8")
    assert SKILL.is_file(), f"methodology SKILL.md missing at {SKILL}"

    # the named binding rule must exist
    assert "RULE 0 (BINDING" in text, "RULE 0 binding header removed"
    assert "benchmark ENTRY ≡ general-IC-design ENTRY" in text, \
        "the entry-equivalence rule title was removed/reworded"

    # the load-bearing clauses of the rule
    assert "vibe_ic_one_shot_runner.py" in text
    assert "spec-to-rtl" in text, "the AI-backup WAIVE handoff must be named"
    assert "phase2/stage1/rtl/" in text, "the runner's RTL path must be named"

    # the anti-pattern must be explicitly forbidden
    lowered = text.lower()
    assert "author_instructions.md" in lowered or "benchmark-only" in lowered, \
        "the bespoke benchmark-only authoring anti-pattern must be forbidden"
    assert "never" in lowered

    # scoring consequence must be stated
    assert "not a" in lowered and "product number" in lowered, \
        "the 'not a product number' scoring consequence must remain"


if __name__ == "__main__":
    test_rule0_entry_equivalence_present()
    print("PASS: RULE 0 (benchmark entry == general entry) is locked in the plugin")
