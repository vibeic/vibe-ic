#!/usr/bin/env python3
r"""test_organic_20260705_cvdp_module_name_prose_and_l9_backfill.py

ORGANIC-20260705 (cvdp-phase1-module-name-prose + l9-port-backfill).

Two verified Phase-1 gaps on the CVDP nonagentic (prompt-only) family, found by
driving the plugin's Phase-1 entry over the 302-case dataset:

  Gap A — L9.top_module stayed on the `chip_top` sentinel even though the prompt
          named the module in one of the two CANONICAL spec-prose forms:
            (1) a "Module Name:" label / `## Module Name` heading whose value is
                the identifier (same line, or backtick-wrapped on the next line);
            (2) an inline ``module `<name>` `` reference in running prose.
          None of the four legacy prose patterns matched either form.

  Gap B — for a prompt-only design whose ports live in `Inputs:`/`Outputs:`
          bullets, the directional-prose fallback harvested the ports into
          L1.pin_table AFTER gen_l9 had already run, so L9.top_ports stayed
          EMPTY (the L9<->L1 crosswalk only mirrored L9->L1, never L1->L9). It
          also emitted each port TWICE (double-harvest).

Fix (phase1_doc_one_shot_runner):
  * `_RE_DOC_TOP_MODULE_NAME_LABEL` + `_RE_DOC_TOP_MODULE_INLINE_BACKTICK` +
    `_doc_module_name_label_or_inline`, wired into `_extract_top_module_from_docs`
    just below the real-declaration check and above the low-confidence heuristics.
  * `_promote_l1_pins_to_l9_ports` + a REVERSE L1->L9 mirror step in
    `_post_emit_crosswalk_l9_ports_to_l1_pin_table_v1_6_555`, plus (name, mode)
    dedup of the directional-prose pin_table.

These are the deterministic, program-first boundary of the flow: the module
NAME and the PORT LIST are structural facts a program can carry; the behavioral
prose -> RTL body synthesis correctly remains the spec-to-rtl AI-backup path.

Run: python3 -m pytest programs/tests/test_organic_20260705_cvdp_module_name_prose_and_l9_backfill.py -q
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_doc_one_shot_runner as P   # noqa: E402


# --------------------------------------------------------------------------- #
# Gap A — module-name prose forms feed L9.top_module.
# --------------------------------------------------------------------------- #
def test_module_name_label_next_line_backtick_with_colon():
    docs = {"p.md": "### Module Name:\n`qam16_mapper_interpolated`\n\nParameterized."}
    assert P._extract_top_module_from_docs(docs) == "qam16_mapper_interpolated"


def test_module_name_heading_no_colon_next_line_backtick():
    # `## Module Name` heading with NO colon, value on the next line.
    docs = {"p.md": "## Module Name\n`qam16_demapper_interpolated`\n\n| Name |"}
    assert P._extract_top_module_from_docs(docs) == "qam16_demapper_interpolated"


def test_module_name_label_same_line_bare():
    docs = {"p.md": "Module Name: crc32_gen\nDescribes a CRC."}
    assert P._extract_top_module_from_docs(docs) == "crc32_gen"


def test_inline_module_backtick_reference():
    docs = {"p.md": "Design an 8x3 priority encoder.\n\n"
                    "**Specifications for module `priority_encoder_8x3 ` :**\n- Inputs:"}
    assert P._extract_top_module_from_docs(docs) == "priority_encoder_8x3"


def test_inline_the_module_backtick():
    docs = {"p.md": "Implement the module `spi_master` which drives MOSI."}
    assert P._extract_top_module_from_docs(docs) == "spi_master"


def test_real_declaration_still_outranks_label():
    docs = {"p.md": "Module Name: wrong_label\n"
                    "module coffee_machine ( input clk, output x );"}
    assert P._extract_top_module_from_docs(docs) == "coffee_machine"


# --------------------------------------------------------------------------- #
# Guards — never grab a prose word / an unnamed design.
# --------------------------------------------------------------------------- #
def test_module_name_next_line_prose_paragraph_not_grabbed():
    # colon, but the next non-space token is an unquoted prose word -> reject.
    docs = {"p.md": "Module Name:\n\nThis paragraph describes behaviour."}
    assert P._extract_top_module_from_docs(docs) is None


def test_unnamed_design_returns_none_not_a_port_name():
    # encoder-family prompt: no module name stated; only ports in backticks.
    docs = {"p.md": "Design a 64b/66b encoder with a 2-bit sync header. "
                    "Ports `clk_in`, `rst_in`, `encoder_data_out`."}
    assert P._extract_top_module_from_docs(docs) is None


def test_param_step_section_tokens_still_rejected():
    for bad in ("DATA_WIDTH", "Step_9", "Interface_Signals"):
        docs = {"p.md": f"Module Name: {bad}\n"}
        assert P._extract_top_module_from_docs(docs) is None, bad


# --------------------------------------------------------------------------- #
# Gap B — L1 -> L9 reverse port promotion + dedup.
# --------------------------------------------------------------------------- #
def test_promote_l1_pins_to_l9_dedups_and_preserves_width():
    l1_pins = [
        {"name": "in", "mode": "input", "width": "8",
         "evidence": "directional-prose Inputs/Outputs bullet",
         "extraction_strategy": "directional_prose_port"},
        {"name": "out", "mode": "output", "width": "3",
         "evidence": "directional-prose Inputs/Outputs bullet",
         "extraction_strategy": "directional_prose_port"},
        # duplicate of the first row (the double-harvest bug) — must collapse.
        {"name": "in", "mode": "input", "width": "8",
         "evidence": "directional-prose Inputs/Outputs bullet",
         "extraction_strategy": "directional_prose_port"},
    ]
    promoted = P._promote_l1_pins_to_l9_ports(l1_pins, "priority_encoder_8x3")
    names = [(p["name"], p["mode"], p.get("width")) for p in promoted]
    assert names == [("in", "input", "8"), ("out", "output", "3")]


def test_promote_empty_when_no_real_pins():
    assert P._promote_l1_pins_to_l9_ports([], "x") == []


# --------------------------------------------------------------------------- #
# End-to-end: a prompt-only priority encoder → L9 has real top_module + ports.
# --------------------------------------------------------------------------- #
PRIORITY_ENCODER_PROMPT = (
    "Design and implement an 8x3 priority encoder using Verilog.\n\n"
    "**Specifications for module `priority_encoder_8x3 ` :**\n\n"
    "- Inputs:\n"
    "    - [7:0] in: An 8-bit input vector. The priority decreases from bit 7 to bit 0.\n\n"
    "- Output:\n"
    "    - [2:0] out: A 3-bit output vector for the highest-priority active input.\n"
)


def test_end_to_end_phase1_populates_l9_top_module_and_ports(tmp_path):
    proj = tmp_path / "proj"
    (proj / "input").mkdir(parents=True)
    (proj / "input" / "phase1_prompt.md").write_text(PRIORITY_ENCODER_PROMPT)
    runner = _PROGRAMS / "phase1_one_shot_runner.py"
    r = subprocess.run([sys.executable, str(runner), str(proj)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    l9 = json.loads((proj / "phase1" / "generated_docs"
                     / "L9_INTEGRATION_SPEC.json").read_text())
    assert l9.get("top_module") == "priority_encoder_8x3", l9.get("top_module")
    tp = l9.get("top_ports") or []
    got = sorted((p.get("name"), p.get("mode")) for p in tp)
    assert got == [("in", "input"), ("out", "output")], got
    # no duplicate port rows.
    assert len(tp) == 2, tp
    # L1 pin_table also deduped to exactly the two real ports.
    l1 = json.loads((proj / "phase1" / "generated_docs"
                     / "L1_DATASHEET.json").read_text())
    assert len(l1.get("pin_table") or []) == 2, l1.get("pin_table")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
