#!/usr/bin/env python3
"""Tests for acceptance_control_check (vibe-ic#401).

The control a change is measured against must be the state BEFORE the
feature. Validating round N against round N-1 measures the branch against
itself and makes a change that contributes nothing look like it contributes
a lot.

Paired throughout: a checker that flagged every declared control would pass
the headline case, and one that flagged none would pass its inverse.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import acceptance_control_check as C  # noqa: E402

PROG = _PROGRAMS / "acceptance_control_check.py"


def _repo(tmp_path: Path):
    """A repo with `main` and a two-commit feature branch off it."""
    g = lambda *a: subprocess.run(["git", "-C", str(tmp_path), *a],
                                  capture_output=True, text=True, check=False)
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)],
                   check=True)
    g("config", "user.email", "t@t"); g("config", "user.name", "t")
    (tmp_path / "a.txt").write_text("base\n")
    g("add", "a.txt"); g("commit", "-qm", "base")
    base = g("rev-parse", "HEAD").stdout.strip()
    g("checkout", "-q", "-b", "feature")
    g("commit", "-q", "--allow-empty", "-m", "round 1")
    r1 = g("rev-parse", "HEAD").stdout.strip()
    g("commit", "-q", "--allow-empty", "-m", "round 2")
    head = g("rev-parse", "HEAD").stdout.strip()
    return tmp_path, base, r1, head


def test_a_branch_local_control_is_flagged(tmp_path):
    repo, base, r1, head = _repo(tmp_path)
    rep = C.audit(repo, base, head, f"Evidence measured against {r1}.")
    assert rep["findings"], rep
    assert rep["findings"][0]["sha"] == r1[:9]


def test_the_merge_base_itself_is_accepted(tmp_path):
    """The paired half. Flagging every declared control would satisfy the
    case above and make the checker useless."""
    repo, base, r1, head = _repo(tmp_path)
    rep = C.audit(repo, base, head, f"Evidence measured against {base}.")
    assert rep["findings"] == [], rep
    assert rep["declared"] == [base]


def test_the_correct_control_is_always_reported(tmp_path):
    """The working half today: measured over 120 commits in the real repo,
    almost none declare a control, so the SHA is what this gate is for."""
    repo, base, r1, head = _repo(tmp_path)
    rep = C.audit(repo, base, head, "no control named here")
    assert rep["correct_control"].startswith(base[:9])
    assert rep["declared"] == [] and rep["findings"] == []


def test_an_unresolvable_ref_is_silence_not_a_finding(tmp_path):
    """A message may name a ref that lives on another host. Inventing a
    verdict about it would be worse than saying nothing."""
    repo, base, r1, head = _repo(tmp_path)
    rep = C.audit(repo, base, head, "measured against deadbeefdeadbeef")
    assert rep["findings"] == []


def test_the_explicit_CONTROL_line_is_read(tmp_path):
    repo, base, r1, head = _repo(tmp_path)
    rep = C.audit(repo, base, head, f"body\n\nCONTROL: {r1}\n")
    assert rep["findings"] and rep["findings"][0]["declared"] == r1


def test_prose_that_merely_says_control_is_not_a_ref():
    """`control: a gutted fixture must FAIL rc1` appears in this repo's real
    history. A parse that treated that as a ref would manufacture findings."""
    assert C.declared_controls(
        "control: a gutted fixture must FAIL rc1") == []


def test_it_never_blocks(tmp_path):
    repo, base, r1, head = _repo(tmp_path)
    r = subprocess.run(
        [sys.executable, str(PROG), "--repo", str(repo), "--base", base,
         "--head", head, "--message", f"against {r1}"],
        capture_output=True, text=True)
    assert r.returncode == 0
    assert "ADVISORY" in r.stdout and "NOT valid" in r.stdout


def test_an_unresolvable_merge_base_is_a_SKIP(tmp_path):
    repo, base, r1, head = _repo(tmp_path)
    r = subprocess.run(
        [sys.executable, str(PROG), "--repo", str(repo),
         "--base", "no/such/ref", "--head", head],
        capture_output=True, text=True)
    assert r.returncode == 2 and "SKIP" in r.stdout


def test_the_source_carries_no_non_ascii():
    """A first draft of this program printed a Chinese word in its own
    output. Shipped source in this repo is English."""
    src = PROG.read_text()
    bad = [c for c in src if ord(c) > 0x2FFF]
    assert not bad, f"non-ASCII CJK in shipped source: {set(bad)}"
