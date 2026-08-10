"""BIDIRECTIONAL CONTROL for the dimension-3 live-production input rule.

WHAT WENT WRONG
===============
``fixtures/matrix_d3_output_manifest.json`` recorded step 10's
``reports/phase3/sta/pre_pnr_summary.json`` as ``PRODUCED_LIVE`` at **969 B**.
``produce_live`` accepted it because the only content test it applied was
``size > 0``.

969 B is not a summary. Measured on this commit by driving the real producer
over every admissible run root, it is byte-for-byte what
``sta_report_check`` writes into a tree that carries **no STA report at all**:

    passed: false
    findings: [STA_REPORT_EXISTS, SCOPE_NOT_FOUND]
    summary.files_found: 0
    summary.scoped_under_missing: [both declared --under scopes]

and it arrived identically from four independent admissible roots. The
producer's own program says what that means, in its own words
(``eda_report_audit._main``): *"none of the --under scope(s) exist ... no file
could be discovered regardless of what the project contains"* — the verdict is
about the SCOPE, not about the project.

So the cell was certifying that step 10 PRODUCES its declared summary on the
strength of the step's own auditor writing "I found nothing to summarise" into
an empty tree. A non-empty absence record was reading as a produced artefact.

THE RULE
========
``produce_live`` now refuses a base run in which **none** of the producer's
declared ``--under`` scopes exists. The bar is at least ONE scope, not all of
them, and that limit is disclosed at the call site rather than hidden: no
admissible run root carries ``phase3/stage3/sta/per_corner``, so requiring all
would be unsatisfiable by this corpus and would redden a cell over evidence
nobody can supply. A producer that declares no ``--under`` scope at all is not
covered by the rule.

WHY THIS FILE EXISTS SEPARATELY
===============================
The rule and its guard live in ``test_matrix_d3_outputs_produced.py``, so a
test in that same file could not be given a two-arm control: reverting the file
to ``origin/main`` would take the test away with the guard and the unfixed arm
would report "no tests ran" instead of failing. Housed here, the control is the
prescribed shape — ``git checkout origin/main --
programs/tests/test_matrix_d3_outputs_produced.py`` makes
:func:`test_control_a_live_production_is_refused_when_nothing_can_be_read`
FAIL, and restoring the file makes it PASS — and it follows the precedent
``test_matrix_a8_published_gds_control.py`` set for exactly this situation.

A fix like this has two ways to go wrong, pulling in opposite directions, so
both are asserted here:

  FORWARD  ``test_control_a_live_production_is_refused_when_nothing_can_be_read``
           FAILS on the byte-identical pre-fix module — the producer runs, the
           absence record lands non-empty, and ``produce_live`` reports the
           entry PRODUCED — and PASSES after.

  REVERSE  ``test_reverse_a_readable_base_run_is_still_accepted``
           GREEN BEFORE AND AFTER. The same probe, with the declared scope
           left in place, must still produce. A guard that refused everything
           would make this dimension unfalsifiable in the other direction, and
           this is what must not have changed.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import test_matrix_d3_outputs_produced as D3

#: The cell whose record the historical defect was found in. Read out of the
#: manifest rather than restated, so a record that moves cannot leave this
#: control silently asserting about a string nobody uses.
_STEP = "10"
_ENTRY = "reports/phase3/sta/pre_pnr_summary.json"


def _record():
    rec = D3.step_record(_STEP)["entries"].get(_ENTRY)
    if rec is None or rec.get("status") != "PRODUCED_LIVE":
        pytest.skip(f"step {_STEP} {_ENTRY!r} is no longer a PRODUCED_LIVE record")
    return rec


def _declared_scopes(rec) -> list:
    argv = list(rec["argv"])
    return [argv[i + 1] for i, tok in enumerate(argv)
            if tok == "--under" and i + 1 < len(argv)]


def _probe_clone_of_base_run(rec, probe: Path, commit, drop_scopes: bool):
    """A committed, tracked-only clone of the recorded base run.

    ``drop_scopes`` removes the producer's declared ``--under`` scopes BEFORE
    the commit, which is the shape of the run root the broken record pointed
    at: a real, runner-marked, non-empty tree that simply carries none of the
    artefacts the producer was told to read.
    """
    src = D3.run_roots().get(rec["base_run"])
    if src is None:
        pytest.skip(f"recorded base run {rec['base_run']!r} is not on this tree")
    n = D3._copy_tracked(src.path, probe)
    assert n, f"{src.path} carries nothing tracked; the probe would be inert"
    if drop_scopes:
        for scope in _declared_scopes(rec):
            p = probe / scope
            if p.is_file():
                p.unlink()
            elif p.is_dir():
                for f in sorted(p.rglob("*")):
                    if f.is_file():
                        f.unlink()
    # -f because the copied set can itself include a tracked `.gitignore`
    # whose rules would otherwise drop files that ARE in the source commit.
    subprocess.run(["git", "add", "-f", "--", "."], cwd=probe, check=True,
                   capture_output=True)
    commit()
    return n


def test_control_a_live_production_is_refused_when_nothing_can_be_read(monkeypatch):
    """A producer that can discover nothing has not produced anything.

    FAILS on the pre-fix module: with the declared scopes gone the producer
    still exits having written a non-empty JSON, and the only test applied to
    it was ``size > 0``, so ``produce_live`` returned ``(True, ...)``.
    """
    rec = _record()
    scopes = _declared_scopes(rec)
    assert scopes, (
        f"step {_STEP}'s recorded producer declares no --under scope; this "
        f"control asserts nothing and must be re-pointed or removed")

    with D3._probe_run_root("d3_scope_") as (probe, commit):
        _probe_clone_of_base_run(rec, probe, commit, drop_scopes=True)
        for scope in scopes:
            assert not (probe / scope).is_file(), (
                f"{scope} survived into the probe; the probe proves nothing")

        monkeypatch.setattr(
            D3, "run_roots",
            lambda: {rec["base_run"]: D3.RunRoot(rec["base_run"],
                                                 D3._IN_REPO_KIND, probe)})
        produced, detail = D3.produce_live(_STEP, _ENTRY, rec)

    assert not produced, (
        f"step {_STEP} {_ENTRY!r} was reported PRODUCED LIVE from a tree "
        f"carrying none of the producer's declared --under scopes {scopes}: "
        f"{detail}. Whatever landed is a record OF THE SCOPE, not a summary "
        f"of this step's outputs, and counting it is how an auditor's "
        f"'I found nothing' becomes a step's produced artefact."
    )
    assert all(s in detail for s in scopes), (
        f"the refusal does not name the scopes that were missing, so a reader "
        f"cannot tell this refusal from any other: {detail!r}")
    assert "tracked at HEAD" not in detail and "nothing a fresh clone" not in detail, (
        f"the entry was refused by a DIFFERENT rule than the one under test, "
        f"so this control would stay green with the scope rule deleted: "
        f"{detail!r}")


def test_reverse_a_readable_base_run_is_still_accepted(monkeypatch):
    """GREEN BEFORE AND AFTER — the guard must not refuse a real base run.

    Same probe, same producer, scopes left in place. If this ever goes red the
    guard has stopped admitting evidence rather than stopped admitting
    absence, which is the failure mode a rule like this has.
    """
    rec = _record()
    scopes = _declared_scopes(rec)

    with D3._probe_run_root("d3_scope_ok_") as (probe, commit):
        _probe_clone_of_base_run(rec, probe, commit, drop_scopes=False)
        present = [s for s in scopes if (probe / s).exists()]
        assert present, (
            f"the recorded base run {rec['base_run']!r} carries none of the "
            f"declared scopes {scopes}; its own cell cannot be evidence and "
            f"the manifest record must be re-pointed")

        monkeypatch.setattr(
            D3, "run_roots",
            lambda: {rec["base_run"]: D3.RunRoot(rec["base_run"],
                                                 D3._IN_REPO_KIND, probe)})
        produced, detail = D3.produce_live(_STEP, _ENTRY, rec)

    assert produced, (
        f"step {_STEP} {_ENTRY!r} could not be produced live from a "
        f"tracked-only clone of {rec['base_run']!r} that carries {present}: "
        f"{detail}")
