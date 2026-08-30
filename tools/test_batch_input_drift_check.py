#!/usr/bin/env python3
"""Tests for batch_input_drift_check — built on real git repos, never on stubs.

The thing under test is a claim ABOUT a git graph, so a stubbed graph would test
the stub. Each test builds a throwaway repo with a real `origin`.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import batch_input_drift_check as M  # noqa: E402


def _g(repo, *args, **kw):
    return subprocess.run(["git", "-C", str(repo)] + list(args),
                          capture_output=True, text=True, check=kw.get("check", True))


def _repo(tmp_path):
    """An `origin` bare repo plus a working clone, with one commit on main."""
    bare, work = tmp_path / "origin.git", tmp_path / "work"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)],
                   capture_output=True, check=True)
    subprocess.run(["git", "clone", str(bare), str(work)],
                   capture_output=True, check=True)
    _g(work, "config", "user.email", "t@t"); _g(work, "config", "user.name", "t")
    (work / "f.txt").write_text("base\n")
    _g(work, "add", "f.txt"); _g(work, "commit", "-m", "base")
    _g(work, "push", "-u", "origin", "main")
    return work


def _branch(work, name, content):
    _g(work, "checkout", "-q", "-b", name, "main")
    (work / f"{name.replace('/', '_')}.txt").write_text(content)
    _g(work, "add", "-A"); _g(work, "commit", "-m", f"work on {name}")
    _g(work, "push", "-q", "-u", "origin", name)
    return _g(work, "rev-parse", "HEAD").stdout.strip()


def _assemble(work, batch, subjects_and_branches):
    _g(work, "checkout", "-q", "-b", batch, "main")
    for subject, br in subjects_and_branches:
        _g(work, "merge", "--no-ff", "-m", subject, br)
    return _g(work, "rev-parse", "HEAD").stdout.strip()


def _run(work, batch):
    return M.main(["--base", "main", "--batch", batch, "--repo", str(work)])


def test_every_input_still_at_the_sha_the_batch_merged(tmp_path, capsys):
    w = _repo(tmp_path)
    _branch(w, "next/a", "a"); _branch(w, "next/b", "b")
    _assemble(w, "land/x", [("merge next/a", "next/a"), ("merge next/b", "next/b")])
    assert _run(w, "land/x") == 0
    assert "Every input is still at the sha the batch merged" in capsys.readouterr().out


def test_an_input_that_moved_is_named_with_both_shas(tmp_path, capsys):
    w = _repo(tmp_path)
    _branch(w, "next/a", "a"); was = _branch(w, "next/b", "b")
    _assemble(w, "land/x", [("merge next/a", "next/a"), ("merge next/b", "next/b")])
    _g(w, "checkout", "-q", "next/b")
    (w / "next_b.txt").write_text("b2"); _g(w, "add", "-A"); _g(w, "commit", "-m", "after the freeze")
    now = _g(w, "rev-parse", "HEAD").stdout.strip(); _g(w, "push", "-q", "origin", "next/b")
    assert _run(w, "land/x") == 1
    out = capsys.readouterr().out
    assert "MOVED   next/b" in out and was[:9] in out and now[:9] in out
    assert "next/a" not in out.split("MOVED")[1] if "MOVED" in out else True


def test_a_branch_merged_TWICE_and_unmoved_since_the_LATEST_merge_is_not_a_mover(
        tmp_path, capsys):
    """REGRESSION. Keyed on the tip, a branch the batch merged twice appeared as
    two inputs and the OLDER tip always differed from the remote -- a false
    MOVED, measured on a real 107-input batch as 36 movers where there were 9."""
    w = _repo(tmp_path)
    _branch(w, "next/a", "a")
    _g(w, "checkout", "-q", "land/x") if False else None
    _g(w, "checkout", "-q", "-b", "land/x", "main")
    _g(w, "merge", "--no-ff", "-m", "merge next/a", "next/a")
    _g(w, "checkout", "-q", "next/a")
    (w / "next_a.txt").write_text("a2"); _g(w, "add", "-A"); _g(w, "commit", "-m", "more")
    _g(w, "push", "-q", "origin", "next/a")
    _g(w, "checkout", "-q", "land/x")
    _g(w, "merge", "--no-ff", "-m", "catch-up: next/a", "next/a")
    assert _run(w, "land/x") == 0, capsys.readouterr().out


def test_a_subject_naming_no_branch_is_UNNAMED_and_does_not_pass(tmp_path, capsys):
    w = _repo(tmp_path)
    _branch(w, "next/a", "a")
    _assemble(w, "land/x", [("merge: bring this branch up to date", "next/a")])
    assert _run(w, "land/x") == 1
    out = capsys.readouterr().out
    assert "UNNAMED" in out and "Reported, not skipped" in out
    assert "a clean result over a partial scan is a partial result" in out.lower()


def test_a_name_that_resolves_to_nothing_is_UNRESOLVED_not_GONE(tmp_path, capsys):
    """It is EITHER a deleted branch OR a misparse, and the checker must not
    accuse anyone of the first when it cannot rule out the second."""
    w = _repo(tmp_path)
    _branch(w, "next/a", "a")
    _assemble(w, "land/x", [("merge next/a", "next/a")])
    _g(w, "push", "-q", "origin", "--delete", "next/a")
    assert _run(w, "land/x") == 1
    out = capsys.readouterr().out
    assert "UNRESOLVED next/a" in out
    assert "cannot tell them apart" in out
    assert "GONE" not in out


def test_a_batch_with_no_merges_is_UNDETERMINED_and_says_so(tmp_path, capsys):
    """rc 2, and it must NAME what it could not read -- 'nothing moved' over an
    empty scan is the liar this whole file exists to keep out."""
    w = _repo(tmp_path)
    _g(w, "checkout", "-q", "-b", "land/x", "main")
    (w / "f.txt").write_text("x"); _g(w, "add", "-A"); _g(w, "commit", "-m", "no merges here")
    assert _run(w, "land/x") == 2
    err = capsys.readouterr().err
    assert "UNDETERMINED" in err and "nothing was examined" in err


def test_the_name_is_recovered_from_all_four_subject_forms():
    f = M._name_from_subject
    assert f("catch-up: next/a (jtwo)") == "next/a"
    assert f("Merge remote-tracking branch 'origin/next/a' into land/x") == "next/a"
    assert f("Merge branch 'next/a' into land/x") == "next/a"
    assert f("merge next/a") == "next/a"
    # and the prose form must NOT capture a sentence's first word
    assert f("merge: bring this branch up to v1.11.70") is None
    assert f("jtwo: regenerate the derived artefacts") is None


def test_a_LANDED_batch_reports_drift_but_does_not_raise(tmp_path, capsys):
    """A landed batch answers truthfully and uselessly: its inputs carried on
    afterwards, which is development and not drift under a measurement.
    Measured on the previous real batch: 11 "MOVED" that mean only that. A true
    number read as an alarm is still a false alarm, so the tool says what its
    answer is ABOUT and returns 0."""
    w = _repo(tmp_path)
    was = _branch(w, "next/a", "a")
    _assemble(w, "land/x", [("merge next/a", "next/a")])
    # land it: main now contains the batch
    _g(w, "checkout", "-q", "main"); _g(w, "merge", "--no-ff", "-m", "land", "land/x")
    _g(w, "push", "-q", "origin", "main")
    # and the input carries on, as inputs do after a landing
    _g(w, "checkout", "-q", "next/a")
    (w / "next_a.txt").write_text("a2"); _g(w, "add", "-A"); _g(w, "commit", "-m", "carried on")
    _g(w, "push", "-q", "origin", "next/a")
    _g(w, "fetch", "-q", "origin")
    rc = M.main(["--base", "main~1", "--batch", "land/x", "--repo", str(w)])
    out = capsys.readouterr().out
    assert "it has LANDED" in out, out
    assert "MOVED   next/a" in out, out
    assert was[:9] in out
    assert rc == 0, f"a landed batch must report, not raise -- got {rc}\n{out}"


def test_an_UNLANDED_batch_with_the_same_drift_DOES_raise(tmp_path, capsys):
    """The control for the one above: identical drift, batch not landed, rc 1."""
    w = _repo(tmp_path)
    _branch(w, "next/a", "a")
    _assemble(w, "land/x", [("merge next/a", "next/a")])
    _g(w, "checkout", "-q", "next/a")
    (w / "next_a.txt").write_text("a2"); _g(w, "add", "-A"); _g(w, "commit", "-m", "moved")
    _g(w, "push", "-q", "origin", "next/a")
    rc = M.main(["--base", "main", "--batch", "land/x", "--repo", str(w)])
    out = capsys.readouterr().out
    assert "it has LANDED" not in out
    assert rc == 1, out
