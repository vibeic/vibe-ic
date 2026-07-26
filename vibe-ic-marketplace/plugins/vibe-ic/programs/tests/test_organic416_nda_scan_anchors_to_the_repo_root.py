#!/usr/bin/env python3
"""ORGANIC #416 — the NDA gate reported PASS on 21 of 20143 blobs.

`--repo` defaulted to `"."`, and git's enumeration commands honour the
current-directory PREFIX: run from a subdirectory, `ls-files -s` and
`ls-tree -r` list only that subtree AND strip the prefix from the paths they
print. `_blobs` then asked `cat-file --batch` for `{ref}:{rel}`, which
resolves against the ROOT, so nearly every request came back `missing` — and
`missing` was a silent `continue`. What survived was the accidental
INTERSECTION of two unrelated directories' path sets, reported with the same
word as a full clean scan.

The centre of gravity here is the LAST test: a token that a subdirectory run
must find. Everything else pins the machinery; that one proves the machinery
was hiding a real leak.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import nda_tracked_tree_scan as S  # noqa: E402

TOKEN = "zzsecretfoundry"           # stand-in; never a real token


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "_patterns",
                        lambda: [re.compile(TOKEN, re.IGNORECASE)])
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(tmp_path), "config", k, v],
                       check=True)
    return tmp_path


def _add(repo: Path, rel: str, text: str):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    subprocess.run(["git", "-C", str(repo), "add", rel], check=True)


def _commit(repo: Path) -> str:
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "x"], check=True)
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


# ── the defect ──────────────────────────────────────────────────────────────

def test_a_subdirectory_scans_the_same_tree_as_the_root(repo):
    """The regression, stated as the invariant it violated: WHERE the caller
    stands must not change WHAT is scanned."""
    _add(repo, "deep/nested/a.md", "clean\n")
    _add(repo, "other/b.md", "clean\n")
    _add(repo, "sub/README.md", "clean\n")
    root = S.scan(repo)
    inner = S.scan(repo / "sub")
    assert inner["scanned"] == root["scanned"] == 3
    assert inner["repo"] == root["repo"] == str(repo)


def test_a_subdirectory_run_finds_a_token_outside_that_subdirectory(repo):
    """THE CONTROL. Not "the counts agree" — a real hit that the old shape
    could not see. `sub/` holds a decoy that resolves at both levels; the
    token lives in `elsewhere/`, which a prefix-narrowed scan never reaches.
    Under the pre-#416 code this reported PASS."""
    _add(repo, "sub/README.md", "clean decoy that exists at both levels\n")
    _add(repo, "elsewhere/leak.md", f"contains {TOKEN} in tracked content\n")
    rep = S.scan(repo / "sub")
    assert [f["file"] for f in rep["findings"]] == ["elsewhere/leak.md"]


def test_the_same_holds_for_a_ref_scan(repo):
    _add(repo, "sub/README.md", "decoy\n")
    _add(repo, "elsewhere/leak.md", f"{TOKEN}\n")
    sha = _commit(repo)
    rep = S.scan(repo / "sub", sha)
    assert [f["file"] for f in rep["findings"]] == ["elsewhere/leak.md"]


# ── an incomplete read may never read as clean ──────────────────────────────

def test_an_unresolvable_blob_is_an_ERROR_not_a_PASS(repo, monkeypatch,
                                                     capsys):
    """`missing` used to be a silent `continue`, which is what let 3316
    dropped lookups add up to a clean verdict. One is now enough to refuse."""
    _add(repo, "a.md", "clean\n")
    _add(repo, "b.md", "clean\n")
    real = S._blobs

    def _one_missing(r, rels, ref=None):
        for i, (rel, text) in enumerate(real(r, rels, ref)):
            yield (rel, None) if i == 0 else (rel, text)

    monkeypatch.setattr(S, "_blobs", _one_missing)
    rc = S.main(["--repo", str(repo)])
    out = capsys.readouterr().out
    assert rc == 2, out
    assert "INCOMPLETELY" in out and "NOT a clean result" in out
    assert "[PASS]" not in out


def test_the_paired_half_a_fully_read_tree_does_pass(repo, capsys):
    _add(repo, "a.md", "clean\n")
    _add(repo, "b.md", "clean\n")
    assert S.main(["--repo", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "[PASS]" in out and "every requested blob was read" in out


def test_git_refusing_to_enumerate_is_an_ERROR_not_a_PASS(tmp_path,
                                                          monkeypatch,
                                                          capsys):
    """`_tracked` returned `[]` on a git failure, and an empty tree scans
    clean. "git would not tell me" is not "there is nothing"."""
    monkeypatch.setattr(S, "_patterns",
                        lambda: [re.compile(TOKEN, re.IGNORECASE)])
    (tmp_path / "not_a_repo").mkdir()
    rc = S.main(["--repo", str(tmp_path / "not_a_repo")])
    out = capsys.readouterr().out
    assert rc == 2, out
    assert "Nothing was scanned" in out and "[PASS]" not in out


# ── submodules: the one exclusion that is correct rather than convenient ────

def test_a_gitlink_is_skipped_explicitly_and_counted(repo, tmp_path):
    """A submodule pointer is a commit in ANOTHER repository — `cat-file`
    cannot read it, and it came back through the same silent `missing` branch
    as the prefix bug. Four of these were being dropped unnoticed on main."""
    sub = tmp_path / "submod"
    subprocess.run(["git", "init", "-q", str(sub)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(sub), "config", k, v], check=True)
    (sub / "f.txt").write_text("upstream content\n")
    subprocess.run(["git", "-C", str(sub), "add", "f.txt"], check=True)
    subprocess.run(["git", "-C", str(sub), "commit", "-qm", "s"], check=True)

    _add(repo, "a.md", "clean\n")
    subprocess.run(["git", "-C", str(repo), "-c", "protocol.file.allow=always",
                    "submodule", "--quiet", "add", str(sub), "IP/x"],
                   check=True, capture_output=True)
    rep = S.scan(repo)
    assert rep["gitlinks"] == ["IP/x"], rep["gitlinks"]
    assert rep["unresolved"] == [], "a gitlink must not read as unreadable"
    assert rep["scanned"] == rep["requested"]


def test_a_gitlink_does_not_suppress_the_verdict(repo, tmp_path, capsys):
    """The paired half: the submodule exclusion must not become a way for a
    tree with a gitlink in it to stop being judged."""
    sub = tmp_path / "submod2"
    subprocess.run(["git", "init", "-q", str(sub)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(sub), "config", k, v], check=True)
    (sub / "f.txt").write_text("x\n")
    subprocess.run(["git", "-C", str(sub), "add", "f.txt"], check=True)
    subprocess.run(["git", "-C", str(sub), "commit", "-qm", "s"], check=True)

    _add(repo, "leak.md", f"{TOKEN}\n")
    subprocess.run(["git", "-C", str(repo), "-c", "protocol.file.allow=always",
                    "submodule", "--quiet", "add", str(sub), "IP/y"],
                   check=True, capture_output=True)
    assert S.main(["--repo", str(repo)]) == 1
    assert "[FAIL]" in capsys.readouterr().out
