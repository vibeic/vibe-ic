#!/usr/bin/env python3
r"""test_organic_20260703_l9_topmodule_misextraction.py

ORGANIC-20260703-runner-l9-topmodule-and-ports-misextraction (P1).

The Phase-1 L9 top-module extractor used to pick a PARAMETER name
(`DATA_WIDTH`, `CLOCK_HZ`, `POLY_LENGTH`), an ALGORITHM-STEP header (`Step_9`),
or a Title_Case documentation section heading (`Data_Latency`,
`Interface_Signals`) as `top_module` — because the low-quality doc heading /
intro-phrase regexes fired and won when the design's real `module <name>(...)`
header was staged into the docs (CVDP input.context) but not inside a
```verilog fence.

Fix (in phase1_doc_one_shot_runner):
  * `_doc_real_module_decl_name` — an actual `module <name> ( <ports> );`
    declaration ANYWHERE in the docs (fenced OR unfenced) is authoritative and
    OUTRANKS every prose heuristic.
  * `_is_valid_top_module_candidate` — rejects SCREAMING_SNAKE parameter names,
    `Step_N` step headers, and Title_Case_Snake section headings, so when NO
    real declaration exists the extractor degrades to the `chip_top` sentinel
    rather than a garbage name.

Run: python3 -m pytest programs/tests/test_organic_20260703_l9_topmodule_misextraction.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_doc_one_shot_runner as P   # noqa: E402


# --------------------------------------------------------------------------- #
# A real module declaration outranks prose noise — fenced AND unfenced.
# --------------------------------------------------------------------------- #
def test_real_fenced_header_beats_prose_noise():
    docs = {"prompt.md": (
        "The coffee_machine controller brews coffee.\n"
        "== Step_9 module\n"
        "The DATA_WIDTH is a module parameter that sets the bus width.\n"
        "```verilog\n"
        "module coffee_machine #(parameter nbw_beans = 8, parameter ns_beans = 4) (\n"
        "    input clk, input rst_n, input req, output reg ready,\n"
        "    output [7:0] cups, input [3:0] level\n"
        ");\n"
        "```\n")}
    assert P._extract_top_module_from_docs(docs) == "coffee_machine"


def test_real_UNFENCED_header_beats_prose_noise():
    # the design's own RTL header is in the context but NOT in a ```verilog
    # fence — the pre-fix code let the `== Interface_Signals module` heading win.
    docs = {"p.md": (
        "== Interface_Signals module\n"
        "The DATA_WIDTH is a module parameter.\n"
        "module coffee_machine ( input clk, input req, output reg ready, "
        "output [7:0] cups );\n"
        "Done.\n")}
    assert P._extract_top_module_from_docs(docs) == "coffee_machine"


def test_nonansi_header_is_accepted():
    docs = {"p.md": "module sound_generator ( clk, rst, note, audio );\n"}
    assert P._extract_top_module_from_docs(docs) == "sound_generator"


def test_param_form_only_header_is_accepted():
    docs = {"p.md": "module prbs_gen #(parameter POLY_LENGTH = 7) (in, out);\n"}
    assert P._extract_top_module_from_docs(docs) == "prbs_gen"


# --------------------------------------------------------------------------- #
# No real declaration → degrade to the chip_top sentinel (None here), never a
# parameter / step / section-heading garbage name.
# --------------------------------------------------------------------------- #
def test_prose_only_no_header_returns_none():
    docs = {"p.md": (
        "The DATA_WIDTH is a module parameter.\n"
        "== Data_Latency module\n"
        "== Step_9 module\n"
        "== Interface_Signals module\n")}
    assert P._extract_top_module_from_docs(docs) is None


def test_prose_parenthetical_is_not_a_declaration():
    # a prose sentence with `module <name> (` must NOT be read as a real decl.
    docs = {"p.md": "The module galois (which computes GF products) is described below.\n"}
    assert P._extract_top_module_from_docs(docs) is None


# --------------------------------------------------------------------------- #
# Candidate filter: param / step / Title_Case rejected; real names accepted.
# --------------------------------------------------------------------------- #
def test_candidate_filter_rejects_param_step_section_tokens():
    for bad in ("DATA_WIDTH", "CLOCK_HZ", "POLY_LENGTH",          # SCREAMING param
                "Step_9", "Step9", "step2",                       # step header
                "Data_Latency", "Interface_Signals", "Register_Map"):  # section
        assert P._is_valid_top_module_candidate(bad) is False, bad


def test_candidate_filter_accepts_real_module_names():
    for good in ("coffee_machine", "aes_core", "hamming_tx", "spi_master",
                 "cpu_top", "riscv_core", "microcode_sequencer",
                 "sound_generator", "prbs_gen"):
        assert P._is_valid_top_module_candidate(good) is True, good


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
