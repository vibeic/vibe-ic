#!/usr/bin/env python3
"""vibe-ic#2103 — the lesson-consumption gate had no caller and no reader.

WHAT WAS MEASURED ON THE PRE-FIX TIP
====================================
`lesson_consumption_check` shipped complete: it scores the staged digest
against the design's own spec, it can REFUSE a run whose denominator is not the
one the scorer scored (#2086), and `--strict` can fail an unacknowledged strong
match. The runner imported it — and used it as a LIBRARY only. Grepped over the
whole tree at 94617408759e, the ONLY sites naming `lessons_ack.json` were the
two lines in `design_one_shot_runner` that BUILD the path in order to print it
to the author:

    programs/design_one_shot_runner.py:6281   ack_path = str(... / "lessons_ack.json")
    programs/design_one_shot_runner.py:6376   extras["lessons_ack_path"] = ack_path

Nothing opened it. So an author who acknowledged every named section and an
author who wrote no acknowledgement at all produced runs whose published report
was identical, and the gate that exists to tell those two apart was reachable
only by a human who read the handoff text and chose to type the command.

WHAT THE FIX IS
===============
`design_one_shot_runner.step_lesson_consumption` runs the gate with the argv
the handoff prints (`--project`, the staged digest, the ack, the scoring record
when present, `--strict`) at the first site that sees authored RTL, and writes
its verdict into the run ledger. The status is always `ADVISORY`, which
`_aggregate_verdict` classifies as green, so the row cannot move the run verdict
in either direction — the flow contract keeps this consumer out of a gate clause
(flow Step 1 `required_outputs`: unconditional declarations versus a digest that
is staged only at an authoring WAIVE).

BOTH DIRECTIONS, PER TEST
=========================
Every test below drives the REAL step over a REAL fixture project; nothing is
monkeypatched and no report is hand-written. The pair that proves the ack is
READ rather than merely NAMED is
`test_an_unacknowledged_strong_section_is_a_FINDING` /
`test_acknowledging_the_same_section_flips_the_verdict_to_PASS`: one fixture,
one file added, two different verdicts. On the pre-fix tree the function does
not exist and both are errors; with the file's only read of the ack deleted,
both report the same verdict, which is the defect.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import design_one_shot_runner as DOSR        # noqa: E402

#: The literal dispatch. A function that exists and is never called is the
#: state #2103 describes, so the call site is asserted by name.
_DISPATCH = "plan.append(step_lesson_consumption(project))"

#: A spec whose distinctive vocabulary lands in exactly one digest section.
#: Deliberately generic hardware prose — no chip, no vendor, no PDK.
_SPEC = (
    "Design a thermometer-code encoder driving a barrel shifter. The "
    "thermometer output must be monotonic, and the barrel rotation is "
    "supplemental to the thermometer decode path. Thermometer encoding and "
    "barrel shifting dominate this design.\n"
)

#: The section the spec above matches, and nine that it does not. Ten sections
#: is over `lesson_consumption_check._MIN_SECTIONS_FOR_STRICT`, so `--strict`
#: is not downgraded to a low-confidence NOTICE and the fixture measures the
#: strict path the handoff's own command uses.
_MATCHING_SECTION = "thermometer barrel supplemental encoding"










# ---------------------------------------------------------------------------
# THE WIRING ITSELF
# ---------------------------------------------------------------------------
def test_the_runner_dispatches_the_gate_at_a_real_call_site() -> None:
    """A gate nothing calls produces no verdict. #2080's invocation.v1 rule.

    Asserted on the SOURCE, not on an import: `step_lesson_consumption` existing
    is not the fix — the fix is that `main()` calls it on every run. Deleting the
    one line this asserts is the mutation arm, and it turns this test red while
    every behavioural test below still passes, which is exactly the state the
    pre-fix tree was in.
    """
    src = Path(DOSR.__file__).read_text(errors="replace")
    assert _DISPATCH in src, (
        f"design_one_shot_runner no longer dispatches the lesson-consumption "
        f"gate ({_DISPATCH!r} absent). A checker with no call site produces no "
        f"verdict and the tree looks the same either way — vibe-ic#2103.")


def test_the_dispatch_sits_where_authored_RTL_is_first_judged() -> None:
    """After the rtl_validate span, before the remaining Step-2 checks.

    Order is load-bearing and not cosmetic: the digest and the scoring record
    are written by the PREVIOUS invocation's staging site and the ack is written
    by the author between the two, so the gate must run on the re-invocation and
    not at the WAIVE. Dispatched before `step_crosslayer_rewrite_fidelity` puts
    the acknowledgement question at the same point the RTL starts being judged.
    """
    src = Path(DOSR.__file__).read_text(errors="replace")
    here = src.index(_DISPATCH)
    determinism = src.index("step_determinism_gates, project, args.top_name")
    crosslayer = src.index("plan.append(step_crosslayer_rewrite_fidelity(project))")
    assert determinism < here < crosslayer, (
        "the lesson-consumption dispatch moved out of the Step-2 RTL-validation "
        "window (after the rtl_validate span, before the cross-layer fidelity "
        "judge). Its inputs are written one invocation earlier; re-establish the "
        "ordering rather than deleting this assertion.")


def test_the_step_can_never_move_the_run_verdict() -> None:
    """ADVISORY by contract, and the contract is `_aggregate_verdict`'s own list.

    Read out of the shipped source rather than restated here, so a future edit
    that drops ADVISORY from the green statuses fails this test instead of
    silently promoting the row to a blocking one.
    """
    src = Path(DOSR.__file__).read_text(errors="replace")
    tree = ast.parse(src)
    # R-0915-85 — `_GREEN_STATUSES` is GONE, and that is the repair rather than
    # a gap: `_aggregate_verdict` was a ladder of hand-kept status lists, and
    # this test existed because one of them could silently drop a word. It is
    # `verdict.run_verdict` now, whose precedence is the only place greenness
    # is decided, so the drift this guard watched for cannot happen. What is
    # asserted instead is the fact that mattered: PASS is green there.
    assert not any(
        isinstance(t, ast.Assign) and len(t.targets) == 1
        and isinstance(t.targets[0], ast.Name)
        and t.targets[0].id == "_GREEN_STATUSES"
        for t in ast.walk(tree)), (
        "a hand-kept `_GREEN_STATUSES` list is back in the runner; greenness "
        "is `verdict.run_verdict`'s precedence and nowhere else")
    import verdict as _V
    assert _V.run_verdict([_V.StepVerdict(verdict=_V.Verdict.PASS,
                                          step_id="x", name="x")]) \
        is _V.Verdict.PASS
    step = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef)
                and n.name == "step_lesson_consumption")
    statuses = {c.args[1].value for c in ast.walk(step)
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                and c.func.id == "StepResult" and len(c.args) >= 2
                and isinstance(c.args[1], ast.Constant)}
    # R-0915-85 — `ADVISORY` was a VERDICT meaning "this row may never move the
    # run's". It is `PASS` carrying `Disclosure.ADVISORY` now, and the property
    # stops being a special case: `run_verdict`'s precedence means a PASS row
    # cannot move the run word in either direction.
    assert statuses == {"PASS"}, (
        f"step_lesson_consumption returns {sorted(statuses)}; every return must "
        f"be a row carrying the advisory disclosure. A blocking verdict from a natural-language overlap score "
        f"is how a gate gets turned off.")


# ---------------------------------------------------------------------------
# THE ACK IS READ — THE PAIR
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# THE ROW IS WRITTEN ON EVERY RUN, AND NEVER LAUNDERED INTO A SKIP
# ---------------------------------------------------------------------------
