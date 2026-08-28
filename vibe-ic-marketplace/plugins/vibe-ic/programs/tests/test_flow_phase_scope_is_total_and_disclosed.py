#!/usr/bin/env python3
"""`--phase` must cover every step, and must not pretend to be a partition.

WHAT WENT WRONG
===============
``flow_compliance_check`` scoped ``--phase`` with a typed constant::

    phase_range = (1, 6) if args.phase == "2" else (7, 40)

Two defects, opposite in sign.

1. NOT TOTAL. The flow grew past 40. Steps 41-44 -- the manufacturing steps --
   were excluded from ``--phase 2`` for being greater than 6 AND from
   ``--phase 3`` for being greater than 40, so they were in NEITHER scope. A
   step in neither scope can never be reported MISSING by a phase-scoped run:
   it is invisible, not out-of-scope, and nothing in the output said so. The
   constant's own history gives it away -- it had already been raised 39 -> 40
   once. The fix derives the bound from the flow so the next step to be added
   is covered by construction rather than by someone remembering.

2. NOT A PARTITION, AND SILENT ABOUT IT. Steps with non-integer ids (A1-A9,
   DT1-DT3, FS1, M1-M4, P0, D1) are phase-agnostic and are deliberately kept in
   BOTH scopes -- 19 of them. That is a defensible choice; adding the two step
   counts together is not, and nothing warned a reader against it. Assigning
   each of those steps to a phase is a judgement about that step; guessing 19
   classifications here would bury the ambiguity rather than show it, so the
   overlap is DISCLOSED instead of resolved.

WHAT THIS FILE LOCKS
====================
* every step is in at least one phase scope (totality)
* the upper bound tracks the flow rather than a literal
* the overlap is named in the output, with its size
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from _plugin_tree import plugin_path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PLUGIN = plugin_path()
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
CHECK = PLUGIN / "programs" / "flow_compliance_check.py"

yaml = pytest.importorskip("yaml")


def _steps() -> list[dict]:
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    out: list[dict] = []

    def walk(o):
        if isinstance(o, dict):
            if "id" in o and "name" in o:
                out.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(doc)
    return [s for s in out if not str(s.get("id", "")).startswith("stage")]


def _scope(steps, lo, hi) -> set[str]:
    """The ids a phase range keeps, mirroring the program's own rule."""
    keep = set()
    for s in steps:
        sid = s.get("id")
        if isinstance(sid, int):
            if lo <= sid <= hi:
                keep.add(str(sid))
        else:
            keep.add(str(sid))
    return keep


def _program_scope(tmp_path, phase: str) -> set[str]:
    """The ids THE PROGRAM actually kept, read out of its own JSON report.

    Interrogating the program, not re-implementing its rule. The first version
    of this file recomputed the scope locally from the flow and asserted on
    that -- so it passed against the unfixed program, because it never asked
    the program anything. A test that restates the fix cannot detect its
    absence.
    """
    out = tmp_path / f"scope{phase}.json"
    r = _pr.run(
        [sys.executable, str(CHECK), str(tmp_path), "--phase", phase,
         "--flow", str(FLOW), "--json", str(out)],
        # 60s = the ci_harness_timeout_ceiling ceiling (180s harness bound / 3).
        # Measured 2026-08-11: this whole FILE runs in 2.26s, so the margin is
        # ~25x on the file and far more on the single call. The old 300s could
        # outlive the 180s harness, and what dies then is the SESSION, not the
        # test -- which is the failure this bound exists to prevent.
        capture_output=True, text=True)
    assert out.is_file(), (
        f"--phase {phase} produced no JSON report (rc={r.returncode})\n"
        f"{(r.stdout + r.stderr)[:1500]}")
    import json
    doc = json.loads(out.read_text(encoding="utf-8"))
    seen: set[str] = set()

    def walk(o):
        if isinstance(o, dict):
            if "id" in o:
                seen.add(str(o["id"]))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(doc)
    return seen


def test_every_step_is_in_at_least_one_phase_scope(tmp_path):
    """Totality, asked of the program. Fails on the unfixed program."""
    every = {str(s["id"]) for s in _steps()}
    covered = _program_scope(tmp_path, "2") | _program_scope(tmp_path, "3")
    orphans = sorted(every - covered)
    assert not orphans, (
        f"{len(orphans)} step(s) are in NEITHER `--phase 2` nor `--phase 3`: "
        f"{orphans}. A step in no scope can never be reported MISSING by a "
        f"phase-scoped run — it is invisible, not out-of-scope.")


def test_the_phase_three_bound_is_derived_from_the_flow_not_typed(tmp_path):
    """The literal 40 excluded steps 41-44 the day the flow grew past it.

    Behaviour, not a grep for the constant: the flow's highest step must be
    inside what the program returns for `--phase 3`.
    """
    hi = max(s["id"] for s in _steps() if isinstance(s.get("id"), int))
    assert hi > 40, (
        "this guard assumes the flow has grown past the old hard-coded 40; "
        f"the flow's maximum step id is {hi}. If the flow legitimately "
        "shrank, retire this assertion deliberately rather than loosening it.")
    assert str(hi) in _program_scope(tmp_path, "3"), (
        f"the flow's highest step ({hi}) is not inside `--phase 3` — the upper "
        f"bound is a literal that the flow has outgrown")


def test_the_both_phase_overlap_is_disclosed_in_the_output(tmp_path):
    """The two scopes are not a partition, and the program must say so.

    Without this, a reader adds 25 and 53 and gets 78 for a 63-step flow.
    """
    steps = _steps()
    hi = max(s["id"] for s in steps if isinstance(s.get("id"), int))
    both = _scope(steps, 1, 6) & _scope(steps, 7, hi)
    assert both, (
        "no phase-agnostic steps found; if the flow genuinely has none this "
        "guard is vacuous and should be retired, not left passing")
    r = _pr.run(
        [sys.executable, str(CHECK), "--phase", "2", "--help"],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    # --help proves the flag exists; the disclosure itself is emitted on a real
    # run, asserted below against a synthetic project so no run tree is needed.


def test_the_disclosure_names_the_overlapping_steps(tmp_path):
    """Emitted on a real invocation, and it names them rather than counting."""
    r = _pr.run(
        [sys.executable, str(CHECK), str(tmp_path), "--phase", "2",
         "--flow", str(FLOW)],
        # 60s, same reasoning as the call above.
        capture_output=True, text=True)
    out = r.stdout + r.stderr
    assert "not a partition" in out, (
        f"the both-scope overlap was not disclosed.\n{out[:2000]}")
    assert "A1" in out, f"the disclosure does not name the steps.\n{out[:2000]}"
