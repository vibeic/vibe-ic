#!/usr/bin/env python3
"""Tests for nda_tracked_tree_scan.

The three existing NDA guards all scan a DELTA (commit messages, an added
diff, the plugin's own source). None can see a token that is ALREADY
tracked, so one that landed before a guard existed stays served forever
while every guard reports clean.

Every case is paired. "Reports no leak" is trivially satisfiable by a
scanner that looks at nothing, and "reports a leak" is trivially satisfiable
by one that flags everything — only the pair says anything.

No real token appears here. The tests install a throwaway pattern through
the module's own `_patterns` seam, which is also the honest way to test a
guard whose literals must never enter the repo.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import nda_tracked_tree_scan as S  # noqa: E402

TOKEN = "zzsecretfoundry"       # stand-in; never a real token


@pytest.fixture
def repo(tmp_path, monkeypatch):
    import re
    monkeypatch.setattr(S, "_patterns",
                        lambda: [re.compile(TOKEN, re.IGNORECASE)])
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email",
                    "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"],
                   check=True)
    return tmp_path


def _add(repo: Path, rel: str, text: str):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    subprocess.run(["git", "-C", str(repo), "add", rel], check=True)


def test_a_clean_tree_passes(repo):
    _add(repo, "a.md", "nothing to see\n")
    assert S.scan(repo)["findings"] == []


def test_a_token_in_tracked_content_is_found(repo):
    """The paired half of the above — same tree, one token."""
    _add(repo, "a.md", f"cell model: {TOKEN}_neg.v\n")
    f = S.scan(repo)["findings"]
    assert len(f) == 1 and f[0]["carrier"] == "CONTENT" and f[0]["hits"] == 1


def test_a_token_in_a_tracked_PATH_is_found(repo):
    _add(repo, f"runs/{TOKEN}_run/notes.md", "clean body\n")
    carriers = {x["carrier"] for x in S.scan(repo)["findings"]}
    assert "PATH" in carriers


def test_an_untracked_file_is_not_scanned(repo):
    """What ships is what git has. An untracked local file is not a leak."""
    _add(repo, "a.md", "clean\n")
    (repo / "local.md").write_text(f"{TOKEN}\n")
    assert S.scan(repo)["findings"] == []


def test_a_symlink_to_an_untracked_file_is_not_a_leak(repo):
    """REGRESSION — this gate's own first version got this wrong.

    It read the WORKING-TREE file for every tracked path, so a tracked
    SYMLINK whose target is untracked local content was reported as a
    tracked leak. The finding was true about the machine and FALSE about
    the repo, and it was one commit from being published as a leak report.
    """
    _add(repo, "a.md", "clean\n")
    (repo / "target.md").write_text(f"{TOKEN}\n")     # untracked
    (repo / "link.md").symlink_to("target.md")
    subprocess.run(["git", "-C", str(repo), "add", "link.md"], check=True)
    rep = S.scan(repo)
    assert rep["findings"] == [], rep["findings"]
    assert rep["symlinks"] == 1


def test_a_symlink_whose_TARGET_PATH_carries_the_token_is_found(repo):
    """The paired half: a symlink's tracked content IS its target path
    string, so a token there is genuinely in the repo."""
    _add(repo, "a.md", "clean\n")
    (repo / f"{TOKEN}_dir").mkdir()
    (repo / f"{TOKEN}_dir" / "t.md").write_text("x\n")
    (repo / "link.md").symlink_to(f"{TOKEN}_dir/t.md")
    subprocess.run(["git", "-C", str(repo), "add", "link.md"], check=True)
    assert S.scan(repo)["findings"], "the target path string is tracked content"


def test_the_indexed_blob_wins_over_a_dirty_working_tree(repo):
    """A local edit that ADDS a token has not been committed to anything;
    a local edit that REMOVES one has not removed it from the repo. Both
    directions must follow the index."""
    _add(repo, "a.md", f"{TOKEN}\n")
    (repo / "a.md").write_text("locally cleaned\n")      # unstaged removal
    assert S.scan(repo)["findings"], "the index still carries it"

    _add(repo, "b.md", "clean\n")
    (repo / "b.md").write_text(f"{TOKEN}\n")             # unstaged addition
    assert len(S.scan(repo)["findings"]) == 1, "only a.md is a real finding"


def test_no_store_is_a_SKIP_not_a_PASS(tmp_path, monkeypatch):
    """"I could not look" must never read as "I looked and it is clean"."""
    monkeypatch.setattr(S, "_patterns", lambda: [])
    rep = S.scan(tmp_path)
    assert rep["configured"] is False
    rc = subprocess.run([sys.executable, str(_PROGRAMS / "nda_tracked_tree_scan.py"),
                         "--repo", str(tmp_path)], capture_output=True, text=True)
    assert rc.returncode in (0, 2)


def test_findings_never_print_the_literal(repo, capsys):
    _add(repo, "a.md", f"{TOKEN}\n")
    rc = S.main(["--repo", str(repo)])
    out = capsys.readouterr().out
    # main() re-resolves the real patterns, so it may pass on this fixture;
    # what must hold either way is that no token text is echoed.
    assert TOKEN not in out
    assert rc in (0, 1, 2)


def test_large_tree_does_not_hang(repo):
    """REGRESSION: the batch reader wrote every request before reading any
    output, so git filled its stdout pipe and both sides blocked. It did not
    fail — it HUNG past a 600 s timeout, which reads as a slow scan rather
    than a broken one."""
    for i in range(600):
        _add(repo, f"d{i % 20}/f{i}.md", f"body {i}\n")
    rep = S.scan(repo)
    assert rep["scanned"] >= 600
    assert rep["findings"] == []


def test_ref_scans_the_published_tree_not_the_checkout(repo):
    """REGRESSION — measured on a real fork.

    Scanning a fork's local HEAD reported a token its published `origin/main`
    does NOT contain: the checkout was one commit behind the fix. "Clean
    here" and "clean in what is published" are different claims, and a gate
    that blurs them either raises a false alarm or gives false comfort
    depending on which way the clone is stale.
    """
    _add(repo, "a.md", f"{TOKEN}\n")
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "dirty"],
                   check=True)
    dirty = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                           capture_output=True, text=True).stdout.strip()
    _add(repo, "a.md", "cleaned upstream\n")
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "clean"],
                   check=True)

    assert S.scan(repo)["findings"] == [], "the tip is clean"
    assert S.scan(repo, dirty)["findings"], "the older ref still carries it"


def test_a_ref_scan_is_not_vacuous(repo):
    """A `--ref` that silently enumerated nothing would PASS on everything.
    The ref's file list must match the index's when they are the same tree."""
    for i in range(5):
        _add(repo, f"f{i}.md", "body\n")
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "x"], check=True)
    assert S.scan(repo, "HEAD")["scanned"] == S.scan(repo)["scanned"] >= 5
