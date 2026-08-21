"""Recompute what is decidable; say plainly what is not.

Synthetic flows — the rules are about declaration shape, not any real step.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

GRID = Path(__file__).resolve().parent.parent / "flow_gate_grid.py"
yaml = pytest.importorskip("yaml")
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("fgg", GRID)
fgg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fgg)


def _flow(tmp: Path, steps) -> Path:
    f = tmp / "flow.yaml"
    f.write_text(yaml.safe_dump({"steps": steps}, allow_unicode=True),
                 encoding="utf-8")
    return f


def _run(flow: Path, programs: Path):
    p = subprocess.run([sys.executable, str(GRID), "--flow", str(flow),
                        "--programs", str(programs)],
                       capture_output=True, text=True, timeout=30)
    return p.returncode, p.stdout + p.stderr


# ------------------------------------------------------- D1, and its trap

def test_a_criterion_naming_a_missing_program_is_found(tmp_path):
    steps = [{"id": 9, "name": "x",
              "gate": {"program_exit_zero": "no_such_program --json a.json"}}]
    rc, out = _run(_flow(tmp_path, steps), tmp_path)
    assert rc == 1, out
    assert "no_such_program.py" in out


def test_the_conditional_form_is_parsed_by_its_command_not_its_keys():
    """THE trap. `optional_program_exit_zero` may be
    {command: ..., condition_files_exist: [...]}; reading the dict's KEYS as
    program names yields `command.py` / `condition_files_exist.py`, which
    resolve to nothing and report 14 clean steps as broken. Measured — that was
    the first cut of this file."""
    got = fgg.program_targets({"command": "real_check . --json r.json",
                               "condition_files_exist": ["a/b.json"]})
    assert got == ["real_check"]


def test_a_plain_string_and_a_list_both_parse():
    assert fgg.program_targets("some_check --flag") == ["some_check"]
    assert fgg.program_targets(["a --x", "b"]) == ["a", "b"]


def test_a_criterion_naming_a_real_program_passes(tmp_path):
    (tmp_path / "real_one.py").write_text("", encoding="utf-8")
    steps = [{"id": 9, "name": "x", "gate": {"program_exit_zero": "real_one"}}]
    rc, out = _run(_flow(tmp_path, steps), tmp_path)
    assert "D1 wiring" not in out, out


# ------------------------------------------------------- D6

def test_a_condition_without_a_kind_is_found(tmp_path):
    """The consumer branches on `condition_kind` and nothing sets it, so the
    `setup_required` path is unreachable and every skip is benign by default."""
    steps = [{"id": 900, "name": "x", "condition": "files_exist: a/b.json",
              "gate": {"program_exit_zero": "p"}}]
    rc, out = _run(_flow(tmp_path, steps), tmp_path)
    assert "D6 skip" in out, out
    assert "900" in out


def test_a_condition_with_a_kind_is_clean(tmp_path):
    (tmp_path / "p.py").write_text("", encoding="utf-8")
    steps = [{"id": 900, "name": "x", "condition": "files_exist: a/b.json",
              "condition_kind": "design_dependent",
              "gate": {"program_exit_zero": "p"}}]
    rc, out = _run(_flow(tmp_path, steps), tmp_path)
    assert "D6 skip" not in out, out


def test_a_baseline_entry_that_gained_a_kind_forces_the_baseline_to_shrink(tmp_path):
    (tmp_path / "p.py").write_text("", encoding="utf-8")
    steps = [{"id": "A1", "name": "x", "condition": "c",
              "condition_kind": "design_dependent",
              "gate": {"program_exit_zero": "p"}}]
    rc, out = _run(_flow(tmp_path, steps), tmp_path)
    assert "must shrink" in out, out


# ------------------------------------------------------- D8

def test_outputs_with_no_catcher_are_found(tmp_path):
    """A declared output nothing would miss."""
    steps = [{"id": 901, "name": "x", "required_outputs": ["r/a.rpt"],
              "gate": {"optional_program_exit_zero": "p"}}]
    rc, out = _run(_flow(tmp_path, steps), tmp_path)
    assert "D8 catcher" in out, out
    assert "901" in out


def test_files_exist_is_a_catcher(tmp_path):
    steps = [{"id": 901, "name": "x", "required_outputs": ["r/a.rpt"],
              "gate": {"files_exist": ["r/a.rpt"]}}]
    rc, out = _run(_flow(tmp_path, steps), tmp_path)
    assert "D8 catcher" not in out, out


# ------------------------------------------------------- honesty

def test_the_underivable_dimensions_are_named_with_reasons(tmp_path):
    """Reporting a dimension as NOT DERIVABLE is the point, not a gap — it is
    what stops the page claiming those cells are live."""
    (tmp_path / "p.py").write_text("", encoding="utf-8")
    rc, out = _run(_flow(tmp_path, [{"id": "D1", "name": "x",
                                     "gate": {"program_exit_zero": "p"}}]),
                   tmp_path)
    for d in ("D3 outputs", "D4 criteria", "D7 list"):
        assert d in out, out
    assert "NOT DERIVABLE FROM SOURCE" in out


def test_it_reports_how_many_cells_it_recomputed(tmp_path):
    """Three, not five: `--programs` points at a directory holding neither
    delegate, so two dimensions were not recomputed and are not counted."""
    (tmp_path / "p.py").write_text("", encoding="utf-8")
    rc, out = _run(_flow(tmp_path, [{"id": "D1", "name": "x",
                                     "gate": {"program_exit_zero": "p"}}]),
                   tmp_path)
    assert "recomputed 3 of 8 cells" in out, out


def test_an_empty_flow_is_not_checked(tmp_path):
    f = tmp_path / "e.yaml"
    f.write_text("steps: []\n", encoding="utf-8")
    rc, out = _run(f, tmp_path)
    assert rc == 2, out
    assert "NOT CHECKED" in out


def test_an_absent_delegate_is_named_and_not_counted(tmp_path, monkeypatch):
    """The headline says how many cells were recomputed. If a delegate is not
    present, counting its dimension anyway would be the exact defect this grid
    exists to remove — a number produced by not looking.
    """
    (tmp_path / "p.py").write_text("", encoding="utf-8")
    flow = _flow(tmp_path, [{"id": "D1", "name": "x",
                             "gate": {"program_exit_zero": "p"}}])
    # --programs points at a directory holding neither delegate
    rc, out = _run(flow, tmp_path)
    assert "NOT RECOMPUTED" in out, out
    assert "recomputed 3 of 8 cells" in out, out
    assert rc == 1, out


def _stub_delegates(d, rc, text="stub"):
    """Write both delegates into ``d`` as programs that exit ``rc``."""
    for nm in ("flow_step_can_fail_check.py", "flow_dependency_graph_check.py"):
        (d / nm).write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            f"print({nm!r} + ': {text}')\n"
            f"sys.exit({rc})\n",
            encoding="utf-8")


def test_a_delegate_that_answers_rc2_is_not_counted_as_recomputed(tmp_path):
    """The other half of the no-answer guard, and the half that was missing.

    ``test_an_absent_delegate_is_named_and_not_counted`` covers rc=3 — the file
    is not there. This covers rc=2 — the delegate IS there, runs, and answers
    "NOT CHECKED". Both delegates return 2 when pyyaml is unavailable or the
    flow yields no steps, so this is an ordinary condition.

    On the unfixed program the run printed ``recomputed 5 of 8 cells``, listed
    no problem and exited 0: the dimension was counted on the strength of a
    delegate that explicitly declined to answer.
    """
    (tmp_path / "p.py").write_text("", encoding="utf-8")
    _stub_delegates(tmp_path, 2, "rc=2 NOT CHECKED")
    flow = _flow(tmp_path, [{"id": "D1", "name": "x",
                             "gate": {"program_exit_zero": "p"}}])
    rc, out = _run(flow, tmp_path)
    assert "NO ANSWER (rc=2)" in out, out
    assert "recomputed 3 of 8 cells" in out, out
    assert rc == 1, out


def test_a_delegate_that_answers_is_still_counted(tmp_path):
    """Guard the guard: the exclusion above must not swallow real answers.

    A no-answer rule that also drops rc=0 and rc=1 would make the grid
    permanently under-report and the test above would still pass. rc=0 is an
    answer ("looked, clean") and must keep its dimension in the count.
    """
    (tmp_path / "p.py").write_text("", encoding="utf-8")
    _stub_delegates(tmp_path, 0, "clean")
    flow = _flow(tmp_path, [{"id": "D1", "name": "x",
                             "gate": {"program_exit_zero": "p"}}])
    rc, out = _run(flow, tmp_path)
    assert "NO ANSWER" not in out, out
    # The count, not the exit code: a one-step fixture also trips the unrelated
    # D6/D8 baseline-shrink notices, so rc here would assert something this test
    # is not about.
    assert "recomputed 5 of 8 cells" in out, out


def test_the_flow_argument_reaches_the_delegates(tmp_path):
    """``--flow`` is presented as selecting the flow for all five recomputed
    dimensions. It was dropped for the two delegated ones, which both accept
    it, so pointing the grid at a flow recomputed 3 of 5 against that file
    while the headline claimed 5.
    """
    (tmp_path / "p.py").write_text("", encoding="utf-8")
    # Always exit 1, so the delegate's last line is echoed by the caller and the
    # forwarded argument becomes observable in the output.
    for nm in ("flow_step_can_fail_check.py", "flow_dependency_graph_check.py"):
        (tmp_path / nm).write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "a = sys.argv[1:]\n"
            "print('GOTFLOW ' + a[a.index('--flow') + 1]\n"
            "      if '--flow' in a else 'NOFLOW')\n"
            "sys.exit(1)\n",
            encoding="utf-8")
    flow = _flow(tmp_path, [{"id": "D1", "name": "x",
                             "gate": {"program_exit_zero": "p"}}])
    rc, out = _run(flow, tmp_path)
    assert "NOFLOW" not in out, out
    assert f"GOTFLOW {flow}" in out, out


def test_a_deleted_baselined_step_is_not_reported_as_fixed(tmp_path):
    """Deleting the evidence and repairing the defect must not look the same.

    ``fixed6``/``fixed8`` were ``BASELINE - still_defective``. A step removed
    from the flow drops out of ``still_defective`` for the same reason a
    repaired one does, so a deletion printed "left the baseline. Good news"
    together with an instruction to shrink the baseline — which would erase the
    record that the step ever owed anything.
    """
    (tmp_path / "p.py").write_text("", encoding="utf-8")
    _stub_delegates(tmp_path, 0, "clean")
    # step "14" is in D8_BASELINE; a flow that does not contain it at all
    flow = _flow(tmp_path, [{"id": "D1", "name": "x",
                             "gate": {"program_exit_zero": "p"}}])
    rc, out = _run(flow, tmp_path)
    assert "NO LONGER EXISTS in the flow" in out, out
    assert "14" in out, out
    # and it must NOT be dressed up as good news
    fixed_lines = [ln for ln in out.splitlines()
                   if "left the baseline" in ln and "D8" in ln]
    assert not fixed_lines, f"a deleted step was announced as fixed: {fixed_lines}"
    assert rc == 1, out


def test_a_genuinely_repaired_baselined_step_is_still_reported_as_fixed(tmp_path):
    """Guard the guard: the deletion arm must not swallow real repairs.

    Excluding absent steps from ``fixed`` would be worthless if it also
    excluded steps that are present and clean — the baseline would then never
    be allowed to shrink, and the test above would still pass.
    """
    (tmp_path / "p.py").write_text("", encoding="utf-8")
    _stub_delegates(tmp_path, 0, "clean")
    # step "14" PRESENT, with a criterion that would catch a missing output,
    # so it is no longer a D8 finding: repaired, not deleted.
    flow = _flow(tmp_path, [
        {"id": "D1", "name": "x", "gate": {"program_exit_zero": "p"}},
        {"id": "14", "name": "y", "required_outputs": ["out.txt"],
         "gate": {"files_exist": ["out.txt"]}},
    ])
    rc, out = _run(flow, tmp_path)
    # Scoped to D8. A tiny fixture necessarily omits D6's 22 baselined steps,
    # so D6 correctly reports them as gone; asserting on the whole output would
    # be asserting on the fixture's size rather than on the behaviour.
    d8 = [ln for ln in out.splitlines() if "D8" in ln]
    assert any("left the baseline" in ln for ln in d8), d8
    assert not any("NO LONGER EXISTS" in ln for ln in d8), d8
