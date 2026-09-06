"""Regression: the runner's OUTER wall for the transition/at-speed ATPG
subprocess must COVER the producer's own size-scaled wall.

ROOT CAUSE this guards
----------------------
`transition_fault_atpg_run.py` sizes its at-speed fault sample to finish within
a size-scaled wall — ``_scaled_wall_budget(floor, scan_flops)`` = 1800 s floor
+ 3 s/scan-flop, CAPPED at ``WALL_BUDGET_MAX`` (7200 s) — and runs its Yosys
batch under a docker ``timeout`` of that same scaled wall, so a large design
earns proportionally more wall (the #581 size-scaling).

`design_one_shot_runner.step_dft_lec_chain` invokes that producer with
``subprocess.run(tdf_cmd, ..., timeout=<T>)``. If ``<T>`` is a fixed value BELOW
the producer's cap, the runner SIGKILLs the producer mid-batch on ANY flop-
bearing design (measured: opentitan_aes x sky130A, 2757 scan flops → producer
wall 7200 s, outer timeout 1800 s): the producer writes no
``transition_coverage.json``, the at-speed sub-check FAILs on absent evidence
(not a measured number), and the producer's Yosys container is orphaned (the
reap runs inside the killed producer) and keeps burning CPU. The fixed outer
timeout silently DEFEATS the producer's entire size-scaling.

FORWARD control (FAILS against the byte-identical pre-fix file, PASSES after):
    the ``subprocess.run(tdf_cmd, ...)`` timeout must NOT be a fixed constant
    below the producer's ``WALL_BUDGET_MAX``.

REVERSE control (PASSES on BOTH pre-fix and post-fix — must STILL pass):
    the fix raises a WALL; it must NOT reach green by making the DFT sign-off
    gate accept absence-of-measurement. `dft_signoff_check.evaluate_transition`
    must STILL FAIL when no coverage record exists and STILL require a real
    at-speed number >= target — proving step 11 can only green on a produced
    number, never on the timeout change.

PURE: no Docker / no Yosys. Forward assertion is a static AST read of the call
site; reverse assertion calls the pure gate evaluator.
"""
import ast
import sys
from pathlib import Path

import pytest

PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))

import transition_fault_atpg_run as tdf          # noqa: E402
import design_one_shot_runner as runner          # noqa: E402
import dft_signoff_check as gate                  # noqa: E402

RUNNER_SRC = Path(runner.__file__).read_text()


def _tdf_dispatch_call():
    """The AST node of the call whose first positional argument is ``tdf_cmd``
    -- the invocation of transition_fault_atpg_run.py -- whichever dispatcher
    it goes through. None if not found.

    CZT-10 — deliberately NOT anchored on ``subprocess.run``. The concern this
    file guards is a property of the DISPATCH, and anchoring on one dispatcher
    made the test unable to see the call the moment the dispatch moved.
    """
    tree = ast.parse(RUNNER_SRC)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (node.args and isinstance(node.args[0], ast.Name)
                and node.args[0].id == "tdf_cmd"):
            continue
        return node
    return None


# ── FORWARD: the outer wall is GONE, which is the strongest form of "it does
#    not defeat the producer's size-scaling" ─────────────────────────────────

def test_the_tdf_dispatch_imposes_no_outer_wall_at_all():
    """CZT-10 supersedes this file's original fix, and states why.

    The original defect was an outer `subprocess.run(timeout=1800)` BELOW the
    producer's own size-scaled cap: the runner SIGKILLed the producer mid-batch
    on any flop-bearing design, no `transition_coverage.json` was written, and
    the producer's Yosys container was orphaned. The repair was to DERIVE the
    outer wall from `WALL_BUDGET_MAX` so it could not drift below the cap.

    That repair is correct and it is still a wall. A wall a correct run can
    reach is a wrong answer at every value, and tracking the cap only moves the
    moment it is wrong. The dispatch is now supervised on the child's own
    forward progress and carries NO bound, so it cannot defeat the producer's
    size-scaling AT ANY size -- which is what this file was written to protect.

    THE SAMPLE DID NOT MOVE, and that is the reason removing the wall is safe
    rather than a trade. Asserted below in `test_the_fault_sample_is_sized_by
    _the_producer_alone`.
    """
    call = _tdf_dispatch_call()
    assert call is not None, (
        "could not locate the dispatch of tdf_cmd in design_one_shot_runner — "
        "test anchor is stale")
    bounds = [kw.arg for kw in call.keywords
              if kw.arg in ("timeout", "hard_ceiling_s")]
    assert bounds == [], (
        f"the transition-ATPG dispatch carries {bounds} — an outer wall on a "
        f"producer that sizes its own batch can only ever kill a run that was "
        f"still grading")


def test_the_fault_sample_is_sized_by_the_producer_alone():
    """WHY REMOVING THE OUTER WALL CANNOT SHRINK WHAT GETS GRADED.

    The coupling is real: the producer's INNER budget sizes its fault sample,
    measured here on its own pure functions. What the outer wall never was is
    an INPUT to that sizing -- the dataflow runs one way, from the producer's
    `WALL_BUDGET_MAX` out to the runner, and the runner's value reaches the
    producer nowhere. So the two are separable, and this asserts it instead of
    asserting that they are.
    """
    # The coupling, at two values -- if this ever stops holding, the argument
    # above is about a mechanism that no longer exists.
    small = tdf._rightsize_sample(0.5, 120.0, 1800, 100000, 50000)
    large = tdf._rightsize_sample(0.5, 120.0, 7200, 100000, 50000)
    assert large > small, (small, large)

    # ...and the outer wall is not one of the sizing inputs.
    import inspect
    sizing_inputs = set(
        inspect.signature(tdf._rightsize_sample).parameters) | set(
        inspect.signature(tdf._scaled_wall_budget).parameters)
    assert "outer" not in " ".join(sizing_inputs)

    # The argv is the whole surface between the two, and it carries no bound.
    # Read with `ast`, which cannot see a comment: the first probe written for
    # this matched the COMMENT that names the old helper, not the argv.
    tree = ast.parse(RUNNER_SRC)
    argv_src = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "tdf_cmd" in names:
                argv_src.append(ast.unparse(node))
        elif (isinstance(node, ast.AugAssign)
              and isinstance(node.target, ast.Name)
              and node.target.id == "tdf_cmd"):
            argv_src.append(ast.unparse(node))
    assert argv_src, "tdf_cmd is not built here any more — anchor is stale"
    joined = " ".join(argv_src)
    for flag in ("--timeout", "--wall", "--budget", "--wall-budget"):
        assert flag not in joined, (flag, joined)


# ── REVERSE: must STILL pass on BOTH pre-fix and post-fix ────────────────────
# Proves the fix does NOT green step 11 by weakening the gate: a design with no
# at-speed coverage record still FAILs, and a real number is still required.

def test_gate_still_fails_on_absent_transition_evidence():
    r = gate.evaluate_transition(None, transition_target=90.0)
    assert r["status"] == "FAIL", (
        "gate must NOT accept a missing at-speed coverage record as a pass — "
        "raising the producer wall must not make absence-of-measurement green")


def test_gate_still_fails_on_below_target_number():
    block = {"transition": {"coverage_pct": 50.0, "target_pct": 90.0}}
    r = gate.evaluate_transition(block, transition_target=90.0)
    assert r["status"] == "FAIL", "below-floor at-speed coverage must still FAIL"


def test_gate_passes_only_on_real_number_at_or_above_target():
    block = {"transition": {"coverage_pct": 95.0, "target_pct": 90.0}}
    r = gate.evaluate_transition(block, transition_target=90.0)
    assert r["status"] == "PASS", (
        "a real at-speed number >= target is the ONLY thing that greens the "
        "at-speed sub-check — this is what the producer must be allowed to write")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
