"""Contract tests for folding the former step 1.6x into flow Step 2."""

import os
from pathlib import Path

import yaml


PLUGIN_ROOT = Path(
    os.environ.get("VIBE_IC_TEST_PLUGIN_ROOT", Path(__file__).resolve().parents[2])
).resolve()
FLOW = PLUGIN_ROOT / "flow" / "phase1_phase2_phase3.yaml"
RUNNER = PLUGIN_ROOT / "programs" / "design_one_shot_runner.py"
JUDGE_COMMAND = (
    "crosslayer_rewrite_equivalence_check . "
    "--report reports/crosslayer/rewrite_equivalence.json "
    "--baseline-marker reports/crosslayer/baseline_rtl "
    "--search-space reports/crosslayer/search_space.json "
    "--json reports/crosslayer/rewrite_equivalence_check.json"
)


def _steps():
    return yaml.safe_load(FLOW.read_text(encoding="utf-8"))["steps"]


def _by_id():
    return {str(step["id"]): step for step in _steps()}


def test_canonical_flow_remains_68_steps_without_a_1_6x_step():
    ids = tuple(str(step["id"]) for step in _steps())
    assert len(ids) == 68, f"canonical flow grew to {len(ids)} steps: {ids}"
    assert "1.6x" not in ids, "rewrite fidelity is a Step-2 clause, not a step"


def test_step_1_remains_the_irreducible_authoring_step():
    step1 = _by_id()["1"]
    assert step1["gate"] == {
        "files_exist": ["phase2/stage1/rtl/*.sv", "phase2/stage1/rtl/*.v"],
        "any_of": True,
    }
    assert not any(
        "crosslayer" in str(value)
        for key, value in step1.items()
        if key != "name"
    ), "Step 1 must not judge and fall back to itself"


def test_step_2_owns_the_complete_rewrite_fidelity_contract():
    step2 = _by_id()["2"]
    assert step2["closed_loop"]["fallback_to"] == 1
    assert {
        "crosslayer_search_space",
        "crosslayer_rewrite_equivalence",
        "crosslayer_rewrite_equivalence_check",
    } <= set(step2["programs"])
    assert "reports/crosslayer/rewrite_equivalence_check.json" in step2[
        "required_outputs"
    ]
    clauses = step2["gate"]["all_of"]
    assert {"program_exit_zero": JUDGE_COMMAND} in clauses


def test_production_runner_executes_the_step_2_clause_exactly_once():
    source = RUNNER.read_text(encoding="utf-8")
    call = "plan.append(step_crosslayer_rewrite_fidelity(project))"
    assert source.count(call) == 1
    assert source.index(call) < source.index(
        "plan.append(step_slot_pad_budget(project, args.top_name))"
    )
