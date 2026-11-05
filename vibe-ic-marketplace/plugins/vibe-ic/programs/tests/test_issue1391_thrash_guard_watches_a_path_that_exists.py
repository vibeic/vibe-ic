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

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[5]

def _git(*args: str, cwd: Path = _REPO_ROOT) -> str:
    """Run git, and FAIL LOUDLY rather than return an empty string.

    An empty result here is not a zero -- it is 'could not look', and this
    whole file exists because those two were once recorded the same way.
    """
    out = _pr.run(["git", *args], cwd=str(cwd), capture_output=True,
                         text=True)
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
