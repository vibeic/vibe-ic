#!/usr/bin/env python3
"""v1.2.97 — lock the owner directive (2026-07-03):

    "entry of benchmark and general ic design should be the same."

The open-benchmark-methodology SKILL.md must keep Rule 0's one-product-entry
contract: benchmark formats stay thin adapters around the same general runner,
benchmark-only solving is forbidden, and ``--solve`` runs the shipped runtime
entry audit. This test fails if that rule is removed or weakened, so the
doctrine cannot silently regress.

Run:
    python3 -m pytest plugins/vibe-ic/programs/tests/test_v1_2_97_benchmark_entry_equals_general_entry.py
"""
from __future__ import annotations
from pathlib import Path

from _plugin_tree import plugin_path

SKILL = plugin_path("skills") / "open-benchmark-methodology" / "SKILL.md"
DISPATCH = plugin_path("programs") / "benchmark_dispatch.py"
ENTRY_AUDIT = plugin_path("benchmark") / "benchmark_entry_surface_check.py"


def test_rule0_entry_equivalence_present():
    assert SKILL.is_file(), f"methodology SKILL.md missing at {SKILL}"
    assert DISPATCH.is_file(), f"benchmark dispatcher missing at {DISPATCH}"
    assert ENTRY_AUDIT.is_file(), f"runtime entry audit missing at {ENTRY_AUDIT}"
    text = SKILL.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    # The named one-product-entry rule and its general runner chain must exist.
    assert "## Rule 0 — one product entry" in text, \
        "Rule 0 one-product-entry header removed"
    for clause in (
            "benchmark_dispatch.py <bench> --solve",
            "benchmark_io_adapter.stage",
            "task_nature_route",
            "vibe_ic_one_shot_runner --entry-step",
            "benchmark_dispatch.py <bench> --resume"):
        assert clause in text, f"Rule 0 general-entry clause removed: {clause}"

    # Benchmark code remains a format-only adapter; product decisions stay in
    # neutrally named general programs reachable from an ordinary project flow.
    assert "## GENERAL-CORE / THIN-ADAPTER" in text
    assert ("Benchmark-specific code may only translate formats or invoke the "
            "official scorer.") in normalized
    assert ("It may not classify the task, author or repair RTL, choose a "
            "product step") in normalized

    # Benchmark-only routing/authoring remains explicitly forbidden.
    assert "Forbidden alternatives include:" in text
    assert "benchmark-name or problem-id routers" in normalized
    assert "writing scoreable RTL directly and then calling a gate/scorer" \
        in normalized

    # The documented audit must also be wired into the real --solve path, and
    # acceptance must stay bound to the current review-qualified artifact.
    assert "benchmark/benchmark_entry_surface_check.py" in text
    assert "is called by `--solve`" in normalized
    dispatch = DISPATCH.read_text(encoding="utf-8")
    assert "import benchmark_entry_surface_check as bes" in dispatch
    assert "entry_audit = bes.audit(" in dispatch
    assert 'if entry_audit.get("verdict") != "PASS":' in dispatch
    assert ('_ACCEPTANCE_REPORT = '
            '"program_first_ai_review_acceptance.json"') in dispatch


if __name__ == "__main__":
    test_rule0_entry_equivalence_present()
    print("PASS: Rule 0 one-product-entry semantics are locked in the plugin")
