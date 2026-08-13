"""covered_by.py — before you fix a red, ask which open branch already fixed it.

`claim.py` settles the ISSUE-claim race. This settles the other one, which no
claim comment can: **a red on `main` is not a free work item just because no
issue names it.** Some open branch may already turn it green, and the only
honest way to know is to RUN the test on that branch.

WHY A SEARCH CANNOT ANSWER THIS  (measured 2026-08-13)
    An agent looked for contention by searching every open PR's title and body
    for the failing test's name, found nothing, built the fix, pushed it, and
    only then discovered PR #1077 had fixed the same red a day earlier. #1077's
    title names the DEFECT — "a write record that named no producer was read as
    one" — which is correct PR-titling and never mentions the test. The search
    was sound and the answer was wrong, because the question is not "who talks
    about this test" but "whose tree makes it pass".

    Four of the five duplicates measured that day were this shape, not a claim
    race. `claim.py` cannot see them: they are not claimed by anybody.

CANDIDATES ARE CHOSEN BY FILE, NEVER BY PROSE
    A branch is a candidate when it touches the test's own file or the module
    the test drives. That is a fact about a diff. Prose is not consulted.

THE FALSE ZERO THIS REFUSES TO REPORT
    A pytest run that dies during collection prints no summary line, and
    grepping its output for `FAILED` yields zero — which reads exactly like
    "nothing failed". A 188.61s item under a 180s `--timeout-method=thread`
    bound does precisely this, and it was mistaken for a clean delta once
    already (vibe-ic#1277). So a run is only believed when its summary line is
    found; anything else is UNKNOWN, and UNKNOWN is never folded into "clear".

EXIT CODES
    0  COVERED    — at least one open branch turns this red green; do NOT
                    author a second fix. The branches are listed.
    1  UNCOVERED  — no candidate branch clears it; the work is genuinely yours.
    2  UNKNOWN    — no candidate could be measured (checkout or run failed, or
                    a run produced no summary line). NEVER read as UNCOVERED:
                    an unmeasured branch is the duplicate this exists to stop.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import (Callable, Dict, List, Optional,
                    Sequence, Tuple)

#: pytest's own end-of-run line. Its ABSENCE is the false zero described above.
_SUMMARY_RE = re.compile(
    r"^\s*=*\s*(\d+ (failed|passed|error)|no tests ran|.*\b\d+ (passed|failed)\b)",
    re.M)

PASSED, FAILED, UNMEASURED = "PASSED", "FAILED", "UNMEASURED"


def classify_run(stdout: str, returncode: int) -> str:
    """`PASSED` / `FAILED` / `UNMEASURED` for one pytest invocation.

    A run is only believed when pytest printed a summary line. Without one the
    process may have been killed mid-collection, and its silence must not be
    read as success OR as failure.
    """
    if not _SUMMARY_RE.search(stdout or ""):
        return UNMEASURED
    if re.search(r"^FAILED ", stdout or "", re.M) or "no tests ran" in (stdout or ""):
        return FAILED
    return PASSED if returncode == 0 else FAILED


def decide(results: Dict[int, str]) -> Tuple[int, List[int], List[int]]:
    """`(exit_code, covering, unmeasured)` from `{pr_number: verdict}`.

    COVERED wins over UNKNOWN: one branch that demonstrably clears the red is
    enough to stop a second author, whatever the others did. UNKNOWN beats
    UNCOVERED, because "we could not look" is not "we looked and found none".
    """
    covering = sorted(n for n, v in results.items() if v == PASSED)
    unmeasured = sorted(n for n, v in results.items() if v == UNMEASURED)
    if covering:
        return 0, covering, unmeasured
    if unmeasured or not results:
        return 2, covering, unmeasured
    return 1, covering, unmeasured


def candidates(pr_files: Dict[int, Sequence[str]], test_path: str,
               also: Sequence[str] = ()) -> List[int]:
    """PRs whose diff touches the test file or any of `also`, by FILE."""
    want = {test_path, *also}
    out = []
    for n, files in pr_files.items():
        if any(f == w or f.endswith("/" + w.lstrip("/")) for f in files for w in want):
            out.append(n)
    return sorted(out)


def report(code: int, covering: List[int], unmeasured: List[int], node: str) -> str:
    if code == 0:
        s = (f"COVERED: {node} is already turned green by "
             + ", ".join(f"#{n}" for n in covering)
             + ". Do NOT author a second fix; verify or extend theirs instead.")
        if unmeasured:
            s += (f" ({len(unmeasured)} other candidate(s) could not be measured: "
                  + ", ".join(f"#{n}" for n in unmeasured) + ")")
        return s
    if code == 1:
        return (f"UNCOVERED: no open branch that touches this file turns {node} "
                f"green. The work is yours.")
    return (f"UNKNOWN: {node} could not be measured on "
            + (", ".join(f"#{n}" for n in unmeasured) or "any candidate")
            + ". This is NOT 'uncovered' — an unmeasured branch is exactly the "
              "duplicate this check exists to prevent. Re-run or measure by hand.")


def _run(cmd: Sequence[str], cwd: Optional[str] = None) -> Tuple[str, int]:
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=1800)
    return (p.stdout or "") + (p.stderr or ""), p.returncode


def measure(prs: Sequence[int], node: str, checkout: Callable[[int], Optional[str]],
            runner: Callable[[str, str], Tuple[str, int]] = None) -> Dict[int, str]:
    """`{pr: verdict}` — run `node` on each PR's tree. IO is injected for tests."""
    runner = runner or (lambda wt, n: _run(
        [sys.executable, "-m", "pytest", "-q", "-p", "pytest_timeout",
         "--timeout=180", "--timeout-method=thread", n], cwd=wt))
    out: Dict[int, str] = {}
    for n in prs:
        wt = checkout(n)
        if wt is None:
            out[n] = UNMEASURED
            continue
        stdout, rc = runner(wt, node)
        out[n] = classify_run(stdout, rc)
    return out


def parse_pr_files(payload: str) -> Dict[int, List[str]]:
    """`{pr: [changed files]}` from `gh pr list --json number,files` output.

    Parsed rather than shelled per-PR: one API call for the whole fleet. A
    per-PR fan-out is what tripped GitHub's secondary rate limit on 2026-08-13
    while the primary counters still read 315/5000, which looks like a
    permission error and is not one.
    """
    try:
        rows = json.loads(payload or "[]")
    except json.JSONDecodeError:
        return {}
    if not isinstance(rows, list):
        return {}
    out: Dict[int, List[str]] = {}
    for r in rows:
        if not isinstance(r, dict) or "number" not in r:
            continue
        files = [f.get("path", "") for f in (r.get("files") or [])
                 if isinstance(f, dict)]
        out[int(r["number"])] = [f for f in files if f]
    return out


def open_pr_files(repo: str) -> Dict[int, List[str]]:
    payload, _ = _run(["gh", "pr", "list", "--repo", repo, "--state", "open",
                       "--json", "number,files", "--limit", "400"])
    return parse_pr_files(payload)


def worktree_checkout(repo_dir: str, work_dir: str, repo: str):
    """A `checkout(pr) -> path | None` that fetches the head and detaches it.

    Returns None on any failure, which `measure` records as UNMEASURED — never
    as "this branch does not fix it".
    """
    def checkout(pr: int) -> Optional[str]:
        ref, rc = _run(["gh", "api", f"repos/{repo}/pulls/{pr}", "--jq", ".head.ref"])
        ref = (ref or "").strip()
        # An API failure yields '' or an error sentence. Fetching that would
        # silently resolve to HEAD and measure the WRONG TREE (measured while
        # verifying vibe-ic#1308), so refuse rather than guess.
        if rc != 0 or not ref or " " in ref or "rate limit" in ref.lower():
            return None
        dest = str(Path(work_dir) / f"cb{pr}")
        _run(["git", "-C", repo_dir, "worktree", "remove", "--force", dest])
        _, rc = _run(["git", "-C", repo_dir, "fetch", "-q", "origin",
                      f"+{ref}:refs/remotes/origin/cbtmp{pr}"])
        if rc != 0:
            return None
        _, rc = _run(["git", "-C", repo_dir, "worktree", "add", "--detach", dest,
                      f"origin/cbtmp{pr}"])
        return dest if rc == 0 else None
    return checkout


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("node", help="pytest node id, e.g. path/test_x.py::test_y")
    ap.add_argument("--repo", default="vibeic/vibe-ic")
    ap.add_argument("--repo-dir", default=".", help="local clone to make worktrees in")
    ap.add_argument("--work-dir", default="/tmp", help="where worktrees are created")
    ap.add_argument("--also", action="append", default=[],
                    help="extra file(s) that make a PR a candidate")
    a = ap.parse_args(argv)

    test_file = a.node.split("::", 1)[0]
    pr_files = open_pr_files(a.repo)
    if not pr_files:
        print(report(2, [], [], a.node))
        return 2
    cands = candidates(pr_files, test_file, a.also)
    print(f"{len(pr_files)} open PR(s); {len(cands)} touch {test_file}: "
          + (", ".join(f"#{n}" for n in cands) or "none"), file=sys.stderr)
    results = measure(cands, a.node,
                      checkout=worktree_checkout(a.repo_dir, a.work_dir, a.repo))
    code, cov, unk = decide(results)
    print(report(code, cov, unk, a.node))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
