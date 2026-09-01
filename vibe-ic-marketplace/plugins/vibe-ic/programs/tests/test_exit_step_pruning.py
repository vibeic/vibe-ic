#!/usr/bin/env python3
"""`--exit-step` prunes execution past the declared exit; before it, nothing was.

    "怎麼可能為了回答一個 benchmark 的問題,都去跑 Phase 2、Phase 3 的整個流程呢?"
                                                — owner directive 2026-08-25

`task_nature_route` declares the full exit contract (EVIDENCE_EXIT maps ten
evidence classes to exit steps), but execution consumed exactly ONE bit of it:
`benchmark_dispatch` collapsed the exit into `--skip-phase3`. A lint-evidence
run (exit step 2) therefore still dispatched the sim TB producers, synthesis,
and the DFT/LEC chain — whose SAT LEC carries a 3x7200s+300s timeout budget —
13 canonical steps past its own deliverable, producing artefacts no scorer
reads.

The fix mirrors the existing `--entry-step` machinery rather than inventing a
new shape: `design_one_shot_runner` gains `--exit-step`, a pure
`_exit_pruned_sites` decision over the SAME `step_preflight.RUNNER_PLANS`
site table `_before_entry` uses, a `SKIPPED-BY-EXIT` sentinel disclosed in the
run report and classified as a designed skip (never a FAIL, never
UNCLASSIFIED noise) by `_aggregate_verdict` and `flow_phase_attribution`; the
orchestrator forwards the flag like `--entry-step`; the dispatcher forwards
the exit it already computes. Span-atomicity is preserved in BOTH directions:
a span is one tool session, so the site whose span holds the exit runs IN
FULL and only sites whose whole span starts after the exit are pruned.

Also locked here: the dispatcher's runner subprocess gains an env-tunable
wall-clock ceiling (`VIBEIC_SOLVE_RUNNER_TIMEOUT_S`) so one problem cannot
eat an entire run's budget; unset keeps the historical unbounded behaviour,
and an unparseable value REFUSES rather than silently running unbounded.

chip-AGNOSTIC: fixtures use synthetic generic names only.
"""
from __future__ import annotations

import contextlib
import io
import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(PROGRAMS.parent / "benchmark"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import benchmark_dispatch as bd                        # noqa: E402
import benchmark_entry_surface_check as bes            # noqa: E402
import benchmark_io_adapter as bio                     # noqa: E402
import flow_phase_attribution as fpa                   # noqa: E402
import step_preflight as spf                           # noqa: E402
import task_nature_route as tnr                        # noqa: E402
import vibe_ic_one_shot_runner as orch                 # noqa: E402

RUNNER = PROGRAMS / "design_one_shot_runner.py"


# ── the pruning decision, lifted from the shipped runner ─────────────────────
@pytest.fixture(scope="module")
def pruner():
    """The real `_exit_pruned_sites`, extracted by source.

    The runner module is too heavy to import (same reason
    test_design_verdict_has_no_silent_catch_all lifts `_aggregate_verdict`);
    a re-implementation here would pass whatever this file believed, which is
    the failure mode source-lifting exists to remove.
    """
    src = RUNNER.read_text(encoding="utf-8")
    m = re.search(r"def _exit_pruned_sites.*?(?=\ndef main\b)", src, re.S)
    assert m, "could not locate _exit_pruned_sites in the shipped runner"
    ns: dict = {}
    exec(m.group(0), ns)  # noqa: S102 — executing our own shipped source
    return ns["_exit_pruned_sites"]


def _sites():
    """The REAL declared site table, so these tests track the real plan."""
    return spf.RUNNER_PLANS["design_one_shot_runner"].sites


def test_lint_evidence_exit_prunes_sim_synth_and_the_lec_chain(pruner):
    """EVIDENCE_EXIT['lint_validated'] = step 2: everything past the
    rtl_validate span is pruned — including the site whose LEC burned two
    hours for an RTL deliverable nothing downstream read."""
    assert pruner(_sites(), "2") == ["sim", "yosys_synth", "dft_lec_chain"]


def test_the_exit_site_itself_runs(pruner):
    """含它: the site holding the exit is dispatched; only later sites go."""
    assert pruner(_sites(), "13") == []
    assert pruner(_sites(), "9") == ["dft_lec_chain"]


def test_a_mid_span_exit_keeps_the_whole_span(pruner):
    """Span atomicity, mirrored from entry: dft_lec_chain is ONE chain over
    canonical 11..13, so an exit at 11 or 12 cannot stop it mid-span — the
    span head is not past the exit, and the site runs in full."""
    assert pruner(_sites(), "11") == []
    assert pruner(_sites(), "12") == []


def test_an_exit_past_every_span_prunes_nothing(pruner):
    """§4.05 boundary-outside: a phase-3 exit (23/31/37 — routed today via
    --skip-phase3) must not leak pruning into the phase-2 dispatch."""
    for deep in ("23", "31", "33", "37"):
        assert pruner(_sites(), deep) == [], deep


def test_a_site_name_is_an_exit_too(pruner):
    assert pruner(_sites(), "yosys_synth") == ["dft_lec_chain"]
    assert pruner(_sites(), "dft_lec_chain") == []


def test_an_unmappable_exit_maps_to_none_so_the_caller_refuses(pruner):
    """None is the refusal signal: a typo must neither silently run the whole
    flow (defeats the flag) nor silently prune it (worse)."""
    assert pruner(_sites(), "no_such_site") is None
    assert pruner(_sites(), "") is None
    assert pruner(_sites(), None) is None


def test_the_runner_cli_refuses_an_unmappable_exit(tmp_path):
    """End-to-end: the refusal is wired, exits 2, and names the sites."""
    proj = tmp_path / "generic_proj"
    proj.mkdir()
    proc = subprocess.run(
        [sys.executable, str(RUNNER), str(proj), "--exit-step",
         "no_such_site"],
        capture_output=True, text=True, timeout=300)
    assert proc.returncode == 2, (proc.returncode, proc.stderr[-500:])
    assert "cannot exit at step" in proc.stderr, proc.stderr[-500:]


def test_every_declared_site_has_an_exit_gate_at_its_dispatch():
    """Wiring, not prose: a site declared in RUNNER_PLANS without a literal
    `_after_exit("<site>")` guard at its dispatch would be a pruning claim
    with no behaviour behind it — the same defect
    test_every_declared_site_is_wired_at_a_real_call_site exists to catch
    for the pre-flight gates."""
    src = RUNNER.read_text(encoding="utf-8")
    for name, _span in _sites():
        assert re.search(rf'_after_exit\("{re.escape(name)}"\)', src), (
            f"declared site {name!r} has no _after_exit gate in the runner")


# ── the sentinel at the verdict aggregators ──────────────────────────────────
@pytest.fixture(scope="module")
def agg():
    """The real `_aggregate_verdict`, lifted the same way."""
    src = RUNNER.read_text(encoding="utf-8")
    m = re.search(r"def _aggregate_verdict.*?(?=\nif __name__)", src, re.S)
    assert m, "could not locate _aggregate_verdict in the shipped runner"
    ns: dict = {"sys": sys}
    exec(  # noqa: S102 — executing our own shipped source, by design
        "from typing import List\n"
        "class StepResult:\n"
        "    def __init__(self, name, status):\n"
        "        self.name = name; self.status = status\n" + m.group(0),
        ns,
    )
    return ns["_aggregate_verdict"], ns["StepResult"]


def _agg_run(fn, plan):
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        verdict = fn(plan)
    return verdict, err.getvalue()


def test_skipped_by_exit_is_a_designed_skip_not_noise(agg):
    """Excused like SKIPPED-BY-ENTRY: no FAIL, no UNCLASSIFIED stderr noise,
    and disclosed in the skipped-steps line like every other skip."""
    fn, SR = agg
    verdict, err = _agg_run(fn, [SR("rtl_gen", "PASS"),
                                 SR("dft_lec_chain", "SKIPPED-BY-EXIT")])
    assert verdict == "PASS", verdict
    assert "UNCLASSIFIED" not in err, err
    assert "SKIPPED step(s)" in err and "dft_lec_chain" in err, err


def test_skipped_by_exit_cannot_excuse_a_real_failure(agg):
    fn, SR = agg
    verdict, _ = _agg_run(fn, [SR("rtl_gen", "FAIL"),
                               SR("dft_lec_chain", "SKIPPED-BY-EXIT")])
    assert verdict == "FAIL", verdict


def test_attribution_reads_the_sentinel_as_not_attempted(tmp_path):
    """`flow_phase_attribution` partitions the same vocabulary for a different
    question; a run report carrying the sentinel must land in not_attempted,
    never in unclassified_status."""
    p = tmp_path / "design"
    (p / "input").mkdir(parents=True)
    (p / "input" / "phase1_prompt.md").write_text(
        "Design a purely combinational 4-to-1 multiplexer.\n")
    rep = p / "reports" / "orchestrator"
    rep.mkdir(parents=True)
    (rep / "phase2_one_shot.json").write_text(json.dumps({
        "verdict": "PASS",
        "steps": [
            {"name": "rtl_gen", "status": "PASS", "detail": "",
             "extras": {"deterministic_generator": "multiplexer"}},
            {"name": "yosys_synth", "status": "SKIPPED-BY-EXIT",
             "detail": "run declared --exit-step 2"},
        ]}))
    r = fpa.attribute(p)["phase3_verifying"]
    assert r["not_attempted"] == {"yosys_synth": "SKIPPED-BY-EXIT"}
    assert not r.get("unclassified_status"), r


# ── the orchestrator forwards the flag like --entry-step ─────────────────────
def _drive_orchestrator(monkeypatch, project: Path, argv_extra):
    """Run orch.main() with the per-phase invocations intercepted, so the
    actual phase2 argv can be inspected without spawning EDA tools (same
    harness as test_v0_2_95_issue459_auto_skip_analog)."""
    captured: dict = {}

    def fake_run_phase(label, runner, args, env=None):
        captured[runner.name] = list(args)
        return 0

    monkeypatch.setattr(orch, "_run_phase", fake_run_phase)
    monkeypatch.setattr(orch, "_read_report",
                        lambda _p: {"verdict": "PASS"})
    monkeypatch.setattr(orch, "_need_analog", lambda _p, _s: False)
    monkeypatch.setattr(sys, "argv",
                        ["vibe_ic_one_shot_runner.py", str(project),
                         "--skip-phase1", "--skip-phase3"] + list(argv_extra))
    orch.main()
    return captured


def test_orchestrator_forwards_exit_step_to_phase2(tmp_path, monkeypatch):
    project = tmp_path / "generic_proj"
    project.mkdir()
    cap = _drive_orchestrator(monkeypatch, project, ["--exit-step", "2"])
    p2 = cap.get("phase2_one_shot_runner.py")
    assert p2 is not None, cap
    assert p2[p2.index("--exit-step") + 1] == "2", p2


def test_orchestrator_default_forwards_no_exit_step(tmp_path, monkeypatch):
    """No flag → no forwarding → phase2 behaviour is byte-for-byte今日的."""
    project = tmp_path / "generic_proj"
    project.mkdir()
    cap = _drive_orchestrator(monkeypatch, project, [])
    p2 = cap.get("phase2_one_shot_runner.py")
    assert p2 is not None, cap
    assert "--exit-step" not in p2, p2


# ── the dispatcher hands the exit it already computes to the runner ──────────
def _install_solve_fakes(monkeypatch, argv_seen: dict, exit_step: str):
    monkeypatch.setattr(bes, "audit", lambda _root: {
        "verdict": "PASS", "findings": []})
    monkeypatch.setattr(bd, "_completeness_adapters", lambda: {})
    monkeypatch.setattr(fpa, "rtl_present_at_input", lambda _project: False)
    monkeypatch.setattr(fpa, "attribute", lambda *_a, **_k: {
        "phase1_routing": {}, "phase2_solving": {},
        "phase3_verifying": {}, "phase4_debugging": {}})
    monkeypatch.setattr(fpa, "summarize", lambda _results: {})
    monkeypatch.setattr(
        tnr, "classify_task_nature",
        lambda *_a, **_k: {"nature": "fixture", "entry_nature": "fixture",
                           "plugin_entry": {}})
    monkeypatch.setattr(tnr, "NATURE_ENTRY", {
        "fixture": {"entry_step": "D1", "default_evidence": "FIXTURE_EV"}})
    monkeypatch.setattr(tnr, "EVIDENCE_EXIT", {
        "FIXTURE_EV": {"exit_step": exit_step}})
    monkeypatch.setattr(tnr, "flow_step_ids", lambda: ["D1", "2", "8", "15"])

    def prepare(_bench, _dataset, run, _fmt, _limit):
        for child in ("projects", "responses", "reports", "transcripts"):
            (run / child).mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(bd, "_prepare_general_solve_run", prepare)
    monkeypatch.setattr(bio, "problems",
                        lambda _fmt, _dataset: [{"id": "p1"}])

    def stage(_fmt, problem, project):
        prompt = project / "input" / "phase1_prompt.md"
        prompt.parent.mkdir(parents=True, exist_ok=True)
        text = f"Design {problem['id']} with an input and an output.\n"
        prompt.write_text(text)
        return {"prompt_chars": len(text)}

    monkeypatch.setattr(bio, "stage", stage)
    monkeypatch.setattr(
        bio, "collect",
        lambda *_a, **_k: {"ok": False, "reason": "fixture-no-candidate"})

    def fake_run(argv, *args, **kwargs):
        argv_seen["argv"] = list(argv)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(bd.subprocess, "run", fake_run)
    # The landed #1985 path runs the solver through _RunnerBudget.run, not
    # bare subprocess.run — capture there too, same claim, current surface.
    monkeypatch.setattr(
        bd._RunnerBudget, "run",
        lambda self, argv, *a, **k: (argv_seen.__setitem__("argv", list(argv)),
                                     SimpleNamespace(rc=0, error=None))[1])


def test_solve_passes_exit_step_alongside_skip_phase3(tmp_path, monkeypatch):
    argv_seen: dict = {}
    _install_solve_fakes(monkeypatch, argv_seen, exit_step="8")
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    bd.cmd_solve("rtllm", str(dataset), str(tmp_path / "run"), jobs=1)
    argv = argv_seen["argv"]
    assert "--skip-phase3" in argv, argv
    assert argv[argv.index("--exit-step") + 1] == "8", argv


def test_solve_never_passes_an_exit_outside_the_flow(tmp_path, monkeypatch):
    """§4.05 boundary-outside: an evidence class whose exit_step is not a
    declared flow step forwards nothing — the runner would refuse it, and
    refusing every solve over a table typo is not this call site's job."""
    argv_seen: dict = {}
    _install_solve_fakes(monkeypatch, argv_seen, exit_step="99")
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    bd.cmd_solve("rtllm", str(dataset), str(tmp_path / "run"), jobs=1)
    argv = argv_seen["argv"]
    assert "--exit-step" not in argv, argv
    assert "--skip-phase3" not in argv, argv


# ── the runner subprocess ceiling ────────────────────────────────────────────
def test_unset_timeout_env_keeps_the_unbounded_historical_shape(monkeypatch):
    monkeypatch.delenv("VIBEIC_SOLVE_RUNNER_TIMEOUT_S", raising=False)
    seen: dict = {}

    def fake_run(argv, *args, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(bd.subprocess, "run", fake_run)
    out = bd._RunnerBudget(1, None, 0).run(["true"])
    assert out.rc == 0 and out.error is None
    assert "timeout" not in seen, seen


def test_timeout_env_reaches_the_subprocess_call(monkeypatch):
    monkeypatch.setenv("VIBEIC_SOLVE_RUNNER_TIMEOUT_S", "5")
    seen: dict = {}

    def fake_run(argv, *args, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(bd.subprocess, "run", fake_run)
    out = bd._RunnerBudget(1, None, 0).run(["true"])
    assert out.rc == 0
    assert seen.get("timeout") == 5.0, seen


def test_a_timed_out_runner_is_one_loud_row_not_a_hung_run(monkeypatch):
    monkeypatch.setenv("VIBEIC_SOLVE_RUNNER_TIMEOUT_S", "5")

    def fake_run(argv, *args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs["timeout"])

    monkeypatch.setattr(bd.subprocess, "run", fake_run)
    out = bd._RunnerBudget(1, None, 0).run(["true"])
    assert out.rc is None
    assert "VIBEIC_SOLVE_RUNNER_TIMEOUT_S" in (out.error or ""), out.error


def test_an_unparseable_timeout_refuses_instead_of_running_unbounded(
        monkeypatch):
    """A guard that degrades to 'off' reports a safety it does not provide."""
    for bad in ("not_a_number", "0", "-3"):
        monkeypatch.setenv("VIBEIC_SOLVE_RUNNER_TIMEOUT_S", bad)
        with pytest.raises(ValueError):
            bd._RunnerBudget(1, None, 0)
