#!/usr/bin/env python3
"""The unified metrics schema exists; this measures who uses it and stops the
number going backwards.

`step_metrics.py` already IS the schema, adopted from OpenROAD-flow-scripts,
and its own docstring records the problem it was written for: 63 declared step
entries, every checker choosing its own shape, no per-step QoR aggregator and
nothing computing a run-to-run delta. MEASURED 2026-09-04: of the 50 flow steps
that declare programs, FOUR emit through it. **Adoption is 8 %.**

So the mechanism was built and then not adopted, and the cost is the question
ORFS answers with one `diff` — "is this run better or worse than the last one"
— being answered here by reading prose across a dozen differently shaped JSONs.
That is how a 393-violation DRC run and a 0-violation one came to be compared by
hand, and how a `0` that meant "nothing was measured" was read as "nothing was
wrong".

A RATCHET, NOT A SWEEP. Converting 46 steps in one change is a diff nobody
reviews and a gate that fires on everything gets waived wholesale. The residual
is recorded and named every run; what BLOCKS is the delta. This is
`atomic_artifact_write_check`'s shape because it is the shape that has held in
this tree.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import step_metrics_adoption_check as A                        # noqa: E402


def test_the_population_is_the_flows_own_steps():
    rep = A.audit(_PLUGIN)
    assert rep["steps_declaring_programs"] >= 40, (
        f"only {rep['steps_declaring_programs']} step(s) declare programs; the "
        f"flow was not read and an unreadable population must not become a "
        f"population of zero")


def test_adoption_is_measured_by_import_not_by_filename():
    """`coverage_metric_check` carries the word and is not the question;
    `placement_legality_check` does not carry it and IS an emitter.

    A name is not a behaviour, and this repo has paid for reading one as the
    other more than once.
    """
    emitters = A.emitting_programs(_PROGRAMS)
    assert "placement_legality_check" in emitters, (
        "a program that imports the emitter was not counted")
    named_only = [s for s in emitters if "metric" in s]
    assert len(emitters) > len(named_only), (
        "every counted emitter has 'metric' in its name — the check is "
        "matching filenames, not imports")


def test_the_gate_refuses_rather_than_passes_without_a_baseline(tmp_path,
                                                                monkeypatch):
    """No baseline is NOT CHECKED, never PASS.

    With nothing to compare against, no step can be called NEW — and a gate
    that answered PASS there would report a healthy tree it never measured.
    """
    rc = A.main([str(_PLUGIN), "--baseline", str(tmp_path / "absent.json")])
    assert rc == 2


def test_a_step_that_stops_emitting_fails(tmp_path):
    """The ratchet's teeth. A step in the baseline's `adopted` that no longer
    emits is a regression, and it must not be absorbed by the residual."""
    bl = tmp_path / "bl.json"
    rep = A.audit(_PLUGIN)
    bl.write_text(json.dumps({
        "adopted": sorted(set(rep["adopted"]) | {"__a_step_that_used_to__"}),
        "not_yet": rep["not_yet"]}))
    assert A.main([str(_PLUGIN), "--baseline", str(bl)]) == 1


def test_a_new_step_that_emits_nothing_fails(tmp_path):
    """Adding a step without metrics must cost something at the moment it is
    added, or the residual grows forever one step at a time."""
    bl = tmp_path / "bl.json"
    rep = A.audit(_PLUGIN)
    shrunk = [s for s in rep["not_yet"]][1:]     # pretend one was never absent
    bl.write_text(json.dumps({"adopted": rep["adopted"], "not_yet": shrunk}))
    assert A.main([str(_PLUGIN), "--baseline", str(bl)]) == 1


def test_todays_tree_passes_against_todays_residual(tmp_path):
    """The control, so "it fails" cannot be read as "it fails on everything"."""
    bl = tmp_path / "bl.json"
    rep = A.audit(_PLUGIN)
    bl.write_text(json.dumps({"adopted": rep["adopted"],
                              "not_yet": rep["not_yet"]}))
    assert A.main([str(_PLUGIN), "--baseline", str(bl)]) == 0


def test_the_residual_is_named_not_just_counted():
    """A count cannot be worked on. The 46 are the work list."""
    rep = A.audit(_PLUGIN)
    assert rep["not_yet"], "nothing left to adopt — then this gate is done"
    assert all(isinstance(s, str) and s for s in rep["not_yet"])
    assert "0.5ic" in rep["not_yet"] or rep["adoption_percent"] > 50, (
        "the residual does not name real step ids")
