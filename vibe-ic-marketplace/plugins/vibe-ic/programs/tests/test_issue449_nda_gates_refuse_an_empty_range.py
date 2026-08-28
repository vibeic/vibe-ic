#!/usr/bin/env python3
"""An empty range is not a clean range.

`gatekeeper_review` holds 11 gates and is in NO CI workflow; this repo lands
most work by DIRECT PUSH, so 9 of them — including BOTH NDA guards — ran on
none of a 33-landing session (#449). Wiring them into CI means giving them a
range, and a range gate handed the wrong range is the classic way a guard
starts reporting confidently about the wrong commits.

MEASURED BEFORE WIRING, on both gates:

    0000…0000..HEAD   (force-push / first push of a branch)   rc 2  refuses
    nonexistentref..HEAD                                      rc 2  refuses
    HEAD..HEAD        (empty range)                           rc 0  **PASS**

The third is the #447 class: zero commits scanned, reported identically to a
real clean scan of 33. That is the one dangerous case, and it is the one a
mis-wired workflow produces silently. Both gates now refuse it.

This repo has a documented history of foundry SKU tokens reaching commit
messages and source (the 2026-07-18 purge). These two gates are what stands
between that and a public push, so a silent pass here is not a small thing.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parent.parent
_REPO = _PROGRAMS.parents[3]


def _run(prog: str, *args: str):
    r = _pr.run(
        [sys.executable, str(_PROGRAMS / prog), *args],
        capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr)


def _repo(tmp_path: Path) -> Path:
    d = tmp_path / "r"
    d.mkdir()
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(d), "config", k, v], check=True)
    (d / "a.txt").write_text("hello\n")
    subprocess.run(["git", "-C", str(d), "add", "a.txt"], check=True)
    subprocess.run(["git", "-C", str(d), "commit", "-qm", "one"], check=True)
    return d


def test_commit_msg_gate_refuses_an_empty_range(tmp_path):
    """THE DANGEROUS CASE."""
    d = _repo(tmp_path)
    rc, out = _run("commit_msg_nda_check.py", "--rev-range", "HEAD..HEAD",
                   "--repo", str(d))
    assert rc == 2, out
    assert "NOTHING_SCANNED" in out, out


def test_diff_gate_refuses_an_empty_range(tmp_path):
    d = _repo(tmp_path)
    rc, out = _run("nda_diff_scan_check.py", "--rev-range", "HEAD..HEAD",
                   "--repo", str(d))
    assert rc == 2, out
    assert "NOTHING_SCANNED" in out, out


def test_both_gates_still_PASS_a_real_clean_range(tmp_path):
    """The paired half. Refusing everything would be its own false gate."""
    d = _repo(tmp_path)
    (d / "b.txt").write_text("world\n")
    subprocess.run(["git", "-C", str(d), "add", "b.txt"], check=True)
    subprocess.run(["git", "-C", str(d), "commit", "-qm", "two"], check=True)
    for prog in ("commit_msg_nda_check.py", "nda_diff_scan_check.py"):
        rc, out = _run(prog, "--rev-range", "HEAD~1..HEAD", "--repo", str(d))
        assert rc == 0, (prog, out)
        assert "PASS" in out, (prog, out)


def test_an_all_zero_sha_still_refuses(tmp_path):
    """A force-push or a branch's first push gives `github.event.before` as an
    all-zero SHA. It already refused before this change; pinned so the
    empty-range fix cannot accidentally turn it into a pass."""
    d = _repo(tmp_path)
    z = "0" * 40
    for prog in ("commit_msg_nda_check.py", "nda_diff_scan_check.py"):
        rc, _ = _run(prog, "--rev-range", f"{z}..HEAD", "--repo", str(d))
        assert rc == 2, prog


def test_empty_STDIN_is_still_allowed(tmp_path):
    """Scoped on purpose: `--stdin` with no diff is a caller who genuinely has
    none, and refusing there would fire on legitimate use."""
    r = _pr.run(
        [sys.executable, str(_PROGRAMS / "nda_diff_scan_check.py"), "--stdin"],
        input="", capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_real_session_range_is_clean():
    """The measurement that justified all of this: 33 direct-push landings went
    in without either gate running. They are clean — checked, not hoped."""
    import pytest
    rc, out = _run("commit_msg_nda_check.py", "--rev-range",
                   "1c1ab9e38..HEAD", "--repo", str(_REPO))
    if rc == 2 and "unknown revision" in out.lower():
        pytest.skip("session base not present in this clone")
    assert rc == 0, out
