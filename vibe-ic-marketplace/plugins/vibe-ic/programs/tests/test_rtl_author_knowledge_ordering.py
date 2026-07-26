"""step_rtl_gen must not say "MANDATORY before authoring" to an author that has
already authored.

THE DEFECT
----------
Every authoring handoff in ``step_rtl_gen`` stages the captured-knowledge
digests and then emits, in the same breath::

    MANDATORY before authoring: open <lessons.md> ...
    DUAL-TRACK (optional second opinion): <ic_expert_db.md> ...

On any run where RTL is already on disk, that ordering did not happen and
cannot now happen: the digests were written AFTER the file they were meant to
shape. Nothing in the StepResult said so — not the prose, and not the extras —
so a consumer had no way to tell an informed authoring from an uninformed one.

MEASURED on `spm x sky130A` (v1.6.4, campaign_v164), the run this came from::

    03:10:51  phase2/stage1/rtl/spm.v        <- RTL authored
    03:12:51  phase2/stage1/lessons.md       <- staged, 120 s LATER
    03:12:51  phase2/stage1/ic_expert_db.md

reproduced on a controlled re-run of the same project (RTL 15:00:55, digests
15:00:59). The `ic_expert_db.md` staged there carried the rule naming that
design's exact anti-pattern — "for a serial-parallel multiplier do NOT author
the accumulate-then-shift form ... use the SYSTOLIC carry-save array" — and the
RTL on disk WAS that anti-pattern. Applying the rule the digest already
contained moved the SS sign-off corner from -6.55 ns to +3.68 ns post-route.
The knowledge was present, correct, matched and staged. It was simply late, and
nothing noticed.

This module drives the REAL lesson corpus, the REAL IC Expert DB and the REAL
path layout — no fixtures — and carries PREMISE tests so an empty corpus fails
loudly instead of making everything below it vacuously green.

BIDIRECTIONAL. The GUARD tests are the ones that earn their keep: they fail if
the fix is "widened" to fire whenever RTL exists, which would put a RE-AUDIT
banner on every legitimate re-run and train authors to ignore it.
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import design_one_shot_runner as R  # noqa: E402

# A real design tree of the shape this defect was measured on. Only its SPEC
# TEXT is used (to make the IC Expert DB matcher fire on a real design class);
# no netlist, report or verdict is read, so the tests cannot inherit a result.
_SPEC_SRC = Path("/home/reyerchu/campaign_v164/spm/converge_1.6.4_sky130A")

_MANDATORY = "MANDATORY before authoring"
_REAUDIT = "RE-AUDIT REQUIRED"


def _spec_available() -> bool:
    return (_SPEC_SRC / "phase1" / "input_doc").is_dir()


requires_spec = pytest.mark.skipif(
    not _spec_available(),
    reason=f"reference spec tree not present at {_SPEC_SRC}")


def _project(tmp_path: Path, *, rtl: str | None = None,
             rtl_age_s: float = 600.0) -> Path:
    """A project tree carrying REAL spec prose, optionally with RTL already on
    disk and stamped `rtl_age_s` seconds in the past (negative = in the
    future, i.e. authored AFTER the digests)."""
    proj = tmp_path / "proj"
    for sub in ("input_doc", "generated_docs"):
        src = _SPEC_SRC / "phase1" / sub
        if src.is_dir():
            shutil.copytree(src, proj / "phase1" / sub)
    if rtl is not None:
        rtl_dir = R._pl.rtl_dir(proj)
        rtl_dir.mkdir(parents=True, exist_ok=True)
        f = rtl_dir / "top.v"
        f.write_text(rtl)
        stamp = time.time() - rtl_age_s
        os.utime(f, (stamp, stamp))
    return proj


# --------------------------------------------------------------------------
# PREMISE — if either knowledge track goes empty, every test below is vacuous.
# --------------------------------------------------------------------------

@requires_spec
def test_premise_lesson_corpus_is_not_empty(tmp_path):
    _, extras = R._stage_author_knowledge_digests(_project(tmp_path))
    assert extras.get("lessons_count", 0) > 0, (
        "the real lesson corpus rendered ZERO sections — every assertion in "
        "this module about digest wording would pass vacuously")


@requires_spec
def test_premise_expert_db_matches_this_design_class(tmp_path):
    _, extras = R._stage_author_knowledge_digests(_project(tmp_path))
    assert extras.get("ic_expert_db_count", 0) > 0, (
        "the real IC Expert DB matched ZERO entries for this spec — the "
        "second track this fix is mostly about would not be exercised")


# --------------------------------------------------------------------------
# DEFECT — these FAIL on the unfixed runner (it says "before authoring"
# unconditionally and reports nothing machine-readable).
# --------------------------------------------------------------------------

@requires_spec
def test_preexisting_rtl_is_not_told_to_read_it_before_authoring(tmp_path):
    hint, _ = R._stage_author_knowledge_digests(
        _project(tmp_path, rtl="module top(); endmodule\n"))
    assert _MANDATORY not in hint, (
        "RTL already existed when the digests were staged, yet the handoff "
        "still instructs the author to read them BEFORE authoring — an order "
        "that already failed to happen")
    assert _REAUDIT in hint


@requires_spec
def test_preexisting_rtl_sets_a_machine_readable_flag(tmp_path):
    _, extras = R._stage_author_knowledge_digests(
        _project(tmp_path, rtl="module top(); endmodule\n"))
    assert extras.get("rtl_predates_authoring_knowledge") is True, (
        "the fact lives only in prose; a gate or later step cannot act on it")
    ev = extras.get("rtl_predating_evidence") or {}
    assert ev.get("count") == 1
    assert ev.get("rtl_files") == ["top.v"]
    assert ev.get("lag_s", 0) > 0, "lag must be positive: digest after RTL"
    assert ev.get("rtl_mtime_iso") and ev.get("digest_mtime_iso")


@requires_spec
def test_reaudit_names_the_design_class_track_too(tmp_path):
    """The generic corpus was already MANDATORY; the design-class track was
    labelled an *optional* second opinion. On this path it is the track that
    carries the architecture/timing craft, so the re-audit must name it."""
    hint, extras = R._stage_author_knowledge_digests(
        _project(tmp_path, rtl="module top(); endmodule\n"))
    db = extras.get("ic_expert_db_digest")
    assert db, "premise: expert-DB digest was staged"
    assert db in hint, "re-audit directive does not name the expert-DB digest"
    assert "optional second opinion" not in hint, (
        "the design-class track is still offered as optional on a path where "
        "the existing RTL has provably never been checked against it")


@requires_spec
def test_all_preexisting_rtl_files_are_reported(tmp_path):
    proj = _project(tmp_path, rtl="module top(); endmodule\n")
    extra = R._pl.rtl_dir(proj) / "sub.sv"
    extra.write_text("module sub(); endmodule\n")
    stamp = time.time() - 600
    os.utime(extra, (stamp, stamp))
    _, extras = R._stage_author_knowledge_digests(proj)
    ev = extras.get("rtl_predating_evidence") or {}
    assert ev.get("count") == 2
    assert sorted(ev.get("rtl_files", [])) == ["sub.sv", "top.v"]


# --------------------------------------------------------------------------
# GUARD — these FAIL if the fix is widened into "RTL exists -> always shout".
# --------------------------------------------------------------------------

@requires_spec
def test_fresh_project_keeps_the_before_authoring_wording(tmp_path):
    hint, extras = R._stage_author_knowledge_digests(_project(tmp_path))
    assert _MANDATORY in hint, (
        "on a genuine author-from-scratch handoff 'before authoring' is "
        "exactly right and must survive")
    assert _REAUDIT not in hint
    assert "rtl_predates_authoring_knowledge" not in extras


@requires_spec
def test_rtl_authored_after_the_digests_does_not_fire(tmp_path):
    """The load-bearing guard. The claim is about ORDER, not existence: RTL
    written AFTER the knowledge was staged is exactly the outcome we want, and
    must not be flagged. A fix that keyed on "rtl/ is non-empty" would fail
    here — and would put a RE-AUDIT banner on every correct re-run."""
    hint, extras = R._stage_author_knowledge_digests(
        _project(tmp_path, rtl="module top(); endmodule\n",
                 rtl_age_s=-600.0))
    assert _REAUDIT not in hint, (
        "RTL postdates the digests — it could have been authored from them; "
        "flagging it teaches authors to ignore the banner")
    assert "rtl_predates_authoring_knowledge" not in extras
    assert _MANDATORY in hint


# --------------------------------------------------------------------------
# CONTRACT — decoration must never break the WAIVE it decorates.
# --------------------------------------------------------------------------

def test_predating_probe_is_best_effort_and_never_raises(tmp_path):
    assert R._rtl_predating_digests(tmp_path / "nope", ["/nonexistent"]) is None
    assert R._rtl_predating_digests(tmp_path, []) is None


@requires_spec
def test_staging_still_returns_the_digest_extras_when_flagged(tmp_path):
    """The re-audit path must not cost the author the paths themselves."""
    _, extras = R._stage_author_knowledge_digests(
        _project(tmp_path, rtl="module top(); endmodule\n"))
    assert extras.get("lessons_digest")
    assert extras.get("lessons_count", 0) > 0
    assert extras.get("ic_expert_db_digest")
