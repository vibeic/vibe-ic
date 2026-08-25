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


#: The canonical flow's step ids, in order. Pinned as IDENTITIES and not only as
#: a COUNT: one step arriving and another leaving in the same change leaves
#: `len(ids) == 68` true and the flow silently different. The count is derived
#: from this tuple at assertion time so the two can never disagree.
CANONICAL_STEP_IDS = (
    'D1', '0.5ic', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11',
    'FS1', 'DT1', '12', '13', 'A1', 'A2', 'A3', 'A4', 'A5', 'A6', 'A7',
    'A8', 'A9', '14', '15', '15.5ic', '16', '17', '18', '19', '20', '21',
    '22', 'DT2', 'DT3', '23', '24', '25', '26', '26.5ic', '27', '28', '29',
    '30', '31', '32', '33', '34', '35', '36', '37', '37.5ip', '37.5ic',
    '38', '39', 'M1', 'M2', 'M3', 'M4', '40', '41', '42', '43', '44', 'P0',
)


def test_canonical_flow_remains_68_steps_without_a_1_6x_step():
    ids = tuple(str(step["id"]) for step in _steps())
    assert ids == CANONICAL_STEP_IDS, (
        "canonical flow changed:\n"
        f"  added   {sorted(set(ids) - set(CANONICAL_STEP_IDS))}\n"
        f"  removed {sorted(set(CANONICAL_STEP_IDS) - set(ids))}\n"
        f"  reordered: {ids != CANONICAL_STEP_IDS and set(ids) == set(CANONICAL_STEP_IDS)}")
    assert len(ids) == len(CANONICAL_STEP_IDS)
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
