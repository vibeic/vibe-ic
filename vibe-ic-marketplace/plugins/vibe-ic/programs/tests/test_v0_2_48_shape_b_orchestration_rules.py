"""v0.2.48 Shape-B orchestration-rules regressions.

Pins the #416 REOPEN fix (field counter-evidence 2026-06-05): the
rate-limit resilience ladder shipped only in blind_instructions_shape_c.md
and under a "Shape-C"-titled methodology heading, while Shape B mandates
the SAME BATCHFILE/batches fan-out architecture that produced the original
312-problem burst-kill — a Shape-B orchestrator had ZERO documented
recovery ladder. Shape B now carries its own ORCHESTRATION RULES section
(batch granularity / disk truth / transcript export / ladder, with a
cross-reference to the shape-C doctrine), and the methodology heading
covers Shapes B/C explicitly (Shape D: single project, no fan-out, exempt).
"""
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
HARNESS = PLUGIN / "benchmark"
SKILL = PLUGIN / "skills" / "open-benchmark-methodology" / "SKILL.md"


def test_shape_b_has_orchestration_rules_section():
    txt = (HARNESS / "blind_instructions_shape_b.md").read_text()
    assert "ORCHESTRATION RULES" in txt


def test_shape_b_carries_ratelimit_ladder():
    txt = (HARNESS / "blind_instructions_shape_b.md").read_text()
    assert "Rate-limit resilience ladder" in txt
    assert "CANARY" in txt
    assert "2–4 concurrent" in txt or "2-4 concurrent" in txt
    assert "completion-driven" in txt


def test_shape_b_cross_references_shape_c_doctrine():
    txt = (HARNESS / "blind_instructions_shape_b.md").read_text()
    assert "blind_instructions_shape_c.md" in txt


def test_shape_b_carries_disk_truth_and_transcript_export():
    txt = (HARNESS / "blind_instructions_shape_b.md").read_text()
    assert "Disk truth" in txt or "disk-truth" in txt
    assert "Transcript export is the DEFAULT" in txt


def test_methodology_heading_covers_batch_shapes():
    txt = SKILL.read_text()
    assert "Batch-dispatch ORCHESTRATION RULES — Shapes B/C" in txt
    assert "Shape D is a single project" in txt or "no fan-out" in txt
