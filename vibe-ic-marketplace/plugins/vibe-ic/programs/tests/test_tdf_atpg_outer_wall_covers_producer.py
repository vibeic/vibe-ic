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


def _tdf_subprocess_run_timeout_node():
    """Return the AST node passed as ``timeout=`` to the ``subprocess.run`` call
    whose first positional argument is the ``tdf_cmd`` list (the invocation of
    transition_fault_atpg_run.py). None if not found."""
    tree = ast.parse(RUNNER_SRC)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_sub_run = (isinstance(func, ast.Attribute) and func.attr == "run"
                      and isinstance(func.value, ast.Name)
                      and func.value.id == "subprocess")
        if not is_sub_run:
            continue
        if not (node.args and isinstance(node.args[0], ast.Name)
                and node.args[0].id == "tdf_cmd"):
            continue
        for kw in node.keywords:
            if kw.arg == "timeout":
                return kw.value
    return None


# ── FORWARD: fails pre-fix (timeout=1800), passes post-fix ──────────────────

def test_tdf_outer_timeout_is_not_a_constant_below_producer_cap():
    """The tdf subprocess.run timeout must not be a bare constant below the
    producer's WALL_BUDGET_MAX. Pre-fix it is Constant(1800) < 7200 → this
    FAILS. Post-fix it is a derived call → this PASSES."""
    cap = tdf.WALL_BUDGET_MAX
    node = _tdf_subprocess_run_timeout_node()
    assert node is not None, (
        "could not locate the subprocess.run(tdf_cmd, ...) timeout in "
        "design_one_shot_runner — test anchor is stale")
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        assert node.value >= cap, (
            f"transition-ATPG subprocess timeout is a FIXED {node.value}s < "
            f"producer WALL_BUDGET_MAX {cap}s — the runner abandons the producer "
            f"before its own size-scaled batch can finish, so no "
            f"transition_coverage.json is ever written and the container leaks")
    # a non-constant (derived) timeout is exactly the fix — accepted here; its
    # VALUE is checked below.


def test_runner_derives_tdf_timeout_and_it_covers_the_cap():
    """The runner must expose a derived transition-ATPG subprocess wall and it
    must be >= the producer's cap. Pre-fix the helper is absent (getattr None)
    → this FAILS; post-fix it returns cap + margin → PASSES."""
    cap = tdf.WALL_BUDGET_MAX
    fn = getattr(runner, "_tdf_atpg_subprocess_timeout_s", None)
    assert fn is not None, (
        "design_one_shot_runner defines no _tdf_atpg_subprocess_timeout_s(); the "
        "tdf subprocess.run hardcodes a fixed timeout that cannot track the "
        "producer's size-scaled WALL_BUDGET_MAX cap")
    outer = fn()
    assert outer >= cap, (
        f"derived transition-ATPG outer wall {outer}s < producer cap {cap}s — "
        f"the producer would still be killed before its own wall")
    # margin must be strictly positive: the producer needs time to reap after its
    # own (capped) wall fires, so outer must be strictly greater than the cap.
    assert outer > cap, (
        f"outer wall {outer}s == cap {cap}s leaves no setup/reap margin above the "
        f"producer's own wall")


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
