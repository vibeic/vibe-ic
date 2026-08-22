#!/usr/bin/env python3
"""programs/picker_fixture_thrash_guard.py — v1.6.63

Pre-commit gate that prevents the issue-#5 picker-thrashing pattern
(a fix for project A silently breaks project B that was previously
correct) from shipping.

The gate runs against the STAGED diff. If the staged change modifies
the `_EXPECTED` dict in `tests/test_phase1_fixtures_regression.py`
— i.e. it asserts a NEW expected ic_name for one of the eleven
benchmark projects — the commit is allowed only if the commit
message contains an explicit acknowledgment line:

    fixture-flip-acknowledged: <project>:<old> -> <new>

This forces the human / debug agent to consciously declare each
real-input behaviour change, so silent thrashing cannot ship.

Exit codes:
  0 — no flips, OR every flip carries a matching acknowledgment line
  1 — at least one flip without acknowledgment

Usage (from pre_commit_check.sh):
    python3 programs/picker_fixture_thrash_guard.py \\
        --repo-root <root> [--commit-msg-file <path>]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

#: Repo-root-relative path of the file whose `_EXPECTED` dict this guard
#: watches. It is fed straight to `git diff --cached -- <path>`, and THAT is
#: why it has to be exact: git does not complain about a pathspec matching
#: nothing, it returns an empty diff. An empty diff means no flips, and no
#: flips means rc=0 — so a wrong path here does not break the guard loudly,
#: it makes the guard say PASS to everything, forever.
#:
#: It named `plugins/vibe-ic/tests/` until vibe-ic#1391. That directory has
#: never been tracked in this repository (`git log --all --diff-filter=A`
#: returns nothing for it); the file has always been under `programs/tests/`.
#: Measured on 75776dbbb with a real `"aes": "AES" -> "AES-XTS"` flip staged
#: in the real file: `PASS: no fixture _EXPECTED flips in staged diff`, rc=0.
#:
#: `test_picker_fixture_thrash_guard.py` could not catch it, and the reason is
#: worth keeping: it builds its temp repo at `repo / mod._FIXTURE_TEST_REL`,
#: so it MANUFACTURES whatever directory this constant names and then proves
#: the logic against it. Every value passes such a test. The pinning test is
#: `test_issue1391_thrash_guard_watches_a_path_that_exists.py`, which resolves
#: this constant against the real tree instead of against a fixture.
_FIXTURE_TEST_REL = (
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/"
    "test_phase1_fixtures_regression.py"
)
_EXPECTED_LINE_RE = re.compile(
    r'^\s*"(?P<project>[a-z0-9_]+)"\s*:\s*"(?P<name>[^"]+)"'
)


def _git(repo_root: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=str(repo_root),
        capture_output=True, text=True, check=False,
    )
    return out.stdout


def _staged_expected_diff(repo_root: Path) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Return (added, removed) maps of project→expected name from the
    staged diff of the fixture test file."""
    diff = _git(repo_root, "diff", "--cached", "--unified=0",
                "--", _FIXTURE_TEST_REL)
    added: Dict[str, str] = {}
    removed: Dict[str, str] = {}
    in_expected_block = False
    for line in diff.splitlines():
        if line.startswith("@@"):
            in_expected_block = True
            continue
        if not in_expected_block:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            m = _EXPECTED_LINE_RE.match(line[1:])
            if m:
                added[m.group("project")] = m.group("name")
        elif line.startswith("-") and not line.startswith("---"):
            m = _EXPECTED_LINE_RE.match(line[1:])
            if m:
                removed[m.group("project")] = m.group("name")
    return added, removed


def _flips(added: Dict[str, str],
           removed: Dict[str, str]) -> List[Tuple[str, str, str]]:
    """A flip is a project that exists in BOTH added and removed maps
    with a different value. (Pure additions are new fixtures and are
    fine; pure removals are deletions and are fine.)"""
    out: List[Tuple[str, str, str]] = []
    for proj, new in added.items():
        old = removed.get(proj)
        if old is not None and old != new:
            out.append((proj, old, new))
    return out


_ACK_RE = re.compile(
    r"^\s*fixture-flip-acknowledged\s*:\s*"
    r"(?P<project>[a-z0-9_]+)\s*:\s*"
    r"(?P<old>.+?)\s*(?:->|=>|→)\s*"
    r"(?P<new>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _acknowledged(commit_msg: str) -> Dict[str, Tuple[str, str]]:
    out: Dict[str, Tuple[str, str]] = {}
    for m in _ACK_RE.finditer(commit_msg):
        out[m.group("project").lower()] = (
            m.group("old").strip(), m.group("new").strip()
        )
    return out


def _read_commit_msg(repo_root: Path,
                     msg_file: Optional[str]) -> str:
    if msg_file:
        p = Path(msg_file)
        if p.is_file():
            return p.read_text(errors="ignore")
    # Fallback: try the standard git commit-msg path.
    git_dir = (repo_root / ".git" / "COMMIT_EDITMSG")
    if git_dir.is_file():
        return git_dir.read_text(errors="ignore")
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--commit-msg-file", default=None)
    args = ap.parse_args()
    repo_root = Path(args.repo_root).resolve()

    added, removed = _staged_expected_diff(repo_root)
    flips = _flips(added, removed)

    if not flips:
        print("  PASS: no fixture _EXPECTED flips in staged diff")
        return 0

    commit_msg = _read_commit_msg(repo_root, args.commit_msg_file)
    acks = _acknowledged(commit_msg)

    missing: List[str] = []
    for project, old, new in flips:
        ack = acks.get(project.lower())
        if not ack:
            missing.append(
                f"  - {project}: {old!r} -> {new!r}  "
                f"(no `fixture-flip-acknowledged:` line)"
            )
            continue
        if ack[1] != new:
            missing.append(
                f"  - {project}: ack target {ack[1]!r} != "
                f"diff new {new!r}"
            )

    if missing:
        print("  FAIL: fixture-thrash guard rejected the commit")
        print("    Issue-#5 lesson: silent flips of "
              "tests/test_phase1_fixtures_regression.py::_EXPECTED")
        print("    are how the v1.6.51→v1.6.58→v1.6.60 thrashing "
              "shipped.")
        print("    For each flip below, add a line to your commit "
              "message like:")
        print("        fixture-flip-acknowledged: <project>:"
              "<old> -> <new>")
        print("    Flips without acknowledgment:")
        for line in missing:
            print(line)
        return 1

    print(f"  PASS: {len(flips)} fixture flip(s), all acknowledged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
