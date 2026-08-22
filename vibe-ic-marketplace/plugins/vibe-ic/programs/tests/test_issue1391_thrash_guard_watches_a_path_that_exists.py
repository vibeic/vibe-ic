"""A guard that watches a path which does not exist says PASS to everything.

`picker_fixture_thrash_guard.py` is the issue-#5 anti-thrash gate, wired into
`tools/ci/pre_commit_check.sh:156`. It feeds `_FIXTURE_TEST_REL` straight to
`git diff --cached -- <path>`. Git does not complain about a pathspec that
matches nothing; it returns an EMPTY DIFF. Empty diff -> no flips -> rc=0.

So the failure mode is not a crash. It is a permanent green:

    _FIXTURE_TEST_REL = "vibe-ic-marketplace/plugins/vibe-ic/tests/..."

That directory has NEVER been tracked in this repository -- `git log --all
--diff-filter=A` returns nothing for it, and the file has always lived under
`programs/tests/`. Measured on 75776dbbb, with a real `"aes": "AES" ->
"AES-XTS"` flip STAGED in the real file:

    PASS: no fixture _EXPECTED flips in staged diff        rc=0

The gate had been structurally incapable of firing for its whole life.

WHY THE EXISTING UNIT TEST COULD NOT CATCH IT
---------------------------------------------
`test_picker_fixture_thrash_guard.py` is thorough about the LOGIC -- eight
cases, pure helpers plus end-to-end subprocess. It builds its temp repo like
this:

    FIXTURE_REL = mod._FIXTURE_TEST_REL
    fix = repo / FIXTURE_REL
    fix.parent.mkdir(parents=True, exist_ok=True)

It MANUFACTURES whatever directory the constant names, then proves the logic
against what it just built. Every possible value of that constant passes such
a test. It is the fixture-the-author-wrote shape: the checker never meets a
real artefact.

This file is the other half. It resolves the constant against the REAL tree,
and it derives the expected location INDEPENDENTLY (from `git ls-files`), so
it cannot be satisfied by agreeing with the thing it is checking.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import picker_fixture_thrash_guard as mod

_REPO_ROOT = Path(__file__).resolve().parents[5]
_PROG = Path(__file__).resolve().parent.parent / "picker_fixture_thrash_guard.py"

#: Bounded well under the 60 s inner-subprocess ceiling (180 s harness // 3).
_GIT_TIMEOUT = 20


def _git(*args: str, cwd: Path = _REPO_ROOT) -> str:
    """Run git, and FAIL LOUDLY rather than return an empty string.

    An empty result here is not a zero -- it is 'could not look', and this
    whole file exists because those two were once recorded the same way.
    """
    out = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                         text=True, timeout=_GIT_TIMEOUT)
    assert out.returncode == 0, (
        f"git {' '.join(args)} failed rc={out.returncode}; this is NOT evidence "
        f"of an empty result, it is evidence the check could not run.\n"
        f"stderr: {out.stderr.strip()}")
    return out.stdout


def _tracked_fixture_test_path() -> str:
    """Where `test_phase1_fixtures_regression.py` ACTUALLY is, per git.

    Derived from the index, never from `mod._FIXTURE_TEST_REL` -- that is the
    value under test.
    """
    hits = [ln for ln in _git("ls-files").splitlines()
            if ln.endswith("/test_phase1_fixtures_regression.py")]
    assert len(hits) == 1, (
        f"expected exactly one tracked test_phase1_fixtures_regression.py, "
        f"found {len(hits)}: {hits}")
    return hits[0]


def test_the_watched_path_is_tracked_in_this_repository():
    """The constant must name a file git actually has."""
    watched = mod._FIXTURE_TEST_REL
    tracked = _git("ls-files", "--", watched).strip()
    assert tracked, (
        f"picker_fixture_thrash_guard._FIXTURE_TEST_REL = {watched!r}\n"
        f"is not tracked. It is passed to `git diff --cached -- <path>`, which "
        f"returns an EMPTY diff for a pathspec matching nothing -- so the gate "
        f"reports `PASS: no fixture _EXPECTED flips` for every commit forever.\n"
        f"The tracked file is at: {_tracked_fixture_test_path()}")


def test_the_watched_path_is_the_file_that_actually_holds_expected():
    """Existing is not enough -- it has to be the RIGHT file."""
    assert mod._FIXTURE_TEST_REL == _tracked_fixture_test_path()
    body = (_REPO_ROOT / mod._FIXTURE_TEST_REL).read_text(encoding="utf-8")
    assert "_EXPECTED" in body, (
        f"{mod._FIXTURE_TEST_REL} carries no `_EXPECTED` dict, so watching it "
        f"cannot detect a fixture flip.")


def test_the_phantom_tests_directory_is_still_absent():
    """Pins the premise, so this file stays honest if the layout ever changes.

    If someone genuinely adds `plugins/vibe-ic/tests/`, the reasoning above
    stops holding and this test says so instead of quietly passing.
    """
    phantom = "vibe-ic-marketplace/plugins/vibe-ic/tests/"
    tracked = _git("ls-files", "--", phantom).strip()
    assert not tracked, (
        f"{phantom} now exists ({len(tracked.splitlines())} tracked file(s)). "
        f"Re-read this module's docstring -- its premise has changed.")


def test_a_real_staged_flip_is_rejected(tmp_path):
    """THE TEETH TEST. Build the repo at the REAL path, stage a REAL flip.

    The layout comes from `_tracked_fixture_test_path()`, not from the
    constant, so pointing the constant anywhere else makes this go red.
    """
    rel = _tracked_fixture_test_path()
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (("init", "-q"), ("config", "user.email", "t@t.com"),
                 ("config", "user.name", "t")):
        _git(*args, cwd=repo)

    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('_EXPECTED = {\n    "aes":  "AES",\n}\n')
    _git("add", rel, cwd=repo)
    _git("commit", "-qm", "init", cwd=repo)

    target.write_text('_EXPECTED = {\n    "aes":  "AES-XTS",\n}\n')
    _git("add", rel, cwd=repo)

    msg = tmp_path / "COMMIT_MSG"
    msg.write_text("no acknowledgment line here\n")
    out = subprocess.run(
        [sys.executable, str(_PROG), "--repo-root", str(repo),
         "--commit-msg-file", str(msg)],
        capture_output=True, text=True, timeout=_GIT_TIMEOUT)

    assert out.returncode == 1, (
        f"an unacknowledged `aes: AES -> AES-XTS` flip was staged at the real "
        f"tracked location and the guard did not reject it (rc={out.returncode}).\n"
        f"stdout:\n{out.stdout}")
    assert "aes" in out.stdout


def test_an_acknowledged_flip_is_still_allowed(tmp_path):
    """The paired direction: teeth, not a blanket refusal."""
    rel = _tracked_fixture_test_path()
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (("init", "-q"), ("config", "user.email", "t@t.com"),
                 ("config", "user.name", "t")):
        _git(*args, cwd=repo)

    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('_EXPECTED = {\n    "aes":  "AES",\n}\n')
    _git("add", rel, cwd=repo)
    _git("commit", "-qm", "init", cwd=repo)

    target.write_text('_EXPECTED = {\n    "aes":  "AES-XTS",\n}\n')
    _git("add", rel, cwd=repo)

    msg = tmp_path / "COMMIT_MSG"
    msg.write_text("bump\n\nfixture-flip-acknowledged: aes: AES -> AES-XTS\n")
    out = subprocess.run(
        [sys.executable, str(_PROG), "--repo-root", str(repo),
         "--commit-msg-file", str(msg)],
        capture_output=True, text=True, timeout=_GIT_TIMEOUT)

    assert out.returncode == 0, (
        f"an ACKNOWLEDGED flip must pass; rc={out.returncode}\n{out.stdout}")
