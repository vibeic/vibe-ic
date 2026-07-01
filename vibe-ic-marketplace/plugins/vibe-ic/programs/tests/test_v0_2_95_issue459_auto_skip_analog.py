#!/usr/bin/env python3
"""Regression for ORGANIC-20260606 #459 — vibe_ic_one_shot_runner must
auto-forward --skip-analog to phase2 when its OWN _need_analog()==False.

Bug (v0.2.90): the orchestrator forwarded --skip-analog to phase2 ONLY when
the *user* passed --skip-analog. The analog-applicability decision
(_need_analog) was evaluated AFTER phase2 and never fed back into the phase2
invocation. So a pure-digital project that did NOT pass --skip-analog left
phase2 without the flag; phase2's final_audit then treated analog A9 as a
HARD condition and FAILed → every pure-digital run halted at phase2. Two
decision points disagreed about the same question.

Fix: decide analog applicability ONCE, BEFORE phase2 runs, as a single
source of truth (run_analog). When the orchestrator is not running the
A-track (user --skip-analog OR _need_analog()==False) it injects
--skip-analog into phase2's argv so final_audit agrees. For analog /
mixed-signal projects (_need_analog()==True) the flag is NEVER injected.

These tests exercise main()'s real control flow by intercepting the per-phase
invocation (_run_phase) so the actual phase2 argv can be inspected, without
spawning external EDA tools.

chip-AGNOSTIC: fixtures use synthetic generic names only.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# conftest puts programs/ on sys.path, but import explicitly for robustness
# matching the sys.path.insert convention used across programs/tests/.
_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import vibe_ic_one_shot_runner as orch  # noqa: E402


def _drive_main(monkeypatch, project: Path, argv_extra, need_analog: bool):
    """Run orch.main() with phase invocations intercepted.

    Returns a dict {phase_label: args_list} of the argv each child phase
    runner was invoked with, plus the captured "analog ran?" flag.
    """
    captured = {"phase_args": {}, "analog_ran": False}

    def fake_run_phase(label, runner, args, env=None):
        # #588 — _run_phase gained an env= kwarg (re-entrancy token);
        # the stub accepts and ignores it.
        captured["phase_args"][runner.name] = list(args)
        if runner.name.startswith("analog"):
            captured["analog_ran"] = True
        return 0  # pretend every child phase succeeded

    def fake_read_report(_p):
        # Non-FAIL verdict so the orchestrator does not halt; lets us reach
        # the analog + phase3 dispatch decisions.
        return {"verdict": "PASS"}

    def fake_need_analog(_project, force_skip):
        if force_skip:
            return False
        return need_analog

    monkeypatch.setattr(orch, "_run_phase", fake_run_phase)
    monkeypatch.setattr(orch, "_read_report", fake_read_report)
    monkeypatch.setattr(orch, "_need_analog", fake_need_analog)

    argv = ["vibe_ic_one_shot_runner.py", str(project)] + list(argv_extra)
    monkeypatch.setattr(sys, "argv", argv)
    orch.main()
    return captured


def _empty_project(tmp_path) -> Path:
    project = tmp_path / "generic_proj"
    project.mkdir(parents=True, exist_ok=True)
    return project


# ---------------------------------------------------------------------------
# FIXED PATH: _need_analog()==False, user did NOT pass --skip-analog
# ---------------------------------------------------------------------------
def test_pure_digital_auto_injects_skip_analog(tmp_path, monkeypatch):
    """Pure-digital (orchestrator _need_analog==False), no user --skip-analog
    → phase2 argv MUST contain --skip-analog so final_audit agrees."""
    project = _empty_project(tmp_path)
    cap = _drive_main(monkeypatch, project,
                      argv_extra=["--skip-phase1", "--skip-phase3"],
                      need_analog=False)
    p2 = cap["phase_args"].get("phase2_one_shot_runner.py")
    assert p2 is not None, "phase2 must have been invoked"
    assert "--skip-analog" in p2, (
        "orchestrator must auto-forward --skip-analog to phase2 when its own "
        f"_need_analog()==False (got: {p2})")
    # And the A-track itself must NOT run for a pure-digital project.
    assert cap["analog_ran"] is False


def test_pure_digital_skips_analog_track(tmp_path, monkeypatch):
    """The single decision gates BOTH sides: pure-digital → no A-track run."""
    project = _empty_project(tmp_path)
    cap = _drive_main(monkeypatch, project,
                      argv_extra=["--skip-phase1", "--skip-phase3"],
                      need_analog=False)
    assert "analog_one_shot_runner.py" not in cap["phase_args"]


# ---------------------------------------------------------------------------
# CORPUS-SWEEP GUARD: analog / mixed-signal project → A-track stays active,
# NO --skip-analog injected (prior correct behaviour preserved).
# ---------------------------------------------------------------------------
def test_analog_project_does_not_inject_skip_analog(tmp_path, monkeypatch):
    """Analog/mixed-signal (orchestrator _need_analog==True), no user flag
    → phase2 argv MUST NOT contain --skip-analog (A-track condition active)."""
    project = _empty_project(tmp_path)
    cap = _drive_main(monkeypatch, project,
                      argv_extra=["--skip-phase1", "--skip-phase3"],
                      need_analog=True)
    p2 = cap["phase_args"].get("phase2_one_shot_runner.py")
    assert p2 is not None, "phase2 must have been invoked"
    assert "--skip-analog" not in p2, (
        "must NOT inject --skip-analog for an analog/mixed-signal project — "
        f"phase2 final_audit's analog condition must stay active (got: {p2})")


def test_analog_project_runs_analog_track(tmp_path, monkeypatch):
    """Analog project → the A-track A1..A8 runner is invoked."""
    project = _empty_project(tmp_path)
    cap = _drive_main(monkeypatch, project,
                      argv_extra=["--skip-phase1", "--skip-phase3"],
                      need_analog=True)
    assert "analog_one_shot_runner.py" in cap["phase_args"]


# ---------------------------------------------------------------------------
# USER --skip-analog: still honoured regardless of _need_analog (back-compat).
# ---------------------------------------------------------------------------
def test_user_skip_analog_forwarded_even_when_need_analog_true(tmp_path, monkeypatch):
    """Explicit user --skip-analog wins over auto-detection: forwarded to
    phase2 and the A-track is NOT run, even if content looks analog."""
    project = _empty_project(tmp_path)
    cap = _drive_main(monkeypatch, project,
                      argv_extra=["--skip-phase1", "--skip-phase3",
                                  "--skip-analog"],
                      # force_skip path returns False; pin both consistent
                      need_analog=True)
    p2 = cap["phase_args"].get("phase2_one_shot_runner.py")
    assert p2 is not None
    assert "--skip-analog" in p2
    assert "analog_one_shot_runner.py" not in cap["phase_args"]


def test_skip_analog_appears_once(tmp_path, monkeypatch):
    """Guard against double-append when user passes --skip-analog AND
    _need_analog would also be False."""
    project = _empty_project(tmp_path)
    cap = _drive_main(monkeypatch, project,
                      argv_extra=["--skip-phase1", "--skip-phase3",
                                  "--skip-analog"],
                      need_analog=False)
    p2 = cap["phase_args"].get("phase2_one_shot_runner.py")
    assert p2.count("--skip-analog") == 1, (
        f"--skip-analog must appear exactly once, not duplicated: {p2}")


# ---------------------------------------------------------------------------
# DECISION ORDERING: the analog decision must be computed BEFORE phase2 so it
# can feed the phase2 argv. We pin this structurally on the source.
# ---------------------------------------------------------------------------
def test_analog_decision_precedes_phase2_in_source():
    src = (Path(__file__).resolve().parents[1]
           / "vibe_ic_one_shot_runner.py").read_text()
    idx_decision = src.find("run_analog = _need_analog(")
    idx_phase2 = src.find("# ---------------- Phase 2 ----------------")
    assert idx_decision != -1, "run_analog single-source decision must exist"
    assert idx_phase2 != -1
    assert idx_decision < idx_phase2, (
        "run_analog must be decided BEFORE the Phase 2 block so it can feed "
        "phase2's --skip-analog forwarding (#459)")
    # The phase2 forwarding must consult the orchestrator's own decision:
    # the auto-injection branch keys off `not run_analog` (the #459 fix).
    assert "elif not run_analog:" in src, (
        "phase2 must inject --skip-analog when _need_analog()==False "
        "(auto-injection branch missing)")
    # Back-compat anchors required by the prior forwarding regression test.
    assert "if args.skip_analog:" in src
    assert 'p2_args.append("--skip-analog")' in src
    # Analog A-track must dispatch off the SAME single decision. GAP-ANALOG-1
    # relaxed the halt gate so an analog IC's EXPECTED digital phase2 FAIL
    # (rtl_gen=null) no longer skips its own A-track; the condition tolerates a
    # phase2 halt but still excludes a phase1 halt (no L5_ADI_SPEC).
    assert 'run_analog and halted_at in ("", "phase2")' in src


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ---------------------------------------------------------------------------
# ORGANIC (GAP-E2E-9 campaign / GAP-ANALOG-1) — an analog IC's digital phase2
# legitimately FAILs (class rtl_gen=null → no synthesizable RTL). That EXPECTED
# digital FAIL (halted_at="phase2") must NOT skip the IC's OWN analog A-track.
# ---------------------------------------------------------------------------
def _drive_main_verdicts(monkeypatch, project: Path, argv_extra,
                         need_analog: bool, verdicts: dict):
    """Like _drive_main but the per-phase report verdict is controlled by
    `verdicts` keyed on the runner basename stem ('phase1'/'phase2'/…),
    defaulting to PASS — so a test can make phase2 FAIL and observe the analog
    dispatch decision."""
    captured = {"phase_args": {}, "analog_ran": False, "order": []}

    def fake_run_phase(label, runner, args, env=None):
        captured["phase_args"][runner.name] = list(args)
        captured["order"].append(runner.name)
        if runner.name.startswith("analog"):
            captured["analog_ran"] = True
        # rc mirrors the configured verdict so main()'s rc-derived verdict agrees
        stem = runner.name.split("_")[0]
        return 0 if verdicts.get(stem, "PASS") != "FAIL" else 1

    def fake_read_report(_p):
        # main() calls _read_report right after each phase; return the verdict
        # for whichever phase most recently ran (the last in order).
        if not captured["order"]:
            return {"verdict": "PASS"}
        stem = captured["order"][-1].split("_")[0]
        return {"verdict": verdicts.get(stem, "PASS")}

    def fake_need_analog(_project, force_skip):
        return False if force_skip else need_analog

    monkeypatch.setattr(orch, "_run_phase", fake_run_phase)
    monkeypatch.setattr(orch, "_read_report", fake_read_report)
    monkeypatch.setattr(orch, "_need_analog", fake_need_analog)
    monkeypatch.setattr(sys, "argv",
                        ["vibe_ic_one_shot_runner.py", str(project)]
                        + list(argv_extra))
    orch.main()
    return captured


def test_analog_track_runs_despite_phase2_digital_fail(tmp_path, monkeypatch):
    """GAP-ANALOG-1: analog IC (need_analog=True) whose digital phase2 FAILs
    (rtl_gen=null → no RTL) MUST still dispatch the analog A-track."""
    project = _empty_project(tmp_path)
    cap = _drive_main_verdicts(
        monkeypatch, project, argv_extra=["--skip-phase1", "--skip-phase3"],
        need_analog=True, verdicts={"phase2": "FAIL"})
    assert cap["analog_ran"] is True, (
        "analog A-track must run even when the digital phase2 halted "
        "(rtl_gen=null FAIL is the EXPECTED digital outcome for an analog IC)")


def test_analog_dispatch_condition_excludes_phase1_halt():
    """NEGATIVE no-leak (source): the analog-dispatch condition tolerates a
    phase2 halt but NOT a phase1 halt (a phase1 FAIL means no L5_ADI_SPEC, which
    the A-track needs) — `halted_at in ("", "phase2")` excludes "phase1"."""
    src = (Path(__file__).resolve().parents[1]
           / "vibe_ic_one_shot_runner.py").read_text()
    assert 'run_analog and halted_at in ("", "phase2")' in src
    assert '"phase1"' not in 'run_analog and halted_at in ("", "phase2")'


def test_pure_digital_phase2_fail_still_skips_analog(tmp_path, monkeypatch):
    """NEGATIVE: a PURE-DIGITAL project (need_analog=False) whose phase2 FAILs
    must NOT suddenly run an analog track."""
    project = _empty_project(tmp_path)
    cap = _drive_main_verdicts(
        monkeypatch, project, argv_extra=["--skip-phase1", "--skip-phase3"],
        need_analog=False, verdicts={"phase2": "FAIL"})
    assert cap["analog_ran"] is False
