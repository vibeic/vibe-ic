"""Trusted verifier snapshots are bound to raw Git blob bytes."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[5]
ATTEST = REPO / "tools" / "ci" / "trusted_worktree_attest.py"

pytestmark = pytest.mark.timeout(0)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True,
        check=True,
    )


def _repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "source"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@localhost")
    _git(root, "config", "user.name", "t")
    (root / "plain.txt").write_text("exact\n", encoding="utf-8")
    target = root / "target.txt"
    target.write_text("target\n", encoding="utf-8")
    (root / "link.txt").symlink_to("target.txt")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "fixture")
    return root, _git(root, "rev-parse", "HEAD").stdout.strip()


def _run(source: Path, snapshot: Path, sha: str, *, worktree: bool = False
         ) -> subprocess.CompletedProcess[str]:
    argv = [
        "python3", str(ATTEST), "--object-repo", str(source),
        "--snapshot", str(snapshot), "--expected-sha", sha,
    ]
    if worktree:
        argv.append("--allow-git-control-file")
    return subprocess.run(argv, capture_output=True, text=True)


def test_plain_object_exact_snapshot_passes_and_extra_path_refuses(tmp_path):
    source, sha = _repo(tmp_path)
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    archive = subprocess.run(
        ["git", "-C", str(source), "archive", "--format=tar", sha],
        stdout=subprocess.PIPE, check=True,
    )
    extracted = subprocess.run(
        ["tar", "-xf", "-", "-C", str(snapshot)],
        input=archive.stdout, capture_output=True,
    )
    assert extracted.returncode == 0, extracted.stderr.decode()

    passed = _run(source, snapshot, sha)
    assert passed.returncode == 0, passed.stdout + passed.stderr
    (snapshot / "candidate-shadow.py").write_text("forged\n", encoding="utf-8")
    refused = _run(source, snapshot, sha)
    assert refused.returncode == 2
    assert "path set differs" in refused.stderr


def test_clean_smudge_filter_cannot_make_a_linked_worktree_self_attest(
        tmp_path):
    source = tmp_path / "filtered"
    source.mkdir()
    _git(source, "init", "-q")
    _git(source, "config", "user.email", "t@localhost")
    _git(source, "config", "user.name", "t")
    (source / ".gitattributes").write_text(
        "audit.txt filter=flip\n", encoding="utf-8")
    (source / "audit.txt").write_text("FAIL\n", encoding="utf-8")
    _git(source, "add", "-A")
    _git(source, "commit", "-qm", "raw blob says fail")
    sha = _git(source, "rev-parse", "HEAD").stdout.strip()
    _git(source, "config", "filter.flip.smudge", "sed s/FAIL/PASS/g")
    _git(source, "config", "filter.flip.clean", "sed s/PASS/FAIL/g")
    _git(source, "config", "filter.flip.required", "true")
    worktree = tmp_path / "filtered-worktree"
    _git(source, "worktree", "add", "-q", "--detach", str(worktree), sha)
    try:
        assert (worktree / "audit.txt").read_text(encoding="utf-8") == "PASS\n"
        assert _git(worktree, "status", "--porcelain").stdout == ""

        proc = _run(source, worktree, sha, worktree=True)

        assert proc.returncode == 2, proc.stdout + proc.stderr
        assert "raw bytes differ" in proc.stderr
    finally:
        _git(source, "worktree", "remove", "--force", str(worktree))


def test_git_control_file_is_allowed_only_for_explicit_linked_worktree_mode(
        tmp_path):
    source, sha = _repo(tmp_path)
    worktree = tmp_path / "linked"
    _git(source, "worktree", "add", "-q", "--detach", str(worktree), sha)
    try:
        default = _run(source, worktree, sha)
        allowed = _run(source, worktree, sha, worktree=True)
        assert default.returncode == 2
        assert allowed.returncode == 0, allowed.stdout + allowed.stderr
    finally:
        _git(source, "worktree", "remove", "--force", str(worktree))


def test_linked_worktree_control_cannot_point_at_another_gitdir(tmp_path):
    source, sha = _repo(tmp_path)
    worktree = tmp_path / "linked"
    _git(source, "worktree", "add", "-q", "--detach", str(worktree), sha)
    control = worktree / ".git"
    original = control.read_bytes()
    try:
        control.write_text(f"gitdir: {source / '.git'}\n", encoding="utf-8")
        refused = _run(source, worktree, sha, worktree=True)
        assert refused.returncode == 2
        assert "outside the object repository" in refused.stderr
    finally:
        control.write_bytes(original)
        _git(source, "worktree", "remove", "--force", str(worktree))


def test_linked_worktree_index_flags_and_replace_refs_refuse(tmp_path):
    source, sha = _repo(tmp_path)
    worktree = tmp_path / "linked"
    _git(source, "worktree", "add", "-q", "--detach", str(worktree), sha)
    try:
        _git(worktree, "update-index", "--skip-worktree", "plain.txt")
        skipped = _run(source, worktree, sha, worktree=True)
        assert skipped.returncode == 2
        assert "skip/assume/unmerged flags" in skipped.stderr

        _git(worktree, "update-index", "--no-skip-worktree", "plain.txt")
        _git(source, "update-ref", f"refs/replace/{sha}", sha)
        replaced = _run(source, worktree, sha, worktree=True)
        assert replaced.returncode == 2
        assert "replacement refs" in replaced.stderr
    finally:
        _git(source, "update-ref", "-d", f"refs/replace/{sha}")
        _git(source, "worktree", "remove", "--force", str(worktree))
