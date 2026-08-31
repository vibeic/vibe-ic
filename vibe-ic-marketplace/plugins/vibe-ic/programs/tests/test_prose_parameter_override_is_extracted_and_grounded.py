#!/usr/bin/env python3
"""A parameter the brief states in a SENTENCE reached nothing.

MEASURED DEFECT
===============
`L8_RTL_CONSTANTS.parameters[]` was populated only by TABLE walkers (markdown
grid tables, Sphinx ``.. table::``, ``.. list-table::``). A design input that
states a parameter in prose had no producer at all.

Measured on a staged-vendor-RTL IC: the brief wrote ``SecMasking=0``, that name
appears in NONE of the ten vendor documents — the brief is its only source —
and ``L8.parameters`` came out **0**. The value never left Phase 1, so the
chip_top emitter copied the vendor default and synthesis aborted on the variant
that default selects.

TWO PROPERTIES THIS PINS
========================
1. A stated value is an OVERRIDE, not a documented DEFAULT. Merging it into the
   default list would tell a consumer that the vendor's default IS the stated
   value — the opposite of what an override means.
2. A bare ``NAME=VALUE`` regex over prose is far too loose to use alone: across
   the benchmark corpus it matches 869 times over 293 distinct names (rc,
   evidence, todo, PASS, x, returncode, size, busy). A match is accepted ONLY
   when the name is DECLARED as a parameter in the IC's own staged RTL. That
   GROUNDING, not the regex, is the mechanism — so it is what this test pins.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import phase1_doc_one_shot_runner as R  # noqa: E402


def _project(tmp_path: Path, rtl: str) -> Path:
    rtl_dir = tmp_path / "input" / "vendor_rtl"
    rtl_dir.mkdir(parents=True)
    (rtl_dir / "dut.sv").write_text(rtl)
    return tmp_path


_RTL = """module dut #(
  parameter bit SecMasking = 1,
  parameter int WidthBits  = 8
) (input logic clk); endmodule
"""


def _run(project, docs):
    content, evidence = {}, {}
    R._v1_14_50_extract_prose_param_overrides(project, docs, content, evidence)
    return content.get("parameters", [])


def test_a_backticked_prose_override_is_extracted(tmp_path):
    project = _project(tmp_path, _RTL)
    docs = {"input/docs/brief.md":
            "Disable masking for this run: `SecMasking=0` please."}

    params = _run(project, docs)

    assert len(params) == 1, (
        "a parameter stated in prose reached nothing; every L8 producer is "
        "table-based")
    entry = params[0]
    assert entry["name"] == "SecMasking"
    assert entry["value"] == "0"
    assert entry["source"] == "input/docs/brief.md"


def test_it_is_recorded_as_an_override_and_not_as_a_default(tmp_path):
    project = _project(tmp_path, _RTL)
    entry = _run(project, {"d.md": "`SecMasking=0`"})[0]

    assert entry["override"] is True
    assert entry["default"] is None, (
        "a value the input STATES is an override; recording it as the "
        "documented DEFAULT would invert its meaning for every consumer")


def test_prose_noise_is_rejected_because_it_is_not_a_declared_parameter(tmp_path):
    """The grounding, not the regex, is what makes this safe."""
    project = _project(tmp_path, _RTL)
    noisy = ("The run finished with rc=0 and evidence=3 while todo=0 and "
             "size=7; returncode=0, x=1, busy=0. PASS=1.")

    assert _run(project, {"log.md": noisy}) == []


def test_an_override_naming_no_declared_parameter_is_rejected(tmp_path):
    project = _project(tmp_path, _RTL)
    assert _run(project, {"d.md": "`NoSuchParameter=4`"}) == []


def test_a_declared_parameter_is_accepted_from_the_same_noisy_document(tmp_path):
    """The rejection above must be the GROUNDING, not the extractor giving up."""
    project = _project(tmp_path, _RTL)
    mixed = "rc=0 and evidence=3 but also `WidthBits=16` for this build."

    params = _run(project, {"d.md": mixed})

    assert [p["name"] for p in params] == ["WidthBits"]
