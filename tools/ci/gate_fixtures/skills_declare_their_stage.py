"""`skills declare their stage` — a shipped skill that names no stage.

THE MUTATION IS THE UNDECIDED STATE, which is the one this gate was sharpened
to see. `skill_stage_membership_check`'s own P1 comment records that membership
used to be tested by KEY, so an entry whose `stages` was absent or `[]` counted
as placed merely because somebody had written the skill's name down — measured
on the shipped file, deleting a skill's entire `stages` list still returned
rc 0. Placement now requires a NON-EMPTY list, and this is the fixture that
holds that repair to its word.

BOTH ARMS SHIP THE SAME TWO SKILLS under the same declaration file. The corpus
never shrinks: `derived` stays placed by the flow, `declared` keeps its
stage_axis entry, and the only thing that moves is the ANSWER inside that entry
— its stage list goes empty. A can_fail that deleted the skill, the entry or
the classification file would reach the gate's `cannot read input` refusal
(rc 2) and would prove only that it notices an absent input.

BOTH PLACEMENT ROUTES ARE EXERCISED IN THE PASSING ARM, because a gate that
accepted a tree where nothing was placed by derivation would not be reading the
flow at all: `derived` is attached by the step that names it and carries no
stage_axis entry (P4 would refuse the second declaration), while `declared` is
attached only by the axis.

chip-AGNOSTIC: the flow, stages, steps and skills below are synthetic names
with no IC, vendor, SKU or process in them.
"""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "skills declare their stage"

#: Two stages, so the passing arm can place one skill in each and P2 has a real
#: table to check a name against rather than a single-entry one.
_FLOW = """\
stages:
  - id: stage_alpha
  - id: stage_beta
steps:
  - id: step_one
    name: the step that names a skill
    stage: stage_alpha
    skills:
      - derived
"""


def _classification(stages_for_declared):
    return json.dumps(
        {"stage_axis": {"stages": {"declared": {"stages": stages_for_declared}}}},
        indent=2) + "\n"


def _tree(work: Path, stages_for_declared) -> Path:
    root = F.git_init(work / "subject")
    flow = root / "flow"
    flow.mkdir(parents=True, exist_ok=True)
    (flow / "phase1_phase2_phase3.yaml").write_text(_FLOW, encoding="utf-8")
    skills = root / "skills"
    for name in ("derived", "declared"):
        d = skills / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
    (skills / "_classification.json").write_text(
        _classification(stages_for_declared), encoding="utf-8")
    F.git_commit(root)
    return root


def can_pass(work: Path) -> Path:
    """`derived` placed by the flow, `declared` placed by the axis."""
    return _tree(work, ["stage_beta"])


def can_fail(work: Path):
    """The same tree, with `declared`'s stage list emptied — the UNDECIDED state."""
    return _tree(work, []), "P1 UNPLACED"
