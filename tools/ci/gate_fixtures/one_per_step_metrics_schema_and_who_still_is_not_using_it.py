"""`one per-step metrics schema, and who still is not using it` — a step
that used the shared emitter stops doing so.

Both arms contain one readable flow step, one declared program and one
non-empty residual.  The only mutation removes the program's import of
``step_metrics`` while the residual continues to name the step as adopted.
That is the ratchet regression the gate owns; neither arm reaches an empty or
missing-input refusal.
"""
import json
from pathlib import Path


GATE = "one per-step metrics schema, and who still is not using it"


_FLOW = """steps:
  - id: 1
    name: synthetic metrics step
    programs:
      - synthetic_stage
"""

_BASELINE = {
    "recorded_by": "step_metrics_adoption_check",
    "adopted": ["1"],
    "not_yet": [],
}


def _tree(work: Path, emits: bool) -> Path:
    root = work / "subject"
    programs = root / "programs"
    flow = root / "flow"
    programs.mkdir(parents=True)
    flow.mkdir(parents=True)
    (flow / "phase1_phase2_phase3.yaml").write_text(
        _FLOW, encoding="utf-8")
    (programs / "synthetic_stage.py").write_text(
        ("import step_metrics\n" if emits else "import json\n"),
        encoding="utf-8")
    (programs / "_step_metrics_adoption_residual.json").write_text(
        json.dumps(_BASELINE, indent=2) + "\n", encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """The declared program still imports the shared emitter: rc 0."""
    return _tree(work, emits=True)


def can_fail(work: Path):
    """Same one-step population; its program stopped importing the emitter."""
    return (_tree(work, emits=False),
            "1 step(s) STOPPED emitting through step_metrics: 1")
