"""`on-pass declared commands are executed` — the mutation is REACHABILITY.

WHY THE MUTATION IS NOT A FLAG. Its sibling fixture,
`on_pass_gates_can_establish_a_verdict`, opens with "THE MUTATION IS ONE FLAG",
and that is exactly the ceiling this gate exists above. MEASURED on v1.13.54
against the repo's own known-BAD tree `stage3_on_pass_review/reject_sgmii`,
which the pristine clause refuses at rc=1 with R3 proven and its regression
emitted: SIX independent mutations of stage3's declared clause left
`on_pass_review_answerable_check` at rc=0 PASS **and** the whole 14-file on-pass
pytest suite at 304 passed, while `stage_on_pass_review` returned rc=2 NOT
CHECKED on every input, forever —

    --stage stage3 -> stage2 / stage99 / stage5_manufacturing
    the project positional "." -> a directory that does not exist
    --emit-test pointed at an unwritable directory
    a second "--flow-def /dev/null" smuggled into the argv

Every one of them keeps `--compliance <the report final_gate writes>`, so it
satisfies both P1 and P2 of the flag-shaped check. The defect is one level
down, inside `stage_on_pass_review.main()`'s rc=2 ladder: WHICH stage is asked,
WHICH project is read, WHERE the proof is written, WHICH flow is parsed.

THE MUTATION BELOW IS ONE OF THOSE SIX, VERBATIM: `--stage stage3` becomes
`--stage stage99`. Nothing else in the document moves — same flow, same stage
block, same enabled clause, same slot, same `--compliance`, same `--json`. Only
whether the dispatched command can reach the rule it names.

WHY THE FAILING ARM IS NOT A MISSING FILE. rc=1 is also what this gate returns
for an unreadable flow, and those two facts are the ones it exists to tell
apart. Both arms therefore ship THE SAME REAL FLOW DOCUMENT — the shipped
`flow/phase1_phase2_phase3.yaml`, byte-for-byte in the passing arm — so a
can_fail that deleted the flow or the stage would reach the "cannot read input"
path and would prove only that the gate notices an absent subject.

WHAT THE PASSING ARM PROVES, AND IT IS THE HALF THAT IS EASY TO SKIP. The gate
runs each declared command against a published known-GOOD tree as well and
requires rc=0. A "fix" that made every on-pass command refuse everything would
satisfy the failing arm here and fail the passing one. The control is inside
the gate, and this fixture is what keeps it honest.

chip-AGNOSTIC: the flow copied here is the repo's own shipped document; this
file names no IC, vendor, SKU or process.
"""
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "on-pass declared commands are executed"

REAL_FLOW = (Path(__file__).resolve().parents[3]
             / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
             / "flow" / "phase1_phase2_phase3.yaml")

#: The clause the mutation edits, and its mutated form. Written out in full so
#: a reader can see that ONE token moves. Asserted present before the edit: a
#: fixture that silently applied no mutation would make the failing arm pass
#: for the wrong reason.
_PRISTINE = ("stage_on_pass_review . --stage stage3 --json "
             "reports/phase3/gates/stage3_on_pass_review.json "
             "--compliance reports/flow_compliance.json")
_MUTATED = _PRISTINE.replace("--stage stage3", "--stage stage99")


def _tree(work: Path, flow_text: str) -> Path:
    root = F.git_init(work / "subject")
    flow = root / "flow"
    flow.mkdir(parents=True, exist_ok=True)
    (flow / "phase1_phase2_phase3.yaml").write_text(flow_text, encoding="utf-8")
    F.git_commit(root)
    return root


def can_pass(work: Path) -> Path:
    """The shipped flow, unmodified: every declared command reaches a verdict."""
    return _tree(work, REAL_FLOW.read_text(encoding="utf-8"))


def can_fail(work: Path):
    """The same flow with stage3's clause retargeted to a stage that does not
    exist — one of the six mutants both existing nets are blind to."""
    text = REAL_FLOW.read_text(encoding="utf-8")
    assert _PRISTINE in text, (
        "the clause this fixture mutates is not in the shipped flow verbatim; "
        "re-derive it rather than loosening the match — a fixture that mutates "
        "nothing proves nothing")
    return _tree(work, text.replace(_PRISTINE, _MUTATED)), "P1 NOT DISPATCHED"
