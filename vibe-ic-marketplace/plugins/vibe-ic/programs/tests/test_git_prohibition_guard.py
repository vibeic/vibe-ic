#!/usr/bin/env python3
"""Tests for git_prohibition_guard.py — the core-agent loop's deny-list
of destructive git/gh operations (chip-AGNOSTIC)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_PROG = Path(__file__).resolve().parents[1] / "git_prohibition_guard.py"
_spec = importlib.util.spec_from_file_location("git_prohibition_guard", _PROG)
gpg = importlib.util.module_from_spec(_spec)
sys.modules["git_prohibition_guard"] = gpg
_spec.loader.exec_module(gpg)


# ---- PASS cases ---------------------------------------------------------
def test_pass_safe_push():
    assert gpg.main(["--command", "git push origin main"]) == 0


def test_pass_force_with_lease_is_allowed():
    # --force-with-lease is the SAFE sibling and must NOT be flagged.
    assert gpg.main(["--command", "git push --force-with-lease origin main"]) == 0


def test_pass_normal_commit():
    assert gpg.main(["--command", "git commit -m 'v0.2.14 — for #41 fix'"]) == 0


def test_pass_gh_issue_edit_label():
    assert gpg.main(["--command",
                     "gh issue edit 41 --add-label core-closed"]) == 0


def test_pass_gh_issue_close_is_allowed():
    # Core CLOSES after self-verify under the new state machine; closing
    # an issue must NOT be flagged.
    assert gpg.main(["--command", "gh issue close 41 --comment done"]) == 0


def test_pass_gh_issue_reopen_is_allowed():
    # Field REOPENS when its audit finds a closed issue inadequate; reopen
    # must NOT be flagged.
    assert gpg.main(["--command", "gh issue reopen 41"]) == 0


# ---- FAIL cases ---------------------------------------------------------
def test_fail_push_force():
    assert gpg.main(["--command", "git push --force origin main"]) == 1


def test_fail_push_dash_f():
    assert gpg.main(["--command", "git push -f"]) == 1


def test_fail_reset_hard():
    assert gpg.main(["--command", "git reset --hard origin/main"]) == 1


def test_fail_commit_no_verify():
    assert gpg.main(["--command", "git commit --no-verify -m wip"]) == 1


def test_fail_checkout_dot():
    assert gpg.main(["--command", "git checkout ."]) == 1


# ---- file scan + JSON + edge --------------------------------------------
def test_file_scan_mixed(tmp_path):
    f = tmp_path / "cmds.txt"
    f.write_text(
        "# the core-agent tick\n"
        "git add programs/foo.py\n"
        "git commit -m 'v0.2.14'\n"
        "git push --force origin main\n"   # the offender
    )
    out = tmp_path / "r.json"
    rc = gpg.main([str(f), "--json", str(out)])
    assert rc == 1
    rep = json.loads(out.read_text())
    assert rep["passed"] is False
    assert rep["scanned"] == 3   # 3 non-comment commands
    assert rep["violations"][0]["rule_id"] == "push_force"
    assert rep["violations"][0]["line_no"] == 4


def test_missing_file_is_honest_error(tmp_path):
    # absent input => rc 2, never a vacuous PASS.
    assert gpg.main([str(tmp_path / "nope.txt")]) == 2


def test_empty_input_is_vacuous_not_verified(tmp_path):
    f = tmp_path / "empty.txt"
    f.write_text("\n# only a comment\n\n")
    out = tmp_path / "r.json"
    rc = gpg.main([str(f), "--json", str(out)])
    assert rc == 0
    rep = json.loads(out.read_text())
    # honest: nothing scanned, flagged vacuous so it can't pose as verified.
    assert rep["vacuous"] is True
    assert rep["scanned"] == 0


def test_no_args_is_error():
    assert gpg.main([]) == 2
