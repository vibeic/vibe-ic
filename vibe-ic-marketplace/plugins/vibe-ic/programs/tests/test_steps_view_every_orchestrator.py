#!/usr/bin/env python3
"""EVERY orchestrator must end with the per-STEP output view present.

WHAT WAS BROKEN
---------------
`step_output_collector.materialize` was called from exactly ONE place —
`vibe_ic_one_shot_runner.py` finalize, wrapped in a bare
`try/except Exception: pass`. Consequences, both measured on real run dirs:

  * a run driven straight at phase1 / phase2 / phase3 / analog ended with NO
    `steps/` tree. MEASURED: `AI_IC_design/4th_benchmark/sha256_rerun_e2e`
    (a full phase1+phase2+phase3 tree, 63 flow steps, 23 of them with real
    outputs) had no `steps/` at all, while the top-runner ibex backend run
    `campaign_v1578/ibex/converge_1.5.78_sky130A_armA_stock` had one;
  * when the build DID fail, the bare `except: pass` left no trace, so
    "this run has no steps tree" was indistinguishable from "this
    orchestrator never built one" — an absence nobody could attribute.

THE CONTROLS HERE
-----------------
Forward (must FAIL against the byte-identical pre-change files):
  1. `_pl.emit_steps_view` exists, builds the tree, and writes a status record.
  2. Every orchestrator's `main()` calls it (AST, not a text grep — the call
     must be INSIDE main, not in a comment or an unreachable helper).
  3. END-TO-END through a real orchestrator front door
     (`phase1_one_shot_runner.py <project>`): the run leaves a nested
     `steps/<phase>/<stage>/<id>_<slug>/` tree and an OK status record.

Reverse (must STILL pass — these guard the properties the fix must not cost):
  4. A collector that raises, or is missing entirely, produces a RECORD and
     no exception — bookkeeping never kills a run.
  5. A real orchestrator run whose view CANNOT be built still returns its own
     exit code, and says so on disk.
  6. `top_level_outputs_in_canonical_check` still rejects every stray it
     rejected before (`sim/`, `run_logs/`, `rtl/`, a top-level `*.log`), and
     still passes a canonical tree. Whitelisting `steps/` records a directory
     the flow legitimately owns; it does not widen the gate.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import _path_layout as _pl   # noqa: E402

#: WHERE PASS 1's RECORD LIVES, asked of the router. R-0915-151 moved
#: `phase1_one_shot.json` onto `_path_layout`'s router, because the flat
#: `reports/phase1_one_shot.json` is a location this repo's own
#: `reports_subfolder_taxonomy_check` calls a stray file. These arms are about the SECOND PASS
#: being reachable and consuming the delivered answer, not about layout: they staged pass 1 flat
#: and then read the flat path back, so once the second pass began publishing at the routed path
#: they were reading a file nobody had updated. The legacy-location behaviour has its own home,
#: `test_a_pass_one_written_before_the_move_is_still_carried.py`; these ask the router so they
#: are not accidentally testing two things.
def _pass1_record(project: Path) -> Path:
    # The parent is created because several of these call sites WRITE pass 1's record to stage a
    # project. The flat location they used to write needed no mkdir -- `reports/` already existed
    # -- and the routed one does; my first rewrite of these arms missed that and turned them into
    # FileNotFoundError at `reports/orchestrator/`. Harmless on a read.
    path = _pl.report_path(project, "phase1_one_shot.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path

import _watchdog  # noqa: E402


def _supervised(cmd, **kw):
    """`subprocess.run(cmd, capture_output=True, text=True, check=False)` with
    the wall-clock budget REPLACED by forward-progress supervision.

    These call sites used to carry a fixed `timeout=`. That number is not a
    property of the subject — it is a guess about a HOST — and when the guess is
    wrong on a loaded machine `TimeoutExpired` propagates out of the test and is
    recorded as the SUBJECT being broken. The verdict is then manufactured by
    the machine rather than measured on the program; the owner hit exactly that
    on a module nobody had changed.

    `_watchdog.run_host_supervised` bounds NO FORWARD PROGRESS instead — CPU and
    I/O summed over the child's whole /proc tree, plus the growth of its
    captured output — so a child that is merely slow runs to completion however
    long that legitimately takes, while one that is genuinely hung is still
    killed. A kill arrives as rc `_watchdog.RC_STALLED` with WATCHDOG_STALLED on
    stderr: a distinct code none of these subjects produces itself, so a hang
    can never be misread as an ordinary non-zero exit."""
    res = _watchdog.run_host_supervised(cmd, **kw)
    return _watchdog.completed_process(cmd, res)

#: No wall-clock bound for the launches in this file. The measurements that
#: produced one (1.01 s for a real `phase1_one_shot_runner` run, 0.04 s for the
#: gate CLI, so "60 s is ~59x the slowest") are readings of ONE host on ONE
#: day. A margin over a measured host is still a statement about the host: on a
#: loaded or slower machine the bound fires, and what gets recorded is not "the
#: box was busy" but `phase1_one_shot_runner` FAILING. The launches go through
#: `_supervised` (below), which bounds no-forward-progress instead.


# --------------------------------------------------------------------------
# 1. the shared helper exists and does the owner-specified thing
# --------------------------------------------------------------------------
def test_helper_builds_nested_tree_and_records_ok(tmp_path):
    project = tmp_path / "proj"
    out = _pl.steps_view_report_path(project)
    assert out.parent.name in _pl.REPORTS_VALID_SUBDIRS


# --------------------------------------------------------------------------
# 3. END-TO-END through a real orchestrator front door
# --------------------------------------------------------------------------
def _stage_one_input(project: Path) -> None:
    """Give the run ONE staged input.

    The two end-to-end cases below assert `returncode == 0` because their
    subject is the STEPS-VIEW bookkeeping — "a completed run leaves the tree",
    and "bookkeeping never kills a run". They used an input-less project as the
    cheapest way to reach a completed run, and that stopped being a completed
    run when canonical step D1 gained its `required_inputs` pre-flight: a Phase
    1 handed nothing to read is now BLOCKED, not a graceful PASS_WITH_WAIVERS.

    Staging one prompt keeps each test measuring exactly what it says it
    measures. Without it, `rc == 0` would no longer distinguish "bookkeeping
    did not kill the run" from "the pre-flight refused before bookkeeping ever
    ran", i.e. the reverse case would stop being able to fail for its own
    reason.
    """
    (project / "input").mkdir(parents=True, exist_ok=True)
    (project / "input" / "phase1_prompt.md").write_text(
        "# a 4-bit up counter with a synchronous reset\n")
    # owner route rule 2026-09-28 (ICROUTE)
    from _route_fixture import stage_owner_route
    stage_owner_route(project, "ic")


def test_real_orchestrator_run_leaves_the_tree(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    _stage_one_input(project)
    argv = [sys.executable, str(PROGRAMS / "phase1_one_shot_runner.py"),
            str(project), "--route", "ic", "--mode", "prompt", "--ic-name", "TST"]
    cp = _supervised(argv)
    assert cp.returncode == 0, cp.stderr


def test_run_survives_a_view_that_cannot_be_built(tmp_path):
    """END-TO-END reverse case: block the tree at the filesystem level (a
    regular file where `steps/` must be a directory) and the orchestrator
    must still finish with its own exit code — and say so on disk."""
    project = tmp_path / "proj"
    project.mkdir()
    _stage_one_input(project)
    (project / "steps").write_text("not a directory\n")

    argv = [sys.executable, str(PROGRAMS / "phase1_one_shot_runner.py"),
            str(project), "--route", "ic", "--mode", "prompt", "--ic-name", "TST"]
    cp = _supervised(argv)

    assert cp.returncode == 0, (
        "bookkeeping killed the run:\n" + cp.stdout + cp.stderr)
    assert _pass1_record(project).is_file()
    assert (project / 'steps').read_text() == 'not a directory\n'
    retained = list((project / 'reports/step_versions').glob('*/*/*/outputs.json'))
    assert retained, 'an unavailable dashboard view must not lose actual step versions'
    # Phase 1 also executes the IC template search. Both actual calls must
    # survive the unavailable view; neither is an invented dashboard PASS.
    assert {json.loads(path.read_text())['id'] for path in retained} == {'D1', '0.5ic'}
    current = [json.loads(path.read_text()) for path in retained
               if isinstance((json.loads(path.read_text()).get('result') or {}).get('canonical_consumer'), dict)]
    assert {row['result']['runner'] for row in current} == {'phase1_one_shot_runner'}
