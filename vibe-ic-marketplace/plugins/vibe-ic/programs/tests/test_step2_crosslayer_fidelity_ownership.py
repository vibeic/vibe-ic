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


#: THE MEMBERS, BESIDE THE COUNT, BECAUSE THE COUNT ALONE CANNOT SEE A SWAP.
#: One step arriving and one leaving in the same batch leaves the count where it
#: was and this
#: module said nothing -- which is what
#: `population_pin_without_its_member_set` reports against this very file
#: ("1 pin(s): 68 via safe_load"). RE-DERIVED 2026-08-25 from the flow YAML this
#: test already reads; not transcribed from any document that states 68.
#:
#: ORDER IS DELIBERATELY NOT PINNED. This is a SET comparison, which is the
#: remedy the checker names. Asserting the sequence as well would make a
#: legitimate reordering read as an arrival plus a departure -- a finding about
#: something this test does not own.
_CANONICAL_STEP_IDS = {
    "D1", "0.5ic", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11",
    "FS1", "DT1", "12", "13",
    "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9",
    "14", "15", "15.5ic", "16", "17", "18", "19", "20", "21", "22",
    "DT2", "DT3",
    "23", "24", "25", "26", "26.5ic", "27", "28", "29", "30", "31", "32", "33",
    "34", "35", "36", "37", "37.4", "37.5ip", "37.5ic", "38", "39",
    "M1", "M2", "M3", "M4",
    "40", "41", "42", "43", "44", "P0",
}


def test_canonical_flow_remains_69_steps_without_a_1_6x_step():
    ids = tuple(str(step["id"]) for step in _steps())
    # NO `len(_CANONICAL_STEP_IDS) == 68` HERE, and that is deliberate. I wrote
    # one at v1.11.85 and `population_guard_asserts_equality_not_a_floor` caught
    # it by name: a len() over an unmutated literal "passes for free, on every
    # tree, forever" -- it checks the file against itself and can never go red.
    # The literal is already asserted against the POPULATION it describes, as a
    # set and in both directions, three lines down; that is the check, and one
    # tautology standing beside it only made the file look better guarded.
    # 68 -> 69 (2026-09-03): canonical step 37.4, sign-off metrics aggregation.
    # AN ARRIVAL, NOT A SWAP, AND THE SET BELOW IS WHAT SAYS SO: '37.4' is the
    # only member added and none departed, which is exactly the distinction the
    # member literal exists to make and a count alone cannot. It is not a rename
    # of the retired '37.5self' either -- that id left at v1.11.18, three
    # populations ago, and nothing in this change restores or re-spells it.
    assert len(ids) == 69, f"canonical flow grew to {len(ids)} steps: {ids}"
    assert len(set(ids)) == len(ids), (
        "the flow declares a duplicate step id: "
        f"{sorted(i for i in set(ids) if ids.count(i) > 1)}")
    got = set(ids)
    assert got == _CANONICAL_STEP_IDS, (
        "the canonical step set moved -- arrived: "
        f"{sorted(got - _CANONICAL_STEP_IDS)}; departed: "
        f"{sorted(_CANONICAL_STEP_IDS - got)}. Re-derive BOTH the count and the "
        "members from the flow YAML; do not edit one to fit the other.")
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
