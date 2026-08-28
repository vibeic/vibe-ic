#!/usr/bin/env python3
"""fresh_agent_rtl_bug_density_metric.py — BACKLOG-v11 P2.3 + v10 P2.4.

Post-benchmark observability tool. Counts independent bug-fix commits
to RTL files in a benchmark project's git history and emits a
quality-metric JSON + appends a row to BENCHMARK_PLUGIN_LEARNING.md.

Motivation
==========

We had no quantified measure of how many bugs the agent's spec-to-rtl
produced per benchmark run. v0.108 had ≥ 5 hand-fixes; v0.116 had
≥ 12. This is a primary plugin-quality metric and tracking the trend
across releases tells us if the plugin is stabilising or still
shipping regressions.

Behaviour
=========

For the given benchmark project directory, walk `git log` of every
RTL path (`*.v` / `*.sv` / `*.svh`) under the project, count commits
whose subject begins with `fix:` / `fix(` / `bug:` / `bug(` / `hotfix:`
(case-insensitive). Style / refactor / docs / chore / test / build
commits do NOT count.

Outputs:
  - reports/plugin_quality/rtl_bug_density.json
  - appends row to docs/design/BENCHMARK_PLUGIN_LEARNING.md
    (creates file if missing)

This is an ADVISORY tool — it does NOT participate in flow_compliance
verdicts. Its only side effects are observability files.

ENFORCEMENT: advisory

Wired at flow step 2 (RTL validation), which already owns this repository's
RTL-bug accounting through `rtl_bug_report_schema_check` and
`reports/phase2/rtl_bugs.json` — that gate grades the SHAPE of a claimed bug,
and this one counts how many the candidate RTL actually needed. It is wired in
the `advisory_program_exit_zero` slot, with `--no-learning-log`: without that
flag the run appends a row to `docs/design/BENCHMARK_PLUGIN_LEARNING.md` in the
REPOSITORY root, i.e. a flow run would mutate a tracked document outside the
project it is grading.

False-alert guards
==================

  - Counts ONLY commits whose message starts with the bug-prefix
    grammar above. Refactors, format changes, and stylistic edits do
    not count as bugs.
  - The benchmark project must be inside a git repo. If `git` is
    unavailable or the dir is not tracked, the tool exits 2 quietly
    (advisory tool — no need to fail builds).

Exit codes: 0 OK / 2 skip (no git or no RTL)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
import _watchdog as _wd            # noqa: E402  progress supervision
import sys
from datetime import datetime, timezone
from pathlib import Path

from gate_utils import find_rtl_files as _rtl_files
import _path_layout as _pl


_BUG_PREFIX_RE = re.compile(
    r"^(fix|bug|hotfix)\s*[:(]", re.IGNORECASE,
)


#: rc for "git could not be RUN", as distinct from "git ran and said no".
#: 127 is the shell's own code for an uninvocable command, and the point of a
#: separate code is that `_resolve_repo_root` used to collapse both into
#: `None`, which `inspect` then published as the SKIP reason "not inside a git
#: repository" — a claim about the PROJECT that is false whenever it was
#: really a slow or missing git. See `_resolve_repo_root`.
_GIT_UNUSABLE_RC = 127

#: How long git may be COMPLETELY IDLE before it is called wedged. Not a bound
#: on how long a `git log` over a deep history may legitimately take.
_GIT_STALL_GRACE_S = 30


def _git(args: list[str], cwd: Path) -> tuple[int, str]:
    try:
        # PROGRESS, NOT RUNTIME — a `git log` over a large history is WORKING,
        # and a 30 s cap on it kills the measurement rather than taking it. The
        # number is now the grace: how long git may be entirely idle.
        res = _wd.run_host_supervised(["git"] + args, cwd=str(cwd),
                                      stall_grace_s=_GIT_STALL_GRACE_S)
    except FileNotFoundError as exc:
        return _GIT_UNUSABLE_RC, f"git is not on PATH ({exc})"
    if res.outcome in ("stalled", "ceiling"):
        return _GIT_UNUSABLE_RC, (
            f"`git {' '.join(args)}` made no forward progress (no CPU, no I/O) "
            f"for {_GIT_STALL_GRACE_S}s and was stopped — git was wedged. "
            f"Nothing was learned about this project.")
    return res.rc, res.out


def _resolve_repo_root(path: Path) -> tuple[Path | None, str]:
    """(root, why-not). `why-not` distinguishes the two ways this returns None.

    THE DEFECT IT CLOSES: git failing to RUN and git answering "this is not a
    repository" both produced `None`, and the single caller turned `None` into
    the published reason "not inside a git repository". On a host where git was
    slow, the metric asserted something FALSE about the project — a wall clock
    deciding a fact about the tree it was pointed at.
    """
    rc, out = _git(["rev-parse", "--show-toplevel"], path)
    if rc == _GIT_UNUSABLE_RC:
        return None, f"git could not be run, so nothing was measured: {out}"
    if rc != 0:
        return None, "not inside a git repository"
    root = out.strip()
    if not root:
        return None, "not inside a git repository"
    return Path(root), ""


def _bug_commits_for_paths(repo: Path, project: Path,
                           rel_paths: list[str],
                           since: str | None = None
                           ) -> list[tuple[str, str, str]]:
    """Return [(sha, date, subject)] for fix:/bug:/hotfix: commits
    that touched any of `rel_paths` (RTL files relative to repo root).
    """
    if not rel_paths:
        return []
    args = ["log", "--pretty=format:%H%x09%ad%x09%s",
            "--date=short", "--no-merges"]
    if since:
        args.append(f"--since={since}")
    args.append("--")
    args.extend(rel_paths)
    rc, out = _git(args, repo)
    if rc != 0:
        return []
    commits: list[tuple[str, str, str]] = []
    for line in out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        sha, date, subj = parts
        if _BUG_PREFIX_RE.match(subj):
            commits.append((sha, date, subj))
    return commits


def _rtl_relpaths(project: Path, repo: Path) -> list[str]:
    rels: list[str] = []
    for f in _rtl_files(project):
        try:
            rels.append(str(f.resolve().relative_to(repo)))
        except ValueError:
            continue
    return rels


def inspect(project: Path, since: str | None = None) -> dict:
    summary: dict = {
        "project": project.name,
        "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "since": since,
        "skipped_reason": "",
        "rtl_files_count": 0,
        "bug_commits": [],
        "bug_commit_count": 0,
        "rtl_files_with_bugs": 0,
        "first_bug_at": None,
        "last_bug_at": None,
    }
    repo, why_not = _resolve_repo_root(project)
    if repo is None:
        summary["skipped_reason"] = why_not
        return summary
    rels = _rtl_relpaths(project, repo)
    summary["rtl_files_count"] = len(rels)
    if not rels:
        summary["skipped_reason"] = "no RTL files in project"
        return summary
    commits = _bug_commits_for_paths(repo, project, rels, since=since)
    summary["bug_commits"] = [
        {"sha": s, "date": d, "subject": subj}
        for s, d, subj in commits
    ]
    summary["bug_commit_count"] = len(commits)
    if commits:
        summary["first_bug_at"] = commits[-1][1]  # git log is newest-first
        summary["last_bug_at"] = commits[0][1]
    # Distinct RTL files touched by bug commits
    if commits:
        touched: set[str] = set()
        for sha, _, _ in commits:
            rc, out = _git(["show", "--name-only", "--pretty=format:", sha],
                           repo)
            if rc == 0:
                for f in out.splitlines():
                    f = f.strip()
                    if f.endswith((".v", ".sv", ".svh")) and f in rels:
                        touched.add(f)
        summary["rtl_files_with_bugs"] = len(touched)
    return summary


def write_report(project: Path, summary: dict) -> Path:
    out = _pl.report_path(project, "plugin_quality/rtl_bug_density.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2))
    return out


def append_learning_log(repo_root: Path, summary: dict) -> Path:
    docs = repo_root / "docs" / "design"
    docs.mkdir(parents=True, exist_ok=True)
    log = docs / "BENCHMARK_PLUGIN_LEARNING.md"
    if not log.exists():
        log.write_text(
            "# BENCHMARK_PLUGIN_LEARNING\n\n"
            "Per-benchmark observability log. Each row records the RTL\n"
            "bug-density observed in a fresh-agent benchmark run.\n"
            "Lower count over successive plugin releases = stabilising\n"
            "plugin. Trend up = regression in code-gen quality.\n\n"
            "| date | project | bug_commits | rtl_files | "
            "files_with_bugs | first_bug | last_bug |\n"
            "|---|---|---|---|---|---|---|\n"
        )
    row = (
        f"| {summary['computed_at'][:10]} "
        f"| {summary['project']} "
        f"| {summary['bug_commit_count']} "
        f"| {summary['rtl_files_count']} "
        f"| {summary['rtl_files_with_bugs']} "
        f"| {summary.get('first_bug_at') or '—'} "
        f"| {summary.get('last_bug_at') or '—'} |\n"
    )
    with log.open("a") as fh:
        fh.write(row)
    return log


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="fresh_agent_rtl_bug_density_metric")
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None,
                    help="Override output JSON path "
                    "(default reports/plugin_quality/rtl_bug_density.json)")
    ap.add_argument("--since", default=None,
                    help="Limit commits to those after this date "
                    "(ISO-8601 or git --since string)")
    ap.add_argument("--no-learning-log", action="store_true",
                    help="Skip appending to BENCHMARK_PLUGIN_LEARNING.md")
    args = ap.parse_args()

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"[error] project not found: {project}", file=sys.stderr)
        return 2

    summary = inspect(project, since=args.since)
    if summary["skipped_reason"]:
        print(f"=== fresh_agent_rtl_bug_density_metric ({project.name}) ===")
        print(f"  [skipped] {summary['skipped_reason']}")
        return 2

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(summary, indent=2))
    out = write_report(project, summary)

    if not args.no_learning_log:
        repo, _why = _resolve_repo_root(project)
        if repo is not None:
            log = append_learning_log(repo, summary)
            print(f"  [appended] {log.relative_to(repo)}")

    print(f"=== fresh_agent_rtl_bug_density_metric ({project.name}) ===")
    print(f"  bug_commits         : {summary['bug_commit_count']}")
    print(f"  rtl_files_count     : {summary['rtl_files_count']}")
    print(f"  rtl_files_with_bugs : {summary['rtl_files_with_bugs']}")
    print(f"  report              : {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
