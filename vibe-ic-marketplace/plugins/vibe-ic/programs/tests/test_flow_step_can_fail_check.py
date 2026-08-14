"""A step whose gate cannot fail must be recorded, and the record may only shrink.

Fixtures are synthetic flows — the rule is about gate shape, not about any real
step.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parent.parent / "flow_step_can_fail_check.py"
yaml = pytest.importorskip("yaml")


def _gate_baseline():
    """The checker's OWN `BASELINE`, read from the module under test.

    Restating the baseline here is what rotted: the fixture below and
    `_strong`'s docstring both listed step 12, which has since LEFT `BASELINE`
    (it gained a criterion that can fail). A step that is not in the baseline is
    a NEW weak step, and `main()` returns on that branch BEFORE it can reach the
    must-shrink branch, so the test failed on the wrong message and never
    exercised the behaviour it is named for. Reading the real dict means this
    file cannot disagree with the checker again.
    """
    spec = importlib.util.spec_from_file_location(
        "_flow_step_can_fail_check_under_test", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return dict(mod.BASELINE)


_BASELINE = _gate_baseline()


def _weak_gate_for(reason: str):
    """A gate whose SHAPE matches the weakness the baseline records, so the
    fixture reproduces what the record actually describes rather than a
    look-alike."""
    if "optional_program_exit_zero" in reason:
        return {"optional_program_exit_zero": "x"}
    return {"files_exist": ["a"]}


def _sid(key: str):
    """Baseline keys are strings; the flow spells numeric ids as ints."""
    return int(key) if key.isdigit() else key


def _run(flow: Path):
    p = subprocess.run([sys.executable, str(GATE), "--flow", str(flow)],
                       capture_output=True, text=True, timeout=30)
    return p.returncode, p.stdout + p.stderr


def _flow(tmp: Path, steps) -> Path:
    f = tmp / "flow.yaml"
    f.write_text(yaml.safe_dump({"steps": steps}, allow_unicode=True),
                 encoding="utf-8")
    return f


def _strong(sid):
    """A step with a criterion that can fail.

    Ids here must stay clear of the real baseline, whatever it currently holds:
    reusing one makes the fixture trip the baseline-must-shrink branch, which is
    the checker working correctly and the test asking the wrong question. The
    guard below reads `_BASELINE` rather than restating it, so this cannot drift
    out of step with the checker the way the old hard-coded list did.
    """
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


def test_a_baseline_entry_that_gained_a_real_gate_forces_the_baseline_to_shrink(tmp_path):
    """The half people forget: a fixed entry must leave the record.

    A baseline that never shrinks stops describing anything and becomes a list of
    permissions.
    """
    assert "P0" in _BASELINE, (
        "this test needs a baseline entry to promote; the checker's baseline no "
        f"longer contains P0 (has {sorted(_BASELINE)})")

    # Every OTHER baseline entry stays weak, so `new` is empty and the run
    # reaches the must-shrink branch instead of returning on the new-weak one.
    steps = [{"id": "P0", "name": "now gated",
              "gate": {"program_exit_zero": "x"}}]
    steps += [{"id": _sid(k), "name": "still weak",
               "gate": _weak_gate_for(v)}
              for k, v in _BASELINE.items() if k != "P0"]

    rc, out = _run(_flow(tmp_path, steps))
    # Harness assertion: prove the fixture reached the intended branch. Without
    # it, a single stray non-baseline id silently sends the run down the
    # new-weak branch and the test reports the wrong thing — which is exactly
    # how this test was red.
    assert "gained a gate that cannot fail" not in out, (
        f"fixture leaked a NEW weak step, so the run never reached the "
        f"must-shrink branch: {out}")
    assert rc == 1, out
    assert "must shrink" in out, out
    assert "P0" in out

    # NEGATIVE CONTROL: with P0 still weak nothing has been fixed, so the
    # baseline must NOT be asked to shrink. Without this arm the assertions
    # above would pass against a checker that demanded a shrink unconditionally.
    steps_unfixed = [{"id": _sid(k), "name": "still weak",
                      "gate": _weak_gate_for(v)}
                     for k, v in _BASELINE.items()]
    unfixed_dir = tmp_path / "unfixed"
    unfixed_dir.mkdir()
    rc2, out2 = _run(_flow(unfixed_dir, steps_unfixed))
    assert rc2 == 0, out2
    assert "must shrink" not in out2, out2


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
