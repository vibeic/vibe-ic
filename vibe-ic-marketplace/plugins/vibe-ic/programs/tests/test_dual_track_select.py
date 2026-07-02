"""dual_track_select — the deterministic 'keep whichever candidate PASSes'
step of dual-track convergence (primary spec-to-rtl attempt vs IC Expert
DB-informed second attempt). Selection is made by a gate/verifier, never by an
author self-report. Two tiers: FUNCTIONAL (a verify cmd = ground truth) and
STRUCTURAL (no oracle → elaborate + PRIMARY-first tie-break, no functional claim).
"""
import sys
from pathlib import Path

import dual_track_select as D

_GOOD = "module m(input a, output y); assign y = a; endmodule\n"
_BAD = "module m(input a, output y  // missing ; and endmodule\n"


def _w(tmp_path, name, txt):
    p = tmp_path / name
    p.write_text(txt)
    return p


# ── FUNCTIONAL tier: verify cmd is ground truth ─────────────────────

def test_functional_picks_the_passing_candidate(tmp_path):
    prim = _w(tmp_path, "primary.sv", "primary")
    db = _w(tmp_path, "db.sv", "db")
    # verify passes (rc 0) only for the file whose content is 'db'
    cmd = "bash -c 'grep -q db {rtl}'"
    rep = D.select([("primary", prim), ("db", db)], verify_cmd=cmd)
    assert rep["tier"] == "functional"
    assert rep["winner_label"] == "db"


def test_functional_primary_wins_when_both_pass(tmp_path):
    prim = _w(tmp_path, "primary.sv", "x")
    db = _w(tmp_path, "db.sv", "x")
    cmd = "true"  # both pass
    rep = D.select([("primary", prim), ("db", db)], verify_cmd=cmd)
    assert rep["winner_label"] == "primary"  # first-to-pass = primary order


def test_functional_no_winner_when_none_pass(tmp_path):
    prim = _w(tmp_path, "primary.sv", "x")
    db = _w(tmp_path, "db.sv", "x")
    rep = D.select([("primary", prim), ("db", db)], verify_cmd="false")
    assert rep["winner_label"] is None
    assert rep["tier"] == "functional"


# ── STRUCTURAL tier: no oracle → elaborate + primary tie-break ──────

def test_structural_picks_elaborating_over_broken(tmp_path):
    prim = _w(tmp_path, "primary.sv", _BAD)   # does not elaborate
    db = _w(tmp_path, "db.sv", _GOOD)          # elaborates
    rep = D.select([("primary", prim), ("db", db)])
    assert rep["tier"] == "structural"
    assert rep["winner_label"] == "db"


def test_structural_ties_to_primary(tmp_path):
    prim = _w(tmp_path, "primary.sv", _GOOD)
    db = _w(tmp_path, "db.sv", _GOOD)
    rep = D.select([("primary", prim), ("db", db)])
    assert rep["winner_label"] == "primary"       # stronger prior on a tie
    assert "does NOT prove functional" in rep["note"]


def test_structural_no_winner_when_none_elaborate(tmp_path):
    prim = _w(tmp_path, "primary.sv", _BAD)
    db = _w(tmp_path, "db.sv", _BAD)
    rep = D.select([("primary", prim), ("db", db)])
    assert rep["winner_label"] is None


def test_structural_only_flag_ignores_verify_cmd(tmp_path):
    prim = _w(tmp_path, "primary.sv", _GOOD)
    db = _w(tmp_path, "db.sv", _GOOD)
    # even with a verify cmd, --structural-only path (vc=None) stays structural
    rep = D.select([("primary", prim), ("db", db)], verify_cmd=None)
    assert rep["tier"] == "structural"


def test_missing_candidate_file_is_not_selected(tmp_path):
    prim = tmp_path / "absent.sv"          # does not exist
    db = _w(tmp_path, "db.sv", _GOOD)
    rep = D.select([("primary", prim), ("db", db)])
    assert rep["winner_label"] == "db"
