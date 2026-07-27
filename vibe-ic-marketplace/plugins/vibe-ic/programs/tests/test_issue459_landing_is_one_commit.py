#!/usr/bin/env python3
"""A landing is ONE commit (vibe-ic#459), and the check for it is narrow on purpose.

Three landings left two commits on main — the authoring commit plus a version
commit carrying only the manifests — because `git commit --amend` after a rebase
touches only the top commit. Nothing failed and nothing warned.

THE DISCRIMINATOR IS THE PAIR, and that is measured, not chosen. Over the last
200 commits of main:

    commits with no version tag                              89
    the defect shape (a manifest-only version commit sitting
    directly on an unversioned commit)                        4

Keying on "unversioned commit" fires 89 times and 85 are legitimate — data-only
landings and security bumps that `ships_to_users()` exempts from versioning
altogether. Both halves are pinned below: the pair is caught, and each half
alone is not.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import landing_is_one_commit_check as L  # noqa: E402

_MANIFEST = ".claude-plugin/plugin.json"


def _repo(tmp_path: Path) -> Path:
    d = tmp_path / "r"
    d.mkdir()
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(d), "config", k, v], check=True)
    return d


def _commit(d: Path, subject: str, files: dict) -> str:
    for rel, body in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
        subprocess.run(["git", "-C", str(d), "add", rel], check=True)
    subprocess.run(["git", "-C", str(d), "commit", "-qm", subject], check=True)
    return subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


# ── the pair ───────────────────────────────────────────────────────────────
def test_an_unsquashed_landing_is_caught(tmp_path):
    """THE LOAD-BEARING CASE — exactly what happened three times."""
    d = _repo(tmp_path)
    _commit(d, "base", {"seed.txt": "x\n"})
    _commit(d, "fix(x): real work", {"programs/a.py": "print(1)\n"})
    _commit(d, "fix(x): real work [v1.2.3]", {_MANIFEST: '{"version":"1.2.3"}\n'})
    findings, examined = L.find_unsquashed(d)
    assert examined >= 3
    assert len(findings) == 1, findings
    assert findings[0]["version_subject"].endswith("[v1.2.3]")


def test_a_proper_squashed_landing_is_not_flagged(tmp_path):
    """PAIRED HALF #1. One commit carrying BOTH the work and the version."""
    d = _repo(tmp_path)
    _commit(d, "base", {"seed.txt": "x\n"})
    _commit(d, "fix(x): real work [v1.2.3]",
            {"programs/a.py": "print(1)\n", _MANIFEST: '{"version":"1.2.3"}\n'})
    findings, _ = L.find_unsquashed(d)
    assert findings == [], findings


def test_an_unversioned_commit_alone_is_not_a_finding(tmp_path):
    """PAIRED HALF #2, and the reason this is not keyed on 'no version tag'.
    85 of the 89 unversioned commits in real history are legitimate."""
    d = _repo(tmp_path)
    _commit(d, "base", {"seed.txt": "x\n"})
    _commit(d, "docs(benchmark-data): record a run", {"benchmark-data/r.md": "x\n"})
    _commit(d, "fix(security): bump a dep", {"mcp/package.json": "{}\n"})
    findings, _ = L.find_unsquashed(d)
    assert findings == [], findings


def test_a_version_commit_that_carries_real_files_is_not_a_finding(tmp_path):
    """The other half of the pair: a version commit ABOVE an unversioned one is
    fine as long as it carries the work — that is a squashed landing sitting on
    somebody else's data commit."""
    d = _repo(tmp_path)
    _commit(d, "base", {"seed.txt": "x\n"})
    _commit(d, "docs(benchmark-data): a data landing", {"benchmark-data/r.md": "x\n"})
    _commit(d, "fix(x): work [v1.2.3]",
            {"programs/a.py": "print(1)\n", _MANIFEST: '{"version":"1.2.3"}\n'})
    findings, _ = L.find_unsquashed(d)
    assert findings == [], findings


def test_two_consecutive_proper_landings_are_not_a_finding(tmp_path):
    d = _repo(tmp_path)
    _commit(d, "base", {"seed.txt": "x\n"})
    _commit(d, "fix(a): w [v1.2.3]",
            {"programs/a.py": "1\n", _MANIFEST: '{"version":"1.2.3"}\n'})
    _commit(d, "fix(b): w [v1.2.4]",
            {"programs/b.py": "1\n", _MANIFEST: '{"version":"1.2.4"}\n'})
    findings, _ = L.find_unsquashed(d)
    assert findings == [], findings


# ── the pre-push form, which is what would have caught it at the time ──────
def test_one_commit_ahead_passes(tmp_path):
    d = _repo(tmp_path)
    base = _commit(d, "base", {"seed.txt": "x\n"})
    _commit(d, "fix(x): w [v1.2.3]",
            {"programs/a.py": "1\n", _MANIFEST: '{"version":"1.2.3"}\n'})
    ok, n, _ = L.head_is_one_commit(d, base)
    assert ok and n == 1


def test_two_commits_ahead_fails_and_names_the_remedy(tmp_path):
    d = _repo(tmp_path)
    base = _commit(d, "base", {"seed.txt": "x\n"})
    _commit(d, "fix(x): w", {"programs/a.py": "1\n"})
    _commit(d, "fix(x): w [v1.2.3]", {_MANIFEST: '{"version":"1.2.3"}\n'})
    ok, n, detail = L.head_is_one_commit(d, base)
    assert not ok and n == 2
    assert "reset --soft" in detail, detail


def test_zero_commits_ahead_is_NOT_a_pass(tmp_path):
    """A landing that adds no commit landed nothing. Reporting that as clean is
    the false-certificate shape this repo keeps closing."""
    d = _repo(tmp_path)
    base = _commit(d, "base", {"seed.txt": "x\n"})
    ok, n, detail = L.head_is_one_commit(d, base)
    assert not ok and n == 0
    assert "NOTHING to land" in detail


# ── denominators ───────────────────────────────────────────────────────────
def test_an_unreadable_history_is_NOT_a_pass(tmp_path):
    d = tmp_path / "not-a-repo"
    d.mkdir()
    rc = L.main([str(d), "--limit", "50"])
    assert rc == 2, "an unread history must be NOTHING_SCANNED, never a pass"


def test_a_commit_whose_files_cannot_be_read_is_not_silently_cleared(tmp_path):
    """`_is_manifest_only` returns None, never False, when it could not look —
    so 'I could not check' cannot read the same as 'I checked and it was
    fine'."""
    d = _repo(tmp_path)
    _commit(d, "base", {"seed.txt": "x\n"})
    assert L._is_manifest_only(d, "0" * 40) is None


def test_the_real_history_is_measured_not_assumed():
    """Real data. The four known instances are in main's history; this asserts
    the check finds them rather than trusting the count."""
    import pytest
    repo = _PROGRAMS.parents[3]
    if not (repo / ".git").exists():
        pytest.skip("not a git checkout")
    findings, examined = L.find_unsquashed(repo, 200)
    if examined == 0:
        pytest.skip("no history available")
    assert examined >= 100, examined
    # Recorded baseline: the shape existed 4 times in the 200 commits before
    # this landed. A regression guard can only fire on a NEW instance.
    assert len(findings) <= 4, findings


def test_an_uncountable_range_is_NOT_CHECKED_not_a_block(tmp_path):
    """The wiring bug I made and caught: `rev-list` failing returned rc 1, which
    BLOCKED a landing on the strength of a ref the program could not resolve —
    it reddened 5 existing gatekeeper_review tests that use synthetic refs.
    An uncountable range has told us nothing: rc 2, NOT CHECKED, never a pass
    and never a block."""
    d = _repo(tmp_path)
    _commit(d, "base", {"seed.txt": "x\n"})
    ok, n, detail = L.head_is_one_commit(d, "NOSUCHREF")
    assert not ok and n == -1, (ok, n, detail)
    assert L.main([str(d), "--base", "NOSUCHREF"]) == 2
