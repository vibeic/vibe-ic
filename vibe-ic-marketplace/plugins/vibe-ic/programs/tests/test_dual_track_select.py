"""dual_track_select — the deterministic 'keep whichever candidate PASSes'
step of dual-track convergence (primary spec-to-rtl attempt vs IC Expert
DB-informed second attempt). Selection is made by a gate/verifier, never by an
author self-report. Two tiers: FUNCTIONAL (a verify cmd = ground truth) and
STRUCTURAL (no oracle → elaborate + PRIMARY-first tie-break, no functional claim).
"""
import shutil
import sys
from pathlib import Path

import pytest

import dual_track_select as D

_GOOD = "module m(input a, output y); assign y = a; endmodule\n"
_BAD = "module m(input a, output y  // missing ; and endmodule\n"

#: The three tests below need a REAL elaborator, because they turn on iverilog
#: telling `_GOOD` from `_BAD` — a stub cannot do that, it accepts or rejects
#: both. On a host without one they used to FAIL (measured: 3 failed / 5 passed
#: on `a38902d1` with iverilog hidden), which is a missing tool reported as a
#: defect in the selection logic. They SKIP now, and the reason names the tool
#: so a green run discloses what it stopped checking (#1128).
#:
#: This is not a loss of coverage on this host, and on a host without iverilog
#: it is not a loss either: the `#1332` tests below drive the same `select()`
#: through a PATH-injected stub and run EVERYWHERE, so the file can no longer
#: pass vacuously for want of a compiler.
_NEEDS_IVERILOG = pytest.mark.skipif(
    shutil.which("iverilog") is None,
    reason="needs a real elaborator to tell good RTL from broken; "
           "missing on this host: iverilog")


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

@_NEEDS_IVERILOG
def test_structural_picks_elaborating_over_broken(tmp_path):
    prim = _w(tmp_path, "primary.sv", _BAD)   # does not elaborate
    db = _w(tmp_path, "db.sv", _GOOD)          # elaborates
    rep = D.select([("primary", prim), ("db", db)])
    assert rep["tier"] == "structural"
    assert rep["winner_label"] == "db"


@_NEEDS_IVERILOG
def test_structural_ties_to_primary(tmp_path):
    prim = _w(tmp_path, "primary.sv", _GOOD)
    db = _w(tmp_path, "db.sv", _GOOD)
    rep = D.select([("primary", prim), ("db", db)])
    assert rep["winner_label"] == "primary"       # stronger prior on a tie
    assert "does NOT prove functional" in rep["note"]


@_NEEDS_IVERILOG
def test_structural_no_winner_when_none_elaborate(tmp_path):
    """THE VACUOUS PASS #1332 names, and the reason `winner_label is None` is
    not sufficient on its own.

    On a host without `iverilog` this asserted `winner_label is None` and got
    None — because NOTHING could elaborate at all, not because the two _BAD
    candidates were rejected. It was green exactly when it proved least.

    Two changes, and both are needed: the skip means it no longer runs where it
    cannot mean anything, and `uncheckable is False` means that even if it did,
    "nothing was measured" can no longer satisfy "nothing won".
    """
    prim = _w(tmp_path, "primary.sv", _BAD)
    db = _w(tmp_path, "db.sv", _BAD)
    rep = D.select([("primary", prim), ("db", db)])
    assert rep["winner_label"] is None
    assert rep["uncheckable"] is False, (
        "this must fail on a REJECTION, never on an absent elaborator")


def test_structural_only_flag_ignores_verify_cmd(tmp_path):
    prim = _w(tmp_path, "primary.sv", _GOOD)
    db = _w(tmp_path, "db.sv", _GOOD)
    # even with a verify cmd, --structural-only path (vc=None) stays structural
    rep = D.select([("primary", prim), ("db", db)], verify_cmd=None)
    assert rep["tier"] == "structural"


@_NEEDS_IVERILOG
def test_missing_candidate_file_is_not_selected(tmp_path):
    prim = tmp_path / "absent.sv"          # does not exist
    db = _w(tmp_path, "db.sv", _GOOD)
    rep = D.select([("primary", prim), ("db", db)])
    assert rep["winner_label"] == "db"


# ── #1332: "I could not look" is not a verdict ──────────────────────────────
#
# Every structural test above needs a real `iverilog`, and on a host without one
# they FAIL — measured, 3 failed / 5 passed on `a38902d1` with iverilog hidden.
# Worse, `test_structural_no_winner_when_none_elaborate` PASSES on such a host,
# for entirely the wrong reason: it asserts `winner_label is None` and gets None
# because NOTHING can elaborate at all. Green exactly when it proves least.
#
# The stub below makes both arms reachable on ANY host with no container, which
# is what makes this file host-independent (#527). It also gives the paired
# guard for free: a stub that exits 1 must produce no winner, and a stub that
# exits 0 must produce one — so the assertions cannot be satisfied by absence.

def _stub_iverilog(tmp_path, rc: int) -> str:
    """A PATH directory whose `iverilog` always exits `rc`."""
    d = tmp_path / f"stub{rc}"
    d.mkdir()
    exe = d / "iverilog"
    exe.write_text("#!/bin/sh\nexit %d\n" % rc)
    exe.chmod(0o755)
    return str(d)


def test_a_MISSING_elaborator_is_uncheckable_not_a_rejection(tmp_path, monkeypatch):
    """THE #1332 DEFECT. `_elaborates` caught FileNotFoundError in a bare
    `except` and returned False — the same value as "iverilog ran and rejected
    this RTL". `select()` then said "no candidate elaborates", which reads as
    "both candidates are broken RTL", and dual-track convergence discards a good
    primary attempt because the host lacked a compiler."""
    monkeypatch.setenv("PATH", str(tmp_path / "empty-no-iverilog"))
    prim = _w(tmp_path, "primary.sv", _GOOD)
    db = _w(tmp_path, "db.sv", _GOOD)
    rep = D.select([("primary", prim), ("db", db)])
    assert rep["uncheckable"] is True, rep
    assert rep["winner_label"] is None
    assert "NOT 'no candidate elaborates'" in rep["note"], rep["note"]
    assert "not on PATH" in rep["note"], rep["note"]


def test_an_elaborator_that_REJECTS_is_still_a_real_no(tmp_path, monkeypatch):
    """The other half, without which the fix is satisfied by calling everything
    uncheckable — which would be a gate that can never say no."""
    monkeypatch.setenv("PATH", _stub_iverilog(tmp_path, 1) + ":/usr/bin:/bin")
    prim = _w(tmp_path, "primary.sv", _GOOD)
    db = _w(tmp_path, "db.sv", _GOOD)
    rep = D.select([("primary", prim), ("db", db)])
    assert rep["uncheckable"] is False, rep
    assert rep["winner_label"] is None
    assert rep["note"] == "no candidate elaborates"


def test_an_elaborator_that_ACCEPTS_still_picks_a_winner(tmp_path, monkeypatch):
    """…and the tie-break still prefers PRIMARY. Runs on any host."""
    monkeypatch.setenv("PATH", _stub_iverilog(tmp_path, 0) + ":/usr/bin:/bin")
    prim = _w(tmp_path, "primary.sv", _GOOD)
    db = _w(tmp_path, "db.sv", _GOOD)
    rep = D.select([("primary", prim), ("db", db)])
    assert rep["uncheckable"] is False, rep
    assert rep["winner_label"] == "primary", rep


def test_a_missing_CANDIDATE_is_a_real_no_not_an_uncheckable(tmp_path, monkeypatch):
    """An absent candidate WAS examined and is absent — that is an answer. If it
    read as uncheckable, a typo'd path would suppress the whole verdict."""
    monkeypatch.setenv("PATH", _stub_iverilog(tmp_path, 0) + ":/usr/bin:/bin")
    rep = D.select([("primary", tmp_path / "nope.sv")])
    assert rep["uncheckable"] is False, rep
    assert rep["winner_label"] is None


def test_a_MISSING_verify_cmd_is_uncheckable_not_a_failed_verify(tmp_path):
    """`_run_verify` carried the identical defect and the issue names only
    `_elaborates`. A verify command that is not installed did not FAIL the
    candidate; it never ran."""
    prim = _w(tmp_path, "primary.sv", _GOOD)
    rep = D.select([("primary", prim)],
                   verify_cmd="definitely-not-a-real-tool-1332 {rtl}")
    assert rep["uncheckable"] is True, rep
    assert "NOT 'no candidate passed'" in rep["note"], rep["note"]


def test_the_CLI_exit_code_separates_uncheckable_from_no_winner(tmp_path, monkeypatch):
    """rc 1 and rc 2 must differ, or the distinction dies at the process
    boundary where callers actually branch (`_vacuous_exit`: 0/1/2)."""
    prim = _w(tmp_path, "primary.sv", _GOOD)
    monkeypatch.setenv("PATH", str(tmp_path / "empty-no-iverilog"))
    assert D.main(["--candidate", f"primary={prim}"]) == 2

    monkeypatch.setenv("PATH", _stub_iverilog(tmp_path, 1) + ":/usr/bin:/bin")
    assert D.main(["--candidate", f"primary={prim}"]) == 1

    monkeypatch.setenv("PATH", _stub_iverilog(tmp_path, 0) + ":/usr/bin:/bin")
    assert D.main(["--candidate", f"primary={prim}"]) == 0
