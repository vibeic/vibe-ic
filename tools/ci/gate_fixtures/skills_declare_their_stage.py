"""`skills declare their stage` — a shipped skill whose declaration names no stage.

WHAT THE GATE IS ASKING: every skill the plugin ships must say WHERE IN THE FLOW
it applies — derived from the flow (a step's `skills:` list, or a stage's
`on_pass_review`), or declared under `stage_axis` in
`skills/_classification.json` as a named stage, `stage_all`, or `off_flow`.
A skill placed by none of those is P1 UNPLACED, and P1 is the finding the whole
axis exists to make sayable.

THE MUTATION IS THE ONE THE PROGRAM SAYS IT COULD NOT SEE. `placed` used to test
membership by KEY, so an entry whose `stages` was absent or `[]` counted as
placed — the skill was "placed" because somebody had written its name down. The
program's own P1 comment records the measurement: deleting a shipped skill's
entire `stages` list still returned rc 0 and "no unplaced skill". So `can_fail`
empties ONE list and changes nothing else. That is the UNDECIDED state the
current predicate exists to catch, and it is reported as `declared but naming NO
stage` rather than as a missing entry.

BOTH ARMS CARRY THE SAME DENOMINATOR, and here the cheap reddenings are the ones
to avoid. Deleting the skill folder would shrink `shipped` and prove only that
the gate counts directories; deleting `_classification.json` or the flow yaml
would route to rc 2 (`cannot read input`), which is not a finding. So both arms
ship the SAME three skill folders, the SAME flow, and a `stage_axis` that is
present and well-formed in both. What moves is one list inside it.

ALL THREE PLACEMENT ROUTES ARE EXERCISED, so a repair that broke one of them
could not leave this fixture green: `alpha-probe` is DERIVED from a step's
`skills:` list, `beta-probe` is DECLARED against a named stage, and
`gamma-probe` is DECLARED `off_flow`. The mutated one is the declared-stage
route, which is the only one an editor of `_classification.json` can reach.

THE SUBJECT IS A PLUGIN DIRECTORY because the declaration passes
`--plugin "$PLUGIN"`; the fixture chooses the INPUT and never the ARGV.

chip-AGNOSTIC: three invented skill names and one invented stage, no IC, vendor,
PDK or process.
"""
import json
from pathlib import Path

GATE = "skills declare their stage"

#: Invented names. They must not collide with real skills or real stages,
#: because the point is that the gate reads THIS tree and not the repository's.
_STAGE = "stage_probe"
_DERIVED = "alpha-probe"
_DECLARED = "beta-probe"
_OFF_FLOW = "gamma-probe"
_SKILLS = (_DERIVED, _DECLARED, _OFF_FLOW)

#: A flow with one stage wrapper and one step under it. The step names
#: `alpha-probe`, so that skill is placed BY DERIVATION and needs no entry —
#: which is also what keeps P4 (double declaration) quiet in both arms.
_FLOW = """\
stages:
  - id: {stage}
    name: Synthetic fixture stage
steps:
  - id: step_probe
    name: Synthetic fixture step
    stage: {stage}
    skills:
      - {derived}
""".format(stage=_STAGE, derived=_DERIVED)


def _tree(work: Path, leaf: str, declared_stages) -> Path:
    root = work / leaf
    skills = root / "skills"
    skills.mkdir(parents=True, exist_ok=True)
    flow = root / "flow"
    flow.mkdir(parents=True, exist_ok=True)
    (flow / "phase1_phase2_phase3.yaml").write_text(_FLOW, encoding="utf-8")
    for name in _SKILLS:
        d = skills / name
        d.mkdir(exist_ok=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\n---\n\nSynthetic fixture skill.\n",
            encoding="utf-8")
    (skills / "_classification.json").write_text(
        json.dumps({
            "stage_axis": {
                "stages": {
                    _DECLARED: {
                        "stages": list(declared_stages),
                        "why": "synthetic fixture entry",
                    },
                },
                "off_flow": {
                    _OFF_FLOW: {
                        "stages": ["off_flow"],
                        "why": "synthetic fixture entry",
                    },
                },
            },
        }, indent=2) + "\n", encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """Three skills, each placed by one of the three routes: rc 0."""
    return _tree(work, "accepted", [_STAGE])


def can_fail(work: Path):
    """The same three folders and the same entry, with its `stages` list
    emptied — a declaration that names the skill and says nothing about where
    it applies. Same denominator, opposite answer."""
    root = _tree(work, "refused", [])
    return root, "declared but naming NO stage: ['%s']" % _DECLARED
