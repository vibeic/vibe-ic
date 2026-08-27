#!/usr/bin/env python3
"""A landed fix could not reach a run, because a stale deck was still on disk.

The repair call site asked `if not repair_tcl_path.is_file()` — EXISTENCE standing in
for CURRENCY. A repair deck is a GENERATED artefact, so reusing one written by an
older generator re-runs the older generator's logic no matter what the plugin
has since learned.

MEASURED (sha256 x sky130A, 2026-08-05). The tree held a deck emitted before
#766 — the fix that made the repair start from the shipped post-route DEF and read
the extracted SPEF instead of restarting from the pre-route DEF against
estimated parasitics. A re-run in place found the file present, skipped the
emit, and reproduced the pre-#766 answer exactly:

    recorded repair regression   -19.010 ns
    true delta                 -0.40 ns   (-3.28 -> -3.68)

a ~47x inflation, because the two numbers described two different netlists —
only 16 of 178 cell types matched between them. The fix had landed months of
work earlier and the run could not reach it.

The deck now carries a digest of its own generator, and is re-emitted when that
digest is absent or different. Both directions are pinned here: a deck this
generator wrote must NOT be needlessly re-emitted (that would make the check a
no-op dressed as a freshness test), and a deck from any other generator must be.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as m  # noqa: E402


def _deck() -> str:
    return m._build_postroute_timing_repair_tcl(
        "top", "/t.lef", "/c.lef", "/l.lib", "/pnr", "/postroute_timing_repair", "met")


def test_the_generator_stamps_its_own_digest_into_the_deck():
    fp = m._repair_deck_fingerprint()
    assert fp, "the generator could not fingerprint itself"
    assert f"{m._POSTROUTE_TIMING_REPAIR_DECK_STAMP}{fp}" in _deck()


def test_a_deck_this_generator_wrote_is_not_re_emitted(tmp_path):
    """THE REVERSE CASE. Without this, 'always stale' would pass every other
    test here while quietly regenerating on every run — a freshness check that
    never checks freshness."""
    p = tmp_path / "postroute_timing_repair.tcl"
    p.write_text(_deck())
    assert m._repair_deck_is_stale(p) is False


def test_a_deck_from_a_different_generator_is_re_emitted(tmp_path):
    p = tmp_path / "postroute_timing_repair.tcl"
    p.write_text(_deck().replace(m._repair_deck_fingerprint(), "0" * 16))
    assert m._repair_deck_is_stale(p) is True


def test_an_unstamped_deck_is_re_emitted(tmp_path):
    """The measured case: every deck written before this stamp existed —
    including the pre-#766 ones that produced the -19.010 ns artefact."""
    p = tmp_path / "postroute_timing_repair.tcl"
    p.write_text("# === ORGANIC #561: post-route timing repair TCL ===\n"
                 "read_def post_hold.def\n"
                 "estimate_parasitics -placement\n"
                 "repair_timing -setup\n")
    assert m._repair_deck_is_stale(p) is True


def test_a_missing_deck_is_re_emitted(tmp_path):
    assert m._repair_deck_is_stale(tmp_path / "nope.tcl") is True


def test_an_unreadable_deck_is_stale_not_current(tmp_path):
    """Failing to read the artefact is not evidence that it is current."""
    p = tmp_path / "dir_not_file.tcl"
    p.mkdir()
    assert m._repair_deck_is_stale(p) is True


def test_the_digest_tracks_the_generator_not_a_hand_bumped_constant():
    """The stamp must change when the emission logic changes, without anyone
    remembering to bump it — that forgetting is how the original defect
    survived. Verified by fingerprinting a modified copy of the source."""
    import hashlib
    import inspect
    src = inspect.getsource(m._build_postroute_timing_repair_tcl)
    mutated = src.replace("repair_timing", "repair_timing_v2", 1)
    assert mutated != src, "the mutation did not apply; the check is vacuous"
    assert (hashlib.sha256(mutated.encode()).hexdigest()[:16]
            != m._repair_deck_fingerprint())


def test_the_stamp_carries_no_design_or_pdk_literal():
    deck = _deck()
    stamp = [ln for ln in deck.splitlines()
             if ln.startswith(m._POSTROUTE_TIMING_REPAIR_DECK_STAMP.strip())]
    assert len(stamp) == 1, stamp
    assert stamp[0].split(":", 1)[1].strip().isalnum()
