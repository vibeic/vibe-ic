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
    assert "recomputed 3 of 9 cells" in out, out


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
    assert "recomputed 3 of 9 cells" in out, out
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
    assert "recomputed 3 of 9 cells" in out, out
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
    assert "recomputed 5 of 9 cells" in out, out


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


# ── D3: the dimension that is a fact about a RUN (vibe-ic, 2026-08-27) ──────
#
# Both poles for every claim. The grid's D3 must refuse a vacuous run, accept a
# real one, refuse to guess when no run is supplied, and never let any of those
# three be mistaken for another.

_VACUOUS_STA = """OpenROAD 26Q3-1797-g1c09d62b96 
[ERROR ORD-2010] no technology has been read.
[ERROR STA-1570] No network has been linked.
[ERROR STA-1571] No network has been linked.
"""

_GOOD_STA = """OpenROAD 26Q3-1797-g1c09d62b96 
Startpoint: _38_ (rising edge-triggered flip-flop clocked by clk)
           1.27   slack (MET)

tns max 0.00
wns max 0.00
"""


def _shipped_run(root, sta_body):
    """A run tree carrying step 10's two declared outputs and nothing else."""
    sta = root / "phase3" / "stage3" / "sta"
    sta.mkdir(parents=True, exist_ok=True)
    (sta / "pre_pnr_timing.rpt").write_text(sta_body)
    summ = root / "reports" / "phase3" / "sta"
    summ.mkdir(parents=True, exist_ok=True)
    (summ / "pre_pnr_summary.json").write_text('{"wns_ns": 1.27}')
    return root


def _grid(*args):
    p = subprocess.run([sys.executable, str(GRID), *args],
                       capture_output=True, text=True, timeout=900)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def test_d3_refuses_a_run_whose_output_records_its_own_tool_failure(tmp_path):
    """THE REAL CASE, through the grid. MEASURED 2026-08-27: eda_sta read no
    LEF, link_design failed STA-1570, every report failed STA-1571, openroad
    exited 0, and a 591-byte report landed. D8's catcher was declared and had
    no reason to fire, because the file was there.
    """
    run = _shipped_run(tmp_path / "r", _VACUOUS_STA)
    rc, out = _grid("--run", str(run))
    assert rc == 1, out
    assert "D3 outputs" in out, out
    assert "step 10" in out, out
    assert "STA-1571" in out, out
    assert "TOOL_REPORTED_ERROR" in out, out


def test_d3_accepts_the_same_step_when_the_run_actually_linked(tmp_path):
    """THE OTHER POLE, so the test above is not proving a detector that always
    fires. Same step, same path, same kind of file.
    """
    run = _shipped_run(tmp_path / "r", _GOOD_STA)
    rc, out = _grid("--run", str(run))
    assert "D3 outputs —" not in out, out
    assert rc == 0, out


def test_d3_reports_NOT_MEASURED_when_no_run_is_supplied():
    """Neither a pass nor a fail. Both wrong answers are named in the source and
    both are asserted against here.
    """
    rc, out = _grid()
    assert "NOT MEASURED" in out and "D3 outputs" in out, out
    assert "Not a pass and not a fail" in out, out
    # not a fail
    assert rc == 0, out
    # and not a pass either: it must be absent from the recomputed set, so the
    # numerator cannot credit it.
    line = [x for x in out.splitlines() if x.strip().startswith("recomputed:")]
    assert line, out
    assert "D3" not in line[0], line[0]


def test_the_numerator_grows_by_exactly_one_dimension_when_a_run_is_given(tmp_path):
    """The disclosure has to MOVE, or it is not a disclosure.

    Without this, D3 could report NOT MEASURED and be silently counted anyway —
    which is the arithmetic defect this grid already documents for its rc=2
    delegates one screen up.
    """
    import re
    run = _shipped_run(tmp_path / "r", _GOOD_STA)
    pat = re.compile(r"recomputed (\d+) of (\d+) cells \((\d+) steps x (\d+) of (\d+)")

    _, without = _grid()
    _, with_run = _grid("--run", str(run))
    a = pat.search(without); b = pat.search(with_run)
    assert a and b, (without, with_run)
    assert int(b.group(4)) == int(a.group(4)) + 1, (a.groups(), b.groups())
    assert int(b.group(1)) == int(b.group(3)) * int(b.group(4))
    # the DENOMINATOR is the declared population and does not move.
    assert a.group(5) == b.group(5) == str(len(fgg.DIMENSIONS))
    assert int(a.group(2)) == int(a.group(3)) * len(fgg.DIMENSIONS)


def test_the_declared_denominator_is_derived_from_both_axes(tmp_path):
    """MEASURED on `40d0e14c0`, this program printed `544 = 68 x 8`: the steps
    tracked the flow and the dimensions were frozen at 8, so the denominator
    matched no reality at all. Both halves are derived now.
    """
    import re
    _, out = _grid()
    m = re.search(r"recomputed \d+ of (\d+) cells \((\d+) steps x \d+ of (\d+)", out)
    assert m, out
    total, steps_n, dims = int(m.group(1)), int(m.group(2)), int(m.group(3))
    assert dims == len(fgg.DIMENSIONS), (dims, fgg.DIMENSIONS)
    assert total == steps_n * dims, (total, steps_n, dims)
    assert total != 544, "the frozen-dimension arithmetic is back"
    assert total != 504, "the frozen-both-axes arithmetic is back"


def test_the_grids_dimension_list_agrees_with_the_live_cell_ledger():
    """ADDING ONE MUST NOT BE POSSIBLE ON ONE SIDE ONLY.

    `matrix_63x8.cells` enumerates the same population from the other end. A
    tenth dimension added there and not here would put this grid back to
    under-reporting its denominator — which is exactly how D9 went uncounted.
    """
    sys.path.insert(0, str(GRID.parent / "tests"))
    from matrix_63x8 import cells  # noqa: E402
    assert len(fgg.DIMENSIONS) == len(cells.DIMENSIONS), (
        f"the grid declares {len(fgg.DIMENSIONS)} dimensions {fgg.DIMENSIONS} "
        f"and the ledger declares {len(cells.DIMENSIONS)} {cells.DIMENSIONS}")


def test_every_declared_dimension_is_either_recomputed_or_says_why():
    """No dimension may be invisible. D9 was: it existed in the ledger, was
    absent from this program's arithmetic, and therefore was never disclosed as
    un-recomputed either. Silence about a dimension is the same defect as a
    false verdict about one.
    """
    _, out = _grid()
    for dim in fgg.DIMENSIONS:
        tag = dim.split()[0]
        recomputed = any(l.strip().startswith("recomputed:") and tag in l
                         for l in out.splitlines())
        disclosed = any(tag in l and ("NOT DERIVABLE" in l or "NOT MEASURED" in l)
                        for l in out.splitlines())
        assert recomputed or disclosed, (
            f"{dim} is neither in the recomputed list nor disclosed as not "
            f"recomputed; it is invisible:\n{out}")


def test_a_run_path_that_is_not_a_directory_is_rc2_not_a_pass(tmp_path):
    f = tmp_path / "notadir"
    f.write_text("x")
    rc, out = _grid("--run", str(f))
    assert rc == 2, out
    assert "NOT CHECKED" in out, out
