#!/usr/bin/env python3
"""Step 36 (tapeout checklist) — the GDS slot cited a file nothing verified.

Deferred tail of the 2026-07-27 `signoff_audit` sign-off-first work (bucket
`signoff_adj`, deferred item 3). That change ranked the NETLIST and TIMING
slots and left the GDS slot on the original unranked
`_has_files(...)[0]` — an arbitrary, filesystem-order `rglob` pick.

MEASURED on the completed spm x ihp-sg13g2 run
(~/campaign_pr427/spm/converge_ihp-sg13g2, plugin @ origin/main v1.7.61):

    $ python3 programs/signoff_audit.py . --mode tapeout
    TAPEOUT_GDS_EXISTS | GDS file found: spm.gds
                       | steps/37_gdsii_output_only_if_step_31_pv_fully_clean/spm.gds

Four GDS files existed in that project:

    phase3/stage3/pnr/spm.gds                    881530 B   real file
    phase3/stage4/gds/spm.gds                    881530 B   real file  <-- declared
    phase3/stage4/foundry_handoff/spm.gds       1014178 B   real file, STALE
    steps/37_gdsii_.../spm.gds                        ->    symlink mirror

`phase3/stage4/gds/*.gds` is what the flow DECLARES as step 37's stream-out
artefact and is the exact path step 37's gate hands to `gds_size_check`,
`gds_substance_check` and `provenance_check`.

--------------------------------------------------------------------------
REVIEW FOLLOW-UP (2026-07-27) — ranking narrowed the ENTRANCE, not the EXIT
--------------------------------------------------------------------------
Ranking decided WHICH file the slot cites. It never decided WHETHER the slot
may be credited: `_gds_rank` returns 0/1/2/3 for every non-draft candidate and
the credit condition was `rank != _PRESIGNOFF_RANK`, so ANY `.gds` ANYWHERE
still certified Step 36. Re-measured, the pre-review tree and the unfixed tree
gave IDENTICAL credit decisions on all five of these — every one CREDITED:

    1. only a `steps/` mirror                       (rank 2)
    2. only a stale `foundry_handoff` copy          (rank 1)
    3. the declared path present but ZERO BYTES     (rank 0, no substance)
    4. a stray `.gds` at the project root           (rank 2)
    5. only the foundry-supplied `scribe_line_layout.gds` (rank 3 — an INPUT
       this file's own comment says "must never outrank a design GDS", yet as
       the sole candidate it certified the tape-out GDS slot anyway)

FIX, in three parts:
  (1) `_gds_rank` + `_rank_signoff_first` — declared stream-out artefact first,
      other phase3 copies next, mirrors/ad-hoc copies after that, and the
      FOUNDRY-SUPPLIED scribe-line frame last (it is an input, not the design);
  (2) refuse to credit the slot when EVERY candidate declares itself a
      pre-sign-off intermediate, disclosing what it refused;
  (3) credit the slot ONLY from `_CREDITABLE_GDS_RANK` (the declared
      stream-out) and only when that file carries GDSII substance — non-empty
      and beginning with a GDSII HEADER record. Every other outcome gets its
      own NON-crediting rule name, so the checklist says which of the five
      shapes it saw instead of certifying it.

Nothing is loosened: the slot is still required, ranking still only REORDERS,
and (2)+(3) add ways to FAIL, never a way to pass.

WHAT THE TRACKED CORPUS PROVES, stated so nobody over-reads it: all nine
tracked `.gds` in this repo sit at `phase3/stage4/gds/*.gds` (rank 0), are
730 KB-2.5 MB, and every one begins with the GDSII HEADER record `00 06 00 02`.
So the corpus proves NON-REGRESSION (0 credit changes, 0 citation changes) and
proves NOTHING about the five refusals — those are fixture-only, below. The
reference run they were measured on is also pure DIGITAL standard-cell: it
contains no analog (A1-A9) or mixed-signal (M1-M4) artefacts, so the A/M
candidates that also match the tape-out GDS glob are covered by CODE-READING
of the flow declaration plus a SYNTHETIC fixture, never by that run.

chip-AGNOSTIC: synthetic project trees only.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import signoff_audit as sa  # noqa: E402
import _gdsii  # noqa: E402
import _si_signoff_fixture  # noqa: E402

_DECLARED = "phase3/stage4/gds/top.gds"


# ---------------------------------------------------------------------------
# fixture helpers
# ---------------------------------------------------------------------------
def _write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _gds(p: Path) -> Path:
    """A REAL minimal GDSII stream. Every GDS fixture here is one, so no test
    below can pass merely because the gate accepted a text placeholder."""
    return _gdsii.write_gdsii(p)


_LVS_MATCH = """\
Subcircuit summary:
Circuit 1: top                          |Circuit 2: top
Netlists match uniquely.
Final result: Circuits match uniquely.
"""


def _other_four_slots(proj: Path) -> Path:
    """netlist + STA + clean DRC + a genuine LVS match, but NO GDS — so each
    test below controls the GDS candidate set completely."""
    _write(proj / "phase3" / "stage3" / "pnr" / "top_pnr.v",
           "module top(); endmodule\n")
    _write(proj / "phase3" / "stage3" / "sta" / "post_route_timing.rpt",
           "slack (MET) 0.10\n")
    _write(proj / "drc_signoff.rpt", "Total violations: 0\n")
    _write(proj / "reports" / "phase3" / "lvs.rpt", _LVS_MATCH)
    # 2026-07-28: tape-out mode gained an SI (crosstalk-delay) blocking
    # condition. This fixture is about the GDS slot, so it carries a PROVED
    # SI verdict — without one every case here would collapse onto the
    # SI refusal and stop discriminating what it exists to pin.
    _si_signoff_fixture.write_proved_si_report(proj)
    return proj


def _root_decoy(proj: Path) -> Path:
    """An ad-hoc copy at the PROJECT ROOT.

    `Path.rglob` yields the top directory's own entries before it descends, so
    the pre-fix `_has_files(...)[0]` pick is this file DETERMINISTICALLY —
    which is what makes every ranking assertion below a real discriminator
    rather than a bet on directory-scan order. Post-fix it ranks below every
    in-`phase3/` candidate and can never credit the slot.
    """
    return _gds(proj / "top_adhoc_copy.gds")


def _finding(result, rule):
    for f in result.findings:
        if f.rule == rule:
            return f
    return None


def _gds_findings(result):
    return [f.rule for f in result.findings if f.rule.startswith("TAPEOUT_GDS")]


def _cited(result, proj: Path, rule: str = "TAPEOUT_GDS_EXISTS") -> str:
    f = _finding(result, rule)
    assert f is not None, f"{rule} not among {[x.rule for x in result.findings]}"
    return Path(f.file).relative_to(proj).as_posix()


# ===========================================================================
# CREDIT — the five shapes that certified Step 36 with no verified stream-out
#
# Each is the whole GDS candidate set of its project, exactly as measured.
# Every one of them CREDITED on the pre-review tree; none may credit now.
# ===========================================================================
def test_only_a_steps_mirror_does_not_credit_the_slot(tmp_path):
    """Shape 1. The `steps/` tree mirrors phase3 artefacts; a mirror of a file
    that was never streamed out is not a stream-out."""
    _other_four_slots(tmp_path)
    _gds(tmp_path / "steps" / "37_gdsii_output" / "top.gds")

    r = sa._check_tapeout(tmp_path)
    assert r.summary["evidence"]["gds"] is False
    assert r.passed is False
    f = _finding(r, "TAPEOUT_GDS_NOT_DECLARED_STREAMOUT")
    assert f is not None and f.severity == "ERROR"
    assert _cited(r, tmp_path, "TAPEOUT_GDS_NOT_DECLARED_STREAMOUT") == \
        "steps/37_gdsii_output/top.gds"
    assert sa.main([str(tmp_path), "--mode", "tapeout"]) == 1


def test_only_a_stale_foundry_handoff_copy_does_not_credit_the_slot(tmp_path):
    """Shape 2. On the real run the hand-off copy was a DIFFERENT, older and
    larger file than the declared stream-out — the checklist could name it and
    certify a layout nobody verified."""
    _other_four_slots(tmp_path)
    _gds(tmp_path / "phase3" / "stage4" / "foundry_handoff" / "top.gds")

    r = sa._check_tapeout(tmp_path)
    assert r.summary["evidence"]["gds"] is False
    assert _finding(r, "TAPEOUT_GDS_NOT_DECLARED_STREAMOUT") is not None
    assert sa.main([str(tmp_path), "--mode", "tapeout"]) == 1


def test_a_zero_byte_declared_streamout_does_not_credit_the_slot(tmp_path):
    """Shape 3. The declared path is populated and the file is EMPTY. Its own
    named rule, because the repair differs from 'stream out Step 37 at all'."""
    _other_four_slots(tmp_path)
    p = tmp_path / _DECLARED
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")

    r = sa._check_tapeout(tmp_path)
    assert r.summary["evidence"]["gds"] is False
    f = _finding(r, "TAPEOUT_GDS_EMPTY")
    assert f is not None and f.severity == "ERROR"
    assert _cited(r, tmp_path, "TAPEOUT_GDS_EMPTY") == _DECLARED
    assert sa.main([str(tmp_path), "--mode", "tapeout"]) == 1


def test_only_a_root_level_adhoc_copy_does_not_credit_the_slot(tmp_path):
    """Shape 4. A stray `.gds` beside the project's README is not a tape-out."""
    _other_four_slots(tmp_path)
    _root_decoy(tmp_path)

    r = sa._check_tapeout(tmp_path)
    assert r.summary["evidence"]["gds"] is False
    assert _cited(r, tmp_path, "TAPEOUT_GDS_NOT_DECLARED_STREAMOUT") == \
        "top_adhoc_copy.gds"
    assert sa.main([str(tmp_path), "--mode", "tapeout"]) == 1


def test_only_the_foundry_supplied_frame_does_not_credit_the_slot(tmp_path):
    """Shape 5, the sharpest one. `scribe_line_layout.gds` is the
    FOUNDRY-SUPPLIED PCM / alignment frame — an INPUT, which `_gds_rank` itself
    ranks last precisely because it "must never outrank a design GDS". As the
    only candidate it nevertheless certified the tape-out GDS slot, because
    rank 3 != `_PRESIGNOFF_RANK`. Rank 3 may never credit, alone or otherwise.
    """
    _other_four_slots(tmp_path)
    _gds(tmp_path / "phase3" / "stage4" / "foundry_handoff"
         / "scribe_line_layout.gds")

    r = sa._check_tapeout(tmp_path)
    assert r.summary["evidence"]["gds"] is False
    f = _finding(r, "TAPEOUT_GDS_NOT_DECLARED_STREAMOUT")
    assert f is not None
    assert "FOUNDRY-SUPPLIED" in f.message      # says WHY it refused
    assert sa.main([str(tmp_path), "--mode", "tapeout"]) == 1


def test_a_placeholder_at_the_declared_path_does_not_credit_the_slot(tmp_path):
    """A few bytes of ASCII at `phase3/stage4/gds/top.gds` is the same defect
    as zero bytes one byte further in: the checklist would certify a LAYOUT it
    has no evidence exists. A GDSII stream's first record is HEADER."""
    _other_four_slots(tmp_path)
    _write(tmp_path / _DECLARED, "GDSII-signoff")

    r = sa._check_tapeout(tmp_path)
    assert r.summary["evidence"]["gds"] is False
    f = _finding(r, "TAPEOUT_GDS_NOT_A_STREAM")
    assert f is not None and f.severity == "ERROR"
    assert sa.main([str(tmp_path), "--mode", "tapeout"]) == 1


def test_a_dangling_mirror_at_the_declared_path_does_not_credit_the_slot(
        tmp_path):
    """The `steps/` tree mirrors through symlinks and a project can be moved.
    A symlink whose target is gone has no substance and must not certify."""
    _other_four_slots(tmp_path)
    link = tmp_path / _DECLARED
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(tmp_path / "never_streamed_out.gds")

    r = sa._check_tapeout(tmp_path)
    assert r.summary["evidence"]["gds"] is False
    assert _finding(r, "TAPEOUT_GDS_EMPTY") is not None


def test_every_refusal_is_named_and_none_of_them_is_the_credit_rule(tmp_path):
    """Cross-cutting: the slot never emits the INFO credit rule together with
    a refusal, so a reader (or a downstream parser) can never see both."""
    _other_four_slots(tmp_path)
    _root_decoy(tmp_path)
    r = sa._check_tapeout(tmp_path)
    rules = _gds_findings(r)
    assert rules == ["TAPEOUT_GDS_NOT_DECLARED_STREAMOUT"], rules


# ===========================================================================
# RANKING — which artefact the slot NAMES, credited or refused
# ===========================================================================
def test_declared_streamout_gds_outranks_an_adhoc_root_copy(tmp_path):
    _other_four_slots(tmp_path)
    _root_decoy(tmp_path)
    _gds(tmp_path / _DECLARED)

    r = sa._check_tapeout(tmp_path)
    assert _cited(r, tmp_path) == _DECLARED
    assert r.summary["evidence"]["gds"] is True


def test_steps_mirror_symlink_never_outranks_the_real_declared_file(tmp_path):
    """The exact shape measured on the real run: the `steps/` tree mirrors the
    phase3 artefact through a symlink. The evidence must cite the canonical
    file, not a duplicate of it."""
    _other_four_slots(tmp_path)
    _root_decoy(tmp_path)
    real = _gds(tmp_path / _DECLARED)
    mirror = tmp_path / "steps" / "37_gdsii_output" / "top.gds"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    mirror.symlink_to(real)

    r = sa._check_tapeout(tmp_path)
    assert _cited(r, tmp_path) == _DECLARED
    assert not Path(_finding(r, "TAPEOUT_GDS_EXISTS").file).is_symlink()


def test_stale_foundry_handoff_copy_never_outranks_the_declared_streamout(
        tmp_path):
    """On the real run the foundry-handoff copy was a DIFFERENT, older and
    larger file than the declared stream-out. Whichever of the two the
    filesystem happened to yield first, the checklist must name the one step
    37's substance gates were pointed at."""
    _other_four_slots(tmp_path)
    _root_decoy(tmp_path)
    _gds(tmp_path / _DECLARED)
    _gds(tmp_path / "phase3" / "stage4" / "foundry_handoff" / "top.gds")

    r = sa._check_tapeout(tmp_path)
    assert _cited(r, tmp_path) == _DECLARED


def test_pnr_handoff_gds_outranks_an_adhoc_copy_in_the_refusal(tmp_path):
    """Step 36 blocks_on [31,32,33,34] and step 37 blocks_on [34,36], so the
    checklist legitimately runs BEFORE stream-out. That does NOT make the P&R
    hand-off copy the tape-out GDS — the slot is refused — but the refusal
    must still name the best candidate, so the reader is pointed at the P&R
    GDS rather than a loose root-level copy."""
    _other_four_slots(tmp_path)
    _root_decoy(tmp_path)
    _gds(tmp_path / "phase3" / "stage3" / "pnr" / "top.gds")

    r = sa._check_tapeout(tmp_path)
    assert r.summary["evidence"]["gds"] is False
    assert _cited(r, tmp_path, "TAPEOUT_GDS_NOT_DECLARED_STREAMOUT") == \
        "phase3/stage3/pnr/top.gds"


def test_analog_and_mixed_signal_gds_do_not_displace_the_streamout(tmp_path):
    """SYNTHETIC fixture, stated as such: the reference run this fix was
    measured on is pure DIGITAL standard-cell and contains no analog (A1-A9)
    or mixed-signal (M1-M4) artefacts, so it did NOT exercise this path.

    The flow declares per-block analog layouts (`phase3/analog/*/*.gds`) and a
    merged mixed-signal top (`phase3/mixed_signal/top_merged.gds`). Both match
    the tape-out GDS glob, so before ranking either could have been cited as
    THE tape-out GDS. A single analog block's layout is not the chip."""
    _other_four_slots(tmp_path)
    _gds(tmp_path / "phase3" / "analog" / "bandgap" / "layout.gds")
    _gds(tmp_path / "phase3" / "mixed_signal" / "top_merged.gds")
    _gds(tmp_path / _DECLARED)

    r = sa._check_tapeout(tmp_path)
    assert _cited(r, tmp_path) == _DECLARED


def test_foundry_supplied_scribe_frame_never_outranks_the_design_gds(tmp_path):
    """`scribe_line_layout.gds` is the FOUNDRY-SUPPLIED PCM / alignment frame
    (the flow yaml says so, and foundry_handoff_package_check keeps it out of
    its required files). It is an input in the same sense as
    `input/pdk/gds/`, so it must never be the cited candidate while a design
    GDS exists — here neither can credit, and the refusal names the design."""
    _other_four_slots(tmp_path)
    _gds(tmp_path / "phase3" / "stage4" / "foundry_handoff"
         / "scribe_line_layout.gds")
    _gds(tmp_path / "top_adhoc_copy.gds")

    r = sa._check_tapeout(tmp_path)
    assert _cited(r, tmp_path, "TAPEOUT_GDS_NOT_DECLARED_STREAMOUT") == \
        "top_adhoc_copy.gds"


# ===========================================================================
# substance — a draft layout is not a thing a tape-out is signed off on
# ===========================================================================
def test_only_a_draft_gds_does_not_certify_the_gds_slot(tmp_path):
    """Mirrors TAPEOUT_NETLIST_PRESIGNOFF_ONLY / TAPEOUT_TIMING_PRESIGNOFF_ONLY.
    The gate DISCLOSES what it found and still refuses to credit the slot."""
    _other_four_slots(tmp_path)
    _gds(tmp_path / "phase3" / "stage4" / "gds_preview" / "top_draft.gds")

    r = sa._check_tapeout(tmp_path)
    assert r.summary["evidence"]["gds"] is False
    assert r.passed is False
    f = _finding(r, "TAPEOUT_GDS_PRESIGNOFF_ONLY")
    assert f is not None and f.severity == "ERROR"
    assert "top_draft.gds" in f.message          # names what it refused
    assert sa.main([str(tmp_path), "--mode", "tapeout"]) == 1


def test_a_draft_gds_alongside_the_signoff_gds_is_simply_outranked(tmp_path):
    """Direction check on the refusal: it fires only when EVERY candidate is a
    draft. One real stream-out is enough, and it is the one cited."""
    _other_four_slots(tmp_path)
    _gds(tmp_path / "phase3" / "stage4" / "gds_preview" / "top_draft.gds")
    _gds(tmp_path / _DECLARED)

    r = sa._check_tapeout(tmp_path)
    assert r.summary["evidence"]["gds"] is True
    assert _cited(r, tmp_path) == _DECLARED
    assert _finding(r, "TAPEOUT_GDS_PRESIGNOFF_ONLY") is None


def test_a_draft_beats_nothing_but_still_loses_to_a_non_declared_copy(
        tmp_path):
    """Rule precedence, pinned: a pre-sign-off draft plus a non-declared copy
    reports the NOT_DECLARED_STREAMOUT refusal (the copy is the better
    candidate), never the PRESIGNOFF_ONLY one, whose whole claim is that
    EVERY candidate was a draft."""
    _other_four_slots(tmp_path)
    _gds(tmp_path / "phase3" / "stage4" / "gds_preview" / "top_draft.gds")
    _root_decoy(tmp_path)

    r = sa._check_tapeout(tmp_path)
    assert _gds_findings(r) == ["TAPEOUT_GDS_NOT_DECLARED_STREAMOUT"]


# ===========================================================================
# DIRECTION-1 GUARDS — behaviour that must NOT change
# ===========================================================================
def test_guard_a_single_signoff_gds_still_credits_the_slot_at_5_of_5(tmp_path):
    _other_four_slots(tmp_path)
    _gds(tmp_path / _DECLARED)

    r = sa._check_tapeout(tmp_path)
    assert r.summary["evidence"]["gds"] is True
    assert r.summary["evidence_count"] == 5
    assert r.passed is True
    assert sa.main([str(tmp_path), "--mode", "tapeout"]) == 0


def test_guard_no_gds_at_all_is_still_a_hard_error(tmp_path):
    _other_four_slots(tmp_path)

    r = sa._check_tapeout(tmp_path)
    assert r.summary["evidence"]["gds"] is False
    assert r.passed is False
    f = _finding(r, "TAPEOUT_GDS_EXISTS")
    assert f is not None and f.severity == "ERROR"
    assert sa.main([str(tmp_path), "--mode", "tapeout"]) == 1


def test_guard_pdk_stdcell_gds_is_still_never_tapeout_evidence(tmp_path):
    """v0.52: `input/pdk/gds/<stdcell>.gds` is an INPUT. Neither ranking nor
    the credit rule may have given it a way back in."""
    _other_four_slots(tmp_path)
    _gds(tmp_path / "input" / "pdk" / "gds" / "stdcell.gds")

    r = sa._check_tapeout(tmp_path)
    assert r.summary["evidence"]["gds"] is False
    assert _gds_findings(r) == ["TAPEOUT_GDS_EXISTS"]   # i.e. "none found"


def test_guard_project_under_a_draft_directory_is_not_penalised(tmp_path):
    """Pre-sign-off markers are matched on the IN-PROJECT path only, so a
    project living under e.g. /home/x/draft/ keeps its GDS slot."""
    proj = tmp_path / "draft" / "proj"
    _other_four_slots(proj)
    _gds(proj / _DECLARED)

    r = sa._check_tapeout(proj)
    assert r.summary["evidence"]["gds"] is True


def test_guard_flow_mode_gds_stage_evidence_is_unchanged(tmp_path):
    """`--mode flow` reports stage PRESENCE and cites nothing; the ranking and
    the credit rule are tapeout-mode only and must not leak into it."""
    (tmp_path / "phase2" / "stage2" / "synth").mkdir(parents=True)
    (tmp_path / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    _write(tmp_path / "phase3" / "stage4" / "gds_preview" / "top_draft.gds",
           "GDSII-draft")
    _write(tmp_path / "sta_timing.rpt", "sta report")

    r = sa._check_flow(tmp_path)
    assert r.summary["stages"]["gds"] is True
    assert r.summary["threshold"] == 4
    assert r.passed is True


def test_guard_the_substance_classifier_is_the_gdsii_header_record(tmp_path):
    """Unit-level pin on `_gds_stream_substance`, so the credit floor cannot
    drift into "any binary file" or "any file over N bytes"."""
    real = _gds(tmp_path / "real.gds")
    assert sa._gds_stream_substance(real) == "ok"

    empty = tmp_path / "empty.gds"
    empty.write_bytes(b"")
    assert sa._gds_stream_substance(empty) == "empty"

    text = tmp_path / "text.gds"
    text.write_text("this is not a layout, it is a sentence")
    assert sa._gds_stream_substance(text) == "not_gdsii"

    # right length, wrong record type — a near miss must still be refused
    near = tmp_path / "near.gds"
    near.write_bytes(b"\x00\x06\x00\x03" + b"\x00" * 100)
    assert sa._gds_stream_substance(near) == "not_gdsii"

    truncated = tmp_path / "trunc.gds"
    truncated.write_bytes(b"\x00\x06")
    assert sa._gds_stream_substance(truncated) == "not_gdsii"
