"""Entry-report input data for downstream blindness and score-gate tests."""
from __future__ import annotations

import json
from pathlib import Path

import _plugin_tree  # noqa: F401  — puts programs/ on sys.path


def prompt_report_document(project: Path) -> dict:
    project = Path(project).resolve()
    steps = [
        {"name": "phase1_ingest_render", "status": "PASS", "duration_s": 0.01,
         "detail": "facts=facts.yaml out=generated_docs", "extras": {}},
        {"name": "phase1_human_docs", "status": "PASS", "duration_s": 0.01,
         "detail": "9 human MD docs", "extras": {}},
    ]
    return {
        "phase": 1,
        "mode": "prompt",
        "project": str(project),
        "ic_name": "TopModule",
        "steps": steps,
        "verdict": "PASS",
        "second_track": "ran",
    }


def write_prompt_report(project: Path) -> Path:
    project = Path(project).resolve()
    # This is the exact path phase1_one_shot_runner writes in both modes.
    path = project / "reports" / "phase1_one_shot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(prompt_report_document(project), indent=2) + "\n")
    return path
