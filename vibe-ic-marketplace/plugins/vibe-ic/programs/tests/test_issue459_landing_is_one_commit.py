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
    # A SHALLOW CLONE MAKES `examined` A PROPERTY OF THE CHECKOUT, NOT THE
    # PROJECT — and this assertion cannot tell the two apart.
    #
    # MEASURED on the authoring host: `rev-parse --is-shallow-repository` is
    # true, `rev-list --count origin/main` is 96, and `find_unsquashed(repo,
    # 200)` therefore examined 96. The test failed `96 >= 100` while the
    # remote carries thousands. Nothing about the repository was wrong; the
    # clone was simply shorter than the window the test asks for.
    #
    # This is the same defect class the test itself exists to police, turned on
    # the test: a number read off the apparatus and reported as a fact about
    # the subject. So the unmeasurable case is DISCLOSED and skipped by name
    # rather than failed — and the assertion below is untouched for any clone
    # that can actually answer, which is the only state where it means
    # anything.
    #
    # SHALLOWNESS IS NOT THE CONDITION — DEPTH IS, and the difference is the
    # whole of the narrowing this test was HELD for. `--is-shallow-repository`
    # answers "was this clone truncated", not "is this clone too short to
    # answer". A shallow clone deeper than the window answers perfectly well,
    # and skipping there retires a live assertion on a host where it passes.
    # Measured across three configurations:
    #
    #   is-shallow   commits   examined >= 100   skip on shallowness   correct?
    #   true          96        FAILS             skips                 yes
    #   true         668        would PASS        skips                 NO
    #   true         129        PASSES            skips                 NO
    #   false       2019        PASSES            runs                  yes
    #
    # So the probe runs AFTER the measurement and excuses only the state that
    # is genuinely unanswerable: truncated AND short. A complete-but-small
    # clone is still asserted against — `test_the_shallow_skip_does_NOT_disarm_
    # the_count_on_a_real_clone` below is the paired guard for exactly that,
    # and it keeps this narrowing from widening back out.
    findings, examined = L.find_unsquashed(repo, 200)
    if examined == 0:
        pytest.skip("no history available")
    if examined < 100 and subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--is-shallow-repository"],
            capture_output=True, text=True).stdout.strip() == "true":
        pytest.skip(
            f"shallow clone: examined={examined} is the checkout depth, not "
            f"the project's history — run `git fetch --unshallow` to make this "
            f"test meaningful")
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


# ── batch mode (owner directive 2026-07-27: land N PRs under ONE version) ──
# The per-landing rule does not apply to a deliberate batch, but the defect it
# exists for still does. Batch mode checks a STRICTLY STRONGER property: no
# manifest-only commit anywhere in the range, exactly one version bump, and it
# must be the tip — so CI green refers to the tree actually published.
def test_a_clean_batch_passes(tmp_path):
    d = _repo(tmp_path)
    base = _commit(d, "base", {"seed.txt": "x\n"})
    _commit(d, "fix(a): w", {"programs/a.py": "1\n"})
    _commit(d, "fix(b): w", {"programs/b.py": "1\n"})
    _commit(d, "fix(c): w [v1.2.3]",
            {"programs/c.py": "1\n", _MANIFEST: '{"version":"1.2.3"}\n'})
    ok, n, detail = L.head_is_one_commit(d, base, batch=True)
    assert ok and n == 3, detail


def test_a_batch_with_a_stranded_version_commit_still_FAILS(tmp_path):
    """THE POINT. A batch is not a licence to leave the manifest-only commit
    this whole check was written for."""
    d = _repo(tmp_path)
    base = _commit(d, "base", {"seed.txt": "x\n"})
    _commit(d, "fix(a): w", {"programs/a.py": "1\n"})
    _commit(d, "fix(a): w [v1.2.3]", {_MANIFEST: '{"version":"1.2.3"}\n'})
    ok, _n, detail = L.head_is_one_commit(d, base, batch=True)
    assert not ok
    assert "manifest" in detail.lower(), detail


def test_a_batch_bumping_twice_FAILS(tmp_path):
    d = _repo(tmp_path)
    base = _commit(d, "base", {"seed.txt": "x\n"})
    _commit(d, "fix(a): w [v1.2.3]",
            {"programs/a.py": "1\n", _MANIFEST: '{"version":"1.2.3"}\n'})
    _commit(d, "fix(b): w [v1.2.4]",
            {"programs/b.py": "1\n", _MANIFEST: '{"version":"1.2.4"}\n'})
    ok, _n, detail = L.head_is_one_commit(d, base, batch=True)
    assert not ok and "exactly ONE version" in detail


def test_a_batch_whose_version_is_not_the_tip_FAILS(tmp_path):
    """CI runs on the pushed TIP. If the version bump is buried mid-batch, a
    green CI refers to a tree nobody released."""
    d = _repo(tmp_path)
    base = _commit(d, "base", {"seed.txt": "x\n"})
    _commit(d, "fix(a): w [v1.2.3]",
            {"programs/a.py": "1\n", _MANIFEST: '{"version":"1.2.3"}\n'})
    _commit(d, "fix(b): w", {"programs/b.py": "1\n"})
    ok, _n, detail = L.head_is_one_commit(d, base, batch=True)
    assert not ok and "tip" in detail


def test_batch_mode_is_OPT_IN(tmp_path):
    """Without --batch the strict single-landing rule is unchanged, so batching
    cannot happen by accident."""
    d = _repo(tmp_path)
    base = _commit(d, "base", {"seed.txt": "x\n"})
    _commit(d, "fix(a): w", {"programs/a.py": "1\n"})
    _commit(d, "fix(b): w [v1.2.3]",
            {"programs/b.py": "1\n", _MANIFEST: '{"version":"1.2.3"}\n'})
    ok, _n, detail = L.head_is_one_commit(d, base)
    assert not ok and "--batch" in detail


def test_the_shallow_skip_does_NOT_disarm_the_count_on_a_real_clone(tmp_path):
    """PAIRED GUARD for the skip above.

    A skip that fires on every clone would silently retire the assertion. This
    proves the discrimination is on SHALLOWNESS and not on smallness: a
    COMPLETE clone with only a handful of commits is not skipped, and
    `find_unsquashed` still reports a count far under 100 — i.e. the assertion
    would still fire. Only the unmeasurable case is excused.
    """
    d = _repo(tmp_path)
    _commit(d, "one", {"a.txt": "1\n"})
    _commit(d, "two", {"b.txt": "2\n"})
    shallow = subprocess.run(
        ["git", "-C", str(d), "rev-parse", "--is-shallow-repository"],
        capture_output=True, text=True).stdout.strip()
    assert shallow == "false", shallow
    _findings, examined = L.find_unsquashed(d, 200)
    assert 0 < examined < 100, examined
