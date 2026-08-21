"""Phase-1 sufficiency: width-completeness advisories from the GENERAL engine.

phase1_sufficiency_check now optionally runs spec_complete_extract.assess_spec over
the design doc + the collected ports, turning each unstated-width port into a
plain-language ADVISORY (never blocking, no silicon jargon). This is how the
benchmark-convergence width-extraction work reaches the general Phase-1 flow: an
unstated bus width becomes a user QUESTION instead of an AI silently guessing.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import phase1_sufficiency_check as P  # noqa: E402


def _layers(ports, name="blk"):
    d = Path(tempfile.mkdtemp())
    (d / "L1.json").write_text(json.dumps(
        {"module_name": name, "pinout": ports}))
    return d


def test_unstated_width_surfaces_advisory():
    d = _layers([{"name": "clk", "direction": "input"},
                 {"name": "data_bus", "direction": "input"},
                 {"name": "result", "direction": "output"}])
    doc = ("Design a block `blk` that processes a data input `data_bus` and "
           "produces `result`. There is a clock `clk`.")
    rep = P.check(d, doc_text=doc)
    assert "width:data_bus" in rep["width_gaps"]
    assert "width:result" in rep["width_gaps"]
    # the advisory is a plain-language question, never silicon jargon
    qs = [a for a in rep["advisories_for_agent"] if "bits wide" in a]
    assert any("data_bus" in q for q in qs)
    for q in qs:  # no jargon tokens leak to the user-facing string
        assert not any(j in q for j in ("CRC", "opcode", "FSM", "reset polarity",
                                        "bit-width", "MOSI", "ADC"))


def test_stated_width_no_advisory():
    d = _layers([{"name": "clk", "direction": "input"},
                 {"name": "din", "direction": "input"}])
    doc = "Design `blk`. Clock `clk`. Input `[7:0] din` is an 8-bit data input."
    rep = P.check(d, doc_text=doc)
    assert "width:din" not in rep["width_gaps"]


def test_no_doc_text_is_inert():
    """Without --doc, behavior is exactly as before (no width gaps section content)."""
    d = _layers([{"name": "clk", "direction": "input"},
                 {"name": "x", "direction": "input"}])
    rep = P.check(d)  # no doc_text
    assert rep["width_gaps"] == []


def test_width_advisory_never_blocks_verdict():
    """A width gap is ADVISORY — it must NOT flip the REQUIRED verdict to insufficient
    (the verdict blocks only on missing name / missing ports)."""
    d = _layers([{"name": "clk", "direction": "input"},
                 {"name": "data_bus", "direction": "input"}])
    # name + >=1 port present -> sufficient regardless of width gaps
    doc = "Design `blk` with a clock `clk` and a data input `data_bus`."
    rep = P.check(d, doc_text=doc)
    assert rep["width_gaps"]  # a gap IS surfaced
    assert rep["verdict"] == "sufficient"  # but does not block
