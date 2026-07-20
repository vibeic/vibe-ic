"""sort_synth — general bubble-sort engine solver (T2->T1 promotion).

Promotes the fully-specified, no-early-termination bubble-sort engine to a
deterministic Tier-1 emit. GENERAL: N/WIDTH parsed from the prompt; the
N*(N-1)+2 latency + comparison schedule are the bubble-sort invariant. Verified
PASS against the design's own cocotb harness. These tests pin the emit shape +
the §4.05 SKIPs (modify/complete-partial, early-termination, missing params).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import sort_synth as S  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_DATASET = corpus_path("_extbench/cvdp_open_v110/"
                       "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")

_PROMPT = (
    "Design an RTL module named `sorting_engine` that sorts an array using the "
    "bubble sort algorithm in ascending order. For this implementation perform "
    "(N)*(N-1) passes to sort the array of N elements with no early termination.\n"
    "**Parameters**\n- `N` (Default is 8, Greater than 0): Number of elements\n"
    "- `WIDTH`(Default is 8, Greater than 0): Bit-width of each element\n"
    "Ports: clk, rst (active high asynchronous), start (pulse), "
    "[N*WIDTH-1:0] in_data, done (1-cycle pulse), [N*WIDTH-1:0] out_data. "
    "Use a state machine with IDLE, SORTING, and DONE states. "
    "Latency should be equal to (N)*(N-1)+2."
)


def _rec(top, prompt, *, ctx=None):
    return {
        "id": f"test_{top}",
        "input": {"prompt": prompt, "context": ctx or {}},
        "output": {"response": "", "context": {f"rtl/{top}.sv": ""}},
        "harness": {"files": {"src/.env": f"TOPLEVEL        = {top}\n"}},
    }


def test_emit_shape_and_params():
    rtl = S.solve(_rec("sorting_engine", _PROMPT))
    assert rtl is not None
    assert "module sorting_engine" in rtl
    assert "parameter N = 8" in rtl and "parameter WIDTH = 8" in rtl
    assert "[N*WIDTH-1:0] in_data" in rtl and "[N*WIDTH-1:0] out_data" in rtl
    assert "IDLE" in rtl and "SORTING" in rtl and "DONE" in rtl
    assert "step == N*(N-1) - 1" in rtl          # the fixed N*(N-1) schedule
    assert "posedge clk or posedge rst" in rtl   # async active-high reset


def test_general_not_overfit_params():
    """A different (N, WIDTH) default emits the corresponding params (reads the
    spec, not a memorized 8/8)."""
    p = _PROMPT.replace("Default is 8, Greater than 0): Number",
                        "Default is 16, Greater than 0): Number").replace(
        "WIDTH`(Default is 8", "WIDTH`(Default is 4")
    rtl = S.solve(_rec("sorting_engine", p))
    assert "parameter N = 16" in rtl and "parameter WIDTH = 4" in rtl


def test_descending_flips_compare():
    p = _PROMPT.replace("ascending order", "descending order, with the largest "
                        "at index 0")
    rtl = S.solve(_rec("sorting_engine", p))
    assert rtl is not None
    # descending: swap when arr[pos] < arr[pos+1]
    assert "arr[(pos*WIDTH) +: WIDTH] < arr[((pos+1)*WIDTH) +: WIDTH]" in rtl


def test_skip_modify_partial():
    p = _PROMPT + " Complete the given partial code; retain the already written part."
    assert S.solve(_rec("sorting_engine", p)) is None


def test_skip_with_input_context():
    assert S.solve(_rec("sorting_engine", _PROMPT, ctx={"rtl/x.sv": "module x;"})) is None


def test_skip_early_termination():
    p = _PROMPT + " The sort should stop when no swaps occur (early termination)."
    assert S.solve(_rec("sorting_engine", p)) is None


def test_skip_non_bubble_sort():
    p = "Design a merge sort engine. Parameters N (default 8), WIDTH (default 8)."
    assert S.solve(_rec("sorting_engine", p)) is None


def test_skip_missing_params():
    p = ("Design a bubble sort engine sorting_engine in ascending order with no "
         "early termination, (N)*(N-1) passes. Ports clk rst start in_data done out_data.")
    assert S.solve(_rec("sorting_engine", p)) is None  # no N/WIDTH defaults


def test_dataset_record_emits_when_present():
    if not _DATASET.exists():
        pytest.skip("dataset not present")
    recs = {json.loads(l)["id"]: json.loads(l) for l in _DATASET.read_text().splitlines()}
    r = recs.get("cvdp_copilot_sorter_0001")
    if r is None:
        pytest.skip("record not present")
    rtl = S.solve(r)
    assert rtl is not None and "module sorting_engine" in rtl
    # the 6 partial/modify siblings must SKIP
    for sid in ("sorter_0003", "sorter_0009", "sorter_0031", "sorter_0051",
                "sorter_0057", "sorter_0059"):
        rr = recs.get(f"cvdp_copilot_{sid}")
        if rr is not None:
            assert S.solve(rr) is None, f"{sid} should SKIP (partial/modify)"
