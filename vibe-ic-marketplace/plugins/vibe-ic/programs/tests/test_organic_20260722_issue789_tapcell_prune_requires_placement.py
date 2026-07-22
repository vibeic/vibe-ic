#!/usr/bin/env python3
"""Regression for ORGANIC-20260722 #789 — the #684 sparse-die tap prune deleted
well-tie taps against a placement that did not exist yet, creating a CONCLUSIVE
latch-up exposure.

`_build_tapcell_tcl` emits, for a low-utilisation die:

    tapcell -distance <d> -tapcell_master <m>     ;# full-die well-tie
    <prune every tap outside the occupied-cell bbox + 2*d margin>

The prune is sound only if an occupied region EXISTS. It does not: in the
emitted `pnr.tcl`, tap insertion runs at the floorplan stage — BEFORE
`global_placement` and `detailed_placement`. At that point every standard cell
is unplaced, so the "occupied bbox" is a fiction.

Observed on caravel_user_project x sky130A (2920 x 3520 um Caravel-fixed die,
~427 cells):

    TAPCELL_INSERTED: master=sky130_fd_sc_hd__tapvpwrvgnd_1 distance=14.0um
    SPARSE_DIE_TAPCELL_BOUNDED: core_util=0.0221...% < 5.0% — kept=8,
                                pruned=134170

Placement then scattered the real cells across the whole die, and the PERC
sign-off correctly refused:

    Latch-up tap spacing (geometry): FAIL — "a placed std cell at
    (2881.90,1808.80) um is infinitely (no tap in neighbourhood) from the
    nearest tap — beyond even the deliberately-generous 30.0 um screening
    radius ... a CONCLUSIVE latch-up spacing exposure."

Fix: the prune requires `_tap_nplaced > 0` — at least one CORE instance whose
odb placement status is PLACED/FIRM/LOCKED. Where the prune cannot be evaluated
it self-disables and the FULL-DIE well-tie taps are retained (the known-correct
OpenROAD/OpenLane default — which is precisely why placing a cell anywhere on
the die is safe). If tap insertion is ever moved after placement, #684's
bloat-reduction resumes working, soundly.

Correctness over instance count: an untapped well is a latch-up defect; surplus
taps are only area. Critically, tap INSERTION is unconditional on both paths —
the pre-fix `else` arm printed SPARSE_DIE_TAPCELL_SKIPPED and inserted NOTHING,
so naively gating the whole block would have been strictly worse (zero taps).
That is pinned by test_taps_are_inserted_on_every_path.

NOTE: this test pins the EMITTED TCL, not an OpenROAD run — executing it needs a
placed design in a container. The end-to-end evidence is the flow re-run, where
SPARSE_DIE_TAPCELL_FULL_DIE replaces SPARSE_DIE_TAPCELL_BOUNDED and the PERC
latch-up geometry category stops failing.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parent.parent
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))

SRC = (PROG_DIR / "phase3_one_shot_runner.py").read_text()


def _emitter_body() -> str:
    """The source text of `_build_tapcell_tcl`."""
    start = SRC.index("def _build_tapcell_tcl(")
    nxt = SRC.index("\ndef ", start + 1)
    return SRC[start:nxt]


# ── the defect ──────────────────────────────────────────────────────────
def test_prune_requires_a_real_placement():
    """The occupied-region prune must be gated on placed instances."""
    body = _emitter_body()
    assert "_tap_nplaced" in body, "placed-instance counter is gone"
    assert "$_tap_nplaced > 0" in body, (
        "the #684 prune no longer requires a real placement — it will delete "
        "well-tie taps against a bbox that does not exist yet (#789)")


def test_placed_status_is_read_from_odb():
    body = _emitter_body()
    assert "getPlacementStatus" in body
    for token in ("*PLACED*", "*FIRM*", "*LOCKED*"):
        assert token in body, f"placement status {token} not recognised"


def test_taps_are_inserted_on_every_path():
    """Tap INSERTION must never be skipped. The pre-fix code inserted nothing
    on the else arm; gating the whole block would trade an under-tapped die for
    a completely untapped one."""
    body = _emitter_body()
    # the sparse branch must run tapcell BEFORE deciding whether to prune
    sparse = body[body.index("R6 — sparse die"):]
    run_at = sparse.index("_tap_run")
    gate_at = sparse.index("$_tap_nplaced > 0")
    assert run_at < gate_at, (
        "tapcell must be inserted before the prune decision, else the "
        "not-evaluable path leaves the die with ZERO taps")


def test_no_path_reports_skipped_without_inserting():
    """The old 'no wells to tie' skip message implied zero taps; it must not
    survive as the not-evaluable outcome."""
    body = _emitter_body()
    assert "SPARSE_DIE_TAPCELL_FULL_DIE" in body, (
        "the not-evaluable path must report retaining full-die taps")


def test_full_die_message_is_honest_about_why():
    """A silent behaviour change is how this class of defect hides. The log
    line must say the prune was not evaluable and taps were retained."""
    body = _emitter_body()
    msg_region = body[body.index("SPARSE_DIE_TAPCELL_FULL_DIE"):]
    for token in ("NOT EVALUABLE", "BEFORE", "kept=$_tap_kept"):
        assert token in msg_region, f"log line does not disclose {token!r}"


# ── ordering: the fact that makes the prune unsound ─────────────────────
def test_tapcell_is_emitted_before_placement_in_the_flow():
    """Pins the ORDER that makes the prune unevaluable. If a future change
    moves tap insertion after placement, this test fails and the author should
    then re-enable the #684 prune (which becomes sound at that point)."""
    # Order in the ASSEMBLED SCRIPT TEMPLATE, not in the source file: the
    # tapcell TCL is substituted as `{tapcell_block}` into the pnr template,
    # and that placeholder sits ahead of the global-placement command.
    ph = SRC.find("{tapcell_block}")
    assert ph > 0, ("pnr template no longer substitutes {tapcell_block} "
                    "— test is stale")
    gp = SRC.find("global_placement -routability_driven", ph)
    assert gp > ph, (
        "tapcell is no longer emitted before global_placement — re-evaluate "
        "whether the #684 occupied-region prune can be re-enabled (#789)")


# ── no-leak ─────────────────────────────────────────────────────────────
def test_dense_die_path_unchanged():
    """A die above the sparse threshold still takes the plain full-die tapcell
    path with no prune at all — byte-identical to before."""
    body = _emitter_body()
    tail = body[body.rindex("} else {"):]
    assert "_tap_run" in tail
    assert "_tap_kill" not in tail, "dense path must not prune"


def test_prune_is_still_present_for_the_evaluable_case():
    """#684 is not deleted — only made conditional."""
    body = _emitter_body()
    assert "_tap_kill" in body and "odb::dbInst_destroy" in body
    assert "SPARSE_DIE_TAPCELL_BOUNDED" in body


def test_prune_failure_still_fails_safe():
    """An odb API drift during the prune must retain taps, not abort PnR."""
    body = _emitter_body()
    assert "TAPCELL_PRUNE_NONFATAL" in body


def _render_tcl() -> str:
    """Render the REAL emitted TCL with a minimal sky130-shaped PdkConfig."""
    import dataclasses
    import phase3_one_shot_runner as P
    kw = {}
    for f in dataclasses.fields(P.PdkConfig):
        if (f.default is not dataclasses.MISSING
                or f.default_factory is not dataclasses.MISSING):
            continue
        kw[f.name] = "" if f.type in ("str", str) else ""
    kw.update(name="sky130A",
              tapcell_master="sky130_fd_sc_hd__tapvpwrvgnd_1",
              tapcell_distance_um=14.0)
    return P._build_tapcell_tcl(P.PdkConfig(**kw))


def test_emitted_tcl_braces_balance():
    """Structural guard on the ACTUAL generated script, not on source text."""
    tcl = _render_tcl()
    assert tcl.count("{") == tcl.count("}"), (
        f"unbalanced braces in emitted TCL: "
        f"{tcl.count('{')} open vs {tcl.count('}')} close")


def test_emitted_tcl_runs_the_expected_shape():
    tcl = _render_tcl()
    assert "tapcell -distance 14.0" in tcl
    assert "$_tap_nplaced > 0" in tcl
    assert "SPARSE_DIE_TAPCELL_FULL_DIE" in tcl
    # tapcell must appear before the prune gate on the sparse branch
    sparse = tcl[tcl.index("R6 — sparse die"):]
    assert sparse.index("tapcell -distance") < sparse.index("$_tap_nplaced > 0")
