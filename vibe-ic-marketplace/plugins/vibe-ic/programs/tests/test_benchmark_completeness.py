"""benchmark_completeness — the GENERAL engine serves EVERY benchmark (thin adapters).

Proves CVDP / RTLLM / VerilogEval all route their interface recovery into the one
`spec_complete_extract.assess_spec` engine, so a width/structure fix made converging
ANY benchmark improves all of them + the general Phase-1 path.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import benchmark_completeness as BC  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_RTLLM = corpus_path("_extbench/RTLLM")
_VE = corpus_path("_extbench/verilog-eval/dataset_spec-to-rtl")


def test_verilogeval_port_parse_and_widths():
    prompt = ("I would like you to implement a module named TopModule with the "
              "following interface. All input and output ports are one bit unless "
              "otherwise specified.\n"
              " - input  scancode (16 bits)\n"
              " - output left\n - output down\n")
    ins, outs = BC.verilogeval_ports(prompt)
    assert ins == ["scancode"] and outs == ["left", "down"]
    spec = BC.assess_verilogeval(prompt)
    widths = {p["name"]: p["width"] for p in spec["interface"]}
    assert widths["scancode"] == 16          # (16 bits) qualifier
    assert widths["left"] == 1 and widths["down"] == 1  # 1-bit by VE convention
    assert spec["completeness"] == "COMPLETE"


def test_rtllm_design_description_assessed_by_shared_engine():
    if not _RTLLM.exists():
        pytest.skip("RTLLM dataset absent")
    f = next(iter(sorted(_RTLLM.glob("*/*/*/design_description.txt"))), None)
    if f is None:
        pytest.skip("no RTLLM design_description found")
    spec = BC.assess_rtllm(f.read_text())
    # the same verdict vocabulary the CVDP path produces
    assert spec["completeness"] in (
        "COMPLETE", "INCOMPLETE_EXTRACTION_GAP", "INCOMPLETE_SPEC_ABSENT")
    assert "interface" in spec and "gaps" in spec


def test_verilogeval_dataset_majority_complete():
    if not _VE.exists():
        pytest.skip("verilog-eval dataset absent")
    files = sorted(_VE.glob("*_prompt.txt"))[:20]
    if not files:
        pytest.skip("no VE prompts found")
    comp = sum(1 for f in files
               if BC.assess_verilogeval(f.read_text())["completeness"] == "COMPLETE")
    # the shared engine recovers a COMPLETE spec for the clear majority of VE specs
    assert comp >= len(files) * 0.6, f"only {comp}/{len(files)} COMPLETE"


def test_shared_verdict_shape_across_benchmarks():
    """All adapters return the SAME spec-dict shape (the engine's contract)."""
    ve = BC.assess_verilogeval("- input a\n- output y\n")
    for key in ("completeness", "interface", "gaps", "structures", "reset",
                "operation_family"):
        assert key in ve
