"""A landing that drops half a PR, and the one signal that distinguishes it.

v1.9.12 shipped `3e7f1490f` under "undecided silence is a hard error, not a
report" carrying two of #591's four files. The checker went on printing the
undecided count and returning 0 — the defect the PR exists to end — while the
commit message said otherwise.

Every other gate passed, and that is the interesting half. The test file was
left behind together with the code it tests, so main received the OLD checker
and the OLD tests and they agree. The landed repository is SELF-CONSISTENT, and
self-consistency is exactly what a suite measures. Nothing reasoning about the
tree alone can see it.

The one thing that could: the author's worktree still held the missing half.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
PROG = _PROGRAMS / "landing_worktree_is_clean_check.py"


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=60)


def _run(repo, *extra):
    return subprocess.run([sys.executable, str(PROG), str(repo), *extra],
                          capture_output=True, text=True, timeout=60)


@pytest.fixture()
def repo(tmp_path):
    """A repo shaped like this one: a shipped tree, and a corpus that is not."""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    prog = tmp_path / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    prog.mkdir(parents=True)
    (prog / "a_check.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "t.sh").write_text("echo\n", encoding="utf-8")
    (tmp_path / "benchmark-data").mkdir()
    _git(tmp_path, "add", "vibe-ic-marketplace", "tools")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


# ── the defect ───────────────────────────────────────────────────────────────
def test_a_tracked_modification_under_the_shipped_tree_fails(repo):
    """The v1.9.12 shape: a file the batch should have carried, left behind."""
    (repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
     / "a_check.py").write_text("x = 2\n", encoding="utf-8")
    r = _run(repo)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "a_check.py" in r.stderr


def test_a_staged_but_uncommitted_change_also_fails(repo):
    """Staged is not landed. The gate verifies commits, and an index entry is
    not one — this is the state one `git commit` short of the real defect."""
    p = repo / "tools" / "t.sh"
    p.write_text("echo hi\n", encoding="utf-8")
    _git(repo, "add", "tools/t.sh")
    r = _run(repo)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "t.sh" in r.stderr


def test_a_deletion_counts_too(repo):
    """A dropped deletion lands a file the batch meant to remove."""
    (repo / "tools" / "t.sh").unlink()
    assert _run(repo).returncode == 1


# ── the accept cases: a gate that fails on correct input gets routed around ──
def test_a_clean_tree_passes(repo):
    r = _run(repo)
    assert r.returncode == 0, r.stdout + r.stderr


def test_untracked_corpus_output_is_ignored(repo):
    """Benchmark runs scatter reports through the corpus and they are never
    committed. Failing on them would make this unusable — and `git clean` is
    forbidden here, so the noise would be permanent."""
    d = repo / "benchmark-data" / "ic" / "x" / "reports"
    d.mkdir(parents=True)
    (d / "audit.log").write_text("run\n", encoding="utf-8")
    assert _run(repo).returncode == 0


def test_untracked_files_INSIDE_the_shipped_tree_are_ignored_too(repo):
    """A new program that is not `git add`ed yet is a different mistake, and one
    the plugin's own audits catch. This gate is about the gap between COMMITTED
    and MODIFIED, not about authoring."""
    (repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
     / "scratch_probe.py").write_text("y = 1\n", encoding="utf-8")
    assert _run(repo).returncode == 0


def test_a_change_outside_the_shipped_scope_is_ignored(repo):
    """The gatekeeper's checkout also holds scratch clones and probe output."""
    (repo / "notes.md").write_text("scratch\n", encoding="utf-8")
    _git(repo, "add", "notes.md")
    _git(repo, "commit", "-q", "-m", "notes")
    (repo / "notes.md").write_text("scratch 2\n", encoding="utf-8")
    assert _run(repo).returncode == 0


# ── it must not pass by looking at nothing ───────────────────────────────────
def test_a_tree_with_no_shipped_paths_refuses(tmp_path):
    """rc 2, not 0. "There was nothing to compare" and "I compared and it is
    clean" are different claims, and this file exists because collapsing that
    distinction is how the original defect survived."""
    _git(tmp_path, "init", "-q")
    r = _run(tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "not a pass" in r.stderr


def test_a_non_repo_refuses(tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    r = _run(d)
    assert r.returncode == 2, r.stdout + r.stderr


# ── the report ───────────────────────────────────────────────────────────────
def test_the_json_names_the_files_and_the_scope(repo, tmp_path):
    (repo / "tools" / "t.sh").write_text("echo hi\n", encoding="utf-8")
    out = tmp_path / "r.json"
    _run(repo, "--json", str(out))
    d = json.loads(out.read_text())
    assert [x["path"] for x in d["modified_tracked"]] == ["tools/t.sh"]
    assert "vibe-ic-marketplace" in d["scope"], (
        "the scope has to be published — a reader cannot otherwise tell a clean "
        "result from a narrow one")


# ── the scope must cover every path a landing gate reads ─────────────────────
def test_the_scope_covers_the_files_the_image_anchor_gate_reads():
    """v1.9.35. `sync_image_version --check` is a landing gate and it reads its
    24 image pointers FROM THE WORKTREE. Two of the files it reads —
    `README.md` and `docs/INSTALL.md` — sat outside this check's scope, so a
    landing advanced the anchor to 0.2.53, `--check` passed on the worktree, and
    the doc edits were never committed: main told users to pull a stale tag
    while every gate reported the pointers consistent.

    A path a landing gate READS and this check does not GUARD is a path where
    the certified tree and the committed tree can differ silently.
    """
    import importlib.util
    root = _PROGRAMS.parents[3]
    sync = root / "tools" / "vibeic-eda" / "sync_image_version.py"
    if not sync.is_file():
        pytest.skip("sync_image_version.py absent")

    def _load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    m = _load("_syncimg", sync)
    scope = tuple(_load("_landingclean", PROG).SHIPPED_PATHS)
    for rel in m.INSTALL_DOC_CANDIDATES:
        if not (root / rel).exists():
            continue          # the list also serves the standalone eda repo
        head = pathlib.Path(rel).parts[0]
        assert head in scope or rel in scope, (
            f"{rel} is read by a landing gate but is outside "
            f"landing_worktree_is_clean's scope {scope}")
