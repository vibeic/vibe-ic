"""v1.9.16 — the landing gate stamped a tree that never existed.

`landing_worktree_is_clean_check` closed the BEFORE edge: it refuses when a
tracked file is modified at the moment the gate starts. It sits in the cheap
tier. The full tier then runs for minutes, reading the WORKTREE, and the stamp
written at the end names a COMMIT.

Measured on the v1.9.16 run of this repo:

    10:28:14   gate starts, tree clean, the cheap-tier check PASSES
    10:35:50   `mixed_signal_top_lvs_run.py` edited (#597, uncommitted)
    10:37:49   a new test file written
    10:41      targeted tests run; "ALL GATES PASS - stamped 9fd81bb45"

The 16 targeted files were selected from the COMMIT RANGE and executed against a
worktree carrying an unrelated uncommitted change. Both directions are wrong:
the edit could have broken something the batch is then blamed for, or repaired
something the batch would otherwise have failed on.

So the fingerprint is taken at the start and re-checked before the stamp.

THE ORDER IS THE FIX. A comparison that runs anywhere before the last suite
leaves exactly the window it exists to close, and a comparison that runs after
the stamp is written cannot withhold it. Both are asserted below, because the
program can be perfectly correct and wired into a place where it answers
nothing — the failure this repo keeps finding.

WHAT IT DOES NOT COVER, asserted nowhere and therefore stated here: an edit made
AND reverted inside the full tier leaves an identical fingerprint. The window
narrows from the whole expensive tier to an edit undone within it; only running
the gates on a private checkout removes it.
"""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
PROG = _PROGRAMS / "landing_worktree_is_clean_check.py"
_LAND_SH = _PROGRAMS.parents[3] / "tools" / "gatekeeper-land.sh"

RC_OK, RC_DIRTY, RC_CANNOT_MEASURE = 0, 1, 2


def _load():
    spec = importlib.util.spec_from_file_location(
        "landing_worktree_is_clean_check", PROG)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["landing_worktree_is_clean_check"] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load()


def _repo(tmp_path):
    """A real git repo carrying one of the SHIPPED_PATHS."""
    for cmd in (["init", "-q", "-b", "main"],
                ["config", "user.email", "t@t"],
                ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(tmp_path), *cmd], check=True,
                       capture_output=True, timeout=60)
    d = tmp_path / "tools"
    d.mkdir()
    (d / "a.sh").write_text("echo a\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "tools/a.sh"],
                   check=True, capture_output=True, timeout=60)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "base"],
                   check=True, capture_output=True, timeout=60)
    return tmp_path


def _run(repo, *extra):
    return subprocess.run([sys.executable, str(PROG), str(repo), *extra],
                          capture_output=True, text=True, timeout=30)


# ── the fingerprint answers "is this the same tree" ──────────────────────────
def test_an_unchanged_tree_fingerprints_the_same(tmp_path):
    r = _repo(tmp_path)
    assert M.fingerprint(r) == M.fingerprint(r)


def test_a_tracked_edit_moves_it(tmp_path):
    """The v1.9.16 case exactly: a tracked file edited while the gates run."""
    r = _repo(tmp_path)
    before = M.fingerprint(r)
    (r / "tools" / "a.sh").write_text("echo b\n", encoding="utf-8")
    assert M.fingerprint(r) != before


def test_an_added_untracked_file_moves_it(tmp_path):
    """pytest can collect a file that appears mid-run, so an addition counts as
    the tree moving even though the cheap-tier check ignores untracked files
    when deciding whether the LANDING is complete."""
    r = _repo(tmp_path)
    before = M.fingerprint(r)
    (r / "tools" / "new.sh").write_text("echo n\n", encoding="utf-8")
    assert M.fingerprint(r) != before


def test_a_new_commit_moves_it(tmp_path):
    """A clean tree at a different HEAD is a different tree."""
    r = _repo(tmp_path)
    before = M.fingerprint(r)
    (r / "tools" / "a.sh").write_text("echo b\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(r), "commit", "-qam", "x"], check=True,
                   capture_output=True, timeout=60)
    assert M.fingerprint(r) != before


def test_it_is_stable_across_a_pytest_run(tmp_path):
    """LOAD-BEARING for the untracked half. If tool droppings moved the
    fingerprint, the comparison would fail on every real run and be removed.
    `git status` drops whatever .gitignore covers, which is what keeps
    `__pycache__` out — asserted rather than assumed."""
    r = _repo(tmp_path)
    (r / "tools" / "t.py").write_text("def test_x():\n    assert True\n",
                                      encoding="utf-8")
    subprocess.run(["git", "-C", str(r), "add", "tools/t.py"], check=True,
                   capture_output=True, timeout=60)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "t"], check=True,
                   capture_output=True, timeout=60)
    (r / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(r), "add", ".gitignore"], check=True,
                   capture_output=True, timeout=60)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "ignore"], check=True,
                   capture_output=True, timeout=60)
    before = M.fingerprint(r)
    subprocess.run([sys.executable, "-m", "pytest", "-q", "tools/t.py"],
                   cwd=str(r), capture_output=True, timeout=60)
    assert M.fingerprint(r) == before


# ── the CLI refuses rather than passing ──────────────────────────────────────
def test_expect_against_a_matching_fingerprint_passes(tmp_path):
    r = _repo(tmp_path)
    fp = tmp_path / "fp.txt"
    assert _run(r, "--emit-fingerprint", str(fp)).returncode == RC_OK
    assert _run(r, "--expect-fingerprint", str(fp)).returncode == RC_OK


def test_expect_after_the_tree_moved_refuses(tmp_path):
    """A tracked edit that is COMMITTED leaves the tree clean, so the
    cheap-tier rule alone still passes — and the gate would stamp a tree its
    suites never read."""
    r = _repo(tmp_path)
    fp = tmp_path / "fp.txt"
    _run(r, "--emit-fingerprint", str(fp))
    (r / "tools" / "a.sh").write_text("echo moved\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(r), "commit", "-qam", "mid-run"],
                   check=True, capture_output=True, timeout=60)
    assert _run(r).returncode == RC_OK, "the tree is clean, so the old rule passes"
    got = _run(r, "--expect-fingerprint", str(fp))
    assert got.returncode == RC_DIRTY, got.stdout + got.stderr
    assert "MOVED" in got.stderr


def test_a_missing_fingerprint_file_is_not_read_as_agreement(tmp_path):
    """"I could not compare" and "they match" are different claims. Returning 0
    here would restore the hole in the one case where the emit step failed."""
    r = _repo(tmp_path)
    got = _run(r, "--expect-fingerprint", str(tmp_path / "never-written"))
    assert got.returncode == RC_CANNOT_MEASURE, got.stdout + got.stderr


def test_the_pre_existing_dirty_rule_is_unchanged(tmp_path):
    r = _repo(tmp_path)
    (r / "tools" / "a.sh").write_text("echo dirty\n", encoding="utf-8")
    assert _run(r).returncode == RC_DIRTY


# ── the wiring, which is where the value actually is ─────────────────────────
@pytest.fixture(scope="module")
def land_sh():
    if not _LAND_SH.is_file():
        pytest.skip(f"{_LAND_SH} absent")
    return _LAND_SH.read_text(encoding="utf-8")


def test_the_landing_gate_takes_a_fingerprint_and_compares_it(land_sh):
    assert "--emit-fingerprint" in land_sh
    assert "--expect-fingerprint" in land_sh


def test_the_comparison_runs_after_the_last_suite_and_before_the_stamp(land_sh):
    """THE WHOLE FIX. Before the last suite it leaves the window open; after
    the stamp it cannot withhold one."""
    emit = land_sh.index("--emit-fingerprint")
    expect = land_sh.index("--expect-fingerprint")
    last_suite = land_sh.rindex("plugin_full_audit.py")
    stamp = land_sh.index('git rev-parse HEAD > "$ROOT/.git/gatekeeper-stamp"')
    assert emit < last_suite, "the fingerprint is taken after the suites ran"
    assert last_suite < expect, (
        "the comparison runs before the last suite, so an edit made during it "
        "is still invisible — the window this exists to close")
    assert expect < stamp, (
        "the comparison runs after the stamp is written, so it cannot withhold "
        "it")


def test_the_fingerprint_path_is_per_run(land_sh):
    """Two gates in one checkout must not read each other's fingerprint. A
    fixed path would make the second run compare against the first's tree."""
    assert "mktemp" in land_sh.split("--emit-fingerprint")[0][-600:], (
        "the fingerprint file is not per-run")
