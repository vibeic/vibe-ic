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
`gds_substance_check` and `provenance_check`. The tape-out checklist named a
different path from the one those substance gates verified, and — because the
pick was unordered — could equally have named the STALE 1014178 B
foundry-handoff copy. A checklist that certifies "GDS present" without being
able to say WHICH GDS is an existence-only gate.

FIX (same two changes the netlist/timing slots already carry, no third idea):
  (1) `_gds_rank` + `_rank_signoff_first` — declared stream-out artefact first,
      other phase3 copies next, mirrors/ad-hoc copies after that, and the
      FOUNDRY-SUPPLIED scribe-line frame last (it is an input, not the design);
  (2) refuse to credit the slot when EVERY candidate declares itself a
      pre-sign-off intermediate, disclosing what it refused.

Nothing is loosened: the slot is still required, ranking only REORDERS, and
(2) adds one new way to FAIL. On the real completed run the verdict is
unchanged (5/5, rc 0) and the citation moves to phase3/stage4/gds/spm.gds.

SCOPE OF THE MEASUREMENT, stated so nobody over-reads it: the reference run is
pure DIGITAL standard-cell. It contains no analog (A1-A9) or mixed-signal
(M1-M4) artefacts, so it did NOT exercise those paths. The analog /
mixed-signal candidates that also match the tape-out GDS glob are covered
below by CODE-READING of the flow declaration plus a SYNTHETIC fixture, never
by the digital run.

chip-AGNOSTIC: synthetic project trees only.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import signoff_audit as sa  # noqa: E402

_DECLARED = "phase3/stage4/gds/top.gds"


# ---------------------------------------------------------------------------
# fixture helpers
# ---------------------------------------------------------------------------
def _write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


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
    return proj


def _root_decoy(proj: Path) -> Path:
    """An ad-hoc copy at the PROJECT ROOT.

    `Path.rglob` yields the top directory's own entries before it descends, so
    the pre-fix `_has_files(...)[0]` pick is this file DETERMINISTICALLY —
    which is what makes every ranking assertion below a real discriminator
    rather than a bet on directory-scan order. Post-fix it ranks below every
    in-`phase3/` candidate and can only ever be cited when it is the only one.
    """
    return _write(proj / "top_adhoc_copy.gds", "GDSII-adhoc")


def _finding(result, rule):
    for f in result.findings:
        if f.rule == rule:
            return f
    return None


def _cited(result, proj: Path, rule: str = "TAPEOUT_GDS_EXISTS") -> str:
    f = _finding(result, rule)
    assert f is not None, f"{rule} not among {[x.rule for x in result.findings]}"
    return Path(f.file).relative_to(proj).as_posix()


# ===========================================================================
# ranking — the slot must cite the artefact the flow declares and the step-37
# substance gates verify
# ===========================================================================
def test_declared_streamout_gds_outranks_an_adhoc_root_copy(tmp_path):
    _other_four_slots(tmp_path)
    _root_decoy(tmp_path)
    _write(tmp_path / _DECLARED, "GDSII-signoff")

    r = sa._check_tapeout(tmp_path)
    assert _cited(r, tmp_path) == _DECLARED
    assert r.summary["evidence"]["gds"] is True


def test_steps_mirror_symlink_never_outranks_the_real_declared_file(tmp_path):
    """The exact shape measured on the real run: the `steps/` tree mirrors the
    phase3 artefact through a symlink. The evidence must cite the canonical
    file, not a duplicate of it."""
    _other_four_slots(tmp_path)
    _root_decoy(tmp_path)
    real = _write(tmp_path / _DECLARED, "GDSII-signoff")
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
    _write(tmp_path / _DECLARED, "GDSII-signoff")
    _write(tmp_path / "phase3" / "stage4" / "foundry_handoff" / "top.gds",
           "GDSII-stale-larger-copy")

    r = sa._check_tapeout(tmp_path)
    assert _cited(r, tmp_path) == _DECLARED


def test_pnr_handoff_gds_outranks_an_adhoc_copy_when_stage4_is_absent(tmp_path):
    """Step 36 blocks_on [31,32,33,34] and step 37 blocks_on [34,36], so the
    checklist legitimately runs BEFORE stream-out. With no declared artefact
    yet, an in-phase3 P&R GDS must still outrank a loose root-level copy."""
    _other_four_slots(tmp_path)
    _root_decoy(tmp_path)
    _write(tmp_path / "phase3" / "stage3" / "pnr" / "top.gds", "GDSII-pnr")

    r = sa._check_tapeout(tmp_path)
    assert _cited(r, tmp_path) == "phase3/stage3/pnr/top.gds"


def test_analog_and_mixed_signal_gds_do_not_displace_the_streamout(tmp_path):
    """SYNTHETIC fixture, stated as such: the reference run this fix was
    measured on is pure DIGITAL standard-cell and contains no analog (A1-A9)
    or mixed-signal (M1-M4) artefacts, so it did NOT exercise this path.

    The flow declares per-block analog layouts (`phase3/analog/*/*.gds`) and a
    merged mixed-signal top (`phase3/mixed_signal/top_merged.gds`). Both match
    the tape-out GDS glob, so before ranking either could have been cited as
    THE tape-out GDS. A single analog block's layout is not the chip."""
    _other_four_slots(tmp_path)
    _write(tmp_path / "phase3" / "analog" / "bandgap" / "layout.gds", "GDSII-a")
    _write(tmp_path / "phase3" / "mixed_signal" / "top_merged.gds", "GDSII-m")
    _write(tmp_path / _DECLARED, "GDSII-signoff")

    r = sa._check_tapeout(tmp_path)
    assert _cited(r, tmp_path) == _DECLARED


def test_foundry_supplied_scribe_frame_never_outranks_the_design_gds(tmp_path):
    """`scribe_line_layout.gds` is the FOUNDRY-SUPPLIED PCM / alignment frame
    (the flow yaml says so, and foundry_handoff_package_check keeps it out of
    its required files). It is an input in the same sense as
    `input/pdk/gds/`, so it must never be cited as the tape-out GDS while a
    design GDS exists."""
    _other_four_slots(tmp_path)
    _write(tmp_path / "phase3" / "stage4" / "foundry_handoff"
           / "scribe_line_layout.gds", "GDSII-frame")
    _write(tmp_path / "top_adhoc_copy.gds", "GDSII-design")

    r = sa._check_tapeout(tmp_path)
    assert _cited(r, tmp_path) == "top_adhoc_copy.gds"


# ===========================================================================
# substance — a draft layout is not a thing a tape-out is signed off on
# ===========================================================================
def test_only_a_draft_gds_does_not_certify_the_gds_slot(tmp_path):
    """Mirrors TAPEOUT_NETLIST_PRESIGNOFF_ONLY / TAPEOUT_TIMING_PRESIGNOFF_ONLY.
    The gate DISCLOSES what it found and still refuses to credit the slot."""
    _other_four_slots(tmp_path)
    _write(tmp_path / "phase3" / "stage4" / "gds_preview" / "top_draft.gds",
           "GDSII-draft")

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
    _write(tmp_path / "phase3" / "stage4" / "gds_preview" / "top_draft.gds",
           "GDSII-draft")
    _write(tmp_path / _DECLARED, "GDSII-signoff")

    r = sa._check_tapeout(tmp_path)
    assert r.summary["evidence"]["gds"] is True
    assert _cited(r, tmp_path) == _DECLARED
    assert _finding(r, "TAPEOUT_GDS_PRESIGNOFF_ONLY") is None


# ===========================================================================
# DIRECTION-1 GUARDS — behaviour that must NOT change (pass on BOTH trees)
# ===========================================================================
def test_guard_a_single_signoff_gds_still_credits_the_slot_at_5_of_5(tmp_path):
    _other_four_slots(tmp_path)
    _write(tmp_path / _DECLARED, "GDSII-signoff")

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
    """v0.52: `input/pdk/gds/<stdcell>.gds` is an INPUT. Ranking must not have
    given it a way back in."""
    _other_four_slots(tmp_path)
    _write(tmp_path / "input" / "pdk" / "gds" / "stdcell.gds", "pdk")

    r = sa._check_tapeout(tmp_path)
    assert r.summary["evidence"]["gds"] is False
    assert _finding(r, "TAPEOUT_GDS_PRESIGNOFF_ONLY") is None


def test_guard_project_under_a_draft_directory_is_not_penalised(tmp_path):
    """Pre-sign-off markers are matched on the IN-PROJECT path only, so a
    project living under e.g. /home/x/draft/ keeps its GDS slot."""
    proj = tmp_path / "draft" / "proj"
    _other_four_slots(proj)
    _write(proj / _DECLARED, "GDSII-signoff")

    r = sa._check_tapeout(proj)
    assert r.summary["evidence"]["gds"] is True


def test_guard_flow_mode_gds_stage_evidence_is_unchanged(tmp_path):
    """`--mode flow` reports stage PRESENCE and cites nothing; the ranking is
    tapeout-mode only and must not have leaked into it."""
    (tmp_path / "phase2" / "stage2" / "synth").mkdir(parents=True)
    (tmp_path / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    _write(tmp_path / "phase3" / "stage4" / "gds_preview" / "top_draft.gds",
           "GDSII-draft")
    _write(tmp_path / "sta_timing.rpt", "sta report")

    r = sa._check_flow(tmp_path)
    assert r.summary["stages"]["gds"] is True
    assert r.summary["threshold"] == 4
    assert r.passed is True
