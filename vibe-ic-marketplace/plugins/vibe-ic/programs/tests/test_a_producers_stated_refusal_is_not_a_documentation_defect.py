"""A producer's stated refusal is an upstream fact, not negligence by the writer.

MEASURED on spm run22, READ-ONLY. Step 37.5ic published:

    [FAIL] release_docs_check — RELEASE_DOCUMENTATION_ABSENT (spm): the run signs
    off layout `spm` under phase3/stage4/gds and
    phase3/stage4/documentation/ic/spm carries no release documentation.

Every word of that is true. And in the same run tree, from the run's own
orchestrator record:

    ic_release_docs_gen   status NOT_MEASURED   duration 2.26 s   producer_rc 1
      flow_step 37.5ic    output_files []
      "NOT RELEASABLE — no product documents written. 1 release(s) examined.;
       the artefacts this run signed off carry no substance (2 refusal(s)):
         STA_NO_SLACK  [sta]   reports/phase3/sta/post_route_summary.json
         POWER_NO_TOTAL [power] reports/phase3/power.json
       A release document for a run that did not pass is worse than no document."

I verified both of the producer's reasons myself rather than repeating its word:
`post_route_summary.json` is 1128 bytes with keys [findings, passed, program,
subject, summary] and carries NO numeric slack field anywhere; `power.json` is 152
bytes with keys [analysis_mode, evidence, source, tool, verdict] and carries NO
numeric power or total field. The producer ran, and it was RIGHT to refuse.

So the documents are OWED (step 37.5ic declares PRELIMINARY_DATASHEET.md and
RELEASE_NOTES.md under phase3/stage4/documentation/ic/*/ and names
`ic_release_docs_gen` under `programs:`), the producer exists and ran, and the only
thing wrong was the CLASSIFICATION: a refusal that survived solely as prose, in a
log and an orchestrator report this gate cannot read, got re-described downstream
as "nobody wrote them".

R-0915-146 — AND THE FIRST CUT OF THIS WAS WRONG IN THE WAY I KNOW BEST. It granted
BLOCKED_BY_UPSTREAM on the RECORD'S SHAPE: a `program`, `verdict: REFUSED`, one or
more reason strings. That is exactly what R-0915-136 names — a program's CLAIM about
a state is not the state — applied to my own change. Three confirmed consequences:

  * STALE: run N refuses for STA_NO_SLACK / POWER_NO_TOTAL, the STA and power
    records are then fixed WITHOUT the producer re-running (the audit never runs
    `ic_release_docs_gen`; it is not in `_PRE_AUDIT_PRODUCERS`), and a re-audit still
    answers NOT_MEASURED/BLOCKED — blaming an STA that is fine, where the step owes
    its documents and FAIL is correct. A hand-written record works identically; the
    record was bound to no file, no digest, no tree_sha.
  * A CRASH READ AS BLOCKAGE: `_clear_refusal` ran only on the success tail, so any
    exception left the previous run's record in place and rc 1 read as "declined".
  * A FOREIGN RELEASE: a leftover record for `spm` excused an absent `spm_v2`.

So the gate now RE-DERIVES the blockage per release, on the current tree, with the
producer's OWN predicates (`_ic_release_artefacts.audit(project, release).errors`,
`tapeout_docs_gen.release_blockers(load_metrics(...))`) — both pure readers, both
imported rather than reimplemented. Every failing release must be blocked NOW, so a
sibling's blockage cannot excuse another's absence. The record survives as a POINTER
in the disclosure and is never the evidence, which the report says in as many words
(`producer_refusal_is_evidence: false`). And the producer clears any stale record
BEFORE anything can raise, so a crash leaves no account of a refusal that did not
happen.

WHAT THIS CHANGE DOES, AND WHAT IT REFUSES TO DO.
  * the producer records its refusal as DATA beside the prose it already prints
    (`reports/phase3/release_docs_producer_refusal.json`), from the same reasons,
    so the record can never say something the log does not;
  * a later SUCCESS clears that record, because a stale refusal would tell this
    gate for ever that the producer had declined;
  * the gate reads it and publishes NOT_MEASURED with
    `reason_class = BLOCKED_BY_UPSTREAM` — a class `_flow_reason_taxonomy` holds
    in INCOMPLETE and NOT in SKIP_ELIGIBLE, so the step stays OWED and cannot be
    read as satisfied — at rc 2, the non-verdict exit, NOT the VACUOUS_PASS
    announcement that the audit promotes to a pass tier;
  * NOTHING becomes a pass, and THE FAIL ARM IS KEPT: an absent document set with
    no refusal record is still FAIL/RELEASE_DOCUMENTATION_ABSENT, which is the
    defect this gate was written for. Documents that exist and fail on their
    content are still FAIL.

The two upstream records are the real work and they are NOT fixed here: a
post-route STA summary with no slack number and a power record with no power
number belong to whoever owns those two artefacts. Writing release documents over
them is precisely the cheat the producer refuses.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN / "programs"
sys.path.insert(0, str(PROGRAMS))

import _flow_reason_taxonomy as _T                            # noqa: E402
import release_docs_check as CHK                              # noqa: E402




def _refusal(project: Path, *, program: str = "ic_release_docs_gen",
             verdict: str = "REFUSED", reasons=("STA_NO_SLACK [sta] ...",),
             blockers=()) -> Path:
    out = project / CHK.PRODUCER_REFUSAL_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "program": program, "verdict": verdict,
        "releases_examined": 1, "releases": ["zzdie"],
        "substance_refusals": list(reasons),
        "release_blockers": list(blockers),
        "documents_written": [],
        "why": "a release document for a run that did not pass is worse than none",
    }) + "\n")
    return out


# ── the two paths the gate now distinguishes ───────────────────────────────





def test_the_class_keeps_the_step_owed(tmp_path):
    """The load-bearing property of the class chosen: BLOCKED_BY_UPSTREAM is in
    INCOMPLETE and NOT in SKIP_ELIGIBLE, so nothing reads the step as satisfied.
    If this ever flips, a blocked release-docs step becomes a silent skip."""
    assert _T.BLOCKED_BY_UPSTREAM in _T.INCOMPLETE
    assert _T.BLOCKED_BY_UPSTREAM not in _T.SKIP_ELIGIBLE




# ── the record is read strictly ────────────────────────────────────────────

def test_a_refusal_naming_no_reason_is_not_evidence(tmp_path):
    _refusal(tmp_path, reasons=(), blockers=())
    assert CHK.producer_refusal(tmp_path) is None


def test_another_programs_document_is_not_this_producers_refusal(tmp_path):
    _refusal(tmp_path, program="somebody_else_gen")
    assert CHK.producer_refusal(tmp_path) is None


def test_a_record_that_does_not_say_refused_is_not_a_refusal(tmp_path):
    _refusal(tmp_path, verdict="PASS")
    assert CHK.producer_refusal(tmp_path) is None


def test_an_unreadable_record_is_not_a_refusal(tmp_path):
    out = tmp_path / CHK.PRODUCER_REFUSAL_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("{not json\n")
    assert CHK.producer_refusal(tmp_path) is None


# ── the producer's half ────────────────────────────────────────────────────









# ── R-0915-146: the blockage is RE-DERIVED, the record is only a pointer ────

#: A GDS whose record walk finds real geometry: length-4 BOUNDARY records, the same
#: walk `analog_a5_layout_check._gds_geometry_count` performs (2-byte big-endian
#: length, record type at offset 2). Synthesised rather than copied from a run,
#: because a fixture that needs a real 100 MB layout is a fixture nobody can run.
_GDS_WITH_GEOMETRY = b"\x00\x04\x08\x00" * 64


#: A metrics record whose every sign-off property PASSES its own predicate. Built
#: from `tapeout_docs_gen.MANUFACTURABILITY + ELECTRICAL` at runtime rather than
#: typed, so a new property added there cannot leave this fixture silently
#: "healthy" while the shipped predicate has something new to say about it.
