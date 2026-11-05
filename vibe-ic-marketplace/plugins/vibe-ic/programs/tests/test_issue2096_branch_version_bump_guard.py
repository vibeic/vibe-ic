"""#2096 — nothing refused a version bump riding into a `next/*` commit.

Lane czstarve4 measured it on 2026-09-07: the plugin test suite WRITES the
version-bearing files, `git add -A` swept them into two of the lane's own
commits, and no hook, gate or checker objected. The lane spotted it by hand
before pushing. The next one will not.

REPRODUCED HERE, ON THE REAL HOOK, before anything was changed. A synthetic
repo in the shipped layout, a `next/x` branch whose only difference from `main`
is a 1.0.0 -> 1.0.1 bump across all six version-bearing files, and
`origin/main`'s `tools/git-hooks/pre-push` fed the stdin git gives it:

    pre-push (origin/main)     rc 0     "PASS: no NDA foundry ... token"
    pre-push (this branch)     rc 1     FAILED — branch carries no version bump

Both directions are damage, and the gate that was already there covers neither:
`version_bump_monotonic_check --version-by-gatekeeper` MUST pass a forward bump
(on the landing path a forward bump is the point), and it reads plugin.json plus
one marketplace.json — the three shipped READMEs state the version in prose and
were read by nothing.

WHAT EACH ARM IS FOR
--------------------
  * `test_the_hook_runs_the_guard`              — the wiring. Red on origin/main.
  * `test_hook_END_TO_END_refuses_a_swept_bump` — the behaviour, driven.
  * `test_MUTANT_hook_without_the_gate_lets_it_through` — the mutation arm. Strip
    ONLY the `run_gate` call from the SHIPPED hook and the same fixture pushes
    clean, so the arm above is measuring that line and not something else.
  * `test_the_guarded_sites_ARE_the_files_the_version_writer_writes` — the
    non-vacuity arm. The guard derives its file list from the same helpers
    `gatekeeper_assign_version --write` writes through; this drives the REAL
    writer and asserts the two sets are equal, so a seventh version-bearing site
    cannot be added to the writer and silently escape the guard.
  * the green arms — an unrelated edit to a version-bearing file, a branch cut
    from an older main, `main` and `land/*` — each of which a guard written as
    "refuse any touch of these files" would have refused. A hook that refuses
    ordinary work is a hook that gets `--no-verify`'d.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr                    # noqa: E402

_PROGRAMS = Path(__file__).resolve().parents[1]


def _find_hook() -> Path:
    """Walk up for the artefact rather than counting directories — a
    hard-coded `parents[N]` is a guess about how deep this file sits."""
    for parent in Path(__file__).resolve().parents:
        cand = parent / "tools" / "git-hooks" / "pre-push"
        if cand.is_file():
            return cand
    raise AssertionError("tools/git-hooks/pre-push not found above this test")


HOOK = _find_hook()

#: The `run_gate` label the hook uses. One spelling, read by both the wiring
#: assertion and the mutation arm, so they cannot drift apart.
GATE_LABEL = "branch carries no version bump"




# ── the fixture: the shipped layout, in miniature ───────────────────────────

def _write_tree(root: Path, version: str) -> None:
    """A repo in the SHIPPED shape: a nested plugin, TWO marketplace manifests
    that reference it (the repo-root one and the nested one), and the three
    prose sites. A one-manifest fixture cannot see a guard that reads only the
    nearest ancestor."""
    plug = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (root / "vibe-ic-marketplace" / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (plug / ".claude-plugin").mkdir(parents=True, exist_ok=True)

    (plug / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "vibe-ic", "version": version}) + "\n", encoding="utf-8")
    (root / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"name": "m", "plugins": [
            {"name": "vibe-ic", "source": "./vibe-ic-marketplace/plugins/vibe-ic",
             "version": version}]}) + "\n", encoding="utf-8")
    (root / "vibe-ic-marketplace" / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"name": "m", "plugins": [
            {"name": "vibe-ic", "source": "./plugins/vibe-ic",
             "version": version}]}) + "\n", encoding="utf-8")
    (root / "README.md").write_text(
        f"[![Plugin v{version}](x)](y)\n\nsome prose\n", encoding="utf-8")
    (root / "vibe-ic-marketplace" / "README.md").write_text(
        f"| Plugin version | **{version}** |\n", encoding="utf-8")
    (plug / "README.md").write_text(
        f"the vibe-ic plugin (**v{version}**)\n", encoding="utf-8")


def _git(root: Path, *a: str) -> subprocess.CompletedProcess:
    return _pr.run(["git", "-C", str(root), *a], capture_output=True, text=True)


def _seed(root: Path, version: str = "1.0.0") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", ".")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _write_tree(root, version)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed")
    _git(root, "branch", "-M", "main")
    return root


def _branch(root: Path, name: str, *, from_ref: str = "main") -> None:
    assert _git(root, "checkout", "-q", "-B", name, from_ref).returncode == 0


def _commit(root: Path, msg: str) -> None:
    _git(root, "add", "-A")
    assert _git(root, "commit", "-q", "-m", msg).returncode == 0




# ── the exemption, which is the whole scope of the gate ─────────────────────





# ── the defect, on the program ──────────────────────────────────────────────









# ── the directions that must NOT move ───────────────────────────────────────







# ── "could not look" is not "looked and it was clean" ───────────────────────





# ── NON-VACUITY: the guarded set IS the written set ─────────────────────────





# ── polarity: a sentence that prints a number and denies it ─────────────────
#
# `prose_polarity_consulted_check` (vibe-ic#712) blocks a NEW extractor that
# searches prose for a value and writes it as a declaration without asking
# whether the sentence DENIES it, and it caught `claims_at` on this branch —
# correctly. These two arms are the behaviour that answer implements, driven
# rather than asserted from the import.

# The `title` claim is `plugin\s*\(\*\*v(\d+\.\d+\.\d+)\*\*\)` — the `v` is
# part of the pattern. Written without it the regex matches NOTHING and this
# fixture passes for the wrong reason; the disclosure assertion below is what
# caught that while this test was being written.
_DENIED_README = ("The old numbering is gone. The vibe-ic plugin (**v1.0.1**) is "
                  "not shipped from this branch.\n")
_PLAIN_README = "the vibe-ic plugin (**v1.0.1**)\n"










# ── the wiring, and the mutation arm ────────────────────────────────────────



def _fixture_repo_with_a_swept_bump(tmp_path: Path) -> Path:
    """A synthetic repo whose `next/x` differs from `main` ONLY by a bump, with
    the REAL programs/ symlinked in so the hook resolves its gates the way it
    does in a checkout."""
    root = _seed(tmp_path / "e2e")
    _branch(root, "next/x")
    _write_tree(root, "1.0.1")
    _commit(root, "fix(x): a real change that swept a version bump in")
    link = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(_PROGRAMS)
    return root


def _drive_hook(hook: Path, root: Path, dest: str = "refs/heads/next/x"):
    """Invoke a pre-push hook the way git does: argv = <remote> <url>, and the
    ref line on stdin."""
    head = _git(root, "rev-parse", "HEAD").stdout.strip()
    base = _git(root, "rev-parse", "main").stdout.strip()
    stdin = f"{dest} {head} {dest} {base}\n"
    return _pr.run(["bash", str(hook), "origin", str(root)],
                   input=stdin, capture_output=True, text=True, cwd=str(root))


@pytest.mark.skipif(not HOOK.is_file(), reason="hook not present in this tree")
def test_hook_END_TO_END_refuses_a_swept_bump(tmp_path):
    root = _fixture_repo_with_a_swept_bump(tmp_path)
    r = _drive_hook(HOOK, root)
    assert r.returncode != 0, (
        "the real hook let a branch carrying a version bump through:\n"
        + (r.stderr or r.stdout)[-2000:])
    assert GATE_LABEL in r.stderr, (
        "the push was refused, but not by this gate — this arm would then be "
        "measuring something else:\n" + r.stderr[-2000:])
    assert "LANDER ASSIGNS THE VERSION" in r.stderr.upper(), (
        "the hook blocked the push without telling the reader who assigns the "
        "version, which is the one thing they act on:\n" + r.stderr[-2000:])


@pytest.mark.skipif(not HOOK.is_file(), reason="hook not present in this tree")
def test_MUTANT_hook_without_the_gate_lets_it_through(tmp_path):
    """THE MUTATION ARM. Take the SHIPPED hook, delete ONLY the `run_gate` call
    for this gate, and the identical fixture pushes clean. Without this arm the
    end-to-end above would pass just as well against a hook that refuses for
    some other reason."""
    root = _fixture_repo_with_a_swept_bump(tmp_path)
    src = HOOK.read_text(encoding="utf-8").splitlines()
    out, i, removed = [], 0, 0
    while i < len(src):
        if GATE_LABEL in src[i] and "run_gate" in src[i]:
            # the call and its continuation lines
            while i < len(src) and src[i].rstrip().endswith("\\"):
                i += 1
            i += 1
            removed += 1
            continue
        out.append(src[i])
        i += 1
    assert removed == 1, (
        f"expected exactly one run_gate call for {GATE_LABEL!r}, removed "
        f"{removed}. PREMISE FIRST: an arm that strips nothing proves nothing.")
    mutant = tmp_path / "pre-push-mutant"
    mutant.write_text("\n".join(out) + "\n", encoding="utf-8")

    m = _drive_hook(mutant, root)
    assert GATE_LABEL not in m.stderr, (
        "the mutant still named the gate, so the line removed is not the one "
        "doing the work:\n" + m.stderr[-2000:])
    assert m.returncode == 0, (
        "the mutant refused the push for some OTHER reason, so the end-to-end "
        "arm is not attributable to this gate:\n" + (m.stderr or m.stdout)[-2000:])
