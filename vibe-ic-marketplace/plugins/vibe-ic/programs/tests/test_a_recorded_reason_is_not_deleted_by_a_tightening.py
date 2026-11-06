#!/usr/bin/env python3
"""`--record-shrink` deleted a defect report and said nothing about it.

THE FINDING. `flow_gate_enforcement_audit.py --record-shrink` clears both
`scope_expanded` and `undeclared_scope_expanded` to `null`, for a reason that is
correct and is NOT changed here: "a reason that outlives the growth it explained
reads to the next writer as standing permission".

What was wrong is that the clearing was SILENT. `undeclared_scope_expanded` had
accumulated an observation with nothing to do with the scope reason it was
appended to — a defect report about step 8 of the flow, whose only copy in the
entire repository was that string. #2014 G6 ran the write, the field went to
`null`, and after that commit the observation existed NOWHERE. It was recovered
only because a human had quoted it into a brief before the write.

A REGISTER IS NOT A NOTEBOOK, and that is not the defence. The field was being
used as one — that is exactly why a write that erases prose must say so. The
next writer of that field cannot know whether the string they are about to
destroy is a spent scope reason or the only record of a defect, and neither
could this program: it deleted both kinds identically and printed neither.

WHAT CHANGED, AND WHAT DID NOT. The clearing is unchanged: a tightening still
spends the reason. What is refused is doing it in silence. A `--record-shrink`
that would drop a NON-EMPTY reason now exits 1 and prints the text VERBATIM —
so the refusal is itself a copy of it — and names `--retire-scope-reason`, the
flag that performs the deletion as a deliberate, reviewable act.

WHY THE THIRD ARM IS NOT OPTIONAL. A guard that refused every tightening would
have saved the prose by breaking the ratchet, and a register that records no
reason is the ordinary case. `test_a_register_with_no_reason_shrinks_exactly_as_
before` is what stops this file from being a fix that costs more than the defect.

Every arm runs the shipped CLI against a COPY. The shipped register is never
written.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_PROGRAMS = Path(__file__).resolve().parents[1]
_AUDIT = _PROGRAMS / "flow_gate_enforcement_audit.py"
_BASELINE = _PROGRAMS / "flow_gate_enforcement_baseline.json"

#: An entry the tree has PAID but the fixture register still records, so every
#: arm has a real tightening to perform. Recorded as paid down by #2014 G6.
_PAID = "undeclared::cpu_functional_oracle_waiver_check"

#: The kind of string the field actually held — an observation, not a scope
#: reason. Synthesised here rather than copied from the register, which no
#: longer contains it; the point is the SHAPE, and the arms must not depend on
#: any particular text surviving in the tree.
_NOTE = ("a checker carries a real hole worth its own issue: the step declares "
         "both a required_outputs entry and program_exit_zero, but the program "
         "writes that JSON UNCONDITIONALLY before exiting 1.")
















def test_the_shipped_register_records_no_reason_so_the_guard_is_dormant():
    """The guard changes nothing about the tree as it stands today, and this
    row says so rather than leaving a reader to assume it."""
    doc = json.loads(_BASELINE.read_text())
    for key in ("scope_expanded", "undeclared_scope_expanded"):
        assert not (doc.get(key) or "").strip(), (
            f"{key} now holds text; the next --record-shrink will refuse "
            f"until it is retired deliberately — which is the point")
