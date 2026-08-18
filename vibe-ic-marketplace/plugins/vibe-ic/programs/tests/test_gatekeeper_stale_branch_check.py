"""test_gatekeeper_stale_branch_check.py — proofs for the stale-branch guard.

The guard catches the phantom-revert trap: a PR branch cut from an OLDER base
than the current tip, whose blind `git checkout HEAD -- <files>` land would
silently revert work that landed since the fork. It must:

  FRESH          — branch on the current tip → rc 0.
  STALE_OVERLAP  — forked earlier AND touches a file landed since → rc 1
                   (blind checkout WOULD revert it; land via cherry-pick).
  STALE_ADVISORY — forked earlier but shares NO file with the landed work
                   (the #246/#247 shape: orthogonal files) → rc 0.
  ERROR          — an unresolvable ref FAILs LOUD (rc 2), never silent-clean.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_PLUGIN_ROOT = _HERE.parents[2]
_PROGRAMS = _PLUGIN_ROOT / "programs"
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import gatekeeper_stale_branch_check as guard  # noqa: E402

_CHECKER = _PROGRAMS / "gatekeeper_stale_branch_check.py"


def _git(repo: Path, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True)


def _run(args):
    p = subprocess.run([sys.executable, str(_CHECKER), *args],
                       capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def _repo(tmp_path: Path) -> Path:
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    (r / "x.py").write_text("x = 0\n")
    (r / "y.py").write_text("y = 0\n")
    _git(r, "add", "."); _git(r, "commit", "-qm", "base0")
    return r


def _fork_pr(r: Path):
    _git(r, "branch", "pr")


def _land_on_main(r: Path, path: str, content: str, msg: str):
    _git(r, "checkout", "-q", "main")
    (r / path).write_text(content)
    _git(r, "add", path); _git(r, "commit", "-qm", msg)


def _commit_on_pr(r: Path, path: str, content: str, msg: str):
    _git(r, "checkout", "-q", "pr")
    (r / path).write_text(content)
    _git(r, "add", path); _git(r, "commit", "-qm", msg)


# ── FRESH ───────────────────────────────────────────────────────────────────
def test_fresh_branch_on_current_tip(tmp_path):
    r = _repo(tmp_path)
    # pr forks AFTER nothing else lands → merge-base == main tip.
    _fork_pr(r)
    _commit_on_pr(r, "x.py", "x = 1\n", "pr change")
    res = guard.analyze(r, "main", "pr")
    assert res.verdict == "FRESH" and res.rc == 0
    rc, out, _ = _run(["--repo", str(r), "--base", "main", "--head", "pr"])
    assert rc == 0 and "FRESH" in out


# ── STALE + OVERLAP (phantom-revert risk) ───────────────────────────────────
def test_stale_overlap_is_blocked(tmp_path):
    r = _repo(tmp_path)
    _fork_pr(r)
    _land_on_main(r, "x.py", "x = 99  # landed fix\n", "land fix on x")
    _commit_on_pr(r, "x.py", "x = 1  # pr edit\n", "pr also edits x")
    res = guard.analyze(r, "main", "pr")
    assert res.verdict == "STALE_OVERLAP" and res.rc == 1
    assert "x.py" in res.overlap_files
    assert res.intervening_commits == 1
    rc, out, err = _run(["--repo", str(r), "--base", "main", "--head", "pr"])
    assert rc == 1
    assert "CHERRY-PICK" in (out + err).upper()


# ── STALE, no overlap (the #246/#247 orthogonal-file shape) ─────────────────
def test_stale_no_overlap_is_advisory(tmp_path):
    r = _repo(tmp_path)
    _fork_pr(r)
    _land_on_main(r, "x.py", "x = 99  # landed fix\n", "land fix on x")
    _commit_on_pr(r, "y.py", "y = 1  # pr edits a DIFFERENT file\n", "pr edits y")
    res = guard.analyze(r, "main", "pr")
    assert res.verdict == "STALE_ADVISORY" and res.rc == 0
    assert res.overlap_files == []
    assert res.intervening_commits == 1
    rc, out, _ = _run(["--repo", str(r), "--base", "main", "--head", "pr"])
    assert rc == 0 and "STALE" in out


def test_stale_overlap_multiple_intervening(tmp_path):
    r = _repo(tmp_path)
    _fork_pr(r)
    _land_on_main(r, "x.py", "x = 1\n", "land1")
    _land_on_main(r, "x.py", "x = 2\n", "land2")
    _commit_on_pr(r, "x.py", "x = 9\n", "pr edits x")
    res = guard.analyze(r, "main", "pr")
    assert res.verdict == "STALE_OVERLAP" and res.rc == 1
    assert res.intervening_commits == 2


# ── ERROR: unresolvable ref fails loud ──────────────────────────────────────
def test_unresolvable_ref_errors_loud(tmp_path):
    r = _repo(tmp_path)
    rc, out, err = _run(["--repo", str(r), "--base", "main", "--head", "nope"])
    assert rc == 2
    assert "error" in (out + err).lower()


def test_json_report_is_written(tmp_path):
    r = _repo(tmp_path)
    _fork_pr(r)
    _land_on_main(r, "x.py", "x = 5\n", "land")
    _commit_on_pr(r, "x.py", "x = 6\n", "pr")
    jf = tmp_path / "out.json"
    rc, _, _ = _run(["--repo", str(r), "--base", "main", "--head", "pr",
                     "--json", str(jf)])
    import json as _j
    data = _j.loads(jf.read_text())
    assert data["gate"] == "gatekeeper_stale_branch_check"
    assert data["verdict"] == "STALE_OVERLAP" and data["rc"] == 1
    assert "x.py" in data["overlap_files"]
