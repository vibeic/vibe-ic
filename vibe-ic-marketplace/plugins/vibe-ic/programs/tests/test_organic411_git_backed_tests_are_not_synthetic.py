#!/usr/bin/env python3
"""PR #411 follow-up, owed publicly on that review and paid here.

`real_artefact_test_backing_check` knew two ways a test can be driven by a
real checked-in artefact — the `_hostpaths` accessors, and a hand-rolled
sweep of a repo data root. There is a third: reaching the repository through
GIT. `test_f10_gitignore_formal_transcript_shippable.py` asks
`git rev-parse --show-toplevel` and then `git check-ignore` / `git ls-files`,
which is not merely a real way to test an ignore rule — it is the only
FAITHFUL one, because the rule's meaning IS what git computes. The program
reported that change `0 of 40` backed, i.e. "every test here is a fixture the
author typed", about tests driving the actual `.gitignore`.

THE DISCRIMINATOR IS `init`. A test that builds a throwaway repo in
`tmp_path` is a fixture no matter how much git it runs, and the tests for
#416 in this same repo are exactly that. Excluding them under-claims when a
test does BOTH — the conservative direction, because over-claiming "real" is
what would let a fixture-only change look backed, which is the whole failure
this program exists to prevent.

MEASURED repo-wide before landing: 1797 test modules, 18254 tests, REAL
149 → 158. Two modules move, both of them gitignore tests. No other module
is reclassified.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import real_artefact_test_backing_check as R  # noqa: E402


def _mod(tmp_path: Path, body: str) -> dict:
    p = tmp_path / "test_x.py"
    p.write_text(textwrap.dedent(body))
    return R.classify_module(p)


def test_a_test_that_asks_git_about_the_real_repo_is_real(tmp_path):
    rep = _mod(tmp_path, '''
        import subprocess

        def test_rule_is_honoured():
            root = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                  capture_output=True, text=True).stdout
            r = subprocess.run(["git", "check-ignore", "a.log"],
                               capture_output=True, text=True)
            assert r.returncode == 0, root
    ''')
    assert rep["real"] == ["test_rule_is_honoured [git repo]"]


def test_a_scratch_repo_built_in_tmp_path_stays_synthetic(tmp_path):
    """The paired half, and the load-bearing one. `git init` in a temp dir is
    a fixture the author typed, however much git it then runs — calling it
    real is the direction that misleads a reviewer."""
    rep = _mod(tmp_path, '''
        import subprocess

        def test_scratch(tmp_path):
            subprocess.run(["git", "init", "-q", str(tmp_path)])
            subprocess.run(["git", "-C", str(tmp_path), "ls-files"])
            assert True
    ''')
    assert rep["synthetic"] == ["test_scratch"]
    assert rep["real"] == []


def test_a_clone_is_scratch_too(tmp_path):
    rep = _mod(tmp_path, '''
        import subprocess

        def test_c(tmp_path):
            subprocess.run(["git", "clone", "x", str(tmp_path)])
            subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"])
            assert True
    ''')
    assert rep["real"] == []


def test_git_alone_is_not_enough(tmp_path):
    """Naming `git` without a repo-state read is not evidence of anything —
    otherwise a test that merely mentions the word gets counted."""
    rep = _mod(tmp_path, '''
        import subprocess

        def test_v():
            subprocess.run(["git", "--version"])
            assert True
    ''')
    assert rep["real"] == []


def test_a_helper_that_hides_the_git_call_still_counts(tmp_path):
    """The accessor and sweep shapes both follow helpers; this must too, or
    the idiomatic `_repo_root()` factoring defeats it."""
    rep = _mod(tmp_path, '''
        import subprocess

        def _root():
            return subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                  capture_output=True, text=True).stdout

        def test_uses_helper():
            assert _root()
    ''')
    assert rep["real"] == ["test_uses_helper [git repo]"]


def test_the_module_that_owed_this_fix_is_now_backed():
    """The concrete case named on PR #411: reported 0 of 40 backed while
    driving the real `.gitignore`."""
    m = _PROGRAMS / "tests" / "test_f10_gitignore_formal_transcript_shippable.py"
    if not m.is_file():
        import pytest
        pytest.skip("module not present")
    rep = R.classify_module(m)
    assert rep["synthetic"] == [], rep["synthetic"]
    assert all("[git repo]" in r for r in rep["real"]), rep["real"]


def test_the_git_shape_does_not_reclassify_this_repos_own_scratch_git_tests():
    """Regression guard on the conservative direction, using a real module:
    the #416 tests run a lot of git, all of it on repos they create."""
    m = _PROGRAMS / "tests" / \
        "test_organic416_nda_scan_anchors_to_the_repo_root.py"
    if not m.is_file():
        import pytest
        pytest.skip("module not present")
    rep = R.classify_module(m)
    assert rep["real"] == [], rep["real"]


def test_a_test_module_that_exists_only_at_HEAD_is_still_classified(tmp_path):
    """Found reviewing #425, which adds a 462-line test module: the checker
    reported "no test module added or modified".

    `_changed_test_modules` listed the changed paths from the DIFF and then
    kept only those satisfying `f.is_file()` in the WORKING TREE. Reviewing a
    PR branch from a main checkout, the added file is in the ref and not on
    disk, so it was dropped — and the checker SKIPPED on exactly the changes
    it exists to judge. Same defect as #416 and #414: the tree you are
    standing in is not the change under review.
    """
    repo = tmp_path / "r"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(repo), "config", k, v], check=True)
    (repo / "seed.txt").write_text("x\n")
    subprocess.run(["git", "-C", str(repo), "add", "seed.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
    base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()

    d = repo / "programs" / "tests"
    d.mkdir(parents=True)
    (d / "test_added.py").write_text(
        "def test_x():\n"
        "    open('benchmark-data/x').read_text()\n")
    subprocess.run(["git", "-C", str(repo), "add",
                    "programs/tests/test_added.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "add test"],
                   check=True)
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    # the working tree no longer holds it — exactly the PR-review situation
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", base], check=True)
    assert not (d / "test_added.py").is_file()

    mods = R._changed_test_modules(repo, base, head)
    assert len(mods) == 1, "a module present only at HEAD was dropped"
    rep = R.classify_module(mods[0])
    assert rep["tests"] == ["test_x"], rep
