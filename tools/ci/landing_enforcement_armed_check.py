#!/usr/bin/env python3
"""Is the enforcement point that reads the landing stamp actually ARMED?

ENFORCEMENT: advisory here — no runner and no gate set invokes this program.
That is a statement about WIRING, not about the verdict it can reach: this
check BLOCKS (rc 1) when it finds the enforcement point disarmed. It is not
wired by this change because the one place it belongs — immediately before
`tools/gatekeeper-land.sh` mints `.git/gatekeeper-stamp` — is sha256-PINNED in
`tools/ci/protected_landing_transition.json` (role `runtime`, in BOTH halves),
as is `tools/ci/repo_hygiene_gates.sh` (role `authority`); editing either
without re-authoring that manifest breaks the protected landing transition. So
wiring it is a REQUEST TO THE LANDER, recorded rather than taken. Declared
because vibe-ic#886 counts an undeclared AUDIT_ONLY gate as an enforcement
decision nobody made.

IT LIVES UNDER `tools/ci/` AND NOT UNDER `programs/`, deliberately. It is a
landing-lane instrument, not an IC-design gate; `gate_is_wired_check` correctly
refuses a `programs/` gate that no automatic verdict consults, and answering
that refusal by wiring this into the one venue that can only fire where the hook
already exists (`pre_commit_check.sh`, which runs from an installed hook) would
be a check that can never see the state it exists to find. Its paired test runs
in the landing lane's own repo-tools arm (`run_repo_tools_pytest`).

WHY (measured, 2026-08-21)
==========================
`prose_polarity_consulted_check` is declared in `repo_hygiene_gates.sh` with no
`gate_scope` and no `uncheckable_until` — always-run, and blocking. It went red
at v1.11.5 and stayed red through v1.11.18. FOURTEEN version-bearing landings
went past it, and it collected two further findings on the way. Every link of
the chain that should have made that impossible is individually sound, and each
was verified by running it:

    a red always-run gate     -> `gate_dispatch_finish` exits non-zero
    that exit                 -> `repo_hygiene_gates.sh` exits non-zero
    that exit                 -> `gatekeeper-land.sh`'s `run` sets FAILED=1
    FAILED != 0               -> `.git/gatekeeper-stamp` is not written, and is
                                 REMOVED if it was there
    no / stale stamp on main  -> `tools/git-hooks/pre-push` refuses the push

The chain ends in a hook, and `.git/hooks/` is NOT TRACKED BY GIT. Measured on
the machine those landings were made from: no `pre-push` hook installed in the
working clone, `core.hooksPath` unset, and

    find <home> -maxdepth 4 -type f -path "*/.git/hooks/pre-push"   -> nothing
    find <home> -maxdepth 3 -type d -name ".git" | wc -l            -> 54

So the terminal link was absent everywhere. `--no-verify` was not the mechanism;
there was nothing to bypass.

AND THIS HAD ALREADY HAPPENED ONCE. `d6ea46e9c` (2026-07-30, v1.8.39) —
"pre-push: the hooks were never installed, and CI is never coming back" — found
`.git/hooks/` empty, installed the hooks by hand, and said so in its subject
line. Twenty-two days later they are gone again. The fix was an ACTION and not a
CHECK, and an action on an untracked directory is exactly as durable as the
machine it ran on. This program is the check.

WHAT IT MEASURES
================
Four questions, answered separately so a reader can act on the right one:

    HOOK_DIR        where git will look for hooks HERE — `core.hooksPath` if
                    set, else `git rev-parse --git-path hooks`. Asked of git
                    rather than assumed, because in a worktree `.git` is a FILE
                    and the naive path does not exist.
    INSTALLED       a `pre-push` is present there and is executable.
    AUTHENTIC       it IS this repo's tracked `tools/git-hooks/pre-push` — the
                    same file by symlink target or by sha256. A hook of somebody
                    else's is not this repo's enforcement point, and "a file
                    named pre-push exists" is not the question worth answering.
    CONSUMER        the tracked hook still reads the stamp the lander writes.
                    An armed hook that no longer checks the stamp is armed at
                    nothing, and that is the same silence in a new place.

"I COULD NOT LOOK" IS NOT "IT IS FINE"
======================================
Not a git checkout, git unavailable, an unreadable hooks directory: every one is
rc 2 and says which. This whole family of defects is a green light standing in
for an absence, and a checker that returned 0 when it could not see its subject
would be one more of them.

chip-AGNOSTIC: git plumbing and this repository's own paths. No chip, PDK,
vendor, foundry or part number appears here or ever should.

USAGE
-----
    landing_enforcement_armed_check.py [--repo .] [--json OUT]

    exit 0 = the enforcement point is armed and still reads the stamp
    exit 1 = DISARMED — a landing can succeed with a red blocking gate (BLOCKING)
    exit 2 = could not be determined — never a vacuous pass
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROGRAM = "landing_enforcement_armed_check"

#: The tracked hook this repository ships, relative to the repo root.
TRACKED_HOOK_REL = "tools/git-hooks/pre-push"
#: The artefact the hook must still consume for the chain to mean anything.
#: Named once here so the producer (`gatekeeper-land.sh`) and this consumer
#: check cannot drift onto different spellings.
STAMP_BASENAME = "gatekeeper-stamp"
#: What the hook has to still DO with it. Not the exact source line — that would
#: make this gate a formatting pin — but the two things it cannot do without.
_CONSUMER_TOKENS = (STAMP_BASENAME, "--absolute-git-dir")

RC_OK, RC_DISARMED, RC_UNDETERMINED = 0, 1, 2


def _git(repo: Path, *args: str) -> Tuple[int, str, str]:
    try:
        p = subprocess.run(["git", "-C", str(repo), *args],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", f"{exc.__class__.__name__}: {exc}"
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def hooks_dir(repo: Path) -> Tuple[Optional[Path], str]:
    """Where git will look for hooks in `repo`, or (None, why-not).

    ASKED OF GIT, NOT COMPUTED. In a linked worktree `.git` is a FILE holding a
    `gitdir:` pointer, so `repo/.git/hooks` does not exist and a checker that
    built the path itself would report DISARMED on every worktree — the same
    defect `gatekeeper-land.sh` records against its own stamp path, fixed there
    with `--absolute-git-dir`.

    `core.hooksPath` wins when set, which is git's own precedence and is also
    the one way an installed hook can be present and still never run.
    """
    rc, out, err = _git(repo, "rev-parse", "--show-toplevel")
    if rc != 0:
        return None, (f"{repo} is not a git checkout, or git could not be "
                      f"asked: {err or 'git rev-parse failed'}")
    root = Path(out)
    rc, out, _ = _git(repo, "config", "--get", "core.hooksPath")
    if rc == 0 and out:
        p = Path(out)
        return (p if p.is_absolute() else (root / p)), "core.hooksPath"
    rc, out, err = _git(repo, "rev-parse", "--git-path", "hooks")
    if rc != 0:
        return None, f"git could not resolve the hooks path: {err}"
    p = Path(out)
    return (p if p.is_absolute() else (root / p)), "git-path"


def _sha256(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def inspect(repo: Path) -> Dict[str, object]:
    """Everything measured, as data. `problems` empty == armed."""
    rep: Dict[str, object] = {
        "program": PROGRAM, "repo": str(repo),
        "hooks_dir": None, "hooks_dir_source": None,
        "installed": None, "authentic": None, "consumer": None,
        "undetermined": [], "problems": [], "notes": [],
    }
    hd, source = hooks_dir(repo)
    if hd is None:
        rep["undetermined"].append(source)          # type: ignore[union-attr]
        return rep
    rep["hooks_dir"], rep["hooks_dir_source"] = str(hd), source

    rc, out, err = _git(repo, "rev-parse", "--show-toplevel")
    root = Path(out) if rc == 0 else repo
    tracked = root / TRACKED_HOOK_REL

    # --- CONSUMER, first: it is a property of the TRACKED file and is worth
    # --- answering even on a checkout whose hooks were never installed.
    if not tracked.is_file():
        rep["undetermined"].append(                 # type: ignore[union-attr]
            f"{TRACKED_HOOK_REL} is not in this checkout, so there is no "
            f"reference hook to compare against and no consumer to inspect")
        return rep
    try:
        tracked_text = tracked.read_text(errors="replace")
    except OSError as exc:
        rep["undetermined"].append(                 # type: ignore[union-attr]
            f"{TRACKED_HOOK_REL} is unreadable: {exc}")
        return rep
    missing = [t for t in _CONSUMER_TOKENS if t not in tracked_text]
    rep["consumer"] = not missing
    if missing:
        rep["problems"].append(                     # type: ignore[union-attr]
            f"{TRACKED_HOOK_REL} no longer names {missing} — the hook is the "
            f"only consumer of `.git/{STAMP_BASENAME}`, so a hook that has "
            f"stopped reading it leaves the expensive tier enforced by nothing "
            f"even when the hook IS installed")

    # --- INSTALLED -------------------------------------------------------- #
    if not hd.is_dir():
        rep["installed"] = False
        rep["problems"].append(                     # type: ignore[union-attr]
            f"the hooks directory {hd} does not exist, so no hook can run")
        return rep
    hook = hd / "pre-push"
    if not hook.exists():
        rep["installed"] = False
        rep["problems"].append(                     # type: ignore[union-attr]
            f"no `pre-push` in {hd}. `.git/hooks/` is NOT tracked by git, so "
            f"shipping {TRACKED_HOOK_REL} does nothing until "
            f"`tools/install-git-hooks.sh` runs. With it absent, a push to "
            f"`main` is not checked against `.git/{STAMP_BASENAME}` at all — "
            f"the expensive tier is optional and nothing says so")
        return rep
    rep["installed"] = True
    try:
        mode = hook.stat().st_mode
    except OSError as exc:
        rep["undetermined"].append(                 # type: ignore[union-attr]
            f"{hook} exists but could not be stat'ed: {exc}")
        return rep
    if not mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
        rep["problems"].append(                     # type: ignore[union-attr]
            f"{hook} is present but not executable, so git will not run it")

    # --- AUTHENTIC -------------------------------------------------------- #
    same = False
    if hook.is_symlink():
        target = Path(os.path.realpath(hook))
        rep["notes"].append(f"symlink -> {target}")  # type: ignore[union-attr]
        same = target == tracked.resolve()
    if not same:
        a, b = _sha256(hook), _sha256(tracked)
        if a is None or b is None:
            rep["undetermined"].append(             # type: ignore[union-attr]
                f"could not hash {hook} or {tracked}")
            return rep
        same = a == b
        rep["notes"].append(                        # type: ignore[union-attr]
            f"sha256 installed={a[:16]} tracked={b[:16]}")
    rep["authentic"] = same
    if not same:
        rep["problems"].append(                     # type: ignore[union-attr]
            f"the installed `pre-push` is NOT this repository's tracked "
            f"{TRACKED_HOOK_REL} (neither the same file by symlink nor the same "
            f"bytes). Whatever it enforces, it is not the gate this chain ends "
            f"in — and a foreign hook is harder to notice than a missing one, "
            f"because the directory looks armed")
    return rep


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Is the enforcement point that reads the landing stamp "
                    "actually armed in this checkout?")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)

    repo = Path(args.repo).resolve()
    rep = inspect(repo)
    undetermined = rep["undetermined"]              # type: ignore[assignment]
    problems = rep["problems"]                      # type: ignore[assignment]
    rep["verdict"] = ("UNDETERMINED" if undetermined
                      else ("DISARMED" if problems else "ARMED"))

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")

    for n in rep["notes"]:                          # type: ignore[union-attr]
        print(f"  {PROGRAM}: {n}")
    if undetermined:
        for u in undetermined:                      # type: ignore[union-attr]
            print(f"[NOT CHECKED] {PROGRAM}: {u}", file=sys.stderr)
        print(f"[NOT CHECKED] {PROGRAM}: the enforcement point could not be "
              f"inspected. This is NOT a pass — 'I could not look' and 'I "
              f"looked and it was armed' are opposite findings.", file=sys.stderr)
        return RC_UNDETERMINED
    if problems:
        for p in problems:                          # type: ignore[union-attr]
            print(f"[FAIL] {PROGRAM}: {p}", file=sys.stderr)
        print(f"[FAIL] {PROGRAM}: DISARMED — a landing can succeed while a "
              f"gate declared always-run and BLOCKING is red. That is not "
              f"hypothetical: it happened for fourteen consecutive landings, "
              f"v1.11.5 through v1.11.18. Arm it with "
              f"`tools/install-git-hooks.sh`.", file=sys.stderr)
        return RC_DISARMED
    print(f"[PASS] {PROGRAM}: the enforcement point is armed "
          f"({rep['hooks_dir']}, via {rep['hooks_dir_source']}) and still reads "
          f"`.git/{STAMP_BASENAME}`.")
    return RC_OK


if __name__ == "__main__":                          # pragma: no cover
    raise SystemExit(main())
