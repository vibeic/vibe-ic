"""test_cvdp_harness_output_invariance.py — the CVDP prompt+context-ONLY compliance guard.

Per the CVDP official rule (arXiv:2506.14074 §2 + README_NON_AGENTIC) the model
sees ONLY `input.prompt` + `input.context`. The ENTIRE hidden harness (cocotb
`dut.<sig>` test, `.env` TOPLEVEL / VERILOG_SOURCES, `harness_library.py`) AND
`output.*` (golden/reference RTL) are OFF-LIMITS oracle.

The load-bearing INVARIANT this guard pins: the deterministic CVDP solve/emit path
(`record_prompt_context_bridge.solve` / `toplevel_name` / `extract_interface`) must produce
IDENTICAL results whether or not `record["harness"]` and `record["output"]` are
present. If stripping the oracle changes the emitted RTL or the module name, the
solver is reading the oracle — a compliance breach.

The strongest single assertion is the DECOY: a record whose `.env` TOPLEVEL and
cocotb `dut.<sig>` names DISAGREE with the prompt. A compliant solver names the
module + binds the interface from the PROMPT and ignores the decoy harness.

NOTE (§3.9): `cvdp_complete_extract` legitimately reads the harness for the
EXTRACTION_GAP diagnostic (post-hoc "what did OUR prompt-extraction miss vs the
hidden TB") — that is analysis, not emission, and its `gaps` field MAY differ with
the harness present. This guard pins only the EMITTED/ENFORCED fields.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))

import record_prompt_context_bridge as B  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402


def _strip_oracle(rec: dict) -> dict:
    r = copy.deepcopy(rec)
    r.pop("harness", None)
    r.pop("output", None)
    return r


# --------------------------------------------------------------------------- #
# DECOY fixture — the harness names DISAGREE with the prompt. A compliant solver
# must name the module + bind ports from the PROMPT (`brent_kung_adder`, a/b/…),
# never the decoy `.env` TOPLEVEL or the decoy cocotb dut signals.
# --------------------------------------------------------------------------- #
_ADDER_PROMPT = """The 32-bit Brent-Kung Adder module `brent_kung_adder` performs binary addition.

| Test case | a        | b        | carry_in | Expected Sum | Expected carry_out |
|-----------|----------|----------|----------|--------------|--------------------|
| 1         | 00000000 | 00000000 | 0        | 00000000     | 0                  |
| 2         | FFFFFFFF | 00000001 | 0        | 00000000     | 1                  |

Identify and Fix the RTL Bug(s).
"""

_DECOY_RECORD = {
    "id": "decoy_adder",
    "input": {"prompt": _ADDER_PROMPT, "context": {}},
    # output.context (golden) — a DECOY the solver must never read.
    "output": {"response": "GOLDEN — MUST NOT BE READ",
               "context": {"rtl/brent_kung_adder.sv":
                           "module DECOY_GOLDEN(input x, output y); assign y=x; endmodule"}},
    # harness .env + cocotb — DECOY names that disagree with the prompt.
    "harness": {"files": {
        "src/.env": "TOPLEVEL = DECOY_HARNESS_NAME\nMODULE = test_decoy\n",
        "src/test_decoy.py": "async def t(dut):\n    dut.DECOY_IN.value=0\n    _=int(dut.DECOY_OUT.value)\n",
    }},
}


def test_decoy_harness_name_is_ignored():
    """The module is named from the PROMPT, never the decoy harness .env TOPLEVEL."""
    top = B.toplevel_name(_DECOY_RECORD)
    assert top == "brent_kung_adder", f"name must come from the prompt, got {top!r}"
    assert top != "DECOY_HARNESS_NAME"


def test_solve_invariant_to_oracle_on_decoy():
    with_oracle = B.solve(_DECOY_RECORD)
    without = B.solve(_strip_oracle(_DECOY_RECORD))
    assert with_oracle == without, "solve must be invariant to harness/output presence"
    if with_oracle is not None:
        assert "module brent_kung_adder" in with_oracle
        assert "DECOY" not in with_oracle


def test_interface_invariant_and_from_prompt():
    a = B.extract_interface(_DECOY_RECORD, "brent_kung_adder")
    b = B.extract_interface(_strip_oracle(_DECOY_RECORD), "brent_kung_adder")
    assert a == b, "interface must be invariant to harness/output presence"
    if a is not None:
        names = {n for n, _ in a[0]} | {n for n, _ in a[1]}
        assert "DECOY_IN" not in names and "DECOY_OUT" not in names
        assert {"a", "b", "carry_in"} <= {n for n, _ in a[0]}


_DATASET = corpus_path("_extbench/cvdp_open_v110/"
                       "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")


@pytest.mark.skipif(not _DATASET.exists(), reason="CVDP dataset not present; set $VIBEIC_CORPUS_ROOT to the external benchmark corpus")
def test_solve_invariant_over_real_dataset():
    """Over the real 302-record dataset, stripping harness+output must NEVER change
    solve() or toplevel_name() — the definitive prompt+context-only proof."""
    mism = []
    with _DATASET.open() as f:
        for line in f:
            rec = json.loads(line)
            s = _strip_oracle(rec)
            if B.solve(rec) != B.solve(s) or B.toplevel_name(rec) != B.toplevel_name(s):
                mism.append(rec.get("id"))
    assert not mism, f"{len(mism)} records read the oracle: {mism[:10]}"
