"""A gate clause must not write an artefact the same audit reports as present.

THE DEFECT, MEASURED on origin/main 74ac9fa78 in the pinned container image,
against a fresh copy of the published run root ``benchmark-data/ic/
u_hawaii_adc``::

    BEFORE: reports/audit/phase1/expert_parse_track.json   (absent)
    $ python3 programs/flow_compliance_check.py <copy>
    AFTER:  reports/audit/phase1/expert_parse_track.json   6834 B

That path is one of step D1's own declared ``required_outputs``. The auditor
created it and then reported it as produced: a green that is a statement about
the auditor's own side effect, not about the run it was asked to grade.

WHY IT REACHED THE FLOW. ``phase1_expert_parse_track.main`` resolves its
destination as ``Path(args.json) if args.json else _pl.report_path(project,
"phase1/expert_parse_track.json")`` and D1's gate clause invoked it with no
``--json``. The producer that is SUPPOSED to write that artefact is
``phase1_one_shot_runner._run_expert_track``, which deletes any previous report
first so that "the report exists" can only mean this run wrote it — a second
producer inside the auditor destroys exactly that freshness.

WHY THIS GUARD IS NOT SPELT AS "D1 must pass --json". That would pin the one
instance and say nothing about the next program to grow a default. The subject
set is DERIVED: every gate clause in the shipped flow whose program resolves
its output as ``<explicit option> if <option> else report_path(project, LIT)``
and whose ``LIT`` routes — through the shipped router, not a copy of its rules —
onto a path some step DECLARES. Exactly one clause in the flow is such a
subject today; the assertion that the set is non-empty is the floor that keeps
this file from grading nothing (matrix_63x8/README.md, "The one rule", form 2).

RELATION TO ``test_matrix_d3_outputs_produced.test_d3_the_compliance_audit_
does_not_create_declared_outputs``. That test measures the same disease from
the other end — it runs the WHOLE audit over published corpus roots and diffs
the tree — and it is the test that caught this. It is also ``@needs_corpus``:
without ``VIBE_IC_BENCHMARK_DATA`` it does not run. This file needs no corpus
and no published run: it builds its own project directory. The two are kept
because they fail on different days.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
from fnmatch import fnmatch
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

from matrix_63x8 import flowref as F

sys.path.insert(0, str(F.PROGRAMS_DIR))
import _path_layout as _pl  # noqa: E402

#: The option names a program may use to override its default destination.
#: Read off the shipped argument parsers, not invented here.
REDIRECT_OPTIONS = ("--json", "--out", "--report")

#: A synthetic project is enough: every subject below writes its default
#: destination from an EMPTY directory (measured — see
#: ``test_the_default_destination_is_reachable_from_an_empty_project``), so the
#: behavioural arms need no published run and no corpus.
_PROJECT_SEED: Dict[str, str] = {}


# ──────────────────────────────────────────────────────────────────────
# Deriving the subject set
# ──────────────────────────────────────────────────────────────────────
def _default_destinations(source: Path) -> Tuple[str, ...]:
    """Relative paths this program writes when its redirect option is absent.

    Detects the ONE shape that makes a program a conditional producer::

        target = Path(args.json) if args.json else _pl.report_path(project, LIT)

    An ``ast.IfExp`` whose ``orelse`` is a ``report_path(_, "<literal>")`` call.
    ``LIT`` is then routed through the SHIPPED ``_path_layout.report_path``, so
    a change to the router's taxonomy moves this guard's answer with it instead
    of leaving a stale copy of the rules here.

    A bare ``report_path(...)`` that is not the fallback arm of a conditional is
    deliberately NOT matched: programs build such paths to READ them
    (``dft_signoff_check`` appends three of them to a candidate list), and a
    rule that could not tell reading from writing would fire on those.
    """
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return ()
    found: List[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.IfExp) or not isinstance(node.orelse, ast.Call):
            continue
        fn = node.orelse.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
        if name != "report_path":
            continue
        args = node.orelse.args
        if len(args) < 2 or not isinstance(args[1], ast.Constant):
            continue
        if not isinstance(args[1].value, str):
            continue
        rel = _pl.report_path(Path("/__P__"), args[1].value).relative_to("/__P__")
        found.append(str(rel))
    return tuple(sorted(set(found)))


@lru_cache(maxsize=1)
def declared_outputs() -> Dict[str, Tuple[str, ...]]:
    """``{declared entry: the steps that declare it}`` over the LIVE flow."""
    out: Dict[str, List[str]] = {}
    for sid in F.step_ids():
        for entry in F.required_outputs(sid):
            for alt in F.split_any_of(entry):
                out.setdefault(alt, []).append(F.normalize_id(sid))
    return {k: tuple(v) for k, v in out.items()}


def _declares(rel: str) -> Tuple[str, ...]:
    """The steps that declare ``rel``, matching the flow's own glob entries."""
    hits: List[str] = []
    for entry, steps in declared_outputs().items():
        if entry == rel or (F.is_glob(entry) and fnmatch(rel, entry)):
            hits.extend(steps)
    return tuple(sorted(set(hits)))


@lru_cache(maxsize=1)
def subjects() -> Tuple[Tuple[str, str, str, str, Tuple[str, ...]], ...]:
    """``(step, command, program, default_rel, declaring steps)`` per subject."""
    found: List[Tuple[str, str, str, str, Tuple[str, ...]]] = []
    for sid in F.step_ids():
        for cmd in F.gate_commands(sid):
            token = cmd.split()[0] if cmd.split() else ""
            prog = F.program_path(token)
            if prog is None:
                continue
            for rel in _default_destinations(prog):
                declaring = _declares(rel)
                if declaring:
                    found.append(
                        (F.normalize_id(sid), cmd, token, rel, declaring))
    return tuple(found)


def _redirect_of(cmd: str) -> Tuple[str, str] | None:
    """The explicit destination this clause passes, if any."""
    toks = cmd.split()
    for i, tok in enumerate(toks):
        if tok in REDIRECT_OPTIONS and i + 1 < len(toks):
            return tok, toks[i + 1]
        for opt in REDIRECT_OPTIONS:
            if tok.startswith(opt + "="):
                return opt, tok.split("=", 1)[1]
    return None


def _make_project(root: Path) -> Path:
    project = root / "proj"
    project.mkdir()
    for rel, body in _PROJECT_SEED.items():
        target = project / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return project


def _run_clause(project: Path, cmd: str, drop_redirect: bool) -> subprocess.CompletedProcess:
    """Replay a gate clause's argv the way ``flow_compliance_check`` does.

    The consumer resolves the program token to ``programs/<token>.py`` and runs
    it with ``cwd=project`` (``flow_compliance_check.py:3114,3126``), which is
    what makes the clause's relative ``--json`` land inside the project. Both
    are reproduced here rather than approximated.
    """
    toks = cmd.split()
    prog = F.program_path(toks[0])
    assert prog is not None, toks[0]
    rest = toks[1:]
    if drop_redirect:
        out: List[str] = []
        skip = False
        for tok in rest:
            if skip:
                skip = False
                continue
            if tok in REDIRECT_OPTIONS:
                skip = True
                continue
            if any(tok.startswith(o + "=") for o in REDIRECT_OPTIONS):
                continue
            out.append(tok)
        rest = out
    return subprocess.run(
        [sys.executable, str(prog), *rest],
        cwd=project, capture_output=True, text=True, timeout=600, check=False)


def _files(project: Path) -> set:
    return {str(p.relative_to(project))
            for p in project.rglob("*") if p.is_file()}


# ──────────────────────────────────────────────────────────────────────
# The floor
# ──────────────────────────────────────────────────────────────────────
def test_the_subject_set_is_not_empty():
    """An empty subject set is a measurement of nothing, not a pass.

    Every assertion below loops over :func:`subjects`. If the detector stopped
    matching — the fallback shape changes, ``report_path`` is renamed, the
    router's taxonomy moves the literal off a declared path — those loops would
    run zero times and this file would go green having examined nothing. That
    is the exact failure mode ``test_waivers_meet_the_registry_standard``
    records for its own mirror, and the reason it is asserted first here.
    """
    found = subjects()
    assert found, (
        "no gate clause in the shipped flow resolves its output through a "
        "`<option> if <option> else report_path(project, LIT)` fallback that "
        "lands on a declared required_output. Every other test in this file "
        "loops over that set and would pass having graded nothing. Either the "
        "detector in `_default_destinations` stopped matching the shape it "
        "was written for, or `_path_layout.report_path` no longer routes any "
        "such literal onto a declared path — establish which before deleting "
        "this file.")


# ──────────────────────────────────────────────────────────────────────
# The rule
# ──────────────────────────────────────────────────────────────────────
def test_no_gate_clause_leaves_its_output_at_a_declared_required_output():
    """A conditional producer wired as a gate MUST carry its redirect."""
    problems: List[str] = []
    for step, cmd, prog, rel, declaring in subjects():
        redirect = _redirect_of(cmd)
        if redirect is None:
            problems.append(
                f"step {step}: gate clause `{cmd}` runs {prog}, whose "
                f"destination falls back to {rel!r} — declared as a "
                f"required_output by step(s) {list(declaring)}. The audit "
                f"would CREATE the artefact it then reports as produced. Pass "
                f"an explicit {REDIRECT_OPTIONS[0]} naming a gate-report path "
                f"(the `reports/<phase>/gates/` convention), and leave "
                f"production to the runner that owns the step.")
            continue
        opt, target = redirect
        also_declared = _declares(target)
        if also_declared:
            problems.append(
                f"step {step}: gate clause `{cmd}` redirects with {opt} to "
                f"{target!r}, which step(s) {list(also_declared)} also declare "
                f"as a required_output. Redirecting one declared artefact onto "
                f"another moves the self-certification, it does not end it.")
    assert not problems, "\n".join(problems)


def test_replaying_the_clause_argv_creates_no_declared_required_output():
    """The rule above, asked of the PROGRAM instead of the string.

    A static reading of the argv can be satisfied by a clause that passes
    ``--json`` to a program that ignores it. This arm runs the real program
    with the real argv, in the working directory the real consumer uses, and
    diffs the tree.
    """
    for step, cmd, prog, rel, declaring in subjects():
        with tempfile.TemporaryDirectory(prefix="gate_producer_") as td:
            project = _make_project(Path(td))
            before = _files(project)
            _run_clause(project, cmd, drop_redirect=False)
            created = _files(project) - before
            self_certified = sorted(c for c in created if _declares(c))
            assert not self_certified, (
                f"step {step}: replaying gate clause `{cmd}` created "
                f"{self_certified} in the project it grades, and the flow "
                f"declares those as required_outputs. The clause's redirect "
                f"is not reaching the program's destination.")


def test_the_default_destination_is_reachable_from_an_empty_project():
    """THE BIDIRECTIONAL CONTROL, and the reason the arm above can fail.

    Same program, same project, the redirect REMOVED — which is the clause as
    it shipped before this guard existed. It must create the declared artefact.
    If it does not, the green above is a statement about a program that writes
    nothing here, not about the redirect working, and this file would go on
    passing after the redirect were deleted.
    """
    for step, cmd, prog, rel, declaring in subjects():
        with tempfile.TemporaryDirectory(prefix="gate_producer_ctl_") as td:
            project = _make_project(Path(td))
            before = _files(project)
            cp = _run_clause(project, cmd, drop_redirect=True)
            created = _files(project) - before
            assert rel in created, (
                f"step {step}: {prog} run WITHOUT its redirect did not create "
                f"{rel!r} (rc={cp.returncode}); created {sorted(created)}. "
                f"Without this the positive arm proves nothing — a program "
                f"that writes nothing here would satisfy it whether or not the "
                f"redirect works.\n"
                f"stderr: {(cp.stderr or '').strip()[-400:]}")
            assert _declares(rel), (
                f"{rel!r} is no longer declared by any step, so the subject "
                f"set is stale")


def test_the_redirect_target_is_written_where_the_clause_names_it():
    """The redirect must LAND, not merely be accepted.

    Asserted separately from the negative arm above because they fail for
    different reasons: a program that silently ignores an unknown option would
    pass "created nothing declared" while writing nowhere at all, and a gate
    whose report is never written is the disclosure gap this repo files as
    RECORDED-NOTHING.
    """
    for step, cmd, prog, rel, declaring in subjects():
        redirect = _redirect_of(cmd)
        assert redirect is not None, f"step {step}: `{cmd}` has no redirect"
        _, target = redirect
        with tempfile.TemporaryDirectory(prefix="gate_producer_tgt_") as td:
            project = _make_project(Path(td))
            cp = _run_clause(project, cmd, drop_redirect=False)
            landed = project / target
            assert landed.is_file(), (
                f"step {step}: gate clause `{cmd}` names {target!r} but the "
                f"program wrote no such file (rc={cp.returncode}).\n"
                f"stderr: {(cp.stderr or '').strip()[-400:]}")
            json.loads(landed.read_text(encoding="utf-8"))
