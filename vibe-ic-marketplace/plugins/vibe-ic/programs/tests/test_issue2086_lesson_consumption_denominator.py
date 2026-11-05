#!/usr/bin/env python3
"""vibe-ic#2086 — the lesson self-check the runner PRINTS could not reproduce
the number the runner PRINTS, and the literal reading of it was a vacuous PASS.

MEASURED DEFECT (8HD-9, v1.18.47, and reproduced on 8HD-6 in this lane): the
spec-to-rtl WAIVE handoff scored the staged lesson digest against
`_gather_spec_text(project)` — all nine input docs plus the generated L-docs,
199,513 bytes — and reported 202 strongly-matched sections. In the same breath
it printed:

    lesson_consumption_check.py --prompt <spec-file> --digest ... --ack ... --strict

`--prompt` takes ONE file. Same digest, same ack, only `--prompt` differing:

    one input doc      2,914 B    0 strong   "PASS: no strongly-matched ..."   rc 0
    nine docs cat'd   25,224 B   17 strong   "PASS: all 17 ... acknowledged"   rc 0
    the gathered text 199,513 B  202 strong  "PASS: all 202 ... acknowledged"  rc 0

All three PASS. The first examined almost nothing and said so in a sentence
that reads exactly like a design to which no lesson applies. An author who
followed the printed instruction literally got the vacuous one.

THE FIX HAS TWO HALVES AND BOTH ARE TESTED HERE:
  * the printed command names the SAME spec source that was scored
    (`--project`, delegating to the one `_path_layout.gather_spec_text` both
    sides now call) and carries `--scoring-record`; and
  * the gate REFUSES (rc 2, NOT_MEASURED) when the text it scored is not the
    text the record was scored over — naming a STRICT SUBSET as one — and when
    the strong-match MEMBERSHIP it reproduces is not the one the author was
    handed.

The control matters as much as the refusal: the gathered arm must still PASS.
A gate that refuses everything is not a gate.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import design_one_shot_runner as R  # noqa: E402
import _path_layout as PL  # noqa: E402

GATE = PROGRAMS / "lesson_consumption_check.py"


_ARCH = """# Serial-parallel multiplier — architecture

A bit-serial arithmetic datapath. One operand `x` is parallel and held stable
for the whole word; the multiplier operand `y` arrives one bit per clock cycle,
LSB first; the product `p` is emitted serially, LSB first. The design computes
p = (x * y) mod 2^N on an N-bit datapath.

## Sequencing

A bit counter counts the bits of the word and wraps to zero at the end of the
word; it must not saturate or hold. A shift register loads the parallel operand
when `load` is asserted and otherwise shifts by one position per clock cycle,
inserting zeros at the vacated position. The accumulator registers the partial
sum on the rising clock edge and is cleared by reset.
"""

_IFACE = """# Interface and handshake

The input side uses a valid/ready handshake. `in_valid` is asserted by the
producer for one clock cycle per bit; `in_ready` is asserted by this block when
it can accept a bit. The output side asserts `out_valid` for exactly one clock
cycle when the product bit on `out_data` is stable. A `done` strobe is one
cycle wide and is asserted in the cycle after the last product bit leaves.

## State machine

The controller is a small finite state machine with states IDLE, LOAD, SHIFT
and DONE. The state register is updated on the clock edge; the next-state
function is combinational and assigns a next state in every branch. The output
of the machine is registered so that the outputs are aligned to the cycle in
which the transition takes effect, not the cycle before it.
"""

_TIMING = """# Reset, clocking and verification notes

Single clock domain. Synchronous active-high reset, asserted for at least one
clock cycle. Every register in the datapath, including the output register, is
reset to zero. No latch may be inferred: every branch of every combinational
case assigns the output.

The testbench samples the outputs on the falling edge and compares against a
reference model of the same width. The comparison procedure needs the bit order
and the number of cycles between the last operand bit and the first product bit
to be declared, because two correct designs disagree on both.
"""


def _mk_project(tmp_path: Path, name: str = "p") -> Path:
    """A project laid out the way the spec gather actually reads it: several
    prose sources plus a generated L-doc, so 'one file' really is a subset.

    The prose is generic design-CLASS text (a bit-serial arithmetic datapath) —
    no chip, no PDK, no vendor, no benchmark literal — and is deliberately big
    enough that the REAL lesson corpus produces strong matches, which is the
    regime #2086 was measured in.
    """
    proj = tmp_path / name
    doc = proj / "phase1" / "input_doc"
    doc.mkdir(parents=True)
    (doc / "L2_architecture.md").write_text(_ARCH)
    (doc / "L3_interface.md").write_text(_IFACE)
    (doc / "L4_timing.md").write_text(_TIMING)
    gen = proj / "phase1" / "generated_docs"
    gen.mkdir(parents=True)
    (gen / "L1.json").write_text(json.dumps(
        {"design_class": "serial arithmetic datapath",
         "reset": "synchronous active-high",
         "notes": "the bit counter wraps to zero; the shift register loads on "
                  "enable and shifts one position per clock cycle otherwise"},
        indent=2))
    return proj


def _staged(proj: Path):
    """(hint, extras) from the REAL corpus — no fixture digest, so an empty or
    moved corpus degrades loudly here rather than passing these tests for a
    reason that has nothing to do with #2086."""
    return R._stage_author_knowledge_digests(proj)








# ---------------------------------------------------------------------------
# PREMISE — without these the tests below could pass over an empty corpus.
# ---------------------------------------------------------------------------

def test_premise_the_real_corpus_stages_strong_matches(tmp_path):
    proj = _mk_project(tmp_path)
    hint, extras = _staged(proj)
    assert extras.get("lessons_count", 0) > 0, "no lesson corpus rendered"
    assert extras.get("lessons_strong_matches"), (
        "the real corpus produced NO strongly-matched section for this spec — "
        "every handoff test below would then be measuring silence, not #2086")




# ---------------------------------------------------------------------------
# THE SUBSET RELATION — pure strings, both ways of being less than the whole.
# ---------------------------------------------------------------------------









# ---------------------------------------------------------------------------
# ONE GATHER — the two denominators are computed by the same function.
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# HALF ONE — the printed command names the source that was actually scored.
# ---------------------------------------------------------------------------



def test_the_scoring_record_records_what_was_scored(tmp_path):
    proj = _mk_project(tmp_path)
    hint, extras = _staged(proj)
    rec_path = Path(extras["lessons_scoring_record"])
    assert rec_path.is_file()
    rec = json.loads(rec_path.read_text())
    assert rec["gate"] == "lesson_consumption_check"
    assert rec["strong_sections"] == extras["lessons_strong_matches"]
    assert rec["spec_bytes"] == len(PL.gather_spec_text(proj).encode("utf-8"))
    assert [Path(s).name for s in rec["spec_sources"]] == [
        "L2_architecture.md", "L3_interface.md", "L4_timing.md", "L1.json"]




# ---------------------------------------------------------------------------
# HALF TWO — the gate refuses a run whose subject is not the recorded one.
# ---------------------------------------------------------------------------























if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
