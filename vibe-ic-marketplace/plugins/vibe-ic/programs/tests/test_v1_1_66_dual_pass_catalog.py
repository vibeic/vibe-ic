"""v1.1.66 — spec_artifact_catalog (master element-type vocabulary) + the DUAL-PASS
understanding layer (program baseline + AI interpreter + reconcile).

The understanding layer is AI-led (interpreting the spec is AI's strength, improves
with LLMs) with a deterministic PROGRAM BASELINE floor: the reconciled result is
ALWAYS a superset of the program baseline. These tests pin (a) the catalog is a
typed non-empty vocabulary, (b) the program baseline floor, (c) the four reconcile
classes, (d) the floor guarantee under conflict.
"""
import sys
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parents[1]
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))
import spec_artifact_catalog as CAT       # noqa: E402
import spec_artifact_dual_pass as DP       # noqa: E402

FSM = ("interface. All input and output ports are one bit unless otherwise specified.\n\n"
       " - input  clk\n - input  reset\n - input  in\n - output out\n\n"
       "Moore state machine. Synchronous active high reset to state A.\n\n"
       "  state | next state in=0, next state in=1 | output\n"
       "  A | A, B | 0\n  B | C, B | 0\n  C | A, D | 0\n  D | C, B | 1\n")


def test_catalog_is_typed_and_nonempty():
    assert len(CAT.CATALOG) >= 40
    for e in CAT.CATALOG:
        assert e.key and e.title and e.category and e.l_docs
        assert e.tier in ("table", "prose", "vision", "hybrid")
        assert e.status in ("live", "extractor_exists", "to_build", "vision_pending")
    # the live types must name a real generator module (sanity vs the registry)
    live = {e.key for e in CAT.by_status("live")}
    assert "truth_table" in live and "fsm_transition_table" in live


def test_program_baseline_extracts_the_table():
    base = DP.program_baseline(FSM)
    types = [e["element_type"] for e in base]
    assert "fsm_transition_table" in types           # the table artifact
    assert "pinout_table" in types                   # + the universal port baseline
    el = next(e for e in base if e["element_type"] == "fsm_transition_table")
    assert el["metadata"]["source"] == "program" and el["metadata"]["tier"] == "table"
    assert set(el["data"]["states"]) == {"A", "B", "C", "D"}


def test_reconcile_four_classes():
    base = DP.program_baseline(FSM)
    ai = list(base)                                   # AI agrees on the table
    ai.append({"element_type": "reset_behavior", "element_id": "reset_behavior_1",
               "data": {"state": "A", "sync": True}})        # ai-only (prose)
    rep = DP.reconcile(base, ai)
    assert "fsm_transition_table" in rep["agree"]
    assert any(c["element_type"] == "reset_behavior"
               for c in rep["ai_only_new_extractor_candidates"])
    assert rep["conflicts"] == []
    assert 0.0 < rep["agreement_rate"] <= 1.0


def test_floor_guarantee_baseline_always_kept():
    base = DP.program_baseline(FSM)
    # an AI pass that MISSES the table entirely must NOT drop it from the merge
    ai = [{"element_type": "functional_requirements", "element_id": "functional_requirements_1",
           "data": {"requirements": []}}]
    out = DP.extract_dual_pass(FSM, ai)
    types = {e["element_type"] for e in out["container"]["structural_elements"]}
    assert "fsm_transition_table" in types                  # floor kept
    assert "functional_requirements" in types               # AI breadth added
    assert "fsm_transition_table" in out["program_only_floor_kept"]


def test_conflict_surfaced_baseline_wins():
    base = DP.program_baseline(FSM)
    # AI returns the SAME element type but with DIFFERENT data -> conflict
    bad = {"element_type": "fsm_transition_table", "element_id": "fsm_transition_table_1",
           "data": {"states": ["X", "Y"]}}
    rep = DP.reconcile(base, [bad])
    assert len(rep["conflicts"]) == 1
    assert rep["conflicts"][0]["element_type"] == "fsm_transition_table"
    # merged keeps the BASELINE on conflict (AI must challenge with evidence)
    out = DP.extract_dual_pass(FSM, [bad])
    fsm = next(e for e in out["container"]["structural_elements"]
               if e["element_type"] == "fsm_transition_table")
    assert set(fsm["data"]["states"]) == {"A", "B", "C", "D"}


def test_baseline_only_when_no_ai_pass():
    out = DP.extract_dual_pass(FSM)
    assert out["baseline_only"] is True
    assert out["container"]["structural_elements"][0]["element_type"] == "fsm_transition_table"
    assert out["container"]["document_type"] == "Functional_Specification"
