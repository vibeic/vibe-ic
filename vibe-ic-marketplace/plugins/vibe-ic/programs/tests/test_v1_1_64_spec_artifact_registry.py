"""v1.1.64 — spec_artifact_registry: the single-source-of-truth catalog of
structured artifact types. Thin delegating layer over the already-reviewed
canonical parsers/generators, so these tests pin the ROUTING (detect classifies
to the right type + extracts; generate routes to the right generator; prose with
no structural artifact yields nothing).
"""
import sys
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parents[1]
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))
import spec_artifact_registry as R  # noqa: E402

_HDR = ("I would like you to implement a module named TopModule with the following\n"
        "interface. All input and output ports are one bit unless otherwise specified.\n\n")

FSM = _HDR + (
    " - input  clk\n - input  reset\n - input  in\n - output out\n\n"
    "Moore state machine. Synchronous active high reset to state A.\n\n"
    "  state | next state in=0, next state in=1 | output\n"
    "  A | A, B | 0\n  B | C, B | 0\n  C | A, D | 0\n  D | C, B | 1\n")

TRUTH = _HDR + (
    " - input  x3\n - input  x2\n - input  x1\n - output f\n\n"
    "Implement the combinational circuit described by this truth table:\n\n"
    "  x3 | x2 | x1 | f\n  0 | 0 | 0 | 0\n  0 | 0 | 1 | 1\n  0 | 1 | 0 | 1\n  0 | 1 | 1 | 0\n"
    "  1 | 0 | 0 | 1\n  1 | 0 | 1 | 0\n  1 | 1 | 0 | 0\n  1 | 1 | 1 | 1\n")

PROSE = _HDR + (
    " - input  clk\n - input  reset\n - output [7:0] q\n\n"
    "Build a counter that increments every clock and resets to 0 when reset is high.\n")


def test_detect_fsm_transition_table():
    arts = R.detect(FSM)
    keys = [a["type"] for a in arts]
    assert "fsm_transition_table" in keys
    fsm = next(a for a in arts if a["type"] == "fsm_transition_table")
    assert set(fsm["structured"]["states"]) == {"A", "B", "C", "D"}
    assert fsm["structured"]["reset"]["state"] == "A"
    assert "L6" in fsm["l_docs"]                     # taxonomy home


def test_detect_truth_table():
    arts = R.detect(TRUTH)
    tt = next((a for a in arts if a["type"] == "truth_table"), None)
    assert tt is not None
    assert tt["structured"]["output"] == "f"
    assert len(tt["structured"]["rows"]) == 8


def test_generate_routes_to_correct_generator():
    k, rtl = R.generate(FSM)
    assert k == "fsm_transition_table" and rtl and "module TopModule" in rtl
    k2, rtl2 = R.generate(TRUTH)
    assert k2 == "truth_table" and rtl2 and "module TopModule" in rtl2


def test_prose_yields_no_structural_artifact():
    # a plain prose counter has no table/k-map/FSM-table artifact -> detect empty,
    # generate None (honest: this is the AI's job, not a deterministic solve)
    assert R.detect(PROSE) == []
    assert R.generate(PROSE) == (None, None)


def test_registry_catalog_is_nonempty_and_typed():
    assert "fsm_transition_table" in R.types()
    assert "truth_table" in R.types()
    for a in R.REGISTRY:
        assert a.key and a.title and a.l_docs            # every entry has a taxonomy home
