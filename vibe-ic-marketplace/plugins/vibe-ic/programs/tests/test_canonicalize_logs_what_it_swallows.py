#!/usr/bin/env python3
"""A step that runs a subprocess and says nothing about it is not "best-effort".

WHY THIS FILE EXISTS. `phase3_one_shot_runner.step_canonicalize_artefacts`
declares, in its own docstring:

    Best-effort: any individual emission failure logs WARN but the step
    continues. The downstream gates verify substance.

MEASURED: the SDC block ran `sdc_syntax_check.py`, bound the result to `r`,
and NEVER READ IT -- not the return code, not stdout, not stderr. It tested
only whether the JSON file appeared, and its handler was `except Exception:
pass`. So on every outcome it logged nothing, while the contract above said it
warns. That is a disclosure that exists from the emitter's side and not the
reader's -- the same shape as a gate whose verdict nothing consumes.

WHAT THIS FILE DOES **NOT** CLAIM. It does not claim the step should BLOCK on
the checker. It should not: the report it emits is read by a downstream gate,
and `step_canonicalize_artefacts` is an emitter. The defect repaired here is
silence, not leniency.

THE TWO OUTCOMES ARE DIFFERENT AND THE NOTE MUST SAY WHICH:

    report written, rc != 0   NOT an emission failure. `sdc_syntax_check`
                              exits `0 if result.passed else 1`, so non-zero
                              means the SDC has real findings -- and they are
                              in the JSON. Worth a note because the runner's
                              notes are what a human reads first.
    report NOT written        a genuine emission failure, which is what the
                              docstring's WARN was promised for.

Conflating them would be its own defect: reporting "emission failed" over a
checker that ran perfectly and found something is a false alarm, and this lane
has spent its whole length removing claims that outrun their evidence.

chip-AGNOSTIC: no design, PDK, vendor, node or codename literal.
"""
from __future__ import annotations

import ast
import pathlib
import sys

import pytest

_TESTS = pathlib.Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
sys.path.insert(0, str(_PROGRAMS))

RUNNER = _PROGRAMS / "phase3_one_shot_runner.py"
_STEP = "step_canonicalize_artefacts"
_CHECKER = "sdc_syntax_check.py"


def _step_node():
    tree = ast.parse(RUNNER.read_text(encoding="utf-8", errors="replace"))
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == _STEP:
            return n
    pytest.fail(f"{_STEP} is not in {RUNNER.name}; this guard has lost its "
                "subject and must be rewritten, not left green")


def _sdc_block():
    """The `try` that runs the SDC checker, located by the program it runs."""
    for node in ast.walk(_step_node()):
        if isinstance(node, ast.Try) and _CHECKER in ast.unparse(node):
            return node
    pytest.fail(
        f"no `try` block in {_STEP} runs {_CHECKER}. If that invocation moved, "
        "this guard is measuring nothing -- relocate it rather than deleting "
        "the assertion")


def test_the_premise_the_step_still_runs_the_checker():
    """Without this, every assertion below passes by finding no subject."""
    block = _sdc_block()
    assert _CHECKER in ast.unparse(block)


def test_the_return_code_is_actually_read():
    """`r` was bound and never read. That is the defect in one line."""
    src = ast.unparse(_sdc_block())
    assert ".returncode" in src, (
        "the SDC block runs a checker and never reads its returncode, so the "
        "step cannot tell 'the report says the SDC failed' from 'the checker "
        "never ran'. Its own docstring promises a WARN it cannot emit.")


def test_both_outcomes_are_reported_and_not_conflated():
    """A findings-report and a missing-report are different events.

    Asserted structurally: the block must append a note on BOTH the
    file-present and the file-absent path, so neither outcome is silent and
    neither is described as the other.
    """
    block = _sdc_block()
    appends = [n for n in ast.walk(block)
               if isinstance(n, ast.Call)
               and isinstance(n.func, ast.Attribute)
               and n.func.attr == "append"
               and ast.unparse(n.func.value) == "notes"]
    assert len(appends) >= 3, (
        "the SDC block must say something on all three outcomes -- report "
        f"written with findings, report not written, and an exception -- and "
        f"it makes only {len(appends)} note(s). A silent branch is the "
        "failure this guard exists to catch.")


def test_the_exception_handler_no_longer_swallows():
    """`except Exception: pass` is silence with a comment on top."""
    block = _sdc_block()
    for handler in block.handlers:
        body = ast.unparse(handler.body)
        assert body.strip() != "pass", (
            "the SDC block still swallows its exception with a bare `pass`, "
            "so a crash in the checker is indistinguishable from a clean run "
            "that produced no findings")
        assert "notes.append" in body, (
            "the exception path does not record anything, so the step's "
            "docstring promise of a WARN remains unkept on the one path that "
            "most needs it")


def test_a_findings_report_is_not_called_an_emission_failure():
    """The false-alarm direction, which is the easier mistake to ship.

    `sdc_syntax_check` exits 1 when the SDC has findings. Describing that as
    "emit failed" would report a tool that worked as a tool that broke.
    """
    src = ast.unparse(_sdc_block())
    assert "reported findings" in src, (
        "the non-zero-with-report path does not distinguish findings from an "
        "emission failure; a checker that ran correctly and found something "
        "must not be reported as having failed to emit")


def test_the_note_names_the_artefact_a_reader_must_open():
    src = ast.unparse(_sdc_block())
    assert "sdc_check_json.relative_to" in src or "sdc_check.json" in src, (
        "the findings note does not name the report holding the verdict, so a "
        "reader is told something is wrong and not where to look")


def test_the_step_does_not_start_blocking_on_it():
    """THE PAIRED HALF. This repair is about silence, not leniency.

    If a future change makes the SDC checker's rc abort or fail the step, that
    is a different decision with different consequences -- the step emits many
    other canonical artefacts after this point, and its docstring says so.
    """
    block = _sdc_block()
    for node in ast.walk(block):
        if isinstance(node, ast.Raise):
            pytest.fail(
                "the SDC block now raises; this step is an emitter and a "
                "raise here would abort the remaining canonical emissions. "
                "If blocking is genuinely wanted, it belongs in a gate.")
        if isinstance(node, ast.Return):
            pytest.fail(
                "the SDC block now returns early, which skips every canonical "
                "artefact emitted after it")
