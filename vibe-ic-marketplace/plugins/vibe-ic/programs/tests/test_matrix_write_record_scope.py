"""WHICH of the 63x8 dimensions may read a run's WRITE RECORD — and which may not.

    ``programs/step_write_ledger.py`` records what a run actually wrote. The
    question this module settles, once, per dimension, is whether that record
    can answer THAT dimension's question BETTER than what it reads today.

Six dimensions read no record: D1, D2, D4, D5, D6, D7. This is not a to-do
list of six wirings. It is six separate questions with six separate answers,
and FIVE OF THEM ARE "NO" — for reasons that are measurable, and that are
measured here rather than asserted in prose, so a decision cannot rot quietly.

    d1  wiring                 NOT WIRED   the record's producer vocabulary is
                                           disjoint from the flow's
    d2  falsifiable            NOT WIRED   the record holds no CONTENT, and
                                           content is d2's unmet need
    d3  outputs_produced       WIRED       (2026-08-06, elsewhere) the ledger
                                           may only SUBTRACT evidence
    d4  criteria_match         NOT WIRED   the record has no notion of a gate
    d5  deps_correct           NOT WIRED   the record observes WRITES, never
                                           READS
    d6  skip_discipline        NOT WIRED   the record carries no verdict, no
                                           exit code and no tier
    d7  outputs_list_complete  WIRED       (2026-08-06) the record is W2's
                                           second producer oracle
    d8  missing_caught         reads it via flow_compliance_check

WHY A REFUSAL IS A RESULT, AND WHY IT IS A TEST
===============================================
"We looked and decided not to" is worth exactly as much as the evidence under
it, and prose evidence rots: the premise stops being true and the paragraph
keeps saying it does. Every refusal below therefore rests on a property of the
RECORD ITSELF, re-measured on every run from a record built by the real
emitter over a real probe tree. The day ``step_write_ledger`` starts recording
file content, or access times, or a per-step verdict, the corresponding
refusal goes RED and the decision has to be taken again by someone who can see
the new evidence.

The second half of each refusal is a pin: the dimension module named still
does not reference the record. That is what stops a future wiring landing
without the argument being re-opened — it is not a ban, it is a tripwire, and
the way to satisfy it is to move the entry, not to delete the test.

THE ONE REASON THAT APPLIES TO ALL FIVE, STATED ONCE
====================================================
D1, D4, D5 and D7 were characterised by an earlier audit as asking about THIS
COMMIT's yaml-versus-source agreement — a property of the commit, not of a
machine — and the concern was that making them read a run would make a cell's
colour vary by host, which is the disease #527 removed from dimension 3.

That concern is real and it is NOT what decides four of the five refusals
below, because it is answerable: dimension 3 answers it by admitting evidence
only from a run tree the COMMIT CARRIES, and dimension 7's binding
(``matrix_d7_write_record``) answers it the same way — ``git ls-tree -r HEAD``,
no ``$HOME`` search, no env var, no manifest of machine paths. Host-dependence
is a solved problem, so it cannot be the reason to refuse; if it were, D7's
wiring would be wrong too. What decides these five is narrower and harder:
**the record does not contain the fact the dimension needs.** Each refusal
below names that fact and measures its absence.

D2 IS THE ONE WHERE THE TEMPTATION IS REAL, SO IT GETS THE LONGEST ANSWER
=========================================================================
Dimension 2 asks "can this gate FAIL?" and answers it by building a broken
project and running the real gate. 33 of the 129 reds it used to publish were
earned only against ``_f_empty`` — "Nothing was produced at all" — and its own
docstring names the counter-example: step 21's
``files_exist: ['phase3/stage3/pnr/routed.def']`` is satisfied by the 25 bytes
``VERSION 5.8 ;\nEND DESIGN\n``. A design with no placement, no routing and no
geometry PASSES. Steps 1, 12 and 35 are honestly WAIVED because absence is the
only red their gates have.

So the need is exact and it is not for a run's bookkeeping: d2 needs a corpus
of artefacts that EXIST and are WRONG. A real run is a project that produced
something wrong rather than nothing — but the record of that run is not, and
cannot be, that corpus:

  * the record READS NO FILE CONTENT. Not a byte, and not a hash of its own
    making: its module docstring states "No file CONTENT is read: no hashing,
    no open()", and this module measures the emitted record for a content or
    digest field and finds none. A gate that must be driven to a CONTENT red
    cannot be driven by a record of sizes and mtimes.
  * pointing d2 at the run tree instead of the record would put the corpus on
    one machine. Unlike d3 and d7, that could not be repaired by admitting
    only committed trees, because d2's rule is "at least one blocking clause
    reaches a real FAIL" — MORE inputs can only make a cell GREENER. A cell
    that goes green because a directory exists on the campaign host is a
    weakening AND a host-dependence, in the one direction where #527's fix
    does not help.

The honest statement of d2's gap is therefore: *the fixtures it needs are
wrong-content artefacts, they belong in the repository beside the ones already
there (``PNR_BAD``, ``QUARTUS_STUCK_AT``, ``PERC_ESD_FAIL``,
``POST_LAYOUT_NO_SPICE``), and no amount of run bookkeeping substitutes for
writing them.* That is a real backlog item, and it is not this one.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Tuple

import pytest

import step_write_ledger as SWL
from matrix_63x8 import flowref as F

#: (dimension, module basename, the FACT the record does not carry, and the
#: record fields that measure it). One row per refusal; the rows ARE the
#: argument, and the test below is what keeps them true.
#:
#: A field name is a claim about the emitted record: bare means it must be
#: ABSENT (the record does not carry that fact), and a leading ``+`` means it
#: must be PRESENT. Both directions are needed — d1's refusal rests on the
#: emitter publishing its own refusal to map two vocabularies, which is a
#: field that has to BE there — and mixing them silently would make the
#: strongest row of the table the one nobody could read.
REFUSALS: Tuple[Tuple[int, str, str, Tuple[str, ...]], ...] = (
    (
        1, "test_matrix_d1_wiring",
        "d1 asks WHICH PLUGIN PROGRAM the executor dispatches. The record's "
        "only producer vocabulary is EDA BINARY names lifted from "
        "provenance.jsonl (yosys / openroad / klayout / magic / netgen / sta), "
        "and the emitter itself REFUSES to map that onto the flow's "
        "`programs:` / `mcp_tools:` names — it publishes both side by side "
        "under `producer_vocabulary_note` and compares neither. MEASURED on "
        "two real runs: the overlap between the tools provenance recorded and "
        "the 164 plugin programs the flow's steps and gates name is 0. A "
        "record therefore cannot say whether a gate is wired; it can say a "
        "binary ran. Worse, ABSENCE would be read backwards — a conditional "
        "step that legitimately did not run leaves the same trace as an "
        "unwired one.",
        ("+producer_vocabulary_note", "program", "gate_program",
         "plugin_program", "dispatched", "executor"),
    ),
    (
        2, "test_matrix_d2_falsifiable",
        "d2 needs artefacts that EXIST and are WRONG; the record contains no "
        "file content and no digest of its own making (see this module's "
        "docstring). Pointing d2 at the run tree instead would also move its "
        "answer in the GREENER direction — more inputs can only demonstrate "
        "MORE falsifiability — which is the one direction #527's "
        "committed-evidence fix cannot make safe.",
        ("content", "sha256", "digest", "bytes", "text"),
    ),
    (
        4, "test_matrix_d4_criteria_match",
        "d4 asks whether a gate MEASURES what its name and docstring CLAIM. "
        "The record has no notion of a gate at all: no clause, no command, no "
        "criterion, no docstring, no argv. It records files. The one thing it "
        "could contribute — 'the gate's declared artefact was never written' — "
        "is dimension 3's question and dimension 3 already binds it.",
        ("gate", "clause", "criteria", "docstring", "argv"),
    ),
    (
        5, "test_matrix_d5_deps_correct",
        "d5 needs the CONSUMER half of the dependency graph — which step READS "
        "an artefact. The record is one lstat walk: it observes writes and "
        "never reads, records no access time, and hooks nothing "
        "(no fanotify, no inotify, no ptrace). NOTE THE NAME COLLISION, which "
        "is the trap here: the record emits findings labelled 'D5', but its D5 "
        "means `unwitnessed_write` — a DECLARED output that landed inside no "
        "logged tool invocation — which is a question about the producer, not "
        "about `blocks_on`. Wiring on the strength of a matching label would "
        "be measuring something adjacent, which is the disease this campaign "
        "exists to remove.",
        ("atime", "st_atime", "accessed", "read_by", "readers"),
    ),
    (
        6, "test_matrix_d6_skip_discipline",
        "d6 asks whether a skip is CONDITIONED on a runtime fact and whether "
        "it is REPORTED at a non-PASS tier. Both are properties of a verdict, "
        "and the record carries no verdict, no exit code, no tier and no "
        "status — by design: it never fails a run and never grades one. 'The "
        "step wrote nothing' is not 'the step skipped' either; a conditional "
        "step that correctly did not apply leaves exactly that trace, and "
        "conflating the two would manufacture skips out of correct behaviour.",
        ("verdict", "exit_code", "tier", "status", "vacuous", "skipped"),
    ),
)

#: Dimension modules that DO read the record, with the seam each one uses.
#: Pinned so a refusal above cannot be quietly converted into a wiring, and so
#: a wiring cannot be quietly removed.
BOUND: Dict[int, str] = {
    3: "flow_compliance_check / write_ledger — the ledger may only SUBTRACT evidence",
    7: "matrix_d7_write_record — W2's second producer oracle; may only ADD paths",
}

_RECORD_TOKENS = ("write_ledger", "written.json", "matrix_d7_write_record")


# ──────────────────────────────────────────────────────────────────────
# One REAL record, built by the REAL emitter, over a probe tree
# ──────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def record() -> Dict[str, Any]:
    """A record ``step_write_ledger`` produced, not a fixture shaped like one.

    Every refusal below is a claim about what the record DOES NOT CONTAIN, so
    it has to be measured against the emitter's actual output. A hand-written
    stand-in would keep passing after the emitter grew the very field whose
    absence is the argument.

    The probe is deliberately tiny (< 20 files): ``mtime_fidelity`` calls a
    tree flattened at ``n >= 20`` with a dominant mtime second, and the
    emitter then withholds its time-derived halves — including the residual
    this campaign's dimension 7 binding reads.
    """
    tmp = Path(tempfile.mkdtemp(prefix="d_scope_"))
    try:
        assert SWL.mark_run_start(tmp)
        # The kernel stamps an inode's mtime from a COARSE clock that lags
        # time.time() by up to a timer tick, so a file written immediately
        # after t0 can read as BEFORE it and fall out of the run window.
        time.sleep(0.05)
        for rel, body in (
            ("phase2/stage2/synth/netlist.v", "module m; endmodule\n"),
            ("phase3/stage3/pnr/openroad.log", "[INFO] done\n"),
            ("reports/phase3/undeclared_probe.json", '{"x": 1}\n'),
        ):
            p = tmp / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body)
        (tmp / "provenance.jsonl").write_text(json.dumps({
            "timestamp": "2026-08-06T00:00:00Z", "tool": "openroad",
            "argv": ["openroad", "-exit"], "inputs": {}, "outputs": {},
            "exit_code": 0, "duration_s": 1.0,
        }) + "\n")
        doc = SWL.build(tmp)
        assert doc["schema"] == SWL.SCHEMA
        assert doc["declaration"]["ok"], doc["declaration"]
        assert doc["counts"]["recorded"] >= 4, doc["counts"]
        yield doc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


#: Sub-objects of the record whose KEYS are DATA, not schema. Skipped by the
#: key walk, and this is load-bearing rather than tidy: the keys of
#: ``written_never_declared_by_dir`` are DIRECTORY NAMES out of the run tree,
#: so a probe (or a real run) that happens to contain a directory called
#: ``gate`` or ``content`` would otherwise make a refusal go red for a reason
#: that has nothing to do with the record's schema. A test whose answer
#: depends on the shape of a tree is the disease this campaign removes.
_DATA_KEYED = ("written_never_declared_by_dir", "by_kind")


def _all_keys(node: Any, acc: set, skip: Tuple[str, ...] = _DATA_KEYED) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            acc.add(str(k))
            if str(k) in skip:
                continue
            _all_keys(v, acc, skip)
    elif isinstance(node, list):
        for v in node:
            _all_keys(v, acc, skip)


@pytest.fixture(scope="module")
def record_keys(record) -> frozenset:
    acc: set = set()
    _all_keys(record, acc)
    return frozenset(acc)


# ──────────────────────────────────────────────────────────────────────
# The refusals
# ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "dim,module,why,absent_fields",
    REFUSALS,
    ids=[f"d{d}" for d, _m, _w, _f in REFUSALS],
)
def test_this_dimension_may_not_read_the_write_record(
        dim, module, why, absent_fields, record, record_keys, record_property):
    """The refusal, and the two things that would make it stop being one.

    (1) THE PREMISE. Each row names a fact the record does not carry, and the
        field names whose absence in a REAL emitted record is the measurement.
        The day ``step_write_ledger`` grows one of them, this reddens and the
        decision is re-taken with the new evidence rather than inherited.

        ``producer_vocabulary_note`` is the one row where the marker must be
        PRESENT: d1's refusal rests on the emitter REFUSING to map EDA binary
        names onto plugin program names, and that refusal is published in
        every step row. If the note disappears, either the mapping arrived (d1
        must be re-decided) or the honesty did (worse).

    (2) THE PIN. The named dimension module still does not reference the
        record. This is a tripwire, not a ban: a future wiring is welcome and
        must move the row into :data:`BOUND` in the same change, which is
        where the argument gets re-opened instead of skipped.
    """
    record_property("write_record_refusal", f"d{dim}: {why}")

    must_be_absent = [f for f in absent_fields if not f.startswith("+")]
    must_be_present = [f[1:] for f in absent_fields if f.startswith("+")]

    arrived = sorted(f for f in must_be_absent if f in record_keys)
    assert not arrived, (
        f"the write record now carries {arrived} — the premise of "
        f"dimension {dim}'s refusal has changed.\n\n"
        f"THE REFUSAL WAS: {why}\n\n"
        f"Re-decide it against the record as it is NOW: either wire the "
        f"dimension (and move d{dim} from REFUSALS into BOUND, with the seam "
        f"named and a bidirectional control), or rewrite the row so it states "
        f"the reason that is still true. Deleting the field name from the row "
        f"would keep the test green and the argument false.")

    gone = sorted(f for f in must_be_present if f not in record_keys)
    assert not gone, (
        f"the write record no longer publishes {gone}, and dimension {dim}'s "
        f"refusal rests on it.\n\n"
        f"THE REFUSAL WAS: {why}\n\n"
        f"For `producer_vocabulary_note` specifically: it is the emitter's own "
        f"refusal to compare `declared_tools` (plugin program / MCP names) "
        f"with `observed_producers` (EDA binary names out of "
        f"provenance.jsonl). If it is gone, either a mapping between the two "
        f"vocabularies now exists — in which case d{dim} must be re-decided "
        f"against it — or the emitter stopped disclosing that it has none, "
        f"which is worse. Do not delete this assertion to make the suite "
        f"green.")

    src = (F.PROGRAMS_DIR / "tests" / f"{module}.py").read_text(
        encoding="utf-8", errors="replace")
    hits = sorted(t for t in _RECORD_TOKENS if t in src)
    assert not hits, (
        f"{module}.py now references the write record ({hits}), but d{dim} is "
        f"registered here as NOT WIRED.\n\n"
        f"THE REASON IT WAS NOT: {why}\n\n"
        f"If that reason has been answered, say how: move d{dim} into BOUND "
        f"naming the seam, and ship the wiring with a control that FAILS "
        f"against the pre-change file. An unargued wiring is worse than none — "
        f"it makes a cell's answer depend on a run without anybody having "
        f"shown the run can answer it.")


def test_the_bound_dimensions_really_are_bound():
    """The other direction: a WIRED dimension that stopped reading the record.

    Without this, the table above degrades into a list of five refusals and
    two claims. A binding that is silently reverted — or an import deleted in
    a refactor — would leave ``BOUND`` asserting something no longer true,
    which is the same rot the refusals are protected from.
    """
    for dim, seam in sorted(BOUND.items()):
        module = {3: "test_matrix_d3_outputs_produced",
                  7: "test_matrix_d7_outputs_list_complete"}[dim]
        src = (F.PROGRAMS_DIR / "tests" / f"{module}.py").read_text(
            encoding="utf-8", errors="replace")
        assert any(t in src for t in _RECORD_TOKENS), (
            f"d{dim} is registered as bound to the write record via {seam}, "
            f"and {module}.py no longer references it at all. Either the "
            f"binding was reverted — in which case say so and move the row "
            f"into REFUSALS with the reason — or it moved somewhere this "
            f"check cannot see, in which case point the check at it.")


def test_every_dimension_has_exactly_one_answer():
    """Six dimensions, six decisions, no dimension in two states and none absent.

    ``d8`` is the one dimension with no row of its own: it reads the record
    only through ``flow_compliance_check``'s verdict, which is the consumer it
    audits rather than a seam of its own, so it is neither a refusal nor a
    binding here. Stated rather than left to be noticed as a gap in the table.
    """
    refused = {d for d, _m, _w, _f in REFUSALS}
    assert refused & set(BOUND) == set(), (
        f"dimension(s) {sorted(refused & set(BOUND))} are registered as both "
        f"refused and bound")
    assert refused | set(BOUND) == {1, 2, 3, 4, 5, 6, 7}, (
        f"every dimension whose seam is decidable must carry exactly one "
        f"answer; missing {sorted({1, 2, 3, 4, 5, 6, 7} - (refused | set(BOUND)))}")
    for dim, _module, why, fields in REFUSALS:
        assert len(why) > 200, f"d{dim}'s reason is too thin to be a record"
        assert fields, f"d{dim}'s refusal rests on no measurable premise"
