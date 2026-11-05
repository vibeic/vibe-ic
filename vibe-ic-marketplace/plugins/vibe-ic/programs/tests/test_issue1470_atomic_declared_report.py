"""The atomic-artefact ratchet is GREEN on main again — vibe-ic#1470.

WHAT #1470 IS ACTUALLY ABOUT
===========================
The issue was filed as "a ratchet shipped without its baseline file". That
reading is refuted by the tree: `programs/_atomic_artefact_residual.json` is
committed, `tools/ci/repo_hygiene_gates.sh` wires the check at top level and
unconditionally, and `gate_red_since.json` carries no acknowledgement row that
would soften it. So the baseline exists and is honoured.

What is REAL is the consequence the issue predicted from the other end: the
gate is a hard failure on main, and it was failing. Not on the 576 phantom
regressions an absent baseline would have manufactured — on a handful of
GENUINE post-baseline ones. Two programs landed after the residual was measured
and wrote their declared report destination with `Path(...).write_text(...)`:

    generated_artifact_conflict_resolve.py:391  .write_text(...)
    hygiene_finding_delta.py:420  .write_text(...)

Both are verdict-bearing. `generated_artifact_conflict_resolve` writes a
RESOLVED/REFUSED/UNMEASURABLE verdict a landing acts on; `hygiene_finding_delta`
writes the subset comparison that BLOCKS a landing. A truncated one of those is
read downstream as the step's own evidence — exactly the lie #1082 exists to
remove — so the fix is to convert them, never to widen the register.

WHY THE REGISTER IS NOT TOUCHED, AND WHY THAT IS ASSERTED HERE
==============================================================
Adding these two names to `_atomic_artefact_residual.json` would also have made
the gate exit 0. It would have bought the green by making the rule smaller,
which is worse than the failure it hides: the residual "may only ever shrink"
is the whole ratchet. `test_the_green_was_not_bought_by_widening_the_register`
is the assertion that pins that, so the cheap fix cannot be reintroduced later
and still look like this one.

AND THE PROPERTY IS CHECKED AT RUNTIME, NOT ONLY AS A SHAPE
===========================================================
Every other test around #1082 checks the SHAPE of the source — that no
`.write_text` reaches a declared destination. A shape assertion cannot tell a
converted program from one whose writer no longer runs. So the two runtime
tests below drive both real programs end to end and check the invariant the
issue is actually about, in both directions:

    the write succeeds  -> the declared destination exists and parses
    the write dies      -> the declared destination DOES NOT EXIST at all,
                           and no temp sibling is left behind

The second is only a measurement because the first exists: a program that wrote
nothing under any circumstances would satisfy "absent after a death" for free.

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _atomic_artefact as A  # noqa: E402
import generated_artifact_conflict_resolve as RESOLVER  # noqa: E402
import hygiene_finding_delta as DELTA  # noqa: E402
import skill_stage_membership_check as MEMBERSHIP  # noqa: E402
import advisory_clause_states_its_reason as ADVISORY  # noqa: E402
import stage_on_pass_review as REVIEW  # noqa: E402

PROGRAMS = Path(__file__).resolve().parent.parent
BASELINE = PROGRAMS / "_atomic_artefact_residual.json"

#: The programs #1470 is about, pinned BY NAME. A count alone would also be
#: satisfied by deleting them, and by any later program regressing in their
#: place.
#:
#: `stage_on_pass_review` is the THIRD, and it arrived the same way as the
#: first two: it landed after the residual was measured, so the register could
#: not excuse it and the ratchet named it on sight —
#: `stage_on_pass_review.py:572  .write_text(...)`, MEASURED on clean main
#: 7d059e03b (v1.12.93) as the one and only new offender. Its `emit()` writes
#: the review's VERDICT (NOT_CHECKED with its reason, or the rejections a
#: landing acts on), which is exactly the class the other two are in.
#: `skill_stage_membership_check` is the FOURTH, and it arrived exactly as the
#: third did: it landed at v1.12.99 (f9c86fe03) AFTER the residual was measured,
#: so the register could not excuse it and the ratchet named it on sight —
#: `skill_stage_membership_check.py:278  .write_text(...)`, MEASURED on clean
#: main 6c798ce4be (v1.13.3) as the one and only new offender. Its `main()`
#: writes `verdict` plus the findings a caller acts on, which is the same class
#: as the other three.
#:
#: `advisory_clause_states_its_reason` is the FIFTH, and it arrived by the same
#: door as the third and fourth: it landed after the residual was measured, so
#: the register could not excuse it and the ratchet named it on sight —
#: `advisory_clause_states_its_reason.py:685  .write_text(...)`, MEASURED on
#: the 2026-08-31 stamp tree 411c0ac73 (v1.14.43) as the one and only new
#: offender, with the residual at 513 against a baseline of 514. Its `main()`
#: writes the census plus `new`/`paid` — the debt a landing is judged on — so
#: it is the same verdict-bearing class as the other four.
#:
#: FIVE programs in five versions is the rate, and it is worth naming: this
#: register does not go stale because anyone edits it, it goes stale because
#: the tree keeps growing programs that write a declared report. The ratchet
#: catching each one BY NAME is the mechanism working, not a defect in it.
CONVERTED = ["generated_artifact_conflict_resolve", "hygiene_finding_delta",
             "stage_on_pass_review", "skill_stage_membership_check",
             "advisory_clause_states_its_reason"]

#: The register's size at the tranche that last pulled it down (#1082's
#: `open(..., 'w')` closure). It may SHRINK below this; growing past it is the
#: ratchet slipping.
REGISTER_CEILING = 515

_SYNTHETIC_OFFENDER = '''\
import argparse
import json
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args()
    Path(a.json_out).write_text(json.dumps({"verdict": "PASS"}), encoding="utf-8")
'''












#: (label, module, argv-builder). Driven end to end in both runtime tests.
DRIVEN = [
    ("generated_artifact_conflict_resolve", RESOLVER, _argv_resolver),
    ("hygiene_finding_delta", DELTA, _argv_delta),
    ("stage_on_pass_review", REVIEW, _argv_review),
    ("skill_stage_membership_check", MEMBERSHIP, _argv_membership),
    ("advisory_clause_states_its_reason", ADVISORY, _argv_advisory),
]








def test_the_green_was_not_bought_by_widening_the_register():
    """Adding these names to the residual would ALSO have exited 0.

    That is the failure mode this repo keeps paying for: a gate turned green by
    shrinking the rule. The register must not name them, and must not have
    grown to make room for them.
    """
    recorded = set(json.loads(BASELINE.read_text(encoding="utf-8"))["offenders"])
    assert len(recorded) <= REGISTER_CEILING, len(recorded)
    for s in CONVERTED:
        assert f"{s}.py" not in recorded, (
            f"{s} was excused into the residual instead of converted")






def test_the_form_this_replaced_really_did_leave_a_file(tmp_path):
    """The CONTRAST, so the test above is a difference and not a tautology.

    Same failure, same payload, the two forms side by side on a real
    filesystem. `Path.write_text` creates the final name and fills it second,
    so the name survives the failure with incomplete contents; the helper
    leaves nothing. `_atomic_artefact`'s own docstring names this: a 0-byte
    file and a finished report are the same answer to `required_outputs`.
    """
    # Encodable prefix, then one code point utf-8 cannot emit: the encoder
    # raises with the destination already opened.
    payload = "x" * 200_000 + "\udcff"

    old = tmp_path / "old_form.json"
    try:
        old.write_text(payload, encoding="utf-8")
    except UnicodeEncodeError:
        pass
    assert old.exists(), (
        "the pre-fix form no longer leaves a file under the final name — this "
        "control no longer models the defect and must be re-derived")
    assert old.stat().st_size < len(payload), "expected an INCOMPLETE artefact"

    new = tmp_path / "new_form.json"
    try:
        A.write_text(new, payload)
    except UnicodeEncodeError:
        pass
    assert not new.exists(), "the helper left a final name after a failed write"
    assert not [p for p in tmp_path.iterdir() if A.is_temp_artefact(p)]
