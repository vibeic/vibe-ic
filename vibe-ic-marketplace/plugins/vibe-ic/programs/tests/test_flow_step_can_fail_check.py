"""A step whose gate cannot fail must be recorded, and the record may only shrink.

Fixtures are synthetic flows — the rule is about gate shape, not about any real
step.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parent.parent / "flow_step_can_fail_check.py"
yaml = pytest.importorskip("yaml")


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

    Ids here stay clear of the real baseline (P0, 1, 12, 14, 18, 27, 32, 35):
    reusing one makes the fixture trip the baseline-must-shrink branch, which is
    the checker working correctly and the test asking the wrong question.
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
    f = _flow(tmp_path, [{"id": "P0", "name": "now gated",
                          "gate": {"program_exit_zero": "x"}},
                         {"id": 14, "name": "still weak",
                          "gate": {"optional_program_exit_zero": "x"}},
                         {"id": 1, "name": "still weak",
                          "gate": {"files_exist": ["a"]}},
                         # step 12 is deliberately NOT here: `018be73dc` removed it
                         # from BASELINE when it gained a real gate. A weak step that
                         # is not in BASELINE is a NEW offender, and that branch
                         # returns before the shrink branch — so leaving it in makes
                         # this test assert the wrong message and hides the property.
                         {"id": 18, "name": "w", "gate": {"files_exist": ["a"]}},
                         {"id": 27, "name": "w", "gate": {"files_exist": ["a"]}},
                         {"id": 32, "name": "w", "gate": {"files_exist": ["a"]}},
                         {"id": 35, "name": "w", "gate": {"files_exist": ["a"]}}])
    rc, out = _run(f)
    assert rc == 1, out
    assert "must shrink" in out
    assert "P0" in out


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
