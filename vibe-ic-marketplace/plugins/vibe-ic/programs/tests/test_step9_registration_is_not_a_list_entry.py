"""Registering a step in an entrypoint table is a DECLARATION.

This whole line of work exists because declarations and behaviour had drifted
apart, so the registration of step 9 has to prove it changes what EXECUTES and
not only what is listed. Every arm below mutates the RUNNER or the REGISTER and
requires the verdict to move; three CONTROL edges (4 -> 1, 23 -> 32, 32 -> 32)
are untouched and must hold their tier in every arm.

The register is `closed_loop_executable_coverage_check.STEP_EXECUTION_ENTRYPOINTS`
and it had two rows for a 68-step flow. Adding a third does nothing on its own:
`bound_to_fallback` only decides whether a citation is ALLOWED to speak for an
edge, and the citation still has to resolve against the AST of the shipped
runner. These tests are what says so out loud.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
sys.path.insert(0, str(PROGRAMS))

import closed_loop_executable_coverage_check as C  # noqa: E402

RUNNER = PROGRAMS / "phase3_one_shot_runner.py"
CONTROLS = (("4", "1", C.REMEASURED),
            ("23", "32", C.ROLLBACK_PROVEN),
            ("32", "32", C.ROLLBACK_PROVEN))

#: The actuator, quoted from the runner. Its `period_relax` keyword is what makes
#: the recursion a different run; its position inside the rc==1 branch is what
#: binds it to the trigger.
ACTUATOR = ("                    _area_retry = step_synth(\n"
            "                        project, top, pdk, container,\n"
            "                        period_relax=AREA_RETRY_PERIOD_RELAX)")
#: The re-measurement, taken AFTER the actuator. `_before` is the same call taken
#: BEFORE it, which is why only the ORDER can tell the tier.
MEASURE_AFTER = "                    _after = _synth_chip_area(project)"


def _root(tmp: Path, runner_text: str | None = None) -> Path:
    """A plugin root carrying the files every cited citation names."""
    (tmp / "programs" / "tests").mkdir(parents=True)
    for name in ("phase3_one_shot_runner.py", "design_one_shot_runner.py"):
        shutil.copy2(PROGRAMS / name, tmp / "programs" / name)
    shutil.copy2(PROGRAMS / "tests" / "test_timing_repair_reverted_regression.py",
                 tmp / "programs" / "tests")
    if runner_text is not None:
        (tmp / "programs" / "phase3_one_shot_runner.py").write_text(runner_text)
    return tmp


def _tier(root: Path, step: str, fallback: str) -> str:
    return C.classify_edge(step, root, fallback_to=fallback)["class"]


def _mutate(old: str, new: str) -> str:
    text = RUNNER.read_text()
    assert text.count(old) == 1, (
        f"mutation anchor is not unique ({text.count(old)}) — the arm would not "
        f"be measuring what it claims to")
    return text.replace(old, new)


def _controls_hold(root: Path) -> None:
    for step, fallback, want in CONTROLS:
        assert _tier(root, step, fallback) == want, (
            f"control edge {step} -> {fallback} moved; an arm that reddens "
            f"everything has told you nothing about the one thing it broke")


# ── the registration EARNS its tier on the shipped tree ─────────────────────

def test_step_9_is_registered_and_earns_REMEASURED(tmp_path):
    root = _root(tmp_path)
    assert "9" in C.STEP_EXECUTION_ENTRYPOINTS
    assert C.STEP_EXECUTION_ENTRYPOINTS["9"] == ("step_synth",)
    assert C.STEP_TRIGGER_ENTRYPOINTS["9"] == ("area_total_vs_budget_check",)
    assert _tier(root, "9", "9") == C.REMEASURED
    _controls_hold(root)


def test_rollback_is_withheld_and_the_reason_is_recorded():
    """The top tier is NOT taken. Step 23's rollback RETAINS the pre-repair
    artefacts; step 9's re-synthesis has already overwritten the first netlist,
    so a retry that did not repair is refused as a VERDICT, not undone. Calling
    both ROLLBACK_PROVEN would make the top tier mean two things."""
    entry = C.REGISTRY["9"]
    assert entry["class"] == C.REMEASURED
    assert "rollback" in entry["not_claimed"]
    assert "rollback" not in entry["evidence"]
    assert "overwrites" in entry["not_claimed"]["rollback"]


# ── ARM 1: registration WITHOUT the behaviour ───────────────────────────────

def test_arm1_the_registration_alone_earns_nothing(tmp_path):
    """Delete the re-entry, keep every row in every table. If the tier survives,
    the registration was a list entry."""
    broken = _mutate(ACTUATOR, ACTUATOR.replace("step_synth(", "_noop_retry("))
    root = _root(tmp_path, broken)
    assert _tier(root, "9", "9") == C.DECLARED_ONLY, (
        "the register still names step 9 and the citation still names "
        "step_synth; only the runner changed, and the tier must follow the "
        "runner")
    _controls_hold(root)


def test_arm2_moving_the_actuator_off_the_trigger_branch_earns_nothing(tmp_path):
    """Keep the call, break the BINDING: run it whatever the gate returned.
    An actuator that fires on both branches is not a response to the trigger."""
    text = _mutate("            if _acp.returncode == 1:",
                   "            if _acp.returncode == 1 or True:")
    root = _root(tmp_path, text.replace(
        ACTUATOR, ACTUATOR) )
    # the guard now reads `_acp.returncode == 1 or True`, which is no longer the
    # exact `== <rc>` compare the citation cites, so no branch owns the actuator
    assert _tier(root, "9", "9") == C.DECLARED_ONLY
    _controls_hold(root)


# ── ARM 3: the ORDER, which is the whole REMEASURED tier ────────────────────

def test_arm3_measuring_before_instead_of_after_falls_a_tier(tmp_path):
    """`_before` and `_after` are the SAME function call. Delete the one that
    follows the actuator and the actuator is still proven — but nothing measures
    what it did, and REMEASURED is exactly that difference."""
    broken = _mutate(MEASURE_AFTER, "                    _after = _before")
    root = _root(tmp_path, broken)
    tier = _tier(root, "9", "9")
    assert tier == C.EXECUTABLE, (
        f"expected the edge to fall from REMEASURED to EXECUTABLE, got {tier}: "
        f"the re-entry still runs, so it has not fallen to DECLARED_ONLY, and "
        f"nothing re-reads chip_area, so it cannot hold REMEASURED")
    _controls_hold(root)


# ── ARM 4: the behaviour WITHOUT the registration ───────────────────────────

def test_arm4_the_behaviour_alone_earns_nothing(tmp_path, monkeypatch):
    """The runner is untouched and the loop runs. Remove the registry row and
    the census reports DECLARED_ONLY — which is the defect this whole line of
    work is about, reproduced on purpose."""
    root = _root(tmp_path)
    reg = dict(C.REGISTRY)
    reg.pop("9")
    monkeypatch.setattr(C, "REGISTRY", reg)
    assert _tier(root, "9", "9") == C.DECLARED_ONLY
    _controls_hold(root)


def test_arm5_an_entrypoint_row_for_the_wrong_function_earns_nothing(
        tmp_path, monkeypatch):
    """The row is the BINDING, not the proof. Point step 9 at a real function
    that is not the actuator and the citation stops being allowed to speak."""
    root = _root(tmp_path)
    monkeypatch.setattr(C, "STEP_EXECUTION_ENTRYPOINTS",
                        {**C.STEP_EXECUTION_ENTRYPOINTS,
                         "9": ("step_floorplan",)})
    assert _tier(root, "9", "9") == C.DECLARED_ONLY
    _controls_hold(root)


# ── the new citation kinds cannot be satisfied by looser code ───────────────

def test_the_gate_is_identified_by_the_program_it_spawns_not_by_a_local(
        tmp_path):
    """Rename the local that holds the gate's path; the binding must survive,
    because the citation names the GATE."""
    text = _mutate("    _area_prog = PROGRAMS_DIR / \"area_total_vs_budget_check.py\"",
                   "    _renamed_prog = PROGRAMS_DIR / \"area_total_vs_budget_check.py\"")
    text = text.replace("_area_prog", "_renamed_prog")
    root = _root(tmp_path, text)
    assert _tier(root, "9", "9") == C.REMEASURED


def test_a_citation_without_an_integer_rc_is_refused():
    """Branch polarity is the exit code here. A citation that does not name one
    is not evidence, the same way a boolean citation without `trigger_value` is
    not."""
    cit = dict(C.REGISTRY["9"]["evidence"]["actuate"][0])
    cit.pop("trigger_rc")
    ok, reason = C._resolve_citation(cit, PLUGIN)
    assert not ok and "trigger_rc" in reason


@pytest.mark.parametrize("rc", [0, 2, 3])
def test_a_citation_naming_the_wrong_exit_code_does_not_resolve(rc):
    """rc 1 is `area_total_vs_budget_check`'s 'the cell area exceeds the die'.
    rc 2 is its INCOMPLETE tier and rc 0 is a pass; neither is this trigger."""
    cit = {**C.REGISTRY["9"]["evidence"]["actuate"][0], "trigger_rc": rc}
    ok, _ = C._resolve_citation(cit, PLUGIN)
    assert not ok
