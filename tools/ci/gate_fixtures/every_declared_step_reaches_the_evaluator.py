"""`every declared step reaches the evaluator` — a step nobody hands over.

THE MUTATION IS THE MEASURED DEFECT. On the 68x9 matrix (plugin v1.12.33),
removing what hands the executor its gate dict for step 21 left dimension D1
green — 86 passed — because D1's observation point is inside `_evaluate_gate`
and its test supplies the caller. On a real project the step vanished from the
tally, MISSING dropped 40 -> 39, and 18 steps that were blocked-by-upstream
silently unblocked.

BOTH TREES ARE THE REAL TREE. Every file is symlinked from it except the
evaluator, which is a real, patched copy in both directions — the can-pass arm
carries an edit that changes nothing (a no-op filter that drops no id) so the
two subjects differ in exactly one thing: whether the evaluator receives step
21. Same flow, same declaration count, same evaluator otherwise.
"""
from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "every declared step reaches the evaluator"

_SEAM = 'steps = flow.get("steps", [])'
_DROPPED_STEP = "21"


def _tree(work: Path, drop: str) -> Path:
    """The real plugin, with an evaluator that drops `drop` (or drops nothing)."""
    root = work / "subject"
    plugin = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    plugin.mkdir(parents=True, exist_ok=True)
    real_plugin = F.PROGRAMS.parent
    for child in real_plugin.iterdir():
        if child.name != "programs":
            os.symlink(child, plugin / child.name)
    programs = plugin / "programs"
    programs.mkdir(exist_ok=True)
    for child in F.PROGRAMS.iterdir():
        if child.name != "flow_compliance_check.py":
            os.symlink(child, programs / child.name)
    text = (F.PROGRAMS / "flow_compliance_check.py").read_text(encoding="utf-8")
    if text.count(_SEAM) != 1:
        raise AssertionError("the seam this fixture edits has moved; "
                             "re-derive it before trusting either arm")
    patched = text.replace(
        _SEAM,
        _SEAM + f'\n    steps = [s for s in steps if str(s.get("id")) != "{drop}"]')
    (programs / "flow_compliance_check.py").write_text(patched, encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """The same patched evaluator, dropping an id no flow step carries."""
    return _tree(work, "__no_such_step_id__")


def can_fail(work: Path):
    """The evaluator stops receiving one declared step."""
    return _tree(work, _DROPPED_STEP), "is declared by the flow and never"
