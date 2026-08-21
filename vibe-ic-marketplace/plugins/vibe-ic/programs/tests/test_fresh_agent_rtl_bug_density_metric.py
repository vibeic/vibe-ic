#!/usr/bin/env python3
"""Tests for fresh_agent_rtl_bug_density_metric.py (BACKLOG-v11 P2.3)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "fresh_agent_rtl_bug_density_metric.py")


def _run(project_dir: Path, *extra) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(PROG), str(project_dir),
           "--no-learning-log"] + list(extra)
    return subprocess.run(cmd, capture_output=True, text=True)


def _git(*args, cwd: Path) -> subprocess.CompletedProcess:
    env = {"GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=cwd, env=env,
                          capture_output=True, text=True)


def _init_repo(tmp_path: Path) -> Path:
    project = tmp_path / "bench"
    (project / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    _git("init", "-q", "-b", "main", cwd=tmp_path)
    return project


def _commit(tmp_path: Path, project: Path, file_rel: str,
            content: str, msg: str):
    f = project / file_rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content)
    _git("add", str(f.relative_to(tmp_path)), cwd=tmp_path)
    _git("commit", "-q", "-m", msg, cwd=tmp_path)


def test_no_git_silent(tmp_path):
    """Project not in a git repo → exit 2."""
    p = tmp_path / "nogit"
    p.mkdir(parents=True, exist_ok=True)
    (p / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (p / "phase2" / "stage1" / "rtl" / "top.sv").write_text("module top; endmodule\n")
    r = _run(p)
    assert r.returncode == 2


def test_no_rtl_silent(tmp_path):
    """Repo exists but no RTL → exit 2."""
    project = _init_repo(tmp_path)
    _commit(tmp_path, project, "bench/README.md",
            "hello", "docs: initial readme")
    r = _run(project)
    assert r.returncode == 2


def test_zero_bug_commits(tmp_path):
    """RTL exists but no bug commits → bug_commit_count=0."""
    project = _init_repo(tmp_path)
    _commit(tmp_path, project, "bench/rtl/top.sv",
            "module top; endmodule\n", "feat: initial RTL")
    r = _run(project)
    assert r.returncode == 0
    rpt = json.loads(
        (project / "reports" / "phase2" / "plugin_quality"
         / "rtl_bug_density.json").read_text())
    assert rpt["bug_commit_count"] == 0
    assert rpt["rtl_files_count"] == 1


def test_counts_only_bug_prefixed_commits(tmp_path):
    """Only commits with fix:/bug:/hotfix: prefix count."""
    project = _init_repo(tmp_path)
    _commit(tmp_path, project, "bench/rtl/top.sv",
            "module top; endmodule\n", "feat: initial RTL")
    _commit(tmp_path, project, "bench/rtl/top.sv",
            "module top; wire q; endmodule\n",
            "refactor: rename signal")
    _commit(tmp_path, project, "bench/rtl/top.sv",
            "module top; reg q; endmodule\n",
            "fix: latch instead of wire")
    _commit(tmp_path, project, "bench/rtl/top.sv",
            "module top; reg q; reg r; endmodule\n",
            "bug(otp): off-by-one read")
    _commit(tmp_path, project, "bench/rtl/top.sv",
            "module top; reg q,r,s; endmodule\n",
            "docs: comment on signals")
    r = _run(project)
    assert r.returncode == 0
    rpt = json.loads(
        (project / "reports" / "phase2" / "plugin_quality"
         / "rtl_bug_density.json").read_text())
    assert rpt["bug_commit_count"] == 2
    assert rpt["rtl_files_with_bugs"] == 1


def test_non_rtl_bug_commits_ignored(tmp_path):
    """fix: commits to non-RTL files don't count."""
    project = _init_repo(tmp_path)
    _commit(tmp_path, project, "bench/rtl/top.sv",
            "module top; endmodule\n", "feat: rtl")
    _commit(tmp_path, project, "bench/README.md",
            "docs", "fix: typo in readme")
    r = _run(project)
    assert r.returncode == 0
    rpt = json.loads(
        (project / "reports" / "phase2" / "plugin_quality"
         / "rtl_bug_density.json").read_text())
    assert rpt["bug_commit_count"] == 0
