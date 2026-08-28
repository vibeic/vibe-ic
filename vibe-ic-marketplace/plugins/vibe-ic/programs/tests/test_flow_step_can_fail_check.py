"""A step whose gate cannot fail must be recorded, and the record may only shrink.

Fixtures are synthetic flows — the rule is about gate shape, not about any real
step.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

GATE = Path(__file__).resolve().parent.parent / "flow_step_can_fail_check.py"
yaml = pytest.importorskip("yaml")


def _run(flow: Path):
    p = _pr.run([sys.executable, str(GATE), "--flow", str(flow)],
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def _flow(tmp: Path, steps) -> Path:
    f = tmp / "flow.yaml"
    f.write_text(yaml.safe_dump({"steps": steps}, allow_unicode=True),
                 encoding="utf-8")
    return f


def _baseline():
    """The checker's OWN baseline, read from the module rather than retyped.

    This list used to be typed out in prose below (`P0, 1, 12, 14, 18, 27, 32,
    35`) and used, by hand, to choose fixture ids. The flow then gave step 12 a
    real gate, the baseline correctly SHRANK to drop it — and the copy here did
    not, so `test_a_baseline_entry_that_gained_a_real_gate_forces_the_baseline_
    to_shrink` began seeding step 12 as a weak step that is no longer baselined.
    That is a NEW weak entry, the checker reported it as one, and the `new`
    branch returns before the `fixed` branch ever runs — so the test looked for
    "must shrink" in a message about something else and went red on main, with
    the property it pins never once violated.

    A baseline that may only shrink is exactly the kind of list a second copy
    cannot track. So there is no second copy.
    """
    sys.path.insert(0, str(GATE.parent))
    import flow_step_can_fail_check as mod
    return dict(mod.BASELINE)


def _strong(sid):
    """A step with a criterion that can fail.

    Ids must stay clear of the real baseline: reusing one makes the fixture trip
    the baseline-must-shrink branch, which is the checker working correctly and
    the test asking the wrong question. Asserted against the module's own
    baseline rather than trusted to a comment.
    """
    assert str(sid) not in _baseline(), (
        f"fixture id {sid!r} is a real baseline entry; pick one that is not, "
        f"or this fixture measures the shrink branch by accident")
    return {"id": sid, "name": f"step {sid}",
            "gate": {"program_exit_zero": "some_check"}}


def test_the_real_flow_matches_its_baseline():
    """The shipped flow must agree with the recorded baseline, exactly."""
    rc, out = _run(GATE.parent.parent / "flow" / "phase1_phase2_phase3.yaml")
    assert rc == 0, out
    assert "may only shrink" in out


def test_a_new_step_with_no_gate_fails(tmp_path):
    f = _flow(tmp_path, [_strong(500), {"id": 900, "name": "ungated"}])
    rc, out = _run(f)
    assert rc == 1, out
    assert "no gate key at all" in out


def test_a_new_step_with_only_an_optional_criterion_fails(tmp_path):
    """`optional_` and `advisory_` cannot fail the step, so they cannot gate it."""
    f = _flow(tmp_path, [_strong(500),
                         {"id": 901, "name": "advisory only",
                          "gate": {"optional_program_exit_zero": "x"}}])
    rc, out = _run(f)
    assert rc == 1, out
    assert "only optional_program_exit_zero" in out


def test_files_exist_alone_fails_because_absence_is_not_content(tmp_path):
    """A file a tool wrote with the wrong answer passes a presence check."""
    f = _flow(tmp_path, [_strong(500),
                         {"id": 902, "name": "presence only",
                          "gate": {"files_exist": ["a/b.rpt"]}}])
    rc, out = _run(f)
    assert rc == 1, out
    assert "never on content" in out


def test_a_blocking_criterion_beside_an_optional_one_is_enough(tmp_path):
    """Advisory extras do not weaken a gate that already has a blocking one."""
    f = _flow(tmp_path, [{"id": 903, "name": "mixed",
                          "gate": {"program_exit_zero": "x",
                                   "advisory_program_exit_zero": "y"}}])
    rc, out = _run(f)
    assert rc == 0, out


def test_combinators_are_walked(tmp_path):
    """A blocking criterion nested under all_of/any_of still counts."""
    f = _flow(tmp_path, [{"id": 904, "name": "nested",
                          "gate": {"any_of": [{"files_exist": ["a"]},
                                              {"program_exit_zero": "x"}]}}])
    rc, out = _run(f)
    assert rc == 0, out


def test_the_baseline_is_not_empty():
    """Vacuity guard for the parametrised test below.

    If the baseline ever empties — the goal — the shrink test has no subject and
    would collect zero cases and report green. That must be a deliberate
    decision, announced here, not a silently empty parametrisation.
    """
    assert _baseline(), (
        "the baseline is empty, so the must-shrink branch can no longer be "
        "exercised; delete the gate's shrink logic deliberately or keep a case")


@pytest.mark.parametrize("promoted", sorted(_baseline()))
def test_a_baseline_entry_that_gained_a_real_gate_forces_the_baseline_to_shrink(
        promoted, tmp_path):
    """The half people forget: a fixed entry must leave the record.

    A baseline that never shrinks stops describing anything and becomes a list of
    permissions.

    DERIVED, and now checked for EVERY entry rather than for `P0` alone. The
    fixture is built from the checker's own baseline: every entry is present and
    still weak except `promoted`, which gains a criterion that can fail. So the
    `new` bucket is empty by construction — which is what lets the `fixed`
    branch be reached at all — and the only finding is the one under test.

    Widened on purpose: the hand-typed version asserted the shrink for `P0` and
    nothing else, so an entry that stopped being reported would have gone
    unnoticed. Every entry now has to earn its place.
    """
    baseline = _baseline()
    steps = []
    for sid in baseline:
        if sid == promoted:
            steps.append({"id": sid, "name": "now gated",
                          "gate": {"program_exit_zero": "x"}})
        else:
            # `files_exist` alone is weak for every entry regardless of which
            # shape its recorded reason names, so this keeps the rest of the
            # baseline in `weak` — and therefore out of BOTH findings — without
            # the fixture needing to know why each one was recorded.
            steps.append({"id": sid, "name": "still weak",
                          "gate": {"files_exist": ["a"]}})
    f = _flow(tmp_path, steps)
    rc, out = _run(f)
    assert rc == 1, out
    assert "must shrink" in out, (
        f"promoting {promoted!r} must reach the shrink branch, not the "
        f"new-weak-step branch:\n{out}")
    assert promoted in out, out


def test_stage_containers_are_not_steps(tmp_path):
    """They carry no gate of their own and must not be counted as ungated."""
    f = _flow(tmp_path, [_strong(500),
                         {"id": "stage_2", "name": "Stage 2", "steps": []}])
    rc, out = _run(f)
    assert rc == 0, out


def test_an_empty_flow_is_not_checked_rather_than_passing(tmp_path):
    """A gate that scanned nothing has not passed."""
    f = tmp_path / "empty.yaml"
    f.write_text("steps: []\n", encoding="utf-8")
    rc, out = _run(f)
    assert rc == 2, out
    assert "NOT CHECKED" in out


def test_an_unreadable_flow_is_not_checked(tmp_path):
    rc, out = _run(tmp_path / "does-not-exist.yaml")
    assert rc == 2, out
