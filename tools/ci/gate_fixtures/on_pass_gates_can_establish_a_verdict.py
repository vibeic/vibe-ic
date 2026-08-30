"""`on-pass gates can establish a verdict` — a clause that can only answer rc=2.

THE MUTATION IS ONE FLAG, and that is the whole point of the gate it proves.
`on_pass_review_answerable_check` was written because six shipped clauses
invoked `stage_on_pass_review` with neither `--compliance` nor `--stage-verdict`,
so `stage_passed()` returned UNESTABLISHED and the program returned rc=2 before
any rule was consulted — on every input, forever. Nothing about the stage, the
rule or the engine differs between the two arms below; only whether the
invocation can put the question.

WHY THE FAILING ARM IS NOT A MISSING FILE. rc=2 is also the honest answer for
an unreadable flow, and those two facts are the ones this gate exists to tell
apart. Both arms therefore ship the SAME well-formed flow, with the same stage,
the same enabled clause and the same `gate.program_exit_zero` key — a can_fail
that deleted the flow, the stage or the gate would reach the `cannot read
input` path and would prove only that the check notices an absent subject.

`--stage-verdict` rather than `--compliance` is deliberate: it satisfies P1
without taking on P2, which would additionally require the flow's `final_gate`
to write the named report. A fixture that tripped P2 while trying to prove P1
would be measuring the wrong predicate.

chip-AGNOSTIC: the stage, step and rule names below are synthetic and name no
IC, vendor, SKU or process.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "on-pass gates can establish a verdict"

#: The declared command, minus the verdict source. Both arms build from this.
_BASE = ("stage_on_pass_review . --stage stage_alpha "
         "--json reports/stage_alpha_on_pass_review.json")

#: THE CLAUSE SITS UNDER `steps:`, WHICH IS WHERE THE ENGINE READS IT.
#: It used to sit under `stages[].on_pass_review.gate` — faithful to the
#: shipped flow at the time this fixture was written, and dispatched by
#: nothing. The six clauses were moved into `steps:`; the checker under test
#: now resolves the command from there, so a fixture still declaring it on the
#: stage would present the checker with NO command and fail its own good arm.
_FLOW = """\
stages:
  - id: stage_alpha
    name: the stage whose on-pass review is declared
    on_pass_review:
      skill: a-review-skill
      verdict: advisory
      dispatched_by: "step_one"
steps:
  - id: step_one
    name: the step the stage carries
    stage: stage_alpha
    gate:
      all_of:
        - advisory_program_exit_zero: {command}
"""


def _tree(work: Path, command: str) -> Path:
    root = F.git_init(work / "subject")
    flow = root / "flow"
    flow.mkdir(parents=True, exist_ok=True)
    (flow / "phase1_phase2_phase3.yaml").write_text(
        _FLOW.format(command=command), encoding="utf-8")
    F.git_commit(root)
    return root


def can_pass(work: Path) -> Path:
    """The clause carries a verdict source, so the question can be put."""
    return _tree(work, _BASE + " --stage-verdict PASS")


def can_fail(work: Path):
    """The same clause with the verdict source removed — rc=2 forever."""
    return _tree(work, _BASE), "P1 CANNOT REJECT"
