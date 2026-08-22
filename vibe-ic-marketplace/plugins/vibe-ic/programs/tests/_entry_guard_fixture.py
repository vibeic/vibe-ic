"""Producer-derived Vibe-IC entry evidence for downstream-gate tests.

These tests exercise gates that run *after* ``vibe_ic_entry_guard``.  Their
fixture must therefore carry the real Phase-1 prompt envelope instead of the
historical empty-file / ``{"verdict":"PASS"}`` marker.  Step rows and verdict
aggregation come from the shipped producer so schema changes cannot silently
leave a hand-copied weak marker behind.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import _plugin_tree  # noqa: F401  — puts programs/ on sys.path
from phase1_one_shot_runner import StepResult, _aggregate_verdict


def prompt_report_document(project: Path) -> dict:
    project = Path(project).resolve()
    steps = [
        StepResult("phase1_ingest_render", "PASS", 0.01,
                   "facts=facts.yaml out=generated_docs"),
        StepResult("phase1_human_docs", "PASS", 0.01,
                   "9 human MD docs"),
    ]
    return {
        "phase": 1,
        "mode": "prompt",
        "project": str(project),
        "ic_name": "TopModule",
        "steps": [asdict(step) for step in steps],
        "verdict": _aggregate_verdict(steps),
        "second_track": "ran",
    }


def write_prompt_report(project: Path) -> Path:
    project = Path(project).resolve()
    # This is the exact path phase1_one_shot_runner writes in both modes.
    path = project / "reports" / "phase1_one_shot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(prompt_report_document(project), indent=2) + "\n")
    return path
