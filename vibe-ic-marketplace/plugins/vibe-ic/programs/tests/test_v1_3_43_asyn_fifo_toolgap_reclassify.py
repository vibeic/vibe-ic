"""v1.3.43 candidate #2 — BENCHMARK_REGISTRY asyn_fifo classification correction.

The v1.3.42 campaign re-ran the § 4.1 floor-proof on the GOLDEN asyn_fifo
(verified_asyn_fifo.v renamed to asyn_fifo + the official testbench.v, which uses
`break;`). Reproduced this session:
  * stock iverilog 12  -> COMPILE FAIL ("sorry: break statements not supported")
  * Verilator 5.020 --timing -> PASS ("Your Design Passed", 10/10 stable;
    a wfull-forced-0 mutant -> "Error", so the pass is DISCRIMINATING)
  * forked iverilog 14-devel (vibeic-eda:0.2.5) -> PASS ("Your Design Passed")

=> asyn_fifo is a GENUINE tool-substitution gap that RECOVERS (same class as
ring_counter), NOT a candidate-RTL functional bug. The registry must classify it
under scorer_substitution_recovered_pass, NOT scorer_substitution_recovered_fail.
This is a record correction: the scorer only consumes scorer_substitution_gap
(unchanged, []), so there is NO pass-rate/denominator change.
"""
import json
from pathlib import Path

_REGISTRY = (Path(__file__).resolve().parents[2]
             / "benchmark" / "BENCHMARK_REGISTRY.json")


def _rtllm_entry() -> dict:
    d = json.loads(_REGISTRY.read_text())

    def find(o):
        if isinstance(o, dict):
            if "scorer_substitution_recovered_pass" in o:
                return o
            for v in o.values():
                r = find(v)
                if r is not None:
                    return r
        return None

    e = find(d)
    assert e is not None, "rtllm entry with substitution keys not found"
    return e


def test_asyn_fifo_reclassified_as_recovered_pass():
    e = _rtllm_entry()
    assert "asyn_fifo" in e["scorer_substitution_recovered_pass"], \
        "asyn_fifo must be classified as a recovered tool-gap"
    # ring_counter stays (parallel treatment)
    assert "ring_counter" in e["scorer_substitution_recovered_pass"]


def test_asyn_fifo_no_longer_recovered_fail():
    e = _rtllm_entry()
    assert "asyn_fifo" not in e.get("scorer_substitution_recovered_fail", []), \
        "asyn_fifo must NOT be a candidate-RTL fail — the golden recovers"


def test_scorer_substitution_gap_unchanged_no_scoring_impact():
    """The scorer (score_iverilog_tb.py) only reads scorer_substitution_gap —
    this record correction must NOT touch it (no pass-rate change)."""
    e = _rtllm_entry()
    assert e.get("scorer_substitution_gap", []) == []


def test_note_records_floor_proof_evidence():
    e = _rtllm_entry()
    note = e.get("scorer_substitution_gap_note", "")
    # the corrected note cites the § 4.1 floor-proof reproduction
    assert "break" in note
    assert "Verilator" in note
    for token in ("floor-proof", "PASS", "genuine tool"):
        assert token.lower() in note.lower(), token
