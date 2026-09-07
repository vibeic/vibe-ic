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
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import design_one_shot_runner as R  # noqa: E402
import lesson_consumption_check as G  # noqa: E402
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


def _printed_command(hint: str):
    """The argv the handoff tells the author to run, parsed out of the hint."""
    marker = "lesson_consumption_check.py"
    assert marker in hint, "the handoff printed no verification command at all"
    tail = hint[hint.index(marker) + len(marker):]
    parts = []
    for raw in tail.splitlines():
        line = raw.strip()
        cont = line.endswith("\\")
        if cont:
            line = line[:-1].strip()
        parts.append(line)
        if not cont:
            break
    return shlex.split(" ".join(parts))


def _run(args):
    cp = subprocess.run([sys.executable, str(GATE), *args],
                        capture_output=True, text=True)
    return cp.returncode, cp.stdout, cp.stderr


def _ack_everything(proj: Path, titles):
    p = PL.phase2_stage1_dir(proj) / "lessons_ack.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"lessons_applied": [
        {"section": t, "applied": True, "note": "considered at authoring time"}
        for t in titles]}, indent=2))
    return p


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


def test_premise_one_input_doc_is_a_strict_subset_of_the_gather(tmp_path):
    """The defect needs the two inputs to really differ. Assert it rather than
    assuming it."""
    proj = _mk_project(tmp_path)
    one = (proj / "phase1/input_doc/L2_architecture.md").read_text()
    whole = PL.gather_spec_text(proj)
    assert one != whole and len(one) < len(whole)
    assert G.spec_subset_relation(one, whole) == "STRICT_SUBSET"


# ---------------------------------------------------------------------------
# THE SUBSET RELATION — pure strings, both ways of being less than the whole.
# ---------------------------------------------------------------------------

def test_subset_relation_recognises_the_whole_spec():
    whole = "alpha beta gamma\n\ndelta epsilon\n"
    assert G.spec_subset_relation(whole, whole) == "SAME"


def test_subset_relation_catches_a_source_whose_words_all_recur():
    """The byte-containment branch is NOT redundant with the term branch. Two
    input docs that share their whole vocabulary — a doc and a restatement of
    it, which this corpus's L-docs routinely are — give the smaller one a term
    set EQUAL to the gather's, so a terms-only test would call it DIFFERENT and
    score it as if it were the whole spec."""
    one = "alpha beta gamma delta\n"
    whole = one + "\n\n" + one + "alpha beta\n"
    assert G._terms(one) == G._terms(whole)          # the term branch is blind here
    assert len(one) < len(whole)
    assert G.spec_subset_relation(one, whole) == "STRICT_SUBSET"


def test_subset_relation_catches_a_reconcatenation_that_is_not_byte_contained():
    """And the containment branch is not enough on its own: joining the same
    sources with a different separator changes no term but changes the bytes."""
    whole = "alpha beta\n\ngamma delta\n\nepsilon\n"
    part = "alpha beta\ngamma delta\n"
    assert part not in whole
    assert G.spec_subset_relation(part, whole) == "STRICT_SUBSET"


def test_subset_relation_calls_an_unrelated_text_different():
    assert G.spec_subset_relation("zeta eta theta\n",
                                  "alpha beta gamma\n") == "DIFFERENT"


# ---------------------------------------------------------------------------
# ONE GATHER — the two denominators are computed by the same function.
# ---------------------------------------------------------------------------

def test_the_runner_and_the_gate_read_the_same_spec_text(tmp_path):
    """A second copy of 'the same fact' answers differently sooner or later;
    #2086 is what that costs. There is one gather now."""
    proj = _mk_project(tmp_path)
    assert R._gather_spec_text(proj) == PL.gather_spec_text(proj)
    assert [Path(f).name for f in PL.spec_text_sources(proj)] == [
        "L2_architecture.md", "L3_interface.md", "L4_timing.md", "L1.json"]


# ---------------------------------------------------------------------------
# HALF ONE — the printed command names the source that was actually scored.
# ---------------------------------------------------------------------------

def test_the_printed_command_names_the_scored_spec_not_one_file(tmp_path):
    proj = _mk_project(tmp_path)
    hint, extras = _staged(proj)
    argv = _printed_command(hint)
    assert "--project" in argv, (
        "the handoff still asks the author for a single --prompt file while it "
        "scored the whole gathered spec (#2086)")
    assert argv[argv.index("--project") + 1] == str(proj)
    assert "--prompt" not in argv
    assert "--scoring-record" in argv


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


def test_the_printed_command_run_verbatim_reproduces_the_printed_number(tmp_path):
    """THE DEFECT, stated as the property that was violated: the number the
    handoff hands the author and the number the printed command computes must
    be the same number."""
    proj = _mk_project(tmp_path)
    hint, extras = _staged(proj)
    titles = extras["lessons_strong_matches"]
    _ack_everything(proj, titles)
    rc, out, err = _run(_printed_command(hint))
    assert rc == 0, f"the command the handoff printed does not pass: {err}"
    assert f"all {len(titles)} strongly-matched" in out, (
        f"the handoff named {len(titles)} strong match(es); its own printed "
        f"command reports something else:\n{out}\n{err}")


# ---------------------------------------------------------------------------
# HALF TWO — the gate refuses a run whose subject is not the recorded one.
# ---------------------------------------------------------------------------

def _record_and_ack(tmp_path):
    proj = _mk_project(tmp_path)
    hint, extras = _staged(proj)
    titles = extras["lessons_strong_matches"]
    ack = _ack_everything(proj, titles)
    return proj, extras, titles, ack, Path(extras["lessons_scoring_record"])


def test_one_file_out_of_the_gather_is_refused_by_name(tmp_path):
    """Row 1 of the issue table: 0 strong matches, printed as a clean PASS."""
    proj, extras, titles, ack, rec = _record_and_ack(tmp_path)
    one = proj / "phase1/input_doc/L2_architecture.md"
    rc, out, err = _run(["--prompt", str(one),
                         "--digest", extras["lessons_digest"],
                         "--ack", str(ack), "--scoring-record", str(rec),
                         "--strict"])
    assert rc == 2, f"a single input doc still verified the whole spec:\n{out}"
    assert "STRICT SUBSET" in err
    assert "NOT_MEASURED" in err
    assert "PASS" not in out


def test_a_reconcatenation_of_the_sources_is_refused_as_a_subset(tmp_path):
    """Row 2: not byte-contained in the gather, yet contributing no term the
    gather does not already carry — still less than what was scored."""
    proj, extras, titles, ack, rec = _record_and_ack(tmp_path)
    cat = tmp_path / "cat.txt"
    cat.write_text("".join(
        p.read_text() for p in sorted((proj / "phase1/input_doc").glob("*.md"))))
    rc, out, err = _run(["--prompt", str(cat),
                         "--digest", extras["lessons_digest"],
                         "--ack", str(ack), "--scoring-record", str(rec),
                         "--strict"])
    assert rc == 2
    assert "STRICT SUBSET" in err


def test_the_gathered_spec_still_passes(tmp_path):
    """Row 3 — THE CONTROL. A gate that refuses everything is not a gate."""
    proj, extras, titles, ack, rec = _record_and_ack(tmp_path)
    rc, out, err = _run(["--project", str(proj),
                         "--digest", extras["lessons_digest"],
                         "--ack", str(ack), "--scoring-record", str(rec),
                         "--strict"])
    assert rc == 0, err
    assert f"all {len(titles)} strongly-matched" in out


def test_the_gate_still_fails_on_an_unacknowledged_section(tmp_path):
    """The verdict this gate exists for must survive the fix: with the record
    in place and NO acknowledgement, --strict is still rc 1."""
    proj = _mk_project(tmp_path)
    hint, extras = _staged(proj)
    rc, out, err = _run(["--project", str(proj),
                         "--digest", extras["lessons_digest"],
                         "--scoring-record", extras["lessons_scoring_record"],
                         "--strict"])
    assert rc == 1
    assert "UNACKNOWLEDGED" in out


def test_a_file_named_beside_a_project_is_refused_without_any_record(tmp_path):
    """The subset refusal does not depend on a record being present."""
    proj = _mk_project(tmp_path)
    hint, extras = _staged(proj)
    one = proj / "phase1/input_doc/L2_architecture.md"
    rc, out, err = _run(["--project", str(proj), "--prompt", str(one),
                         "--digest", extras["lessons_digest"], "--strict"])
    assert rc == 2
    assert "STRICT SUBSET" in err


def test_a_digest_that_moved_under_the_record_is_not_measured(tmp_path):
    proj, extras, titles, ack, rec = _record_and_ack(tmp_path)
    smaller = tmp_path / "smaller.md"
    smaller.write_text("### Skill: only one section\n\nbody\n")
    rc, out, err = _run(["--project", str(proj), "--digest", str(smaller),
                         "--ack", str(ack), "--scoring-record", str(rec),
                         "--strict"])
    assert rc == 2
    assert "digest moved under the record" in err


def test_an_unreadable_scoring_record_is_not_measured_never_a_pass(tmp_path):
    proj, extras, titles, ack, rec = _record_and_ack(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    rc, out, err = _run(["--project", str(proj),
                         "--digest", extras["lessons_digest"],
                         "--ack", str(ack), "--scoring-record", str(bad),
                         "--strict"])
    assert rc == 2
    assert "NOT_MEASURED" in err


def test_a_strong_set_that_does_not_reproduce_is_not_measured(tmp_path):
    """MEMBERSHIP, not count: the same spec scored under a different threshold
    is a different measurement, and must not be reported as a verification of
    the one the author was handed."""
    proj, extras, titles, ack, rec = _record_and_ack(tmp_path)
    rc, out, err = _run(["--project", str(proj),
                         "--digest", extras["lessons_digest"],
                         "--ack", str(ack), "--scoring-record", str(rec),
                         "--threshold", "0.99", "--strict"])
    assert rc == 2
    assert "must be the same number" in err


def test_a_project_with_no_spec_source_refuses_rather_than_scoring_nothing(tmp_path):
    """'Could not read it' is not 'read it and it was empty'."""
    empty = tmp_path / "empty"
    (empty / "phase2" / "stage1").mkdir(parents=True)
    digest = empty / "phase2/stage1/lessons.md"
    digest.write_text("### Skill: a\n\nbody\n")
    rc, out, err = _run(["--project", str(empty), "--digest", str(digest),
                         "--strict"])
    assert rc == 2
    assert "NOT_MEASURED" in err


def test_naming_no_spec_source_at_all_is_a_usage_error(tmp_path):
    digest = tmp_path / "d.md"
    digest.write_text("### Skill: a\n\nbody\n")
    rc, out, err = _run(["--digest", str(digest), "--strict"])
    assert rc == 2
    assert "name a spec source" in err


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
