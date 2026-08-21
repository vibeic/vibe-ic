"""vibe-ic#794 — an ORGANIC backlog item on disk that git does not know about.

THE DEFECT, MEASURED
====================
Thirteen ORGANIC backlog items were written into
`vibe-ic-marketplace/community/backlogs/` between 2026-06-14 and 2026-07-12 and
never committed, beside twenty-five siblings that were. `ls` shows one
directory; git shows a smaller one. Nothing in the repo ever asked the
difference, so the loss was silent for seven weeks and the files are now gone.

The write path is prose (`skills/community-backlog-submit` Step 3 writes the
file, Step 4 sanitizes it, Step 5 optionally opens a GitHub issue — no step
commits it). This pins the missing PREDICATE instead: `backlog_sanitize_check
--audit tracked` refuses a directory that holds a backlog file git does not
track.

Every test here DRIVES the program as a subprocess against a REAL git
repository built in `tmp_path` — no fixture stands in for git's answer, because
the whole question is what git actually says.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "backlog_sanitize_check.py"

def _shipped_version() -> str:
    """The version the manifest actually declares.

    Hard-coded here before, which made this fixture go red on every release
    bump for a reason nobody broke — the record under test is meant to be
    CURRENT, and "current" is a property of the manifest, not a literal."""
    import json as _j
    here = Path(__file__).resolve().parent.parent.parent
    return str(_j.loads((here / ".claude-plugin" / "plugin.json").read_text())["version"])


_ITEM = f"""\
type: bug
severity: P1
component: program:some_gate
plugin_version: "{_shipped_version()}"
title: >-
  A generic gate mis-classifies a structural shape and blocks a correct design
pattern: |
  The gate reads a declaration region without stripping comments, so a
  commented-out declaration is credited as real.
suggested_fix: |
  Strip comments before the declaration scan.
"""




def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "community" / "backlogs").mkdir(parents=True)
    _git(repo.parent, "init", "-q", str(repo))
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    return repo


def _write(repo: Path, name: str) -> Path:
    p = repo / "community" / "backlogs" / name
    p.write_text(_ITEM)
    return p


def _commit(repo: Path, *rel: str) -> None:
    _git(repo, "add", "--", *rel)
    _git(repo, "commit", "-q", "-m", "add backlog item")


def _run(repo: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), "--dir",
         str(repo / "community" / "backlogs"), *extra],
        capture_output=True, text=True)


def _doc(proc: subprocess.CompletedProcess) -> dict:
    return json.loads(proc.stdout)


# ── the defect itself ───────────────────────────────────────────────────────

def test_untracked_backlog_item_is_an_error(tmp_path):
    """The exact #794 shape: one committed sibling, one that never was."""
    repo = _repo(tmp_path)
    _write(repo, "ORGANIC-20260101-tracked-sibling.yaml")
    _commit(repo, "community/backlogs/ORGANIC-20260101-tracked-sibling.yaml")
    _write(repo, "ORGANIC-20260614-never-committed.yaml")

    proc = _run(repo, "--audit", "tracked")

    assert proc.returncode == 1, proc.stdout + proc.stderr
    doc = _doc(proc)
    assert doc["summary"]["pass"] is False
    cats = [f["category"] for f in doc["findings"]]
    assert cats == ["UNTRACKED_BACKLOG"], cats
    assert doc["findings"][0]["file"].endswith(
        "ORGANIC-20260614-never-committed.yaml")


def test_all_tracked_passes_and_states_its_denominator(tmp_path):
    """A clean directory passes — and says how many files it looked at."""
    repo = _repo(tmp_path)
    for n in ("ORGANIC-20260101-a.yaml", "ORGANIC-20260102-b.yaml"):
        _write(repo, n)
    _commit(repo, "community/backlogs")

    proc = _run(repo, "--audit", "tracked")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    t = _doc(proc)["summary"]["tracked_audit"]
    assert (t["on_disk"], t["tracked"]) == (2, 2)
    assert t["untracked"] == [] and t["ignored"] == []
    # The denominator must be readable without parsing JSON: a PASS that says
    # nothing is indistinguishable from a PASS over an empty directory.
    assert "2 backlog file(s) examined" in proc.stderr


def test_gitignored_backlog_item_is_reported_apart(tmp_path):
    """`git add` would silently refuse it — a different remedy, so a different
    category. Folding it into UNTRACKED would send the reader to a fix that
    does not work."""
    repo = _repo(tmp_path)
    (repo / ".gitignore").write_text("community/backlogs/*-draft.yaml\n")
    _git(repo, "add", "--", ".gitignore")
    _git(repo, "commit", "-q", "-m", "ignore drafts")
    _write(repo, "ORGANIC-20260614-hidden-draft.yaml")

    proc = _run(repo, "--audit", "tracked")

    assert proc.returncode == 1, proc.stdout + proc.stderr
    cats = [f["category"] for f in _doc(proc)["findings"]]
    assert cats == ["IGNORED_BACKLOG"], cats


# ── the two ways of not being able to answer ────────────────────────────────

def test_outside_a_git_work_tree_refuses_rather_than_passes(tmp_path):
    """"I could not look" must never reach a reader as "I looked and it was
    clean" — the vacuous-PASS shape this repo removes one gate at a time."""
    loose = tmp_path / "loose" / "backlogs"
    loose.mkdir(parents=True)
    (loose / "ORGANIC-20260614-x.yaml").write_text(_ITEM)

    proc = subprocess.run(
        [sys.executable, str(PROG), "--dir", str(loose), "--audit", "tracked"],
        capture_output=True, text=True,
        # HOME/GIT_CEILING so a git repo ABOVE tmp_path cannot answer for this
        # directory and make the test pass for the wrong reason.
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
             "GIT_CEILING_DIRECTORIES": str(tmp_path)})

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert _doc(proc)["summary"]["refused"] is True
    assert "not inside a git work tree" in proc.stderr


def test_git_binary_missing_refuses_rather_than_crashing(tmp_path):
    """No git on PATH is a THIRD outcome. A traceback exits 1, which the
    dispatcher reads as "found a defect"; an empty tracked set would report
    every file on disk as lost. Neither is a verdict this program earned."""
    repo = _repo(tmp_path)
    _write(repo, "ORGANIC-20260101-a.yaml")
    _commit(repo, "community/backlogs")

    empty_bin = tmp_path / "nogit"
    empty_bin.mkdir()
    proc = subprocess.run(
        [sys.executable, str(PROG), "--dir",
         str(repo / "community" / "backlogs"), "--audit", "tracked"],
        capture_output=True, text=True,
        env={"PATH": str(empty_bin), "HOME": str(tmp_path)})

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "Traceback" not in proc.stderr, proc.stderr
    assert _doc(proc)["summary"]["refused"] is True


def test_empty_backlog_directory_refuses_in_tracked_mode(tmp_path):
    """A zero population certifies nothing. rc 2, not a pass."""
    repo = _repo(tmp_path)
    proc = _run(repo, "--audit", "tracked")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "0 backlog file(s) on disk" in proc.stderr


# ── the content lane is untouched ───────────────────────────────────────────

def test_default_audit_is_content_and_ignores_trackedness(tmp_path):
    """Backward compatibility: with no --audit the program behaves exactly as
    it did, so the 18 pre-existing content findings on this repo's own corpus
    cannot leak into the new blocking lane (and vice versa)."""
    repo = _repo(tmp_path)
    _write(repo, "ORGANIC-20260614-never-committed.yaml")

    proc = _run(repo)   # no --audit

    assert proc.returncode == 0, proc.stdout + proc.stderr
    doc = _doc(proc)
    assert doc["summary"]["files_checked"] == 1
    assert "tracked_audit" not in doc["summary"]
    assert doc["findings"] == []


def test_both_runs_the_two_audits_together(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "ORGANIC-20260614-never-committed.yaml")

    proc = _run(repo, "--audit", "both")

    assert proc.returncode == 1, proc.stdout + proc.stderr
    doc = _doc(proc)
    assert doc["summary"]["files_checked"] == 1
    assert doc["summary"]["tracked_audit"]["on_disk"] == 1
    assert [f["category"] for f in doc["findings"]] == ["UNTRACKED_BACKLOG"]


# ── the categories, written out ─────────────────────────────────────────────

def test_tracked_audit_category_names(tmp_path):
    """Named as LITERALS and compared for set equality — deliberately NOT a
    loop over the program's own constants, which would delete its own coverage
    the moment a member was removed."""
    sys.path.insert(0, str(PROG.parent))
    import backlog_sanitize_check as mod

    assert mod.CAT_UNTRACKED == "UNTRACKED_BACKLOG"
    assert mod.CAT_IGNORED == "IGNORED_BACKLOG"
    assert {mod.CAT_UNTRACKED, mod.CAT_IGNORED} == {
        "UNTRACKED_BACKLOG", "IGNORED_BACKLOG"}


# ── the watched directory is the one the skills tell you to write to ────────

def test_every_documented_backlog_directory_resolves_to_a_real_one():
    """A backlog written where the gate does not look is lost the same way.

    Two loop skills said `<plugin_root>/community/backlogs/`, which resolves to
    `plugins/vibe-ic/community/backlogs/` — a directory that does not exist,
    while `agent_checkin_scope_guard.ZONE_BACKLOG` and the hygiene gate both
    watch `vibe-ic-marketplace/community/backlogs/`. This RESOLVES each
    documented path against the real tree (the `tracked_symlink_target_present`
    doctrine: a pointer nobody dereferences is not a pointer) rather than
    matching source text.
    """
    plugin_root = PROG.resolve().parents[1]
    repo_root = PROG.resolve().parents[4]
    marketplace = repo_root / "vibe-ic-marketplace"

    prefixes = {
        "<plugin_root>": plugin_root,
        "<repo_root>": repo_root,
        "<marketplace_root>": marketplace,
        # No placeholder: marketplace-root-relative, which is the cwd
        # `community-backlog-submit` invokes the sanitizer from.
        "": marketplace,
    }
    # Only the forms that tell an agent WHERE TO WRITE — a directory followed
    # immediately by the ORGANIC filename template. Prose that quotes a path to
    # explain why it is wrong is not an instruction and is not the population.
    pattern = re.compile(r"(<[a-z_]+>/)?([\w./-]*community/backlogs)/ORGANIC-")

    unresolved = []
    for md in sorted((plugin_root / "skills").rglob("SKILL.md")):
        for line in md.read_text(errors="replace").splitlines():
            for prefix, rel in pattern.findall(line):
                base = prefixes[prefix.rstrip("/")]
                cand = base / rel
                if not cand.is_dir():
                    unresolved.append(f"{md.relative_to(plugin_root)}: "
                                      f"{prefix}{rel} -> {cand}")
    # The scan must have found something, or it proves nothing.
    assert pattern.search(
        (plugin_root / "skills" / "community-backlog-submit"
         / "SKILL.md").read_text()), "the write-path form is no longer matched"
    assert not unresolved, (
        "documented backlog directory does not exist — a file written there is "
        "watched by nothing:\n  " + "\n  ".join(unresolved))


# ── the gate is WIRED, proven by running the wiring ─────────────────────────

def test_gate_is_declared_in_the_hygiene_set():
    """A predicate nobody invokes is the producer/consumer break one level up.

    Proven by RUNNING `repo_hygiene_gates.sh --list`, which enumerates through
    the same `_gate_dispatch` the real run uses — not by grepping the script.
    """
    root = PROG.resolve().parents[4]
    script = root / "tools" / "ci" / "repo_hygiene_gates.sh"
    if not script.is_file():          # published plugin tree without tools/ci
        pytest.skip(f"{script} not present in this tree")

    proc = subprocess.run(["bash", str(script), "--list"],
                          capture_output=True, text=True, cwd=str(root))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    listed = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    assert "backlog items are tracked" in listed, listed[-15:]
