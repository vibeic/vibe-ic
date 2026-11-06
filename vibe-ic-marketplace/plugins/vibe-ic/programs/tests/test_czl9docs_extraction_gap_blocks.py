#!/usr/bin/env python3
"""#czl9docs — "no ports" has two causes, and only one of them is legitimate.

Measured on live main 73728b9f: docs-mode Phase-1 emitted an L9 with 0 ports
over an input that declares five, printed `insufficient / MISSING ['ports']`
itself, and the run CONTINUED with rc=0 — so the flow's step-2 spec-conformance
clause read PASS rc=0 with 0 findings on RTL violating every element it checks.
A verdict over an empty population, one layer earlier than where this repo
usually refuses it.

`phase1_sufficiency_check` could not tell the two causes apart because it never
read the design INPUT:

  * the input declares no ports  -> a behavioural spec. Allowed through.
  * the input declares ports and the L docs carry none -> an EXTRACTION GAP.
    Nothing downstream can be measured.

Pinned in BOTH directions, because a gate that blocks everything is not a gate:
the extraction gap must exit 1, and the port-less behavioural spec must still
exit 0 with its own label.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))


_PORTFUL_INPUT = ("Implement a framed serial receiver.\n"
                  "\n"
                  " - input  clk\n"
                  " - output cmd_out (4 bits)\n")
_PORTLESS_INPUT = ("Each frame is one start bit, an 8-bit payload and one\n"
                   "stop bit. Frames are separated by three idle periods.\n")


def _project(tmp_path, doc_text, ports):
    proj = tmp_path / "p"
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "input" / "docs" / "spec.md").write_text(doc_text)
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    # `_collect_port_names` reads L1/L8R/L5/L17 — L1.pin_table is where the
    # docs-mode extractor lands a pin and where the sufficiency gate looks.
    (gd / "L1_DATASHEET.json").write_text(json.dumps({
        "schema_version": 2, "ic_name": "dut", "pin_table": ports}))
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "schema_version": 2, "ic_name": "dut", "ports": ports}))
    return proj, gd










def test_the_runner_wires_project_and_strict_extraction_gap(tmp_path):
    # A gate that is never invoked with the flag cannot block. Pin the call
    # shape in the runner, not just the checker's own behaviour.
    src = (PROGRAMS / "phase1_doc_one_shot_runner.py").read_text()
    assert '"--strict-extraction-gap"' in src
    assert '"phase1_sufficiency_check",' in src
    assert 'FAIL: EXTRACTION GAP' in src
