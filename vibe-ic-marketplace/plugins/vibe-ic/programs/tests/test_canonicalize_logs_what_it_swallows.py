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

WHICH REPAIRS ARE ACTUALLY EXERCISED BY A RUNNING STEP -- MEASURED, NOT ASSUMED.
Most arms here are STRUCTURAL: they read source and prove the status is consumed
and no branch is silent. `test_every_added_note_actually_EVALUATES` adds the
message half, but it evaluates the EXPRESSIONS, not the runner. So the question
"does any test actually EXECUTE these lines" was answered with `sys.settrace`
over the two suites that call `step_canonicalize_artefacts` against fixture
projects (`test_postlayout_lec_nameerror.py`,
`test_v0_3_26_issue527_spef_sta_canonical.py`):

    SDC block                 12 lines executed   YES
    DFM block                 12 lines executed   YES
    thermal screen            11 lines executed   YES
    flow_compliance refresh   18 lines executed   YES

ALL FOUR are covered by real execution, including the emitted message: line
`_fc = _sp_fc.run(...)`, the `if _fc.returncode != 0:` that reads it, and the
`[INFO] flow_compliance refresh returned rc=...` print itself all run, under
`test_hold_corner_coverage_check.py`, `test_phase3_cache_producer_identity.py`,
`test_phase3_postpnr_disclosure_and_gds_guard.py` and their neighbours, which
drive the runner far enough to reach finalize.

AN EARLIER VERSION OF THIS PARAGRAPH SAID THE FOURTH WAS **NOT** REACHED, and
it was wrong. The first measurement traced only the two suites that call
`step_canonicalize_artefacts` -- the refresh is not in that step, so of course
it did not appear -- and "no harness in this suite reaches it" was generalised
from a sample of three. Tracing the suites that call the runner's `main` shows
it plainly. The correction is left visible rather than silently overwritten,
because the mistake was not the measurement but the SCOPE claimed for it, which
is the recurring defect this whole lane has documented.

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

#: Every spawn in this runner whose status was discarded, and the function it
#: lives in. The first was found by hand; the other three were found by
#: `spawned_gate_whose_status_is_declared`-class analysis on
#: next/protected-tuple-drift-attribution, which reported them on main and does
#: not repair them. All four are ADVISORY by design -- their verdict travels in
#: an artefact -- so the remedy is the second one that instrument names: say so
#: at the call site instead of leaving it inferred from silence.
_SPAWNS = (
    ("sdc_syntax_check.py", "step_canonicalize_artefacts"),
    ("dfm_screen_check.py", "step_canonicalize_artefacts"),
    ("thermal_screen_check.py", None),
    ("flow_compliance_check.py", None),
)


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


def _spawn_block(program):
    """The `try` anywhere in the runner that spawns `program`."""
    tree = ast.parse(RUNNER.read_text(encoding="utf-8", errors="replace"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and program in ast.unparse(node):
            return node
    pytest.fail(f"nothing in {RUNNER.name} spawns {program} inside a try; this "
                "arm has lost its subject and must be relocated, not deleted")


def _spawn_scope(program):
    """The FUNCTION that spawns `program`, not merely the `try`.

    THIS GUARD'S OWN FIRST DRAFT WAS SCOPED TOO NARROWLY and said so out loud
    rather than being quietly widened: it asserted `.returncode` appeared
    inside the `try`, and for `thermal_screen_check` the status is read in the
    `if not out_json.is_file():` branch DIRECTLY AFTER the try. The status was
    read; the instrument was looking in the wrong place. A structural test that
    reports "discarded" over code that consumes the value one line later is a
    false finding, which is the thing this whole lane exists to remove.
    """
    tree = ast.parse(RUNNER.read_text(encoding="utf-8", errors="replace"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if program in ast.unparse(node):
                return node
    pytest.fail(f"no function in {RUNNER.name} spawns {program}; this arm has "
                "lost its subject and must be relocated, not deleted")


@pytest.mark.parametrize("program,_fn", _SPAWNS)
def test_every_discarded_spawn_now_reads_its_status(program, _fn):
    """The other three sites, which an independent instrument found first.

    `next/protected-tuple-drift-attribution` ships
    `spawned_gate_whose_status_is_discarded.py`, which reports these three on
    main -- "result unbound, check off, inside a handler that swallows
    everything" -- and does not repair them; that branch does not touch this
    file at all. (It does NOT report the SDC site, because its clause requires
    the result to be UNBOUND and that one was bound-and-never-read. The two
    findings are complementary, which is why both live here.)

    ALL FOUR ARE ADVISORY BY DESIGN and none is made blocking: each one's
    verdict travels in an artefact a later reader opens. The remedy applied is
    the second the instrument itself names -- say so at the call site, so the
    decision is on the record rather than inferred from silence.
    """
    # KEYED ON THE SPAWN'S OWN BOUND NAME, not on the substring `.returncode`.
    #
    # THE FIRST VERSION OF THIS ASSERTION WAS VACUOUS AND ITS OWN CONTROL SAID
    # SO. It searched the whole enclosing function for `.returncode`; for
    # `flow_compliance_check` that function is `main`, which on pristine main
    # ALREADY contains two unrelated `.returncode` uses. So the arm passed
    # against pre-fix code -- it could not fail, which makes it the defect
    # rather than the guard. (Scoping it to the `try` instead was the opposite
    # error: `thermal_screen` reads its status one branch AFTER the try, and
    # that version reported a false finding.)
    #
    # The bound name settles both: an UNBOUND spawn is discarded by
    # construction and fails here, and a bound one must have ITS OWN
    # `<name>.returncode` read somewhere in the function.
    scope = _spawn_scope(program)
    target = None
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if program in ast.unparse(node.value):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        target = t.id
    assert target is not None, (
        f"the spawn of {program} is not bound to anything, so its status "
        "cannot be read at all -- the result is discarded by construction")
    assert f"{target}.returncode" in ast.unparse(scope), (
        f"the spawn of {program} binds `{target}` and never reads "
        f"`{target}.returncode`, so a reader cannot tell a crashed run from a "
        "clean one")


@pytest.mark.parametrize("program,_fn", _SPAWNS)
def test_no_discarded_spawn_hides_behind_a_bare_pass(program, _fn):
    for handler in _spawn_block(program).handlers:
        body = ast.unparse(handler.body).strip()
        assert body != "pass", (
            f"the spawn of {program} swallows its exception with a bare "
            "`pass`; a failure there is indistinguishable from success")


def test_the_refresh_no_longer_calls_itself_BLOCKING():
    """The prose defect, which was the worst of the four.

    The `flow_compliance_check` re-run described itself as "This direct,
    BLOCKING flow_compliance re-run" while running with `check=False`, an
    unbound result and `except Exception: pass`. Prose asserted a property the
    code could not have, and a reader would believe a failed re-run stops the
    verdict when nothing would even mention it.

    The failure is material, which is why the silence mattered: without the
    refresh, `_derive` reads a STALE phase23_completion_audit.json and the
    headline can disagree with its own sign-off.
    """
    src = ast.unparse(_spawn_block("flow_compliance_check.py"))
    assert "BLOCKING" not in src, (
        "the flow_compliance refresh still calls itself BLOCKING while running "
        "check=False; either it blocks or it does not say that it does")
    assert "STALE" in src.upper(), (
        "the failure path does not say what a missing refresh costs -- a stale "
        "audit read by _derive -- so the note is a shrug rather than a warning")


def _added_note_expressions():
    """Note/print calls AT the four spawn sites, selected by POSITION.

    SELECTED BY POSITION AND NOT BY NAME, and that is the whole point. The
    first version of this collector looked for expressions containing
    `sdc_check_json.relative_to` -- and when the `_rel_to` bug was reintroduced
    as a control, the note stopped containing that string, so the collector did
    not collect it and the behavioural arm stayed GREEN over the exact defect
    it was written to catch. A guard that recognises its subject by the string
    the defect deletes cannot see the defect.

    So the window is structural: each spawn's `try`, plus the statements
    immediately after it (the file-absent branch, which is where
    `thermal_screen` reads its status). Renaming or rewriting a note cannot
    move it out of that window.
    """
    tree = ast.parse(RUNNER.read_text(encoding="utf-8", errors="replace"))
    windows = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.Try):
                continue
            u = ast.unparse(node)
            if not any(p in u for p, _ in _SPAWNS):
                continue
            end = getattr(node, "end_lineno", node.lineno) or node.lineno
            windows.append((fn, node.lineno, end + 12))

    out = []
    for fn, lo, hi in windows:
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            nm = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            if nm not in ("append", "print"):
                continue
            if nm == "append" and ast.unparse(f.value) != "notes":
                continue
            if lo <= node.lineno <= hi:
                out.append((fn.name, node.lineno, node))
    return out


def test_every_added_note_actually_EVALUATES():
    """THE BEHAVIOURAL HALF. Everything else in this file is structural.

    WHY IT EXISTS, from a defect I shipped into my own working tree and caught
    only by reading: the first version of the SDC findings note called
    `_rel_to(project, ...)`, a helper that does not exist in the runner. Inside
    its `try` that raises NameError, is caught by the very `except Exception`
    added to end the silence, and emits a note claiming the EMISSION failed --
    a false message manufactured by the repair itself.

    NO STRUCTURAL ASSERTION IN THIS FILE WOULD HAVE CAUGHT IT. `.returncode`
    was present, the note count was right, the handler was not a bare `pass`.
    The source LOOKED repaired and the runtime path was broken. So each added
    note argument is compiled and EVALUATED here against a real
    `subprocess.CompletedProcess`, which is what catches a wrong attribute, a
    bad f-string, or a name that is not there.

    It does NOT run the runner -- these are the message expressions only, in a
    stubbed namespace. Stated so this arm is not read as end-to-end coverage
    it does not have.
    """
    import subprocess as _sp

    exprs = _added_note_expressions()
    assert exprs, (
        "no note expression in the runner reads any of the bound subprocess "
        "results, so either the repair was reverted or this arm has lost its "
        "subject -- relocate it rather than leaving it green over nothing")

    project = pathlib.Path("/tmp/_probe_project")
    known = {
        "_dfm": _sp.CompletedProcess(["x"], 3, stdout="out\n", stderr="err\n"),
        "_th": _sp.CompletedProcess(["x"], 4, stdout="", stderr="boom\n"),
        "_fc": _sp.CompletedProcess(["x"], 1, stdout="", stderr=""),
        "r": _sp.CompletedProcess(["x"], 1, stdout="", stderr="sdc\n"),
        "sdc_check_json": project / "reports/phase2/sdc_check.json",
        "project": project,
        "sys": sys,
    }

    # THE NAMESPACE IS DERIVED FROM THE FUNCTION, NOT HAND-LISTED. A hand-list
    # made this arm fail on correct code: the SDC block binds `tail` while the
    # others bind `_tail`, and a stub set that knew only `_tail` reported a
    # NameError the runtime would never raise. A guard that invents failures is
    # worse than one that misses them.
    #
    # So every name the enclosing function ASSIGNS is bound here, to a
    # permissive stub where its real value is unknown. A name that is never
    # assigned anywhere in the function -- which is exactly what `_rel_to`
    # was -- is still absent, and still raises.
    class _Any(str):
        def __getitem__(self, k):
            return self
        def __getattr__(self, k):
            return self
        def __call__(self, *a, **k):
            return self

    for fname, lineno, node in exprs:
        fn = next((f for f in ast.walk(ast.parse(
            RUNNER.read_text(encoding="utf-8", errors="replace")))
            if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
            and f.name == fname), None)
        assigned = set()
        if fn is not None:
            for x in ast.walk(fn):
                if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store):
                    assigned.add(x.id)
                elif isinstance(x, ast.ExceptHandler) and x.name:
                    assigned.add(x.name)
                elif isinstance(x, (ast.Import, ast.ImportFrom)):
                    for a in x.names:
                        assigned.add((a.asname or a.name).split(".")[0])
            for a in fn.args.args + fn.args.kwonlyargs:
                assigned.add(a.arg)
        ns = {n: _Any("stub-line") for n in assigned}
        ns.update(known)
        for arg in node.args:
            expr = ast.Expression(ast.fix_missing_locations(arg))
            try:
                value = eval(compile(expr, "<note>", "eval"), {}, dict(ns))
            except Exception as exc:  # noqa: BLE001 - reporting the failure IS the test
                pytest.fail(
                    f"{fname}:{lineno} builds a note that raises "
                    f"{type(exc).__name__}: {exc}. A repair whose own message "
                    f"cannot be produced reports a failure that did not happen. "
                    f"Expression: {ast.unparse(arg)[:200]}")
            assert isinstance(value, str) and value.strip(), (
                f"{fname}:{lineno} builds an empty note; a blank line is the "
                "silence this repair exists to end")


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
