"""fibonacci_synth — general Fibonacci generator solver (T2->T1 promotion).

Promotes fibonacci_series_0001 (a 0/5 problem, unblocked by the v1.2.13 scorer-env
fix) to a deterministic Tier-1 emit. The generator seeds F(0)=0/F(1)=1, advances
one number per clock, and on overflow (sum exceeds W bits) sets overflow_flag +
auto-restarts. GENERAL: data width parsed. Verified PASS on the design's own
cocotb harness (through the env-normalized scorer).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import fibonacci_synth as S  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_DATASET = corpus_path("_extbench/cvdp_open_v110/"
                       "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")

_PROMPT = (
    "Design a 32-bit Fibonacci series generator that updates at each clock cycle, "
    "starting from F(0)=0 and F(1)=1. When the sum exceeds 32 bits the module detects "
    "overflow and sets the `overflow_flag` after one clock cycle, then restarts.\n"
    "Inputs: clk, rst (active-high reset).\n"
    "Outputs: fib_out (32-bit), overflow_flag."
)


def _rec(top, prompt, *, ctx=None):
    return {
        "id": f"test_{top}",
        "input": {"prompt": prompt, "context": ctx or {}},
        "output": {"response": "", "context": {f"rtl/{top}.sv": ""}},
        "harness": {"files": {"src/.env": f"TOPLEVEL        = {top}\n"}},
    }


def test_emit_shape_and_width():
    rtl = S.solve(_rec("fibonacci_series", _PROMPT))
    assert rtl is not None
    assert "module fibonacci_series" in rtl
    assert "[31:0] fib_out" in rtl
    assert "reg [31:0] RegA, RegB" in rtl
    assert "wire [32:0] next_fib = RegA + RegB" in rtl
    assert "if (next_fib[32])" in rtl          # overflow on the W-th bit
    assert "RegB <= 32'd1" in rtl              # F(1)=1 seed


def test_general_not_overfit_width():
    """A 16-bit instance emits 16-bit registers + a 16-bit overflow boundary."""
    p = _PROMPT.replace("32-bit Fibonacci", "16-bit Fibonacci").replace(
        "exceeds 32 bits", "exceeds 16 bits").replace("fib_out (32-bit)",
                                                       "fib_out (16-bit)")
    rtl = S.solve(_rec("fibonacci_series", p))
    assert "reg [15:0] RegA, RegB" in rtl
    assert "wire [16:0] next_fib" in rtl
    assert "if (next_fib[16])" in rtl


def test_skip_modify_partial():
    p = _PROMPT + " Complete the given partial code; retain the already written part."
    assert S.solve(_rec("fibonacci_series", p)) is None


def test_skip_with_context():
    assert S.solve(_rec("f", _PROMPT, ctx={"rtl/x.sv": "module x;"})) is None


def test_skip_lfsr_or_loadable_variant():
    p = _PROMPT + " The start value is a loadable seed input."
    assert S.solve(_rec("fibonacci_series", p)) is None


def test_skip_non_fibonacci():
    assert S.solve(_rec("c", "Design a 32-bit counter. clk rst out.")) is None


def test_skip_without_overflow():
    p = ("Design a 32-bit Fibonacci series generator updating each clock from "
         "F(0)=0, F(1)=1. Inputs clk, rst. Output fib_out.")
    assert S.solve(_rec("fibonacci_series", p)) is None  # no overflow contract


def test_dataset_record_emits_when_present():
    if not _DATASET.exists():
        pytest.skip("dataset not present")
    recs = {json.loads(l)["id"]: json.loads(l) for l in _DATASET.read_text().splitlines()}
    r = recs.get("cvdp_copilot_fibonacci_series_0001")
    if r is None:
        pytest.skip("record not present")
    rtl = S.solve(r)
    assert rtl is not None and "module fibonacci_series" in rtl
