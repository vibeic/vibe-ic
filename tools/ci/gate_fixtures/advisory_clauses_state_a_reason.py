"""`advisory clauses state a reason` — an advisory gate that does not say why.

THE MUTATION IS THE MEASURED DEFECT ITSELF. On main at v1.13.61, 76 of the
flow's 228 gate clauses sit in the `advisory_program_exit_zero` slot and NOT
ONE states a reason for being there. A clause wired advisory deliberately and a
clause somebody downgraded to make a red go away print the same way, read the
same way, and are the same bytes to every program in this tree. The can_fail
tree is that state in miniature: a clause in the slot, with nothing said.

BOTH TREES CARRY TWO ADVISORY CLAUSES and the mutation changes ONE of them.
`control_gate` states a real reason and is GREEN IN BOTH DIRECTIONS. Nothing is
added and nothing is deleted between the arms: same flow, same two steps, same
two clauses, same register, same file count — only the four lines of
`subject_gate`'s docstring differ. So the red direction goes red because an
ANSWER changed, and not because the population it walks got smaller. A tree
with no advisory clause at all is rc 2 by this gate's own rule (an empty
denominator is NOT OBSERVED, not PASS), and proving that refusal here would
prove nothing about the predicate under test.

WHY THE MUTATION IS DELETION OF THE DECLARATION AND NOT A PLACEHOLDER. Either
would go red, and the placeholder arms are exercised in the unit tests. The one
worth spending the fixture on is SILENCE, because silence is the state actually
measured on the tree — and because a fixture whose can_fail is a placeholder
would still pass a version of this gate that had lost the ability to notice
that nothing was said at all.

WHY THE REGISTER IS EMPTY IN BOTH ARMS. The register is shrink-only recorded
debt. An entry for `subject_gate` would make the can_fail direction exit 0 —
correctly, that is what recording debt means — so the fixture must not carry
one. An empty `known` list is an explicit MEASUREMENT and the gate accepts it;
a MISSING register is rc 2, which is a third thing and not this test's subject.
"""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "advisory clauses state a reason"

_PLUGIN_REL = Path("vibe-ic-marketplace") / "plugins" / "vibe-ic"

_FLOW = """steps:
  - id: "1"
    name: the control step
    gate:
      advisory_program_exit_zero:
        command: "control_gate . --json out.json"
  - id: "2"
    name: the subject step
    gate:
      advisory_program_exit_zero:
        command: "subject_gate . --json out.json"
"""

#: GREEN IN BOTH DIRECTIONS. Never mutated.
_CONTROL = '''#!/usr/bin/env python3
"""control_gate — the arm that must stay green in both directions.

ADVISORY_REASON: what it reports is a disclosure about the corpus and not a
defect in the design under test, so a run that trips it has produced nothing
wrong and refusing that run would be a false refusal.
"""
'''

#: The arm the mutation changes — WITH its reason.
_SUBJECT_STATED = '''#!/usr/bin/env python3
"""subject_gate — the arm the mutation changes.

ADVISORY_REASON: the metric this gate measures has no producer on any published
run yet, so wiring it blocking would stop every run over debt that is already
recorded and owned somewhere else.
"""
'''

#: The SAME file with the declaration removed. Same length of docstring, same
#: module, same name, same clause — only the sentence that answers WHY is gone.
_SUBJECT_SILENT = '''#!/usr/bin/env python3
"""subject_gate — the arm the mutation changes.

This gate measures whether the metric reaches a producer and reports what it
finds. It is wired into the flow's advisory slot, where its verdict is recorded
and can never stop the step it guards.
"""
'''


def _tree(work: Path, subject: str) -> Path:
    root = work / "subject"
    plugin = root / _PLUGIN_REL
    (plugin / "flow").mkdir(parents=True, exist_ok=True)
    programs = plugin / "programs"
    programs.mkdir(parents=True, exist_ok=True)
    (plugin / "flow" / "phase1_phase2_phase3.yaml").write_text(
        _FLOW, encoding="utf-8")
    (programs / "control_gate.py").write_text(_CONTROL, encoding="utf-8")
    (programs / "subject_gate.py").write_text(subject, encoding="utf-8")
    (programs / "advisory_reason_baseline.json").write_text(
        json.dumps({"_comment": "fixture: an EXPLICITLY EMPTY register is a "
                                "measurement; a missing one is rc 2.",
                    "previous_size": None,
                    "known": []}, indent=2) + "\n", encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """Two advisory clauses, both of which say why they are advisory."""
    return _tree(work, _SUBJECT_STATED)


def can_fail(work: Path):
    """The same two clauses; the second one now says nothing about why."""
    root = _tree(work, _SUBJECT_SILENT)
    return root, "state no reason"
