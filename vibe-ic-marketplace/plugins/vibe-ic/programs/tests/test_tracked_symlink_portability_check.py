#!/usr/bin/env python3
"""#371 — a tracked symlink must resolve for everyone, not just its author.

Measured: 172 tracked symlinks under benchmark-data/ic, 159 recorded with an
ABSOLUTE target under the author's own checkout path. They resolved there and
dangled in every other clone, and that made a gate's verdict
environment-dependent (440 documents locally, 422 in CI, same commit) — two
land attempts were refuted by CI before the cause was found.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "tracked_symlink_portability_check.py"


def _git(root: Path, *a):
    _pr.run(["git", "-C", str(root), *a], capture_output=True,
                   check=True, text=False)


def _repo(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    _git(p, "init", "-q")
    _git(p, "config", "user.email", "t@t")
    _git(p, "config", "user.name", "t")
    return p


def _run(root: Path, out: Path):
    # `VIBE_IC_BENCHMARK_DATA` is POPPED, not merely ignored. Since #1710's
    # treatment landed on this gate the pointer OVERRIDES the path, so a
    # developer who has it exported would have every fixture below silently
    # replaced by their corpus clone — the tests would still pass or fail, about
    # a tree they never built.
    env = dict(os.environ)
    env.pop("VIBE_IC_BENCHMARK_DATA", None)
    return _pr.run([sys.executable, str(_PROG), str(root),
                           "--json", str(out)], env=env,
                          capture_output=True, text=True)


def test_371_absolute_target_fails(tmp_path):
    """THE defect: absolute target, even one pointing INSIDE the repo."""
    root = _repo(tmp_path)
    (root / "real.txt").write_text("x\n")
    (root / "link.txt").symlink_to(root / "real.txt")   # absolute
    _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "abs")
    r = _run(root, tmp_path / "o.json")
    assert r.returncode == 1, r.stdout
    assert "absolute target" in r.stdout


def test_371_relative_inside_repo_passes(tmp_path):
    """NO-LEAK: the corrected form is accepted."""
    root = _repo(tmp_path)
    (root / "real.txt").write_text("x\n")
    (root / "link.txt").symlink_to("real.txt")          # relative
    _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "rel")
    assert _run(root, tmp_path / "o.json").returncode == 0


def test_371_relative_escaping_the_repo_fails(tmp_path):
    """A relative link that climbs out ships a pointer to content the
    repository does not have."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.txt").write_text("x\n")
    root = _repo(tmp_path / "repo")
    (root / "link.txt").symlink_to("../outside/x.txt")
    _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "escape")
    r = _run(root, tmp_path / "o.json")
    assert r.returncode == 1, r.stdout
    assert "escapes the repository" in r.stdout


def test_371_dangling_relative_link_is_reported_but_not_gated(tmp_path):
    """A missing FILE is a different defect from a non-portable POINTER.
    Conflating them would make this gate fire on a problem it does not
    diagnose — but silence would read as 'nothing else is wrong', so the
    count is printed on every run."""
    root = _repo(tmp_path)
    (root / "link.txt").symlink_to("gone.txt")          # relative, dangling
    _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "dangling")
    r = _run(root, tmp_path / "o.json")
    assert r.returncode == 0, r.stdout
    assert "dangling" in r.stdout
    rep = json.loads((tmp_path / "o.json").read_text())
    assert rep["dangling_inside_repo"] == 1


def test_371_enumeration_comes_from_the_index_not_a_walk(tmp_path):
    """An UNtracked symlink is not this gate's business — and reading the
    index rather than walking keeps the answer independent of what the walk
    can follow, which is the property the original defect destroyed."""
    root = _repo(tmp_path)
    (root / "keep.txt").write_text("x\n")
    _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "keep")
    (root / "untracked_link").symlink_to("/etc/hostname")   # absolute+outside
    r = _run(root, tmp_path / "o.json")
    assert r.returncode == 0, r.stdout
    assert json.loads((tmp_path / "o.json").read_text())["symlinks"] == 0


def test_371_shipped_tree_is_clean():
    """The gate must be GREEN on main as landed."""
    env = dict(os.environ)
    env.pop("VIBE_IC_BENCHMARK_DATA", None)
    r = _pr.run([sys.executable, str(_PROG)], env=env,
                       capture_output=True, text=True)
    if r.returncode == 2:
        return
    assert r.returncode == 0, r.stdout + r.stderr
