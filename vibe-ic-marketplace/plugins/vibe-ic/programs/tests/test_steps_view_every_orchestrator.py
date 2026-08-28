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

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import _path_layout as _pl   # noqa: E402
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

# DISCOVERED, not hand-listed: a new `*_one_shot_runner.py` front door must
# wire the view or this control fails, instead of quietly reopening the hole
# this change closed. Two files are excluded, each for a stated reason:
#
#   phase2_one_shot_runner.py     — a verbatim re-export shim
#                                   (`from design_one_shot_runner import main`).
#                                   It defines no main() of its own; the design
#                                   entry is what actually runs.
#   phase1_doc_one_shot_runner.py — a DELEGATE, not a front door. It is spawned
#                                   by phase1_one_shot_runner's docs mode, which
#                                   publishes the view after it returns; no
#                                   command or skill invokes it directly.
_NOT_A_FRONT_DOOR = {
    "phase2_one_shot_runner.py",
    "phase1_doc_one_shot_runner.py",
}
ORCHESTRATORS = sorted(
    p.name for p in PROGRAMS.glob("*_one_shot_runner.py")
    if p.name not in _NOT_A_FRONT_DOOR)


def test_orchestrator_discovery_is_not_empty_or_stale():
    """The parametrized control above is only as good as this list."""
    assert len(ORCHESTRATORS) >= 6, ORCHESTRATORS
    for excluded in _NOT_A_FRONT_DOOR:
        assert (PROGRAMS / excluded).is_file(), (
            f"{excluded} is excluded from the wiring control but no longer "
            f"exists — drop the exclusion instead of carrying it")
    shim = (PROGRAMS / "phase2_one_shot_runner.py").read_text()
    assert "from design_one_shot_runner import main" in shim, (
        "phase2_one_shot_runner is excluded on the grounds that it is a "
        "verbatim re-export shim; it no longer is")

TOP_LEVEL_GATE = PROGRAMS / "top_level_outputs_in_canonical_check.py"

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
    (project / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (project / "phase2" / "stage1" / "rtl" / "top.v").write_text(
        "module top(); endmodule\n")

    rec = _pl.emit_steps_view(project, PROGRAMS, runner="unit-test")

    assert rec["status"] == "OK", rec
    assert rec["n_steps"] > 0, rec
    # The owner's shape: phase / stage / step, NOT a flat steps/.
    assert rec["nested_folders"] == rec["n_steps"], rec
    idx = json.loads((project / "steps" / "index.json").read_text())
    for step in idx["steps"]:
        assert step["folder"].count("/") == 2, step
        assert (project / "steps" / step["folder"]).is_dir()

    # ... and the status record is on disk, in a taxonomy-legal location.
    out = _pl.steps_view_report_path(project)
    assert out.is_file()
    assert out.parent.name in _pl.REPORTS_VALID_SUBDIRS
    assert json.loads(out.read_text())["status"] == "OK"


# --------------------------------------------------------------------------
# 2. every orchestrator calls it, inside main()
# --------------------------------------------------------------------------
# The two ways main() may build the view. `publish_report_then_steps_view` is
# `emit_steps_view` with the run's own per-step verdicts written to disk FIRST,
# so the collector subprocess can join them onto the step records; a runner that
# uses it builds the tree exactly as before. Admitting the name here is not a
# relaxation — `test_the_view_publisher_actually_builds_the_view` below asserts,
# by AST, that the wrapper really does call `emit_steps_view` and really does
# write the report before it. Without that companion this list would let a
# same-named no-op satisfy the control.
_VIEW_BUILDERS = ("emit_steps_view", "publish_report_then_steps_view")


@pytest.mark.parametrize("runner", ORCHESTRATORS)
def test_every_orchestrator_calls_emit_steps_view_in_main(runner):
    tree = ast.parse((PROGRAMS / runner).read_text())
    mains = [n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
             and n.name == "main"]
    assert mains, f"{runner}: no main() to wire"
    calls = [n for m in mains for n in ast.walk(m)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr in _VIEW_BUILDERS]
    assert calls, (
        f"{runner}: main() never builds the steps view (no call to any of "
        f"{_VIEW_BUILDERS}) — a run driven through this front door would end "
        f"with no steps/ tree")


def test_the_view_publisher_actually_builds_the_view():
    """The wrapper admitted above must do both halves of its name.

    ORDER IS THE POINT, and it is asserted rather than assumed: the collector
    runs as a SUBPROCESS and can only join this run's per-step verdicts onto
    the step records if the report is already on disk. A wrapper that built the
    view first would silently restore the defect it exists to remove — a step
    whose runner returned FAIL published as `pass`, because the FAIL's own
    artefacts had already been written when existence was measured.
    """
    tree = ast.parse((PROGRAMS / "_path_layout.py").read_text())
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef)
               and n.name == "publish_report_then_steps_view"), None)
    assert fn is not None, (
        "_path_layout no longer defines publish_report_then_steps_view, but "
        "the wiring control above still admits the name")

    def _offset(pred):
        hits = [n.lineno for n in ast.walk(fn) if pred(n)]
        assert hits, "not found in publish_report_then_steps_view"
        return min(hits)

    write_at = _offset(
        lambda n: isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute) and n.func.attr == "write_text")
    build_at = _offset(
        lambda n: isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name) and n.func.id == "emit_steps_view")
    assert write_at < build_at, (
        "publish_report_then_steps_view builds the steps view at line "
        f"{build_at} but only writes the report at line {write_at} — the "
        "collector would read a report from a previous run, or none")


def test_phase1_wires_both_of_its_exits():
    """phase1's main() returns from two places (docs mode and prompt mode);
    wiring only one leaves the vendor-document front door without a tree."""
    tree = ast.parse((PROGRAMS / "phase1_one_shot_runner.py").read_text())
    main = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    calls = [n for n in ast.walk(main)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "emit_steps_view"]
    assert len(calls) >= 2, (
        "phase1_one_shot_runner.main() has two exits (docs / prompt) and "
        f"only {len(calls)} emit_steps_view call(s)")


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


def test_real_orchestrator_run_leaves_the_tree(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    _stage_one_input(project)
    cp = _supervised(
        [sys.executable, str(PROGRAMS / "phase1_one_shot_runner.py"),
         str(project), "--mode", "prompt", "--ic-name", "TST"])
    assert cp.returncode == 0, cp.stderr

    idx_path = project / "steps" / "index.json"
    assert idx_path.is_file(), (
        "a completed orchestrator run left no steps/index.json:\n" + cp.stdout)
    steps = json.loads(idx_path.read_text())["steps"]
    assert steps
    assert all(s["folder"].count("/") == 2 for s in steps)

    rec = json.loads(_pl.steps_view_report_path(project).read_text())
    assert rec["status"] == "OK", rec
    assert rec["runner"] == "phase1_one_shot_runner", rec
    assert rec["n_steps"] == len(steps)

    # The runner's own report carries the same record, so a reader who opens
    # only the summary still sees the view's state.
    summary = json.loads(
        (project / "reports" / "phase1_one_shot.json").read_text())
    assert summary["steps_view"]["status"] == "OK", summary["steps_view"]


# --------------------------------------------------------------------------
# 4-5. REVERSE: a failed view is recorded, never raised, never fatal
# --------------------------------------------------------------------------
def _fake_programs(tmp_path: Path, body: str) -> Path:
    d = tmp_path / "fake_programs"
    d.mkdir()
    (d / "step_output_collector.py").write_text(body)
    return d


def test_collector_that_raises_is_recorded_not_raised(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    fake = _fake_programs(tmp_path, "raise SystemExit('boom: no collector')\n")

    rec = _pl.emit_steps_view(project, fake, runner="unit-test")

    assert rec["status"] == "BUILD_FAILED", rec
    assert rec["error"], "a failure with no reason is still a silent failure"
    assert not (project / "steps").exists()
    on_disk = json.loads(_pl.steps_view_report_path(project).read_text())
    assert on_disk["status"] == "BUILD_FAILED"
    assert on_disk["runner"] == "unit-test"


def test_missing_collector_is_recorded(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    empty = tmp_path / "no_programs"
    empty.mkdir()

    rec = _pl.emit_steps_view(project, empty, runner="unit-test")

    assert rec["status"] == "COLLECTOR_MISSING", rec
    assert json.loads(
        _pl.steps_view_report_path(project).read_text())["status"] \
        == "COLLECTOR_MISSING"


def test_collector_timeout_is_recorded(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    fake = _fake_programs(tmp_path, "import time\ntime.sleep(30)\n")

    rec = _pl.emit_steps_view(project, fake, runner="unit-test", timeout=1)

    assert rec["status"] == "TIMEOUT", rec
    assert json.loads(
        _pl.steps_view_report_path(project).read_text())["status"] == "TIMEOUT"


def test_run_survives_a_view_that_cannot_be_built(tmp_path):
    """END-TO-END reverse case: block the tree at the filesystem level (a
    regular file where `steps/` must be a directory) and the orchestrator
    must still finish with its own exit code — and say so on disk."""
    project = tmp_path / "proj"
    project.mkdir()
    _stage_one_input(project)
    (project / "steps").write_text("not a directory\n")

    cp = _supervised(
        [sys.executable, str(PROGRAMS / "phase1_one_shot_runner.py"),
         str(project), "--mode", "prompt", "--ic-name", "TST"])

    assert cp.returncode == 0, (
        "bookkeeping killed the run:\n" + cp.stdout + cp.stderr)
    assert (project / "reports" / "phase1_one_shot.json").is_file()
    rec = json.loads(_pl.steps_view_report_path(project).read_text())
    assert rec["status"] != "OK", rec
    assert rec["error"], rec
    # Not silent: the human watching the run is told too.
    assert "steps view NOT built" in cp.stderr


# --------------------------------------------------------------------------
# 6. REVERSE: the top-level hygiene gate still rejects what it always did
# --------------------------------------------------------------------------
def _gate(project: Path) -> subprocess.CompletedProcess:
    return _supervised([sys.executable, str(TOP_LEVEL_GATE), str(project)])


def _canonical_project(tmp_path: Path, name: str) -> Path:
    project = tmp_path / name
    for d in ("input", "phase1", "phase2", "phase3", "reports"):
        (project / d).mkdir(parents=True)
    (project / "waivers.json").write_text("{}\n")
    return project


def _stray_dirs_reported(cp: subprocess.CompletedProcess) -> str:
    """The stray-dir list off the VERDICT line only — the trailing
    'Allowed dirs:' help line legitimately contains the word `steps`."""
    line = next(l for l in cp.stdout.splitlines() if l.startswith("[FAIL]"))
    return line.split("stray dir(s):")[1].split(";")[0] if "stray dir(s):" in line else ""


# -- REVERSE INVARIANTS: these must pass BEFORE and AFTER the change. No
#    `steps/` in the fixture, so they assert only what the gate always did.
@pytest.mark.parametrize("stray", ["sim", "run_logs", "rtl", "synth", "pnr"])
def test_top_level_gate_still_rejects_stray_dirs(tmp_path, stray):
    project = _canonical_project(tmp_path, f"p_{stray}")
    (project / stray).mkdir()
    cp = _gate(project)
    assert cp.returncode == 1, cp.stdout
    assert stray in _stray_dirs_reported(cp), cp.stdout


def test_top_level_gate_still_rejects_stray_files(tmp_path):
    project = _canonical_project(tmp_path, "p_file")
    (project / "runner.log").write_text("noise\n")
    cp = _gate(project)
    assert cp.returncode == 1, cp.stdout
    assert "runner.log" in cp.stdout


def test_top_level_gate_still_passes_a_canonical_tree(tmp_path):
    cp = _gate(_canonical_project(tmp_path, "p_plain"))
    assert cp.returncode == 0, cp.stdout
    assert "[PASS]" in cp.stdout


# -- FORWARD: the view is a canonical home, and whitelisting it cost the gate
#    none of its teeth (a stray beside the view is still reported).
def test_top_level_gate_accepts_the_steps_view(tmp_path):
    project = _canonical_project(tmp_path, "p_view")
    (project / "steps").mkdir()
    cp = _gate(project)
    assert cp.returncode == 0, (
        "every run now publishes steps/; a hygiene gate that reddens on every "
        "run is a gate readers learn to ignore:\n" + cp.stdout)


def test_steps_view_does_not_mask_a_stray_beside_it(tmp_path):
    project = _canonical_project(tmp_path, "p_view_stray")
    (project / "steps").mkdir()
    (project / "sim").mkdir()
    cp = _gate(project)
    assert cp.returncode == 1, cp.stdout
    listed = _stray_dirs_reported(cp)
    assert "sim" in listed, cp.stdout
    assert "steps" not in listed, (
        "the owner's publication view is being reported as a stray: " + listed)
