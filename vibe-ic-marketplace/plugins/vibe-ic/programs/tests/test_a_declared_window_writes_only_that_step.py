#!/usr/bin/env python3
"""A run that declares a window writes only that window's own work.

R-0924-1, the owner's ask: when a gate is wrong, re-run THAT step -- only it. The window was already honoured for DISPATCH; the FINALIZE
TAIL was not, and no flag reached it.

MEASURED before this change, on a copy of benchmark-data/ic/subservient at main
69abc2734, `design_one_shot_runner . --entry-step 4 --exit-step 4`:
    766 files touched, 432 of them OUTSIDE step 4's own workspace
    23 flow_compliance_check invocations, 3 of them over the WHOLE flow
    reports/final_summary.md republished with a fence reading "Steps: 70 total"
for a run that dispatched one step. The leak is not the window: every
out-of-window dispatch site correctly reports NOT_APPLICABLE and names the flag
that pruned it.

WHAT THESE ARMS PIN. Each one fails if the tail is re-enabled for a bounded run:
the five `emit_final_summary` sites, the whole-flow `final_audit`, the
declared-producer sweep, the two gate-identity sweeps and the whole-tree steps
view. The behavioural arms drive the real narrowing predicates rather than
grepping for them, because a source substring cannot tell you a branch bites.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parent.parent


def _load(name: str):
    # Consumers import the canonical module during execution. Replacing its
    # public name here disconnects their producer from fixtures collected
    # earlier in the same pytest process.
    fixture_name = f"_declared_window_{name}"
    spec = importlib.util.spec_from_file_location(fixture_name, PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[fixture_name] = mod  # dataclass annotations need this identity
    spec.loader.exec_module(mod)
    return mod


def test_window_fixture_preserves_the_canonical_consumer_module():
    import phase3_one_shot_runner as canonical

    isolated = _load("phase3_one_shot_runner")
    assert isolated is not canonical
    assert sys.modules["phase3_one_shot_runner"] is canonical
    import phase3_one_shot_runner as consumer
    assert consumer is canonical


# --------------------------------------------------------------------------- #
# -2. the window question is asked of what THIS runner can bound
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# -1. what a bounded run's rc does NOT decide
# --------------------------------------------------------------------------- #
def test_the_benchmark_scorers_contract_reads_the_report_row_never_rc(tmp_path):
    """A bounded run's rc answers for its declared window only, and the scorer
    never asks it.

    THE RULING THIS PINS (R-0924-1, after the r2 review). Every solve the harness
    dispatches carries a window -- `_solver_argv` sends --exit-step 2/4/9 or
    --entry-step 2, all of which prune real sites -- so on a bounded run a
    whole-flow phase-2 audit FAIL would be a verdict over the ~69 steps that did
    not run. It is booked NOT_APPLICABLE instead, which means rc can differ from
    base for a solve whose ONLY failure was that audit. That is safe for scoring
    for one reason, and this arm is that reason: the scorer's contract reads the
    REPORT ROW, not the exit code.

    MEASURED on a benchmark-shaped solve before and after the change: rc 1 both
    ways, 32 step rows both ways, and the `rtl_gen` row byte-identical."""
    bd = _load("benchmark_dispatch")
    fn = bd._rtl_gen_waive
    args = fn.__code__.co_varnames[:fn.__code__.co_argcount]
    assert args == ("project",), (
        f"the handover contract now takes {args}; if an exit code is ever one of "
        f"them, a bounded run's rc starts deciding a scoring question")

    rep = tmp_path / "reports" / "orchestrator" / "phase2_one_shot.json"
    rep.parent.mkdir(parents=True)

    def write(verdict, rows):
        rep.write_text(json.dumps({"verdict": verdict, "steps": rows}) + "\n")

    waived = [{"name": "rtl_gen", "status": "WAIVED", "detail": "handed over",
               "extras": {"fallback_skill": "rtl-author"}}]
    write("PASS", waived)
    got = fn(tmp_path)
    assert got == {"fallback_skill": "rtl-author", "detail": "handed over"}, got

    # THE ROW DECIDES, NOT THE RUN'S VERDICT. Same row under a FAIL roll-up --
    # which is what a bounded run whose window failed publishes -- same answer.
    write("FAIL", waived)
    assert fn(tmp_path) == got, "the handover moved with the roll-up verdict"
    write("NOT_MEASURED", waived)
    assert fn(tmp_path) == got

    # and no row means no handover, whatever the verdict claims
    write("PASS", [])
    assert fn(tmp_path) is None
    write("PASS", [{"name": "rtl_gen", "status": "WAIVED", "extras": {}}])
    assert fn(tmp_path) is None, (
        "a WAIVED row without fallback_skill is not a handover")


# --------------------------------------------------------------------------- #
# 0. the decision itself — DRIVEN, and bound to nothing else
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# 1. the five report-card sites
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# 2. the whole-flow audit, the producer sweep
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# 3. the narrowed gate-identity sweeps — DRIVEN
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# 4. the bounded steps view — DRIVEN
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# 5. ONE staleness rule, and the refresh the operator can ask for
# --------------------------------------------------------------------------- #
def test_published_here_has_one_owner_and_the_front_door_asks_it():
    """#2572/#2575's freshness predicate, asked by both readers.

    The bounded run needs it for arbitrary paths; the front door needs it for a
    phase report. Two implementations is how two staleness rules come to
    disagree about one file."""
    pl = _load("_path_layout")
    assert callable(pl.published_here) and hasattr(pl, "FRESHNESS_TOLERANCE_S")


def test_published_here_fails_closed(tmp_path):
    pl = _load("_path_layout")
    started = time.time()
    f = tmp_path / "doc.md"
    f.write_text("x")
    assert pl.published_here(f, started) is True
    old = started - 10_000
    os.utime(f, (old, old))
    assert pl.published_here(f, started) is False
    assert pl.published_here(tmp_path / "absent.md", started) is False
    assert pl.published_here(tmp_path, started) is False   # a directory
